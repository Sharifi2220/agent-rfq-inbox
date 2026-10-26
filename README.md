# OpenQuote Lite

**A small, self-hosted endpoint that lets AI agents send bounded, machine-readable quote requests to a service provider, where a person reviews every request.**

**Public source alpha:** `v0.1.1a1`. The name is a working title; a commercial quoting product already uses “OpenQuote”. This project is independent and has no affiliation with it. See [name and provenance](docs/NAME_AND_PROVENANCE.md).

```
person ──asks──▶ personal agent ──request_quote──▶ OpenQuote Lite ──▶ local inbox ──▶ person at the provider
                       ◀── receipt: "received, a person will follow up" (never a quote) ──┘
```

## Why

Personal AI agents increasingly do errands for people: "get me offers for my gas boiler service". Today they phone businesses or scrape contact forms. OpenQuote Lite gives a small business one clean, safe door for exactly one action, **the quote request**:

* it has commercial value (most service jobs start with one),
* it is bounded: it cannot spend money, book a slot or commit a price,
* a person already reads every request today.

It deliberately builds on existing standards instead of inventing a new protocol: plain HTTPS + JSON Schema, an **MCP** server for agents, **schema.org** `AskAction` for discovery on the website, and the **RFC 9727** `/.well-known/api-catalog`.

## What it does - and refuses to do

| Does | Refuses |
|---|---|
| Accepts requests that match the provider profile (service, postal code, response types) | Accepting prices, confirming orders, booking appointments, carrying payment data: such fields reject the **whole** request (`commitment_not_allowed`) |
| Returns a fixed-wording receipt with `is_quote: false`, `is_commitment: false` | Emergencies: there is no `emergency` urgency; receipts say so |
| Keeps every request for human review in a local SQLite inbox | Fetching URLs, attachments, or running AI on request text |
| Idempotent retries, duplicate detection, per-client/contact/global rate limits, a kill switch | Echoing the requester's free text back to agents |
| Hash-chained pseudonymous audit log; manual/scheduled retention, export and partial erasure commands | Pretending profile data is verified (it is published as `self_declared`) |

## Quick start

```bash
git clone https://github.com/Sharifi2220/agent-rfq-inbox.git
cd agent-rfq-inbox
python -m pip install -e ".[mcp]"  # Python 3.11+; core has no runtime dependencies
openquote-lite init --dir my-office --base-url http://127.0.0.1:8787
cd my-office
# edit provider-profile.json (services, postal codes, privacy notice URL), then:
openquote-lite check-profile
openquote-lite serve                # HTTP API on 127.0.0.1:8787
```

Send a request (from another shell):

```bash
curl -s -X POST http://127.0.0.1:8787/api/v0/quote-requests \
     -H 'Content-Type: application/json' --data @../examples/quote-request.example.json
```

Work the inbox:

```bash
openquote-lite inbox list
openquote-lite inbox show oqr_...
openquote-lite inbox set oqr_... in_review
openquote-lite inbox set oqr_... follow_up_planned      # or: declined --reason no_capacity
openquote-lite pause --message "Holidays until 7 January"   # kill switch; `resume` to reopen
```

Connect an MCP client over stdio using [`examples/mcp-client-config.example.json`](examples/mcp-client-config.example.json). The MCP binding exposes `get_provider_profile`, `request_quote`, and `get_request_status`. The `request_quote` tool requires explicit confirmation that the person asked to send this request and agreed to contact. Streamable HTTP is also supported with `openquote-lite mcp --transport streamable-http`; secure that transport separately before remote use.

Put the discovery snippet on the provider's website:

```bash
openquote-lite jsonld > snippet.html     # <script type="application/ld+json"> with a schema.org AskAction
```

See the whole flow with four fictional providers: `python examples/demo_agent_providers.py`.

## Architecture

```text
HTTP (WSGI) ─┐
             ├─> validation + policy ─> SQLite inbox ─> local operator CLI
MCP tools ───┘          │                    │
                       └─ fixed receipt     └─ hash-chained audit log

provider-profile.json ─> public profile, JSON-LD and API catalog
```

The provider owns the profile, SQLite database and instance secret. HTTP and MCP call the same service layer, so both use the same validation, rate limits and non-binding receipts. Staff review and change statuses using the local CLI. See [architecture and data flow](docs/ARCHITECTURE.md).

## HTTP API

| Method | Path | Purpose |
|---|---|---|
| GET/HEAD | `/.well-known/api-catalog` | RFC 9727 API catalog (linkset+json) |
| GET | `/api/v0/profile` | provider profile (self-declared) |
| GET | `/api/v0/profile.jsonld` | schema.org JSON-LD |
| GET | `/api/v0/openapi.json` | OpenAPI 3.1 |
| GET | `/api/v0/schemas/{file}` | JSON Schemas |
| POST | `/api/v0/quote-requests` | submit a request → `201` receipt, `200` on idempotent retry |
| GET | `/api/v0/quote-requests/{id}` | status: `received`, `in_review`, `follow_up_planned`, `declined`, `closed` |

Errors always look like `{"openquote": "0.1", "error": {"code": "...", "message": "...", "details": [...]}}`. The normative description is in [`docs/SPEC.md`](docs/SPEC.md) and the JSON Schemas in `src/openquote_lite/schemas/`.

## Deployment notes

* The built-in server is for local evaluation. No public service is deployed by this repository. A future deployment needs a TLS reverse proxy, controlled `X-Forwarded-For` handling, abuse controls and operator review. Keep `trust_proxy = false` unless the proxy is trusted and appends the client address. A WSGI server can call `openquote_lite.http_api:app_from_env` with `OPENQUOTE_CONFIG` set.
* Keep the data directory on a local disk (SQLite WAL does not work on network or cloud-synced folders) and back it up.
* Run `openquote-lite privacy purge --yes` regularly (e.g. daily) and store `openquote-lite audit head` outside the database from time to time.
* Read [`SECURITY.md`](SECURITY.md) (threat model) and [`docs/PRIVACY.md`](docs/PRIVACY.md) before going live.

## Development

```bash
pip install -e ".[mcp,test]"
pytest
```

The tests include schema conformance against `jsonschema`, HTTP and MCP round trips, audit-chain concurrency and the demo. The alpha was tested on Windows with Python 3.11, 3.13 and 3.15; see [test evidence](docs/TEST_RESULTS.md) for the exact results and GitHub Actions status.

## Limits of this alpha

The software does not verify a sender's identity or consent. A request ID grants access to coarse status information. Erasure does not remove all traces from the audit log, SQLite WAL, backups or infrastructure logs. No production security, privacy or legal approval is claimed. Keep real requests off an internet-facing instance until these issues are addressed. See [security](SECURITY.md), [privacy](docs/PRIVACY.md), and [current limitations](LIMITATIONS.md).

## License

Apache License 2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE). No package is published to PyPI; install from this repository.
