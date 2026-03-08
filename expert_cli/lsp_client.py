"""LSP client for Expert Elixir Language Server.

Supports both stdio (subprocess) and TCP transport modes.
"""

import json
import os
import socket
import subprocess
import sys
import time


class LSPClient:
    """Handles JSON-RPC communication with Expert LSP."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._request_id = 0
        self._engine_ready = False
        self._process: subprocess.Popen | None = None
        self._sock: socket.socket | None = None
        # Readers/writers set by connect method
        self._reader = None
        self._writer = None

    def _log(self, direction: str, msg):
        if self.verbose:
            text = json.dumps(msg, indent=2) if isinstance(msg, dict) else str(msg)
            print(f"[{direction}] {text}", file=sys.stderr)

    def connect_stdio(self, root_path: str):
        """Start Expert as a subprocess using stdio transport."""
        import shutil
        binary = shutil.which("expert")
        if not binary:
            for candidate in [
                os.path.expanduser("~/.local/bin/expert"),
                "/usr/local/bin/expert",
            ]:
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    binary = candidate
                    break

        if not binary:
            raise FileNotFoundError(
                "Could not find 'expert' binary. "
                "Make sure it's installed and on your PATH."
            )

        self._process = subprocess.Popen(
            [binary, "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=root_path,
        )
        self._reader = self._process.stdout
        self._writer = self._process.stdin

    def connect_tcp(self, host: str = "127.0.0.1", port: int = 9876):
        """Connect to an already-running Expert instance via TCP."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(300)
        self._sock.connect((host, port))
        self._reader = self._sock.makefile("rb")
        self._writer = self._sock

    def close(self):
        if self._sock:
            self._sock.close()
            self._sock = None
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _send(self, message: dict):
        self._log("SEND", message)
        body = json.dumps(message).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        if self._process:
            self._writer.write(header + body)
            self._writer.flush()
        elif self._sock:
            self._sock.sendall(header + body)

    def _recv(self) -> dict:
        """Read one JSON-RPC message (Content-Length framed)."""
        # Read headers
        headers = {}
        while True:
            if self._process:
                line = self._reader.readline()
            else:
                line = b""
                while not line.endswith(b"\r\n"):
                    chunk = self._reader.read(1)
                    if not chunk:
                        raise ConnectionError("Connection closed while reading header")
                    line += chunk

            if not line:
                raise ConnectionError("Connection closed")

            line = line.decode("utf-8").strip()
            if not line:
                break  # Empty line = end of headers
            if ":" in line:
                key, val = line.split(":", 1)
                headers[key.strip().lower()] = val.strip()

        content_length = int(headers.get("content-length", 0))
        if content_length == 0:
            raise ValueError(f"No Content-Length in headers: {headers}")

        # Read body
        body = b""
        while len(body) < content_length:
            if self._process:
                chunk = self._reader.read(content_length - len(body))
            else:
                chunk = self._reader.read(content_length - len(body))
            if not chunk:
                raise ConnectionError("Connection closed while reading body")
            body += chunk

        msg = json.loads(body.decode("utf-8"))
        self._log("RECV", msg)
        return msg

    def _send_request(self, method: str, params: dict) -> int:
        """Send a JSON-RPC request. Returns the request id."""
        msg_id = self._next_id()
        self._send({
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params,
        })
        return msg_id

    def _send_response(self, msg_id, result):
        """Send a JSON-RPC response (for server-initiated requests)."""
        self._send({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": result,
        })

    def _send_notification(self, method: str, params: dict):
        self._send({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        })

    def _recv_until_response(self, expected_id: int) -> dict:
        """Receive messages until we get the response matching expected_id."""
        while True:
            msg = self._recv()

            # Response to our request
            if "id" in msg and "method" not in msg:
                if msg["id"] == expected_id:
                    return msg
                continue

            # Server-initiated request — must respond
            if "id" in msg and "method" in msg:
                self._handle_server_request(msg)
                continue

            # Notification
            self._handle_notification(msg)

    def _handle_server_request(self, msg: dict):
        """Handle requests from the server (e.g., client/registerCapability)."""
        self._log("SERVER_REQ", msg["method"])
        self._send_response(msg["id"], None)

    def _handle_notification(self, msg: dict):
        """Track notifications, especially log messages for engine status."""
        if msg.get("method") == "window/logMessage":
            log_text = msg.get("params", {}).get("message", "")
            self._log("LOG", log_text)
            if "Engine initialized" in log_text:
                self._engine_ready = True

    def handshake(self, root_path: str) -> dict:
        """Perform the LSP initialize/initialized handshake."""
        root_uri = f"file://{os.path.abspath(root_path)}"

        init_id = self._send_request("initialize", {
            "processId": os.getpid(),
            "capabilities": {
                "textDocument": {
                    "hover": {"contentFormat": ["markdown", "plaintext"]},
                    "definition": {},
                    "references": {},
                    "documentSymbol": {},
                },
                "workspace": {
                    "symbol": {},
                },
            },
            "rootUri": root_uri,
            "rootPath": root_path,
            "workspaceFolders": [{"uri": root_uri, "name": os.path.basename(root_path)}],
        })

        init_response = self._recv_until_response(init_id)
        self._send_notification("initialized", {})
        return init_response.get("result", {})

    def wait_for_engine(self, timeout: int = 300):
        """Wait for the Expert engine to be ready by draining log messages.

        Must be called after handshake() and did_open(). Blocks until
        'Engine initialized' appears in log messages.
        """
        if self._engine_ready:
            return

        start = time.time()
        while not self._engine_ready and (time.time() - start) < timeout:
            try:
                msg = self._recv()
            except (ConnectionError, TimeoutError):
                if not self._engine_ready:
                    raise TimeoutError(
                        f"Expert engine did not initialize within {timeout}s"
                    )
                return

            if "id" in msg and "method" in msg:
                self._handle_server_request(msg)
            elif "method" in msg:
                self._handle_notification(msg)

        if not self._engine_ready:
            raise TimeoutError(
                f"Expert engine did not initialize within {timeout}s"
            )

    def did_open(self, file_path: str):
        """Send textDocument/didOpen for a file."""
        abs_path = os.path.abspath(file_path)
        with open(abs_path) as f:
            text = f.read()

        self._send_notification("textDocument/didOpen", {
            "textDocument": {
                "uri": f"file://{abs_path}",
                "languageId": "elixir",
                "version": 1,
                "text": text,
            }
        })

    def hover(self, file_path: str, line: int, column: int) -> dict | None:
        """Get hover info. Line and column are 0-based (LSP convention)."""
        abs_path = os.path.abspath(file_path)
        req_id = self._send_request("textDocument/hover", {
            "textDocument": {"uri": f"file://{abs_path}"},
            "position": {"line": line, "character": column},
        })
        response = self._recv_until_response(req_id)
        return response.get("result")

    def definition(self, file_path: str, line: int, column: int) -> dict | None:
        abs_path = os.path.abspath(file_path)
        req_id = self._send_request("textDocument/definition", {
            "textDocument": {"uri": f"file://{abs_path}"},
            "position": {"line": line, "character": column},
        })
        response = self._recv_until_response(req_id)
        return response.get("result")

    def references(self, file_path: str, line: int, column: int) -> dict | None:
        abs_path = os.path.abspath(file_path)
        req_id = self._send_request("textDocument/references", {
            "textDocument": {"uri": f"file://{abs_path}"},
            "position": {"line": line, "character": column},
            "context": {"includeDeclaration": True},
        })
        response = self._recv_until_response(req_id)
        return response.get("result")

    def document_symbols(self, file_path: str) -> dict | None:
        abs_path = os.path.abspath(file_path)
        req_id = self._send_request("textDocument/documentSymbol", {
            "textDocument": {"uri": f"file://{abs_path}"},
        })
        response = self._recv_until_response(req_id)
        return response.get("result")

    def workspace_symbols(self, query: str) -> dict | None:
        req_id = self._send_request("workspace/symbol", {
            "query": query,
        })
        response = self._recv_until_response(req_id)
        return response.get("result")
