"""Daemon that keeps Expert LSP running and brokers CLI requests.

Expert exits when its connection closes, so we need a persistent process
that holds the stdio subprocess open. CLI invocations connect to this
daemon via a Unix domain socket, send a request, and get a response.

Protocol over Unix socket (simple line-delimited JSON):
  Client sends: {"command": "hover", "file": "...", "line": 0, "col": 0}
  Daemon sends: {"result": ...} or {"error": "..."}
"""

import json
import os
import signal
import socket
import sys
import threading
import time

from expert_cli.lsp_client import LSPClient

SOCKET_DIR = ".expert-cli"
SOCKET_NAME = "daemon.sock"
PID_FILE = "daemon.pid"


def socket_path() -> str:
    return os.path.join(SOCKET_DIR, SOCKET_NAME)


def pid_path() -> str:
    return os.path.join(SOCKET_DIR, PID_FILE)


def is_daemon_running() -> bool:
    """Check if a daemon is already running."""
    pp = pid_path()
    if not os.path.exists(pp):
        return False
    try:
        with open(pp) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        # Also check socket exists and is connectable
        sp = socket_path()
        if not os.path.exists(sp):
            return False
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.settimeout(2)
            s.connect(sp)
            s.close()
            return True
        except (ConnectionRefusedError, OSError):
            return False
    except (ProcessLookupError, ValueError, FileNotFoundError):
        return False
    except PermissionError:
        return True


def stop_daemon() -> bool:
    """Stop a running daemon."""
    pp = pid_path()
    if not os.path.exists(pp):
        return False
    try:
        with open(pp) as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            try:
                os.kill(pid, 0)
                time.sleep(0.25)
            except ProcessLookupError:
                break
        _cleanup_files()
        return True
    except (ProcessLookupError, ValueError, FileNotFoundError):
        _cleanup_files()
        return False


def _cleanup_files():
    for f in [socket_path(), pid_path()]:
        try:
            os.remove(f)
        except FileNotFoundError:
            pass


class Daemon:
    """Long-running process that holds Expert open and serves CLI requests."""

    def __init__(self, project_root: str, verbose: bool = False):
        self.project_root = project_root
        self.verbose = verbose
        self.client: LSPClient | None = None
        self.lock = threading.Lock()
        self._running = True

    def _log(self, msg: str):
        if self.verbose:
            print(f"[daemon] {msg}", file=sys.stderr, flush=True)

    def start_expert(self):
        """Start Expert and wait for engine ready."""
        self._log("Starting Expert...")
        self.client = LSPClient(verbose=self.verbose)
        self.client.connect_stdio(self.project_root)
        self.client.handshake(self.project_root)
        self._log("Handshake done, waiting for engine...")
        self.client.wait_for_engine()
        self._log("Engine ready!")

    def handle_request(self, request: dict) -> dict:
        """Handle a single request from a CLI client."""
        command = request.get("command")
        file_path = request.get("file", "")
        line = request.get("line", 0)
        col = request.get("col", 0)

        with self.lock:
            try:
                if command == "ping":
                    return {"result": "pong"}

                if command in ("hover", "definition", "references"):
                    self.client.did_open(file_path)

                if command == "hover":
                    result = self.client.hover(file_path, line, col)
                elif command == "definition":
                    result = self.client.definition(file_path, line, col)
                elif command == "references":
                    result = self.client.references(file_path, line, col)
                elif command == "symbols":
                    self.client.did_open(file_path)
                    result = self.client.document_symbols(file_path)
                elif command == "search":
                    query = request.get("query", "")
                    result = self.client.workspace_symbols(query)
                else:
                    return {"error": f"Unknown command: {command}"}

                return {"result": result}
            except Exception as e:
                return {"error": str(e)}

    def handle_client(self, conn: socket.socket):
        """Handle one CLI client connection."""
        try:
            data = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break

            if not data:
                return

            request = json.loads(data.decode("utf-8").strip())
            self._log(f"Request: {request.get('command')} {request.get('file', '')}")

            response = self.handle_request(request)
            conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
        except Exception as e:
            try:
                conn.sendall((json.dumps({"error": str(e)}) + "\n").encode("utf-8"))
            except:
                pass
        finally:
            conn.close()

    def run(self):
        """Main daemon loop."""
        os.makedirs(SOCKET_DIR, exist_ok=True)

        # Clean up stale socket
        sp = socket_path()
        if os.path.exists(sp):
            os.remove(sp)

        # Write PID
        with open(pid_path(), "w") as f:
            f.write(str(os.getpid()))

        # Start Expert
        try:
            self.start_expert()
        except Exception as e:
            print(f"Failed to start Expert: {e}", file=sys.stderr)
            _cleanup_files()
            sys.exit(1)

        # Listen on Unix socket
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(sp)
        server.listen(5)
        server.settimeout(1)  # Allow periodic shutdown check

        def handle_signal(signum, frame):
            self._running = False

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        self._log(f"Daemon listening on {sp}")
        print(f"Expert daemon ready (PID {os.getpid()})", flush=True)

        while self._running:
            try:
                conn, _ = server.accept()
                t = threading.Thread(target=self.handle_client, args=(conn,), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except OSError:
                break

        self._log("Shutting down...")
        server.close()
        if self.client:
            self.client.close()
        _cleanup_files()


def run_daemon(project_root: str, verbose: bool = False):
    """Entry point to run the daemon in the current process."""
    d = Daemon(project_root, verbose=verbose)
    d.run()


def send_request(request: dict) -> dict:
    """Send a request to the running daemon and return the response."""
    sp = socket_path()
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(30)
    s.connect(sp)
    s.sendall((json.dumps(request) + "\n").encode("utf-8"))

    data = b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
        if b"\n" in data:
            break
    s.close()

    return json.loads(data.decode("utf-8").strip())
