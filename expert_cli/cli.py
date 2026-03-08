"""CLI entry point for expert-cli."""

import argparse
import os
import subprocess
import sys
import time

from expert_cli import daemon, formatter


def parse_location(args: list[str]) -> tuple[str, int | None, int | None]:
    """Parse file:line:col or separate arguments. Returns (file, line, col).

    Line and col are returned as 0-based (LSP convention) but accepted as
    1-based from the user (editor convention).
    """
    if not args:
        print("Error: file path required", file=sys.stderr)
        sys.exit(1)

    first = args[0]

    # file:line:col format
    parts = first.split(":")
    if len(parts) >= 3:
        return parts[0], int(parts[1]) - 1, int(parts[2]) - 1
    if len(parts) == 2:
        return parts[0], int(parts[1]) - 1, 0

    # Separate arguments
    file_path = parts[0]
    line = int(args[1]) - 1 if len(args) > 1 else None
    col = int(args[2]) - 1 if len(args) > 2 else None

    return file_path, line, col


def get_project_root() -> str:
    """Find the project root (directory containing mix.exs)."""
    path = os.getcwd()
    while path != "/":
        if os.path.exists(os.path.join(path, "mix.exs")):
            return path
        path = os.path.dirname(path)
    return os.getcwd()


def ensure_daemon(verbose: bool = False) -> None:
    """Make sure the daemon is running, start it if not."""
    if daemon.is_daemon_running():
        return

    print("Starting Expert daemon...", file=sys.stderr)
    root = get_project_root()

    # Start daemon as a background subprocess
    cmd = [
        sys.executable, "-m", "expert_cli.daemon_main",
        "--root", root,
    ]
    if verbose:
        cmd.append("--verbose")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=None if verbose else subprocess.DEVNULL,
        start_new_session=True,
    )

    # Wait for the daemon to print its ready message
    try:
        for _ in range(300):  # up to 5 minutes
            line = proc.stdout.readline().decode("utf-8").strip()
            if "ready" in line.lower():
                print(line, file=sys.stderr)
                break
            if proc.poll() is not None:
                print("Error: daemon process exited unexpectedly", file=sys.stderr)
                sys.exit(1)
            time.sleep(0.1)
        else:
            print("Error: daemon did not become ready in time", file=sys.stderr)
            proc.kill()
            sys.exit(1)
    finally:
        # Detach from stdout so daemon keeps running
        proc.stdout.close()


def make_request(command: str, file_path: str | None = None,
                 line: int | None = None, col: int | None = None,
                 query: str | None = None, as_json: bool = False) -> str:
    """Send request to daemon and format the response."""
    req = {"command": command}
    if file_path:
        req["file"] = os.path.abspath(file_path)
    if line is not None:
        req["line"] = line
    if col is not None:
        req["col"] = col
    if query is not None:
        req["query"] = query

    response = daemon.send_request(req)

    if "error" in response:
        return f"Error: {response['error']}"

    result = response.get("result")

    if command == "hover":
        return formatter.format_hover(result, as_json=as_json)
    elif command == "definition":
        return formatter.format_definition(result, as_json=as_json)
    elif command == "references":
        return formatter.format_references(result, as_json=as_json)
    elif command == "symbols":
        return formatter.format_symbols(result, as_json=as_json)
    elif command == "search":
        return formatter.format_workspace_symbols(result, as_json=as_json)
    else:
        return json.dumps(result, indent=2)


def main():
    parser = argparse.ArgumentParser(
        prog="expert-cli",
        description="CLI wrapper for Expert Elixir Language Server",
    )
    parser.add_argument("--json", action="store_true",
                        help="Output raw JSON")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show LSP protocol messages")

    subparsers = parser.add_subparsers(dest="command")

    # Daemon management
    subparsers.add_parser("start", help="Start Expert daemon")
    subparsers.add_parser("stop", help="Stop Expert daemon")
    subparsers.add_parser("status", help="Check daemon status")

    # LSP commands
    for cmd in ("hover", "definition", "references"):
        sub = subparsers.add_parser(cmd, help=f"Get {cmd} info")
        sub.add_argument("location", nargs="+", help="file:line:col or file line col")

    sub_sym = subparsers.add_parser("symbols", help="List symbols in a file")
    sub_sym.add_argument("file", help="File path")

    sub_search = subparsers.add_parser("search", help="Search workspace symbols")
    sub_search.add_argument("query", help="Search query")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    verbose = getattr(args, "verbose", False)

    # Daemon management commands
    if args.command == "start":
        if daemon.is_daemon_running():
            print("Expert daemon is already running.")
        else:
            ensure_daemon(verbose=verbose)
            print("Expert daemon started.")
        return

    if args.command == "stop":
        if daemon.stop_daemon():
            print("Expert daemon stopped.")
        else:
            print("No daemon running.")
        return

    if args.command == "status":
        if daemon.is_daemon_running():
            pp = daemon.pid_path()
            with open(pp) as f:
                pid = f.read().strip()
            print(f"Expert daemon running (PID {pid})")
        else:
            print("No daemon running.")
        return

    # LSP commands — ensure daemon is running (auto-start)
    try:
        ensure_daemon(verbose=verbose)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    as_json = getattr(args, "json", False)

    try:
        if args.command in ("hover", "definition", "references"):
            file_path, line, col = parse_location(args.location)
            if line is None or col is None:
                print("Error: line and column required for this command", file=sys.stderr)
                sys.exit(1)
            output = make_request(args.command, file_path=file_path, line=line, col=col, as_json=as_json)
        elif args.command == "symbols":
            output = make_request("symbols", file_path=args.file, as_json=as_json)
        elif args.command == "search":
            output = make_request("search", query=args.query, as_json=as_json)
        else:
            parser.print_help()
            sys.exit(1)

        print(output)
    except ConnectionRefusedError:
        print("Error: cannot connect to daemon. Try: expert-cli start", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
