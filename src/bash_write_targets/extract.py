"""Static extraction of file-write targets from a bash command string.

Never executes anything. Conservative by design: a missed target is a miss,
never a crash.

Covered:
  * redirections:  >, >>, >|, &>, &>>, 2>, 2>>, <>
  * heredocs (<<EOF): bodies are stripped so their contents are not mistaken
    for targets
  * command substitution: $(...) and `...` are scanned recursively
  * tee (all operands, -a/--append aware)
  * cp / mv / install (destination operand; --target-directory aware)
  * sed -i (in-place operands)
  * dd of=FILE, truncate, touch, shred, zip (archive operand)
  * -o / --output style flags for curl, wget, gcc/cc/g++/clang, sort,
    pandoc, psql, tar -f/--file

Known gaps (documented, not guessed at):
  * eval and paths built at runtime
  * unresolvable $VAR expansions (skipped, not guessed)
  * bare globs (skipped)
  * /dev/null (skipped)
  * python3 -c "open(...).write(...)" style embedded writes
  * network sinks (e.g. curl --data posting to a URL)
"""

import re
import shlex

_SEPARATORS = {"|", "||", "&", "&&", ";", "(", ")", "\n"}
_PREFIX_COMMANDS = {"sudo", "env", "command", "time", "nohup"}

_FD_WORD = re.compile(r"^&?\d+$")
_ASSIGN_WORD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
_DD_OF = re.compile(r"^of=(.+)$")
_GLOB_CHARS = re.compile(r"[*?\[]")
_VAR_CHARS = re.compile(r"[$]")

# command -> output flags whose next token (or --flag=value) names a file
KNOWN_OUTPUT_FLAGS = {
    "curl": ("-o", "--output"),
    "wget": ("-O", "--output-document"),
    "gcc": ("-o",),
    "cc": ("-o",),
    "g++": ("-o",),
    "clang": ("-o",),
    "clang++": ("-o",),
    "sort": ("-o", "--output"),
    "pandoc": ("-o", "--output"),
    "psql": ("-o", "--output"),
    "tar": ("-f", "--file"),
}


def _valid_target(word):
    """Decide whether a candidate word is a plausible file path."""
    if not word:
        return False
    if word == "/dev/null":
        return False
    if word == "-":  # stdout/stdin placeholder
        return False
    if _FD_WORD.match(word):
        return False
    if _VAR_CHARS.search(word):
        return False  # unresolvable at static time; skip, don't guess
    if _GLOB_CHARS.search(word):
        return False  # bare globs are ambiguous; skip, don't guess
    return True


def _strip_heredocs(text):
    """Remove heredoc bodies so their contents are not parsed as commands."""
    pattern = re.compile(r"<<-?[ \t]*(?P<q>['\"]?)(?P<word>[A-Za-z0-9_]+)(?P=q)")
    out = text
    while True:
        m = pattern.search(out)
        if not m:
            return out
        word = m.group("word")
        term = re.compile(r"^" + re.escape(word) + r"[ \t]*$", re.M)
        tm = term.search(out, m.end())
        end = tm.end() if tm else len(out)
        out = out[: m.start()] + " " + out[end:]


def _extract_substitutions(text):
    """Pull out $(...) and `...` spans; return (outer_text, [inner, ...])."""
    inners = []
    out = []
    i, n = 0, len(text)
    while i < n:
        if text.startswith("$(", i):
            depth, j = 1, i + 2
            in_single = in_double = False
            while j < n and depth:
                c = text[j]
                if in_single:
                    if c == "'":
                        in_single = False
                elif in_double:
                    if c == '"':
                        in_double = False
                    elif c == "\\":
                        j += 1
                else:
                    if c == "'":
                        in_single = True
                    elif c == '"':
                        in_double = True
                    elif c == "(":
                        depth += 1
                    elif c == ")":
                        depth -= 1
                j += 1
            if depth == 0:
                inners.append(text[i + 2 : j - 1])
                out.append(" ")
                i = j
            else:  # unbalanced; keep scanning char by char
                out.append(text[i])
                i += 1
        elif text[i] == "`":
            j = i + 1
            while j < n and text[j] != "`":
                if text[j] == "\\":
                    j += 1
                j += 1
            if j < n:
                inners.append(text[i + 1 : j])
                out.append(" ")
                i = j + 1
            else:
                out.append(text[i])
                i += 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out), inners


def _tokenize(text):
    """shlex tokenize with shell punctuation kept as separate tokens."""
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars="|&;()<>\n")
    except TypeError:  # very old Python without punctuation_chars
        lexer = shlex.shlex(text, posix=True)
    lexer.whitespace_split = True
    raw = list(lexer)
    # merge doubled punctuation chars: >>, <<, &&, ||
    merged = []
    for tok in raw:
        if merged and tok in (">", "<", "&", "|") and merged[-1] == tok:
            merged[-1] = tok * 2
        else:
            merged.append(tok)
    return merged


