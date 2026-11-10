# Configuration and publication

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

## Inspect publication candidates

```bash
python scripts/check_publication.py
python scripts/check_publication.py --json
```

The guard checks both index content and working copies, plus non-ignored new
files. It reports category, path and line, never the matched value. It checks
credential/key patterns, URL credentials, personal home paths, non-example email
literals and tracked files covered by local ignore rules. Ignored files are not
read. Symlinks, unmerged entries and unsupported large files require review.

For additional identity checks, set `PUBLICATION_BLOCK_TERMS` locally to a
comma-separated list of your own literal identifiers. Do not commit the list.
The guard is bounded pattern detection; it cannot prove the absence of all
sensitive information and does not scan or rewrite Git history.

## Export working source for review

```bash
python scripts/export_source.py
```

This creates a new sandbox directory containing `source.zip` and a hash manifest.
It checks the publication candidates first, rechecks the exact text bytes it
packages and omits Git metadata and ignored content. Paths inside the archive and
manifest are relative to the checkout. The source ZIP contains current working
files, including publishable new files, rather than a historical Git snapshot.

Review the archive and its manifest before sharing. Generated host configuration
and raw runtime evidence remain local; exporting does not remove anything from
an existing remote repository or from earlier commits. Publishing and historical
cleanup are separate decisions.
