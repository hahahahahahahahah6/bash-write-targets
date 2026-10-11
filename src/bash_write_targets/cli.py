"""CLI: targets '<bash command>' -> list the files the command may write to."""

import argparse
import json
import sys

from . import __version__
from .extract import extract


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="targets",
        description=(
            "Statically list the file-write targets of a bash command "
            "(redirections, tee, -o/--output flags, cp/mv destinations, ...). "
            "The command is never executed."
        ),
    )
    parser.add_argument("command", help="bash command string to audit")
    parser.add_argument(
        "--json", action="store_true", help="print targets as a JSON array"
    )
    parser.add_argument(
        "--version", action="version", version="%(prog)s " + __version__
    )
    args = parser.parse_args(argv)

    targets = extract(args.command)
    if args.json:
        print(json.dumps(targets))
    else:
        for t in targets:
            print(t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
