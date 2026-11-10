# Configuration

## Replace placeholders for external tests

Offline checks, the local console and MCP setup need no `.env`. The optional
[Connections](CONNECTIONS.md) forms configure their own session-only endpoint,
schema and credentials; they do not import or save the booking environment
configuration. Provider keys are optional for catalog authentication checks and
are separate from the target API credential and the MCP host's own sign-in.

External booking tests currently require a Restful-Booker-compatible booking/authentication API
that permits creating and deleting synthetic records. Another API requires
adapted clients and tests, not only a different base URL. Copy `.env.example` to an ignored `.env`, then configure:

| Field | Supply |
|---|---|
| `API_BASE_URL` | The HTTPS base URL of the test API. `api.example.com` is a reserved example, not a working target. |
| `API_USERNAME`, `API_PASSWORD` | Dedicated test credentials from your environment or secret store. Replace the `YOUR_...` placeholders. |
| `API_TOKEN` | Optional pre-issued token; otherwise leave blank. |
| `SSL_CA_BUNDLE` | Optional local CA bundle path; blank uses the normal verified defaults. |
| `LOG_FILE` | An absolute path inside your sandbox. Replace `/path/to/your/sandbox`. |
| `REDIS_URL` | Blank for serial execution; configure a test Redis for shared breaker state across workers. |

The separate public-demo workflow explicitly uses the demonstration provider's
published example credentials. Those are not credentials for your own API.
Never copy private values into React source, MCP client templates, YAML,
screenshots or committed configuration.

The image workflow derives a lowercase registry name from its current GitHub
repository. The Kubernetes manifest deliberately uses `example-org` and
`<DIGEST>` placeholders: replace both with a reviewed image before deployment.
No image is built or deployed simply by editing these templates locally.

## Scan for secrets

```bash
python scripts/check_publication.py
python scripts/check_publication.py --json
```

The scan checks tracked files, working copies and non-ignored new files for
credential and key patterns, URL credentials, personal home paths and non-example
email addresses. It reports category, path and line, never the matched value.
Set `PUBLICATION_BLOCK_TERMS` to a comma-separated list of extra literal terms to
block. It is pattern detection: it cannot prove that no sensitive value exists.

## Source archive

```bash
python scripts/export_source.py
```

Runs the scan, then writes `source.zip` and a hash manifest to a new directory.
The archive omits Git metadata and ignored files.
