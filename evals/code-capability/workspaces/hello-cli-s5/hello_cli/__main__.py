"""Entry point for `python -m hello_cli`."""

import argparse
import sys


def cmd_greet(args: argparse.Namespace) -> int:
    """Print a greeting for the given name."""
    print(f"Hello, {args.name}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    """Print the sum of two integers."""
    result = args.a + args.b
    print(result)
    return 0


def cmd_run_plan(args: argparse.Namespace) -> int:
    """Print the run plan: all available commands and descriptions."""
    print("=== hello_cli Run Plan ===")
    print()
    print("Available commands:")
    print("  greet <name>      - Print a greeting: Hello, <name>")
    print("  add <a> <b>       - Print the sum of two integers")
    print("  run_plan          - Print this run plan")
    print("  --help / -h       - Show usage information")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="hello_cli",
        description="A minimal Python CLI: greet, add, and run_plan.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # greet subcommand
    greet_parser = subparsers.add_parser("greet", help="Greet a person by name")
    greet_parser.add_argument("name", help="Name to greet")
    greet_parser.set_defaults(func=cmd_greet)

    # add subcommand
    add_parser = subparsers.add_parser("add", help="Add two integers")
    add_parser.add_argument("a", type=int, help="First integer")
    add_parser.add_argument("b", type=int, help="Second integer")
    add_parser.set_defaults(func=cmd_add)

    # run_plan subcommand
    run_plan_parser = subparsers.add_parser(
        "run_plan", help="Print the run plan (list all commands)"
    )
    run_plan_parser.set_defaults(func=cmd_run_plan)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
