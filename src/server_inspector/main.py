"""CLI entry point for server-inspector."""

import argparse
import sys

import yaml

from .colors import Colors
from .inspector import VERSION, ServerInspector
from .utils import ensure_root, fatal, is_quiet, print_error, set_quiet


def _run_inspect(args: list[str]) -> None:
    """Run the inspect subcommand (default behavior)."""
    parser = argparse.ArgumentParser(
        prog="server-inspector inspect",
        description="Inspect server hardware and generate specs files",
        epilog="Example: server-inspector inspect white",
    )
    parser.add_argument("name", help="Server name (e.g., white, black, aio)")
    parser.add_argument("--output", "-o", help="Override output YAML file path (default: hardware-<name>.yml)")

    parsed = parser.parse_args(args)

    ensure_root()

    yaml_file = parsed.output or f"hardware-{parsed.name}.yml"

    try:
        inspector = ServerInspector(parsed.name)
        inspector.run()
        inspector.save_yaml(yaml_file)
        inspector.print_summary()

        if not is_quiet():
            print()
            print(f"{Colors.BOLD}Next Steps:{Colors.END}")
            print(f"  1. Review {yaml_file} (optional)")
            print("  2a. For Proxmox: proxmox-wizard hardware-detect")
            print(
                f"  2b. Standalone:  mkdir -p servers/{parsed.name} && mv {yaml_file} servers/{parsed.name}/hardware.yml"
            )
            print(f'      Then:        storage-planner plan "description" --server {parsed.name}')
            print()

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted by user{Colors.END}")
        sys.exit(2)
    except FileNotFoundError as e:
        print_error(f"File error: {e}")
        sys.exit(1)
    except (yaml.YAMLError, ValueError) as e:
        print_error(f"Validation error: {e}")
        sys.exit(1)
    except (OSError, RuntimeError) as e:
        print_error(f"{type(e).__name__}: {e}")
        sys.exit(1)


_SUBCOMMANDS = {"inspect"}


def _insert_default_subcommand(argv: list[str]) -> list[str]:
    """Insert 'inspect' when the user omits the subcommand."""
    for i, arg in enumerate(argv):
        if arg.startswith("-"):
            continue
        if arg not in _SUBCOMMANDS:
            return argv[:i] + ["inspect"] + argv[i:]
        return argv
    return argv


def main() -> None:
    """Main entry point with subcommand routing."""
    parser = argparse.ArgumentParser(
        description="Server Hardware Inspector - Auto-detect hardware for server deployment",
        epilog="Example: server-inspector inspect white",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress non-error output")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show debug detail")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser(
        "inspect",
        help="Inspect server hardware and generate specs files",
        add_help=False,
    )

    args, remaining = parser.parse_known_args(_insert_default_subcommand(sys.argv[1:]))

    if args.quiet and args.verbose:
        fatal("Cannot use --quiet and --verbose together")
    if args.quiet:
        set_quiet(True)

    if args.command == "inspect":
        _run_inspect(remaining)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
