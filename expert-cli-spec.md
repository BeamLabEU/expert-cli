# expert-cli — CLI Wrapper for Expert Elixir Language Server

## Motivation

Expert is the official Elixir language server (LSP). It provides rich code intelligence — types, docs, go-to-definition, references, symbols — but it's only accessible via the LSP protocol, which requires a complex handshake and stateful connection.

This makes it unusable for:

1. **AI coding agents** (Claude Code, Cursor, etc.) that can run shell commands but can't use LSP directly. Claude Code has an LSP tool, but it doesn't handle `client/registerCapability` requests that expert sends, so it hangs forever. A CLI wrapper bypasses this entirely.

2. **Terminal workflows** — developers who want quick lookups without leaving the shell or opening an editor.

3. **Scripts and CI** — automated code analysis, documentation generation, dead code detection.

4. **Other tools** — any program that can shell out but doesn't want to implement an LSP client.

## How Expert LSP Works

- Expert is a single binary (packaged with Burrito, includes its own BEAM runtime)
- Supports `--stdio` and `--port <N>` transport modes
- On first connection to a project, it builds an "engine" via `Mix.install` — this compiles the project and its dependencies for indexing. Takes 1-5 minutes on first run, cached afterward in `~/.cache/expert/`
- After initialization, expert sends a `client/registerCapability` request that the client MUST respond to, or expert blocks forever
- Once initialized, responses are fast (sub-second)

## Architecture

### Daemon + CLI Model

```
expert-cli hover file.ex:18:6
    |
    v
expert-cli checks: is daemon running?
    |
    yes -> send request via TCP -> get response -> print
    no  -> start expert --port <port> -> wait for ready -> send request
```

### Daemon Management

```bash
# Start daemon (or confirm it's running)
expert-cli start [--port 9876]

# Stop daemon
expert-cli stop

# Check status
expert-cli status
# Output: "Expert daemon running on port 9876, PID 12345, engine: ready"
```

The daemon is just `expert --port <N>` running in the background. The CLI wrapper:
1. Starts it if not running
2. Handles the LSP handshake (initialize, initialized, registerCapability response)
3. Sends the actual request
4. Parses the JSON-RPC response
5. Prints human-readable output

### State File

Store daemon state in the project directory:

```
.expert-cli/
  daemon.json    # {"pid": 12345, "port": 9876, "started_at": "..."}
```

Or use a global location like `~/.cache/expert-cli/`.

## Commands

### hover — Get docs and type info

```bash
expert-cli hover lib/phoenix_kit.ex:18:6
```

Output:
```
PhoenixKit.version()
@spec version() :: String.t()

Returns the current version of PhoenixKit.
```

### definition — Go to definition

```bash
expert-cli definition lib/phoenix_kit.ex:6:3
```

Output:
```
lib/phoenix_kit/config.ex:1:1  defmodule PhoenixKit.Config
```

### references — Find all references

```bash
expert-cli references lib/phoenix_kit.ex:18:6
```

Output:
```
lib/phoenix_kit_web/router.ex:45:12
lib/phoenix_kit/installer.ex:23:8
test/phoenix_kit_test.exs:10:5
```

### symbols — List symbols in a file

```bash
expert-cli symbols lib/phoenix_kit.ex
```

Output:
```
module  PhoenixKit                    1:1
func    version/0                    18:3
func    config/0                     22:3
func    config/1                     26:3
```

### search — Workspace symbol search

```bash
expert-cli search "Router"
```

Output:
```
module  PhoenixKitWeb.Router         lib/phoenix_kit_web/router.ex:1:1
module  PhoenixKitWeb.AdminRouter    lib/phoenix_kit_web/admin_router.ex:1:1
func    router_helpers/0             lib/phoenix_kit/config.ex:45:3
```

## Input Format

Support multiple input styles:

```bash
# file:line:column (1-based, like editors show)
expert-cli hover lib/phoenix_kit.ex:18:6

# Separate arguments
expert-cli hover lib/phoenix_kit.ex 18 6

# Just file (for symbols)
expert-cli symbols lib/phoenix_kit.ex
```

## Output Formats

```bash
# Default: human-readable
expert-cli hover lib/phoenix_kit.ex:18:6

# JSON: for programmatic use by agents/scripts
expert-cli hover lib/phoenix_kit.ex:18:6 --json

# Quiet: just the essential info (good for piping)
expert-cli hover lib/phoenix_kit.ex:18:6 --quiet
```

## Implementation Language Options

### Option A: Elixir (escript or Mix task)

- Natural fit, same ecosystem
- Can reuse LSP client libraries
- Slower startup for CLI (BEAM boot time)
- Could be distributed as a Mix archive

### Option B: Python

- Fast to prototype
- No compile step
- Socket/JSON handling is trivial
- Already proven in our TCP tests
- Easy for agents to modify

### Option C: Go or Rust

- Fast startup, single binary
- Better for distribution
- More work to build

**Recommendation:** Start with Python for the prototype. It's proven (our test script already does the full handshake), fast to iterate on, and easy for AI agents to modify. Move to Elixir or Go later if it gets traction.

## LSP Protocol Details

The wrapper needs to handle this sequence on each connection:

```
1. Connect TCP to expert --port <N>
2. Send: initialize (id=1)
3. Recv: initialize response (capabilities)
4. Send: initialized notification
5. Recv: window/logMessage notification
6. Recv: client/registerCapability request (id=1)  <-- MUST respond
7. Send: registerCapability response (id=1, result=null)
8. Send: textDocument/didOpen (with file content)
9. Wait for indexing
10. Send: actual request (hover/definition/references/etc)
11. Recv: response
```

Key gotcha: step 6 is where Claude Code's LSP client breaks. The wrapper MUST handle this.

## Connection Pooling / Persistence

Opening a new connection for every CLI invocation would be slow (handshake + didOpen each time). Options:

- **Keep-alive daemon**: The TCP connection stays open. The CLI communicates with a local intermediary process that holds the connection.
- **Simple approach**: Accept the ~2s overhead per call. For agent/human use, this is fine.
- **File cache**: Track which files are already open on the server, skip didOpen for known files.

Start simple (new connection per call), optimize later if needed.

## Potential Future Features

- `expert-cli completions file.ex:18:6` — Get completions at cursor position
- `expert-cli format file.ex` — Format file via LSP (alternative to `mix format`)
- `expert-cli diagnostics file.ex` — Get warnings/errors
- `expert-cli actions file.ex:18:6` — Get available code actions
- `expert-cli calls file.ex:18:6 --incoming` — Call hierarchy
- `expert-cli calls file.ex:18:6 --outgoing` — What does this function call?
- Integration with `fzf` for interactive symbol search
- Watch mode: `expert-cli watch diagnostics` — continuous output as files change

## Prior Art

- `elixir-ls` — another Elixir LSP, same integration challenges
- `rust-analyzer` has a similar problem; `ra-multiplex` exists as a workaround
- `clangd` has `--check` mode for single-file diagnostics
- `typescript-language-server` is typically used only via editors

## Open Questions

1. Should the daemon auto-start on first CLI call, or require explicit `expert-cli start`?
2. Should we support `--stdio` mode too (for editor integration that works around the registerCapability bug)?
3. Should the tool be expert-specific or generic enough to wrap any LSP server?
4. Package as a standalone repo, or part of the claude-code-elixir plugin?
