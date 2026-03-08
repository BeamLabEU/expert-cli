# expert-cli

CLI wrapper for [Expert](https://github.com/elixir-lang/expert), the official Elixir Language Server.

Expert provides rich code intelligence — types, docs, go-to-definition, references, symbols — but it's only accessible via the LSP protocol. This tool makes it available from the command line.

Useful for:
- **AI coding agents** (Claude Code, Cursor, etc.) that can shell out but can't use LSP directly
- **Terminal workflows** — quick lookups without leaving the shell
- **Scripts and CI** — automated code analysis and documentation generation

## Install

```bash
# Using uv (recommended)
uv tool install --editable /path/to/expert-cli

# Or with pip
pip install -e /path/to/expert-cli
```

This puts `expert-cli` on your PATH.

Also requires the `expert` binary on your PATH. See [Expert installation](https://github.com/elixir-lang/expert).

## Usage

Run from any directory inside an Elixir project (with `mix.exs`):

```bash
# Get docs and type info
expert-cli hover lib/my_app.ex:18:6

# List symbols in a file
expert-cli symbols lib/my_app.ex

# Go to definition
expert-cli definition lib/my_app.ex:6:20

# Find all references
expert-cli references lib/my_app.ex:18:6

# Search workspace symbols
expert-cli search "Router"
```

### Input formats

```bash
# file:line:column (1-based, as editors show)
expert-cli hover lib/my_app.ex:18:6

# Separate arguments
expert-cli hover lib/my_app.ex 18 6
```

### Output formats

```bash
# Default: human-readable (truncated for long docs)
expert-cli hover lib/my_app.ex:18:6

# JSON: raw LSP response for programmatic use
expert-cli hover lib/my_app.ex:18:6 --json

# Verbose: show LSP protocol messages
expert-cli -v hover lib/my_app.ex:18:6
```

## Daemon

The first call auto-starts a background daemon that keeps Expert running. Subsequent calls are fast (~100ms) because the engine stays loaded.

```bash
# Manual daemon management
expert-cli start     # Start daemon (happens automatically on first call)
expert-cli status    # Check if daemon is running
expert-cli stop      # Stop daemon
```

### Performance

| Scenario | Time |
|----------|------|
| First call (starts daemon + loads engine) | ~10-15s (cached) / ~2-5min (first time) |
| Subsequent calls | ~100-500ms |

The engine cache lives in `~/.cache/expert/` and persists across daemon restarts.

## How it works

Expert exits when its connection closes, so a persistent daemon process is needed. The architecture:

```
expert-cli hover file.ex:18:6
    │
    ▼
CLI connects to daemon via Unix socket (.expert-cli/daemon.sock)
    │
    ▼
Daemon holds Expert subprocess (--stdio) open with engine loaded
    │
    ▼
Daemon forwards LSP request → Expert responds in <100ms
    │
    ▼
CLI formats and prints the result
```

The daemon handles the full LSP handshake including the `client/registerCapability` response that Expert requires (and that trips up most LSP clients including Claude Code's built-in LSP tool).

## Requirements

- Python 3.10+
- [Expert](https://github.com/elixir-lang/expert) binary on PATH
- An Elixir project with `mix.exs`

## Project structure

```
expert_cli/
  cli.py           — CLI entry point (argparse)
  daemon.py        — Background daemon (Unix socket broker)
  daemon_main.py   — Daemon subprocess entry point
  lsp_client.py    — LSP JSON-RPC client (stdio + TCP transport)
  formatter.py     — Human-readable output formatting
```

## License

MIT
