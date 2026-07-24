"""CLI entry logic for hello_cli."""

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hello_cli",
        description="A minimal CLI demo: greet and add.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # greet subcommand
    greet = subparsers.add_parser("greet", help="Greet someone by name.")
    greet.add_argument("name", help="Name of the person to greet.")

    # add subcommand
    add = subparsers.add_parser("add", help="Add two integers.")
    add.add_argument("a", type=int, help="First integer.")
    add.add_argument("b", type=int, help="Second integer.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "greet":
        print(f"Hello, {args.name.strip()}")
        sys.exit(0)
    elif args.command == "add":
        print(args.a + args.b)
        sys.exit(0)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    sys.exit(main())
