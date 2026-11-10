# Framework architecture

The framework exercises API contracts, HTTP client resilience, and persisted effects while retaining evidence for each test attempt. The [README](../README.md) describes installation and commands.

**[Open the interactive architecture](architecture.html)** in a browser. Hover or focus a node to highlight its immediate connections; click or press Enter/Space to pin it. Incoming connections are blue and outgoing connections are amber. Escape or Clear selection resets the view. The viewer embeds its diagram and interaction code; it does not need a CDN or a running server.

## Structure and test flow

```mermaid
---
config:
  themeCSS: |
    .root:has(.node:hover) .edgePaths path { opacity: 0.16; }
    .root:has(.node[id*="flowchart-Console-"]:hover) path[id*="_Console_"], .root:has(.node[id*="flowchart-Console-"]:hover) path[id*="-Console-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Console-"]:hover) path[id*="L_Console_"], .root:has(.node[id*="flowchart-Console-"]:hover) path[id*="L-Console-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-MCP-"]:hover) path[id*="_MCP_"], .root:has(.node[id*="flowchart-MCP-"]:hover) path[id*="-MCP-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-MCP-"]:hover) path[id*="L_MCP_"], .root:has(.node[id*="flowchart-MCP-"]:hover) path[id*="L-MCP-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Control-"]:hover) path[id*="_Control_"], .root:has(.node[id*="flowchart-Control-"]:hover) path[id*="-Control-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Control-"]:hover) path[id*="L_Control_"], .root:has(.node[id*="flowchart-Control-"]:hover) path[id*="L-Control-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-OfflineCI-"]:hover) path[id*="_OfflineCI_"], .root:has(.node[id*="flowchart-OfflineCI-"]:hover) path[id*="-OfflineCI-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-OfflineCI-"]:hover) path[id*="L_OfflineCI_"], .root:has(.node[id*="flowchart-OfflineCI-"]:hover) path[id*="L-OfflineCI-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Runner-"]:hover) path[id*="_Runner_"], .root:has(.node[id*="flowchart-Runner-"]:hover) path[id*="-Runner-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Runner-"]:hover) path[id*="L_Runner_"], .root:has(.node[id*="flowchart-Runner-"]:hover) path[id*="L-Runner-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-LiveCI-"]:hover) path[id*="_LiveCI_"], .root:has(.node[id*="flowchart-LiveCI-"]:hover) path[id*="-LiveCI-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-LiveCI-"]:hover) path[id*="L_LiveCI_"], .root:has(.node[id*="flowchart-LiveCI-"]:hover) path[id*="L-LiveCI-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-ConfigCI-"]:hover) path[id*="_ConfigCI_"], .root:has(.node[id*="flowchart-ConfigCI-"]:hover) path[id*="-ConfigCI-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-ConfigCI-"]:hover) path[id*="L_ConfigCI_"], .root:has(.node[id*="flowchart-ConfigCI-"]:hover) path[id*="L-ConfigCI-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Settings-"]:hover) path[id*="_Settings_"], .root:has(.node[id*="flowchart-Settings-"]:hover) path[id*="-Settings-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Settings-"]:hover) path[id*="L_Settings_"], .root:has(.node[id*="flowchart-Settings-"]:hover) path[id*="L-Settings-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Offline-"]:hover) path[id*="_Offline_"], .root:has(.node[id*="flowchart-Offline-"]:hover) path[id*="-Offline-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Offline-"]:hover) path[id*="L_Offline_"], .root:has(.node[id*="flowchart-Offline-"]:hover) path[id*="L-Offline-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Live-"]:hover) path[id*="_Live_"], .root:has(.node[id*="flowchart-Live-"]:hover) path[id*="-Live-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Live-"]:hover) path[id*="L_Live_"], .root:has(.node[id*="flowchart-Live-"]:hover) path[id*="L-Live-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Evaluation-"]:hover) path[id*="_Evaluation_"], .root:has(.node[id*="flowchart-Evaluation-"]:hover) path[id*="-Evaluation-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Evaluation-"]:hover) path[id*="L_Evaluation_"], .root:has(.node[id*="flowchart-Evaluation-"]:hover) path[id*="L-Evaluation-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Snapshots-"]:hover) path[id*="_Snapshots_"], .root:has(.node[id*="flowchart-Snapshots-"]:hover) path[id*="-Snapshots-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Snapshots-"]:hover) path[id*="L_Snapshots_"], .root:has(.node[id*="flowchart-Snapshots-"]:hover) path[id*="L-Snapshots-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Mutation-"]:hover) path[id*="_Mutation_"], .root:has(.node[id*="flowchart-Mutation-"]:hover) path[id*="-Mutation-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Mutation-"]:hover) path[id*="L_Mutation_"], .root:has(.node[id*="flowchart-Mutation-"]:hover) path[id*="L-Mutation-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Booking-"]:hover) path[id*="_Booking_"], .root:has(.node[id*="flowchart-Booking-"]:hover) path[id*="-Booking-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Booking-"]:hover) path[id*="L_Booking_"], .root:has(.node[id*="flowchart-Booking-"]:hover) path[id*="L-Booking-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Billing-"]:hover) path[id*="_Billing_"], .root:has(.node[id*="flowchart-Billing-"]:hover) path[id*="-Billing-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Billing-"]:hover) path[id*="L_Billing_"], .root:has(.node[id*="flowchart-Billing-"]:hover) path[id*="L-Billing-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-HTTP-"]:hover) path[id*="_HTTP_"], .root:has(.node[id*="flowchart-HTTP-"]:hover) path[id*="-HTTP-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-HTTP-"]:hover) path[id*="L_HTTP_"], .root:has(.node[id*="flowchart-HTTP-"]:hover) path[id*="L-HTTP-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Public-"]:hover) path[id*="_Public_"], .root:has(.node[id*="flowchart-Public-"]:hover) path[id*="-Public-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Public-"]:hover) path[id*="L_Public_"], .root:has(.node[id*="flowchart-Public-"]:hover) path[id*="L-Public-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Lab-"]:hover) path[id*="_Lab_"], .root:has(.node[id*="flowchart-Lab-"]:hover) path[id*="-Lab-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Lab-"]:hover) path[id*="L_Lab_"], .root:has(.node[id*="flowchart-Lab-"]:hover) path[id*="L-Lab-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-DB-"]:hover) path[id*="_DB_"], .root:has(.node[id*="flowchart-DB-"]:hover) path[id*="-DB-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-DB-"]:hover) path[id*="L_DB_"], .root:has(.node[id*="flowchart-DB-"]:hover) path[id*="L-DB-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Oracle-"]:hover) path[id*="_Oracle_"], .root:has(.node[id*="flowchart-Oracle-"]:hover) path[id*="-Oracle-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Oracle-"]:hover) path[id*="L_Oracle_"], .root:has(.node[id*="flowchart-Oracle-"]:hover) path[id*="L-Oracle-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Context-"]:hover) path[id*="_Context_"], .root:has(.node[id*="flowchart-Context-"]:hover) path[id*="-Context-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Context-"]:hover) path[id*="L_Context_"], .root:has(.node[id*="flowchart-Context-"]:hover) path[id*="L-Context-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-HistoryReport-"]:hover) path[id*="_HistoryReport_"], .root:has(.node[id*="flowchart-HistoryReport-"]:hover) path[id*="-HistoryReport-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-HistoryReport-"]:hover) path[id*="L_HistoryReport_"], .root:has(.node[id*="flowchart-HistoryReport-"]:hover) path[id*="L-HistoryReport-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Hooks-"]:hover) path[id*="_Hooks_"], .root:has(.node[id*="flowchart-Hooks-"]:hover) path[id*="-Hooks-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Hooks-"]:hover) path[id*="L_Hooks_"], .root:has(.node[id*="flowchart-Hooks-"]:hover) path[id*="L-Hooks-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Events-"]:hover) path[id*="_Events_"], .root:has(.node[id*="flowchart-Events-"]:hover) path[id*="-Events-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Events-"]:hover) path[id*="L_Events_"], .root:has(.node[id*="flowchart-Events-"]:hover) path[id*="L-Events-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Summary-"]:hover) path[id*="_Summary_"], .root:has(.node[id*="flowchart-Summary-"]:hover) path[id*="-Summary-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Summary-"]:hover) path[id*="L_Summary_"], .root:has(.node[id*="flowchart-Summary-"]:hover) path[id*="L-Summary-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Artifacts-"]:hover) path[id*="_Artifacts_"], .root:has(.node[id*="flowchart-Artifacts-"]:hover) path[id*="-Artifacts-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Artifacts-"]:hover) path[id*="L_Artifacts_"], .root:has(.node[id*="flowchart-Artifacts-"]:hover) path[id*="L-Artifacts-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Bridge-"]:hover) path[id*="_Bridge_"], .root:has(.node[id*="flowchart-Bridge-"]:hover) path[id*="-Bridge-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Bridge-"]:hover) path[id*="L_Bridge_"], .root:has(.node[id*="flowchart-Bridge-"]:hover) path[id*="L-Bridge-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Vault-"]:hover) path[id*="_Vault_"], .root:has(.node[id*="flowchart-Vault-"]:hover) path[id*="-Vault-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Vault-"]:hover) path[id*="L_Vault_"], .root:has(.node[id*="flowchart-Vault-"]:hover) path[id*="L-Vault-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Probe-"]:hover) path[id*="_Probe_"], .root:has(.node[id*="flowchart-Probe-"]:hover) path[id*="-Probe-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Probe-"]:hover) path[id*="L_Probe_"], .root:has(.node[id*="flowchart-Probe-"]:hover) path[id*="L-Probe-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Remote-"]:hover) path[id*="_Remote_"], .root:has(.node[id*="flowchart-Remote-"]:hover) path[id*="-Remote-"] { stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }
    .root:has(.node[id*="flowchart-Remote-"]:hover) path[id*="L_Remote_"], .root:has(.node[id*="flowchart-Remote-"]:hover) path[id*="L-Remote-"] { stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }
---
flowchart LR
    subgraph Entry["Entry points and automation"]
        Console["React console<br/>Loopback session"]
        MCP["MCP stdio adapter<br/>Isolated SDK"]
        Control["src/control/service.py<br/>Bounded local operations"]
        OfflineCI["offline-tests.yml"]
        Runner["scripts/run_offline.py"]
        LiveCI["live-demo.yml"]
        ConfigCI["api-tests.yml<br/>Configured integration"]
    end
    subgraph Tests["Tests and configuration"]
        Settings["config/settings.py"]
        Offline["tests/unit + tests/offline<br/>Controlled failures"]
        Live["tests/functional + tests/contract<br/>Canary before CRUD"]
        Evaluation["evaluate_responses.py<br/>Recorded response checks"]
        Snapshots["src/utils/contracts.py<br/>fixtures/contracts/*.json"]
        Mutation["scripts/mutation_check.py<br/>Isolated copies and seeded defects"]
    end
    subgraph Clients["Client and adapters"]
        Booking["booking_client.py<br/>Pydantic models"]
        Billing["billing_client.py<br/>Synthetic events"]
        HTTP["base_client.py<br/>Retry, breaker, timeout,<br/>TLS and correlation-ID"]
    end
    subgraph Targets["Systems under test"]
        Public["Restful-Booker<br/>External demo API"]
        Lab["tests/fixtures/billing_server.py<br/>Synthetic local HTTP server"]
        DB[("Test SQLite database")]
        Oracle["src/utils/db_oracle.py<br/>Read only"]
    end
    subgraph Evidence["Evidence per run"]
        Context["run_context.py<br/>Source and environment provenance"]
        HistoryReport["build_history_report.py<br/>Comparable-run heatmap"]
        Hooks["conftest.py + test_results.py<br/>Phase, attempt and result"]
        Events["JSONL results<br/>Run context"]
        Summary["scripts/summarize_results.py<br/>Summary with reruns"]
        Artifacts["Reports and logs<br/>Isolated directory"]
    end
    Console --> Control
    MCP --> Control
    MCP --> Bridge["Console bridge<br/>Authenticated loopback"]
    Bridge --> Control
    Console --> Vault["Connections<br/>Process-memory profiles"]
    Control --> Vault
    Vault --> Probe["Bounded GET check<br/>Inline JSON Schema or catalog"]
    Probe --> Remote["Configured JSON endpoint<br/>or fixed provider catalog"]
    Control --> Runner
    Control --> Snapshots
    Control --> Evaluation
    OfflineCI --> Runner --> Offline
    LiveCI --> Live
    ConfigCI --> Live
    Settings --> HTTP
    Offline --> Snapshots
    Mutation --> Offline
    Offline --> Billing
    Offline --> HTTP
    Live --> Booking --> HTTP
    Billing --> HTTP
    HTTP --> Public
    HTTP --> Lab --> DB
    Offline --> Oracle --> DB
    Offline --> Hooks
    Live --> Hooks
    Hooks --> Events --> Summary --> Artifacts
    HTTP --> Artifacts
    Runner --> Context --> Hooks
    Events --> HistoryReport --> Artifacts
    Offline --> Evaluation --> Artifacts
```

