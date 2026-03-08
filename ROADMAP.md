# Roadmap

## Current state (v0.1)

Working Python prototype with daemon architecture:
- Commands: hover, definition, references, symbols, search
- Background daemon keeps Expert running for fast (~100ms) subsequent calls
- Human-readable and JSON output formats
- AI agent integration via CLAUDE.md/AGENTS.md instructions

## Short term

### More commands

- `expert-cli completions file.ex:18:6` — get completions at cursor position
- `expert-cli diagnostics file.ex` — get warnings and errors
- `expert-cli format file.ex` — format file via LSP
- `expert-cli actions file.ex:18:6` — get available code actions
- `expert-cli calls file.ex:18:6 --incoming` — incoming call hierarchy
- `expert-cli calls file.ex:18:6 --outgoing` — outgoing call hierarchy

### Better output

- `--quiet` flag for minimal output (good for piping)
- Smarter truncation for long docs (show @spec and first paragraph only)
- Colorized terminal output
- Relative file paths in output (instead of absolute)

### Reliability

- Daemon auto-restart if Expert crashes
- Better error messages when engine is still loading
- Timeout handling for slow requests
- Health check / watchdog for long-running daemon

## Medium term

### MCP server integration

Wrap expert-cli as an [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server. This is a more integrated way to give AI agents access to tools — the agent discovers available tools automatically instead of relying on instructions in a markdown file.

How it would work:
- Run `expert-cli mcp` to start an MCP server (stdio transport)
- Register it in Claude Code's MCP config (`~/.claude/mcp.json`)
- Claude Code sees tools like `elixir_hover`, `elixir_definition`, etc.
- No CLAUDE.md instructions needed — tools are discovered automatically

```json
{
  "mcpServers": {
    "expert-cli": {
      "command": "expert-cli",
      "args": ["mcp"]
    }
  }
}
```

Benefits over CLAUDE.md approach:
- Zero-config for end users once installed
- Agent sees tool descriptions and schemas, uses them more reliably
- Works across all MCP-compatible agents (Claude Code, Cursor, etc.)
- Structured input/output instead of parsing CLI text

### Claude Code plugin

Package expert-cli as a publishable Claude Code plugin that users install with one command. Combines the MCP server with proper packaging and distribution.

What this adds over a standalone MCP server:
- `claude plugin install expert-cli` (or similar) — one-command setup
- Auto-configures MCP registration
- Version management and updates
- Could include slash commands (e.g., `/elixir-hover`)
- Shareable via plugin registry

### Distribution

- Publish to PyPI (`pip install expert-cli`)
- Standalone binary via PyInstaller or Nuitka (no Python required)
- Homebrew formula

## Long term

### Watch mode

`expert-cli watch diagnostics` — continuous output as files change. Useful for CI or terminal-based development workflows.

### Interactive mode

`expert-cli shell` — REPL-like interface for multiple queries without restarting. Could integrate with `fzf` for interactive symbol search.

### Generic LSP wrapper

Make the tool generic enough to wrap any LSP server, not just Expert. The core challenge (connection management, JSON-RPC framing, daemon lifecycle) is the same for any language server.

### Elixir rewrite

Rewrite in Elixir (escript or Burrito-packaged) for:
- Same ecosystem, natural fit
- No Python dependency
- Could ship as a Mix archive (`mix archive.install`)
- Better integration with Expert internals
