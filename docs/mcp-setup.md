# EAB MCP Server Setup

Connect Claude Desktop (or any MCP-compatible client) directly to your embedded
devices via the Embedded Agent Bridge MCP server.

## Quickstart

```bash
pip install "embedded-agent-bridge[mcp]"   # install with MCP extra
eabctl start --port /dev/ttyUSB0            # start the EAB daemon first
eabmcp                                      # launch the MCP server (stdio)
```

## Claude Desktop Configuration

Add the following block to your `claude_desktop_config.json`
(usually `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "embedded-agent-bridge": {
      "command": "eabmcp",
      "args": [],
      "env": {}
    }
  }
}
```

If `eabmcp` is not on your `$PATH`, use the full path instead:

```json
{
  "mcpServers": {
    "embedded-agent-bridge": {
      "command": "/path/to/venv/bin/eabmcp",
      "args": [],
      "env": {}
    }
  }
}
```

Restart Claude Desktop after saving the config.  The EAB tools will appear in
the **Tools** panel automatically.

## Available MCP Tools

| Tool | Description |
|------|-------------|
| `eab_status` | Daemon status: running, PID, port, uptime |
| `eab_tail` | Last N lines of the device serial log |
| `eab_wait` | Wait for a regex pattern in the log |
| `eab_send` | Send a command to the device |
| `eab_reset` | Hardware-reset the device |
| `eab_fault_analyze` | Analyze Cortex-M fault registers via debug probe |
| `eab_rtt_tail` | Last N lines of the J-Link RTT log |
| `eab_regression` | Run hardware-in-the-loop regression tests |

## Alternative: eabctl mcp-server

You can also launch the MCP server through the standard `eabctl` dispatcher:

```bash
eabctl mcp-server
```

This is useful if you prefer a single binary entry point or want to pass
`--base-dir` / `--device` global flags.
