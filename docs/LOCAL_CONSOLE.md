# Local console

The React console provides a visual entrypoint for three offline operations:
offline acceptance, contract-baseline checking and evaluation of the supplied
synthetic responses. Results are real executions, with failures preserved.
An empty workspace shows no invented runs or measurements. The optional
[Connections](CONNECTIONS.md) view adds a target GET contract and provider-catalog
authentication checks; these explicitly configured operations can use the network.

## Start

On Linux, the [application launcher](LINUX_LAUNCHER.md) can start, reopen and stop
the console, and install an optional application-menu entry.

Prepare the core sandbox environment using the [README](../README.md). Node.js
22.12+ and npm are needed for the optional frontend build:

```bash
python scripts/console.py
```

The command copies frontend source to a fingerprinted sandbox directory,
installs the locked packages there, audits them and builds the assets. It never
installs `node_modules` into the checkout. Matching successful builds are reused;
the first build needs package-registry access. Reused assets do not constitute a
new dependency audit. React and Vite versions are pinned in `ui/package.json`
and the dependency lockfile is kept alongside the source.

Open the exact local session URL printed by the command. The server binds only
to `127.0.0.1` on an available port. The token is passed in the URL fragment,
removed from the address bar and kept in session storage for that browser tab.
Do not share the launch link. Press Ctrl+C to stop the server and its owned jobs;
retained evidence is preserved.

`--sandbox` selects another directory beneath `~/sandbox`; `--port` selects a
loopback port. To serve an existing build without Node.js at runtime:

```bash
python scripts/serve_console.py --assets /path/to/built/dist \
  --data-dir "$HOME/sandbox/enterprise-api-testing-framework/control"
```

## What the views mean

| View | Behavior |
|---|---|
| Overview | Choose a local check, start it and inspect recent outcomes. |
| Runs | Filter outcomes and open a count-only result summary. |
| History | Inspect a journal of run outcomes. It does not classify test flakiness or compare differing contexts. |
| Evaluation | Execute the four-record synthetic sample. No provider call or credential is involved. |
| Connections | Configure session-only target/provider credentials and run bounded network checks. |
| Connect MCP | Prepare the optional connector and copy a placeholder client template. |
| Architecture | Open the public interactive architecture in a separate tab. |

Setup instructions and placeholders are shown as instructions, not as working
connections. `running` is not `passed`; wait for a terminal result. Counts from
different checks have different units and overlapping test runs must not be
summed as unique coverage. The context-aware CLI history report remains the
interface for comparing matching tests, source and environment contexts.

## Local boundaries

The browser and [MCP connector](MCP.md) use the same stdlib control service.
Their default data directory is
`~/sandbox/enterprise-api-testing-framework/control/`. Use that same directory
when overriding either adapter if they should share runs and their execution
lock. Only one operation runs at a time across adapters sharing that directory.
The list is bounded to the most recent 200 run records.

The JSON API requires the session token; writes also require the exact same
Origin. Host checks reject alternate hostnames. The run API accepts only an
operation identifier. Connection settings use separate
authenticated routes with explicit URL/schema/credential fields. MCP tools accept
no URLs or credentials. No route accepts shell commands or arbitrary file paths.
Run responses contain generated IDs, operation, timestamps, status, fixed error
codes and whitelisted counts. Connection status responses expose configured and
credential-present flags plus the authentication mode, without returning profiles
or credentials. Target/provider check bodies are not saved. Existing offline raw
logs and source paths remain in sandbox and are not downloadable through this server.

This is a single-user local tool, without a hosted multi-user permission model.
Connections explicitly configures bounded external GET checks. Standalone MCP
shares disk history and the execution lock only; use the console bridge to share
in-memory connections. Retained offline raw evidence can contain machine paths
or application data; review it before
sharing. Log redaction covers configured credential patterns, nested credential
fields and URL userinfo/queries, not every possible application-specific secret.
POSIX shutdown closes owned process groups; Windows descendant cleanup has not
been verified.

## Browser acceptance

With an existing optional renderer installation that includes Puppeteer, set
`RENDERER_TOOLS` to that package root and run:

```bash
# Set CONSOLE_URL to the private launch link in this terminal only.
node scripts/check_console.mjs \
  --tools "$RENDERER_TOOLS" \
  --work-dir "$HOME/sandbox/enterprise-api-testing-framework/console-check-new"
```

The check executes actual offline, contract and evaluation jobs, tests keyboard/focus,
history navigation, mobile layout, and the session boundary. Its browser profile
is removed on completion; screenshots and a count-only check record remain in
the selected sandbox directory. The separate `scripts/check_connections.mjs`
acceptance uses `tests/fixtures/connections_console.py` with synthetic loopback
target/provider responses; it does not validate real provider accounts. See
[Connections](CONNECTIONS.md) for the supported behavior and credential lifetime.
Source-build guidance follows the official
[React integration guide](https://react.dev/learn/add-react-to-an-existing-project)
and [Vite documentation](https://vite.dev/guide/).
