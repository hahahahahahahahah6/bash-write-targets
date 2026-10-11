"""Smoke tests for bash-write-targets. Run: python3 tests/test_targets.py"""

import io
import json
import os
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bash_write_targets import cli  # noqa: E402
from bash_write_targets.extract import extract  # noqa: E402


def check(name, command, expected):
    got = extract(command)
    assert got == expected, f"{name}: for {command!r} got {got!r}, want {expected!r}"


def test_simple_redirect():
    check("redirect", "echo hello > out.txt", ["out.txt"])


def test_append_redirect():
    check("append", "echo hello >> log.txt", ["log.txt"])


def test_stderr_redirect():
    check("stderr", "cmd 2> err.log", ["err.log"])


def test_combined_redirect():
    check("combined", "cmd &> all.log", ["all.log"])


def test_fd_duplication_skipped():
    check("fddup", "cmd > out.txt 2>&1", ["out.txt"])
    check("fddup2", "cmd >&2", [])


def test_dev_null_skipped():
    check("devnull", "cmd > /dev/null 2>&1", [])


def test_tee():
    check("tee", "make 2>&1 | tee build.log", ["build.log"])
    check("tee-multi", "cmd | tee -a a.log b.log", ["a.log", "b.log"])


def test_output_flags():
    check("curl-o", "curl -s -o page.html https://example.com", ["page.html"])
    check("curl-long", "curl --output=dl.bin https://example.com/x", ["dl.bin"])
    check("wget", "wget -O data.zip https://example.com/d", ["data.zip"])
    check("gcc", "gcc -O2 -o app main.c", ["app"])


def test_copy_move():
    check("cp", "cp -r src/ dst/", ["dst/"])
    check("mv", "mv old.txt new.txt", ["new.txt"])


def test_sed_inplace():
    check("sed-i", "sed -i 's/a/b/' file.txt", ["file.txt"])


def test_dd_truncate_touch():
    check("dd", "dd if=/dev/zero of=disk.img bs=1M count=10", ["disk.img"])
    check("truncate", "truncate -s 0 app.log", ["app.log"])
    check("touch", "touch newfile.txt", ["newfile.txt"])


def test_heredoc_body_not_parsed():
    check(
        "heredoc",
        "cat > note.txt <<EOF\nsome > text >> here\nEOF",
        ["note.txt"],
    )


def test_command_substitution_recursive():
    check(
        "subst",
        "echo $(date > inner.txt) > outer.txt",
        ["inner.txt", "outer.txt"],
    )


def test_var_and_glob_skipped():
    check("var", "echo hi > $OUTFILE", [])
    check("glob", "echo hi > *.log", [])


def test_pipeline_segments():
    check(
        "pipeline",
        "grep foo in.txt | sort -o sorted.txt; mv sorted.txt final.txt",
        ["sorted.txt", "final.txt"],
    )


def test_quoted_filename():
    check("quoted", 'echo x > "my file.txt"', ["my file.txt"])


def test_no_writes():
    check("nowrite", "ls -la | grep foo", [])


def test_cli_text_output():
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["echo hi > cli.txt"])
    assert rc == 0
    assert buf.getvalue().strip() == "cli.txt"


def test_cli_json_output():
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["--json", "cmd | tee j1.log j2.log"])
    assert rc == 0
    assert json.loads(buf.getvalue()) == ["j1.log", "j2.log"]


if __name__ == "__main__":
    tests = [
        v for k, v in sorted(globals().items()) if k.startswith("test_")
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