The offline path uses a test-owned HTTP server, SQLite, and synthetic data. The external path requires a configured, available API and permission to create and remove test resources. Database assertions independently check persistence: HTTP 200 alone does not establish that the stored effect is correct.

Markdown hover highlighting depends on a preview that supports Mermaid custom CSS and CSS `:has()`. The standalone HTML viewer provides pinned selection and keyboard navigation without changing editor security settings.

## Components

| Location | Responsibility |
|---|---|
| `config/settings.py` | Validate configuration, timeouts, and transport requirements. |
| `src/client/base_client.py` | Apply replay policy, transient-error handling, retry limits, breaker state, and correlation IDs. |
| `src/client/booking_client.py` and `src/models/booking.py` | Adapt the booking API and validate modeled requests and responses. |
| `src/utils/contracts.py` and `fixtures/contracts/` | Compare generated model schemas with the versioned local baseline. |
| `conftest.py`, `src/utils/run_context.py` and `src/utils/test_results.py` | Record phases, attempts, and run context while retaining initial failures and setup/teardown outcomes. |
| `src/client/billing_client.py` and `tests/fixtures/billing_server.py` | Exercise signed synthetic event delivery, concurrency, and lost responses against a controlled reference. |
| `src/utils/db_oracle.py` | Check persisted effects with approved parameterized queries and a read-only connection. |
| `scripts/run_offline.py` | Execute isolated local checks and preserve reports, versions, commands, exit status, and hashes. |
| `scripts/summarize_results.py` | Produce per-run summaries without hiding reruns or incomplete evidence. |
| `scripts/mutation_check.py` | Check selected source defects in temporary copies after a passing baseline. |
| `scripts/build_history_report.py` | Build a context-grouped history report from recorded phase evidence. |
| `scripts/evaluate_responses.py` | Check captured structured responses against configured deterministic rules. |
| `.github/workflows/` | Run reproducible checks and configured external acceptance tests, then retain artifacts. |