def _redir_op(tok):
    """Normalize a token to a redirection operator, or None.

    Leading fd digits are stripped: '2>' -> '>'.
    """
    m = re.match(r"^(\d*)(>>?|<<-?|>&|&>>?|>\||<>)$", tok)
    if not m:
        return None
    return m.group(2)


def _scan_tokens(tokens, add):
    i, n = 0, len(tokens)
    at_start = True
    cmd = None
    flags = []
    operands = []
    pending_value = None  # flag waiting for its value (name, kind)
    target_dir = None

    def finish_segment():
        nonlocal cmd, flags, operands, pending_value, target_dir
        if cmd == "tee":
            for op in operands:
                add(op)
        elif cmd in ("cp", "mv", "install"):
            if target_dir is not None:
                add(target_dir)
            elif len(operands) >= 2:
                add(operands[-1])
        elif cmd == "sed":
            if any(
                f == "-i" or f.startswith("-i") or f == "--in-place"
                for f in flags
            ):
                files = operands
                # without -e/-f the first operand is the sed script, not a file
                if files and not any(
                    f == "-e" or f == "-f" or f.startswith("-e") or f.startswith("--expression")
                    for f in flags
                ):
                    files = files[1:]
                for op in files:
                    add(op)
        elif cmd == "dd":
            for t in operands + flags:
                m = _DD_OF.match(t)
                if m:
                    add(m.group(1))
        elif cmd in ("truncate", "touch", "shred"):
            for op in operands:
                add(op)
        elif cmd == "zip":
            if operands:
                add(operands[0])
        cmd, flags, operands, pending_value, target_dir = (
            None, [], [], None, None,
        )

    def consume_flag_value():
        nonlocal i, pending_value, target_dir
        name, kind = pending_value
        pending_value = None
        if i < n and tokens[i] not in _SEPARATORS and _redir_op(tokens[i]) is None:
            if kind == "output":
                add(tokens[i])
            elif kind == "targetdir":
                target_dir = tokens[i]
            # kind == "skip" (e.g. truncate -s): value consumed, not a target
            i += 1

    while i < n:
        tok = tokens[i]

        if pending_value is not None:
            consume_flag_value()
            continue

        if tok in _SEPARATORS:
            finish_segment()
            at_start = True
            i += 1
            continue

        op = _redir_op(tok)
        if op is not None:
            nxt = tokens[i + 1] if i + 1 < n else None
            if op in ("<<", "<<-"):
                i += 2  # heredoc bodies already stripped; skip delimiter
                continue
            if op == "<":
                i += 2 if nxt not in (None, "(") else 1  # input side, not a target
                continue
            # output redirections: >, >>, >|, &>, &>>, <>
            if nxt == "(":
                i += 1  # process substitution >(...); not a file target
                continue
            if nxt == "&":
                # >&2 / 2>&1 style fd duplication; only a real path counts
                tgt = tokens[i + 2] if i + 2 < n else None
                if (
                    tgt is not None
                    and tgt not in _SEPARATORS
                    and _redir_op(tgt) is None
                    and not _FD_WORD.match(tgt)
                ):
                    add(tgt)
                i += 3
                continue
            if nxt is None or nxt in _SEPARATORS or _redir_op(nxt) is not None:
                i += 1  # malformed; skip
                continue
            add(nxt)
            i += 2
            continue

        if at_start:
            if _ASSIGN_WORD.match(tok):
                i += 1  # FOO=bar env assignment
                continue
            if tok in _PREFIX_COMMANDS:
                i += 1
                continue
            cmd = tok.split("/")[-1]
            at_start = False
            i += 1
            continue

        # operand / flag position for the current command
        if tok.startswith("-") and tok != "-":
            flags.append(tok)
            if cmd in KNOWN_OUTPUT_FLAGS and tok in KNOWN_OUTPUT_FLAGS[cmd]:
                if "=" in tok:
                    _, _, value = tok.partition("=")
                    add(value)
                else:
                    pending_value = (tok, "output")
            elif "=" in tok and tok.split("=", 1)[0] in (
                "--target-directory",
                "--output",
                "--file",
                "--output-document",
            ):
                _, _, value = tok.partition("=")
                if tok.startswith("--target-directory"):
                    target_dir = value
                else:
                    add(value)
            elif cmd == "truncate" and tok in ("-s", "--size"):
                pending_value = (tok, "skip")
            elif cmd in ("cp", "mv", "install") and tok in ("-t", "--target-directory"):
                pending_value = (tok, "targetdir")
            i += 1
            continue

        if _ASSIGN_WORD.match(tok) and cmd != "dd":
            i += 1  # VAR=x in operand position is not a file
            continue
        operands.append(tok)
        i += 1

    finish_segment()


def extract(command):
    """Return the ordered, deduplicated list of files the command may write.

    Pure static analysis; the command is never executed.
    """
    targets = []

    def add(word):
        if _valid_target(word) and word not in targets:
            targets.append(word)

    outer, inners = _extract_substitutions(_strip_heredocs(command))
    for inner in inners:
        for t in extract(inner):
            add(t)
    _scan_tokens(_tokenize(outer), add)
    return targets
