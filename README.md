# bash-write-targets

Give it a bash command string; get back the list of files it may write to —
before anything runs.

```bash
$ targets 'make 2>&1 | tee build.log; curl -s -o app.tar.gz https://example.com/app'
build.log
app.tar.gz
```

Stdlib-only. Static analysis — the command is **never executed**.

## Why

AI coding agents run a lot of bash. Before a command executes, an auditor
(like a PreToolUse hook) wants to know: *which files could this touch?*
Grepping for `>` misses `tee`, `curl -o`, `sed -i`, `dd of=`, `cp`/`mv`
destinations, and writes hidden inside `$(...)`.

`bash-write-targets` answers that one question, for one command, with no
dependencies.

## Install

```bash
pip install bash-write-targets
```

Requires Python 3.9+.

## Usage

```bash
targets '<bash command>'        # one target per line
targets --json '<bash command>' # JSON array, for hooks and scripts
```

Examples:

```bash
$ targets 'echo hello > out.txt'
out.txt

$ targets 'cat > note.txt <<EOF
hello > world
EOF'
note.txt

$ targets 'grep -r foo . | sort -o sorted.txt; mv sorted.txt final.txt'
sorted.txt
final.txt

$ targets 'sed -i "s/a/b/g" config.ini && dd if=/dev/zero of=disk.img bs=1M count=1'
config.ini
disk.img
```

Covered: `>` `>>` `>|` `&>` `&>>` `2>` `2>>` `<>`, heredocs (bodies are
stripped, not parsed), `$(...)` and backticks (scanned recursively), `tee`
(including `-a`), `cp`/`mv`/`install` destinations, `sed -i`, `dd of=`,
`truncate`, `touch`, `shred`, `zip` archives, and `-o`/`--output`-style
flags for `curl`, `wget`, `gcc`/`cc`/`g++`/`clang`, `sort`, `pandoc`,
`psql`, and `tar -f`.

Deliberately skipped (not guessed at): `/dev/null`, fd duplications
(`2>&1`), unresolvable `$VAR` expansions, bare globs, and input-side `<`
redirections.

## Differentiation

This project exists because
[agent-guard](https://github.com/hahahahahahahahah6/agent-guard) says so —
literally. Its README's *Honest limitations* section documents the
situation:

> **Bash write-target extraction is static and approximate.** It is
> shlex-based, so heavy quoting, `eval`, command substitution building
> paths at runtime, and `python3 -c "open(...).write(...)"` are known gaps
> — the target list is conservative by design (a missed target is a miss,
> never a crash). ... **This is the documented frontier for a future
> version, not a finished parser.**

`bash-write-targets` is that future version, as a standalone tool:

- **Deeper than the inline heuristic.** agent-guard's hook extracts
  targets inline with a shallow shlex pass, good enough for a hot-path
  block decision. This package goes further: heredoc-aware stripping,
  recursive command-substitution scanning, and command-aware operand
  parsing (`tee`, `sed -i` script-vs-file disambiguation, `cp -t`,
  `--output=` forms).
- **Reusable anywhere.** A PreToolUse hook, a CI audit step, or a human
  double-checking a pasted command — one `targets` call, one line per
  file, plus `--json` for machines.
- **Safe by construction.** Pure static parsing over the command string.
  Nothing is executed, no subshell is spawned, no file is touched —
  auditing a destructive command cannot itself be destructive.

## Honest limitations

- Static, not proof. `eval`, paths assembled at runtime, and
  `python3 -c "open(p).write(x)"` are known gaps — the list is
  conservative by design.
- `$VAR` and bare globs are skipped rather than resolved.
- Network sinks (e.g. `curl --data` POSTing somewhere) are out of scope:
  this tool lists *file* write targets.
- A missed target is a miss, never a crash: malformed input yields fewer
  results, not an exception.

## License

MIT. See [LICENSE](LICENSE).
