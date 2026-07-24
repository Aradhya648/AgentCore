from __future__ import annotations

import argparse
import sys

from fixme.greet import greet
from fixme.mathops import add


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fixme", description="fix-me-kit demo CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="add two integers")
    p_add.add_argument("a", type=int)
    p_add.add_argument("b", type=int)

    p_greet = sub.add_parser("greet", help="greet someone")
    p_greet.add_argument("name", type=str)

    p_mul = sub.add_parser("multiply", help="multiply two integers")
    p_mul.add_argument("a", type=int)
    p_mul.add_argument("b", type=int)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "add":
        print(add(args.a, args.b))
        return 0
    if args.cmd == "greet":
        print(greet(args.name))
        return 0
    if args.cmd == "multiply":
        print(args.a * args.b)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
