# Linux launcher

`api-lab` is an executable Bash/Python launcher for the local React console and
optional stdio MCP server. It is a source-based launcher with runtime
dependencies, rather than a compiled binary or AppImage. Docker is optional and
is not used by this launcher.

## Prepare and open

Run from the checkout root on Linux with Python 3.11+, its `venv` module, Node.js
22.12+ and npm installed:

```bash
./api-lab setup
./api-lab start
```

Setup installs the pinned core requirements into
`~/sandbox/enterprise-api-testing-framework/venv`. Matching installed core
versions are reused. The first setup and frontend build need package-registry
access. No global pip installation or repository-local `node_modules` is used.

Start builds the frontend when needed, serves on loopback, opens the private
session link through `xdg-open` and reuses this checkout's running instance on
subsequent starts. Terminal-only use can start with `./api-lab start --no-open`
and open the printed link manually. Closing a tab leaves the server running.

```bash
./api-lab status
./api-lab stop
```

Stop verifies the saved process identity and command, then signals that process
through a Linux process handle. It does not stop other checkouts, unrelated
Python processes or containers. Retained run evidence is preserved. This
requires Linux process-handle support (`pidfd`, available on modern Linux).

The launcher places private state and logs under
`~/sandbox/enterprise-api-testing-framework/desktop/<checkout-id>/`; the state
contains the session token. Run data remains under the sandbox's `control/`.
Keep both private. `status --json` includes the private launch URL while running.

To select an already prepared core environment, put global options before the
subcommand and use the same sandbox for start, status and stop:

```bash
./api-lab --sandbox "$HOME/sandbox/enterprise-api-testing-framework" \
  --python "/path/to/prepared/venv/bin/python" start
```

Setup refuses to repair an arbitrary interpreter selected with `--python`.
Moving the checkout changes its application ID. Stop its old instance before
moving it and review any old menu entry separately.

## Application menu

After setup:

```bash
./api-lab install
```

This creates a checkout-specific API Testing Framework entry in the current user's
applications directory, normally `~/.local/share/applications/`. It contains
machine-local paths and belongs outside source control. Select API Testing Framework in your
Linux application menu to open it. No login autostart is configured. Installing
with `--sandbox` and `--python` captures those options in the menu entry.
An existing entry with differing contents requires manual review before replacement.

## MCP entrypoints

```bash
./api-lab mcp-setup --format claude
./api-lab mcp-setup --format codex
./api-lab mcp
```

Setup prepares the separate SDK environment and prints configuration; it does
not edit Claude or Codex settings. `mcp` is a stdio process intended to be
started by a host, with no console browser or normal text on stdout. Its
default SDK Python is `<sandbox>/mcp/venv/bin/python`; `--sdk-python` selects an
existing isolated SDK interpreter. The generated configuration directly starts
the SDK Python, as described in the [MCP guide](MCP.md).

Use `./api-lab mcp-setup --console --format codex` (or `claude`) to share the
running console's Connections profiles. Optional connection checks contact the
configured target or provider catalog; the connector does not generate model text.
The `mcp` subcommand itself starts standalone MCP with separate process memory;
use the bridge configuration printed by `mcp-setup --console` when browser-entered
credentials should be shared. Stopping the console clears its profiles and makes
bridge calls unavailable. Closing a bridge host leaves the console running.
Actual host authentication and tool permissions remain the host's responsibility.
See [Connections](CONNECTIONS.md) for target/schema limits and key lifetime.
