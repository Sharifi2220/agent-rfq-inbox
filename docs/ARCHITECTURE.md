# Architecture

OpenQuote Lite accepts one kind of write: a request for a human to consider a quote. It does not generate a quote, book a visit or contact the requester automatically.

## Components

| Component | Responsibility |
|---|---|
| `profile.py` | Validates one provider profile and derives the public profile, schema.org JSON-LD and RFC 9727 catalog. These are self-declared provider facts. |
| `http_api.py` | Dependency-free WSGI HTTP adapter, JSON transport checks and public API endpoints. |
| `mcp_server.py` | Optional MCP SDK adapter with three tools. It builds the same request JSON used by HTTP. |
| `validation.py` and `schema_engine.py` | Strict JSON parsing, schema checks, service-area and commitment policy. |
| `service.py` | Shared acceptance, idempotency, duplicate detection, rate limits, status and operator operations. |
| `store.py` and `audit.py` | Local SQLite state, short transactions and a hash-chained audit trail. |
| `cli.py` | Local operator inbox and privacy commands; no remote admin API. |

## Request path

1. The provider edits `provider-profile.json` and checks it with the CLI.
2. An HTTP or MCP client submits a bounded JSON request after the person authorizes it. The authorization fields are declarations and do not prove identity or consent.
3. The transport enforces its size and format rules. The service validates the request against the profile, checks limits and duplicates, then writes it to SQLite in one transaction.
4. The client receives a fixed receipt with `is_quote: false` and `is_commitment: false`. It may poll coarse status with the random request ID.
5. A person reads the local inbox and decides whether to follow up. The tool never sends that follow-up.

The instance secret keys HMAC buckets for rate limits and duplicate checks. It is separate from the database. The audit chain detects edits only when a prior head hash has been anchored outside the database; it is not a tamper-proof log by itself.

## Data ownership and deployment boundary

The provider controls the profile, instance secret and SQLite directory. The built-in WSGI server binds to loopback by default and is intended for local evaluation. `trust_proxy` changes how the client address is interpreted; it must only be used with a correctly configured trusted reverse proxy. SQLite WAL requires local storage. Operators must plan backups, retention scheduling, disk encryption and access control separately.

See [the protocol specification](SPEC.md), [security model](../SECURITY.md) and [privacy notes](PRIVACY.md).
