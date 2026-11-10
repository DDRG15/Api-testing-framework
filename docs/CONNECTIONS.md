# Connections and optional BYOK

Connections adds explicit network checks alongside the existing offline checks.
An AI-provider key is optional. Credentials for the API under test and credentials
for a model provider are separate. The application does not generate model text.

## Check your API

1. Open **Connections** and enter one full JSON endpoint URL.
2. Choose no authentication, a Bearer token or an API-key header. For a custom
   header, enter its name, such as `X-API-Key`, and its value separately.
3. Set the expected successful HTTP status (200–299) and an inline JSON Schema.
4. Select **Save for this session**, then **Check target**. Saving configuration
   makes no remote request and does not verify the credential.
5. Save edited fields before checking. A reloaded target form must be re-entered
   and saved before it can run, so an undisplayed old target is not checked.
6. Wait for the run's terminal outcome. Inspect its count-only summary in Runs.

For example, the initial schema expects an object whose `status` equals `ok`.
Adapt it to your actual endpoint. The URL placeholder is not a configured API.
The check sends one GET and validates both status and JSON Schema. It does not
adapt the existing booking CRUD suite, discover endpoints or test a complete API.
Schemas use Draft 2020-12. Schema `format` is not enforced, and schema references
are not supported. The schema must be a nonempty object within the configured
size and traversal limits; it is not an OpenAPI document or an endpoint-discovery
configuration.

HTTPS is required, with HTTP permitted on loopback for local APIs. Credentials,
query strings and fragments in URLs are rejected. Requests do not follow
redirects, retry, use proxy environment variables or send browser cookies.
Compressed responses are rejected; the body limit is 1 MiB. Socket operations
have a five-second timeout and body reads check an eight-second budget. The whole
network/validation operation, including DNS and schema CPU time, runs in an
owned worker with a ten-second parent-enforced deadline (or a shorter configured
service timeout). Termination cleanup can add up to two seconds. Profiles cross
a memory pipe, never command arguments, environment variables or files.
Only JSON responses are supported. Error responses and payloads are not echoed.

## Optional provider keys

Enter your own OpenAI or Anthropic key in its separate form, save, and select
**Check authentication**. The backend sends a single GET to the provider's fixed
model-catalog endpoint. A successful status and catalog-shaped JSON response
pass this bounded check; catalog contents are not returned or saved.

This does not generate tokens, evaluate model output, prove access to a particular
inference endpoint or establish a cost estimate. Provider permissions, billing
and availability remain external. Verification of this implementation uses
synthetic loopback catalogs, not a real account. See the official
[OpenAI model-list API](https://developers.openai.com/api/reference/resources/models/methods/list)
and [Anthropic model-list API](https://platform.claude.com/docs/en/api/models/list).

## Credential lifetime

Password fields clear when a valid form is submitted. Credentials travel to the authenticated
loopback backend and remain in that service process's memory and briefly in its owned check worker; they are not
saved by the app in browser storage, files, environment variables or subprocess
arguments. Status APIs expose configured/key-present flags, not key prefixes,
URLs, header values or schemas. Results persist only fixed codes and counts.

Closing a tab leaves the console and its credentials running. **Disconnect** or
**Disconnect all connections** removes saved profiles. Restarting/stopping the
console forgets them. An in-flight request keeps its captured profile until it
finishes. Python strings are not guaranteed to be securely erased from memory;
this is a local single-user process, not a hardware-backed credential vault.
Browser developer tools can inspect your own submitted requests. The existing
console session token is separate and remains in tab session storage.

## VS Code through the MCP console bridge

Start the Linux console, then generate configuration for the desired host:

```bash
./api-lab mcp-setup --console --format codex
./api-lab mcp-setup --console --format claude
```

Use the same global `--sandbox`/`--python` options as your console when customized.
The helper prints machine-local configuration; it does not modify host settings.
Copy the output into your host's MCP settings as described in the [MCP guide](MCP.md).
The bridge reads the private launcher state on each call, including after a
restart. The console must remain running. A restart also clears its connections.
Connection settings are entered explicitly in the UI; existing booking `.env`
configuration is not imported into these profiles.

The underlying bridge command uses the isolated SDK Python:

```text
<MCP_VENV_PYTHON> <PROJECT_ROOT>/scripts/mcp_server.py --console-state <CONSOLE_STATE_JSON>
```

Ask the assistant to inspect `connections`, then use `start_run` with `target`,
`openai` or `anthropic` and poll `get_run`. These operations can make the configured
network request. Enter secrets in Connections, never in chat or tool arguments.
No MCP tool configures a URL or accepts a credential. Closing the MCP bridge
does not close the user-owned console. Actual authenticated editor-host sessions
require separate local registration and verification.

Without `--console-state`, standalone MCP runs in a separate process and cannot
see credentials entered in the browser. Sharing a data directory shares run
history and the execution lock, not process memory.

## Acceptance checks

`tests/offline/test_connections.py` covers loopback requests, schema failures,
redirect refusal, authentication headers, secret-free evidence and the bridge.
`tests/fixtures/connections_console.py` plus `scripts/check_connections.mjs`
exercise the real frontend against explicitly synthetic catalogs and target.
All generated fixture state, browser profiles and evidence belong in sandbox.