The optional [local console](LOCAL_CONSOLE.md) and [MCP adapter](MCP.md) share a bounded operation service. They accept fixed operation identifiers and expose sanitized summaries. They do not expose arbitrary commands, files or live API execution.

## Execution boundaries

- HTTP retries happen inside one client request. Pytest reruns repeat a test and may create new resources; their evidence is recorded separately.
- Explicit replay permission assumes a server-side deduplication contract. Adding an idempotency header does not create that contract.
- The in-memory breaker coordinates threads within one process. The Redis implementation requires a separately configured service to coordinate processes.
- The synthetic billing lab is not a Stripe integration, and SQLite results do not establish PostgreSQL guarantees or isolation behavior.
- Model snapshots describe the local schema baseline. They do not establish all OpenAPI compatibility rules or every consumer's expectations.
- History reports only compare recorded observations within their context. They do not quarantine tests automatically.
- Response evaluation works on captured data. It does not establish a live AI provider's accuracy, availability, or latency distribution.

## Rebuild and check the viewer

Rendering tools are optional development dependencies. Rendering needs Mermaid CLI; pass its paths explicitly; keep generated outputs and browser profiles in sandbox. With those tools and a local browser available:

```bash
# Set MMDC to the existing CLI and RENDERER_TOOLS to its package directory.
: "${MMDC:?Set the Mermaid CLI executable path}"
: "${RENDERER_TOOLS:?Set the renderer package directory}"
python scripts/build_diagram_viewer.py \
  --mmdc "$MMDC" \
  --browser /usr/bin/google-chrome --add-hover
node scripts/check_diagram_viewer.mjs --tools "$RENDERER_TOOLS"
```

The build command updates the public Markdown hover rules and generates `docs/architecture.html`. The browser check exercises highlighting, pinned selection, keyboard behavior, and local-only loading. Temporary rendering files and browser profiles stay under sandbox; the generated viewer is a durable project artifact.

## Recorded evidence tools

`build_history_report.py` compares phase records only within matching source/environment contexts and known chronology. It exposes review candidates without automatically quarantining tests. `evaluate_responses.py` checks recorded responses against JSON Schema and approved numeric invariants; it does not call a model provider. See the README for commands and sample inputs.

Connections stores session profiles in process memory. The optional MCP bridge
shares that console session; standalone MCP shares only disk history/locking.
Network checks persist counts and fixed codes, not profiles or remote payloads.
See [Connections](CONNECTIONS.md) for supported checks and verification limits.
