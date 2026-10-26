# Changelog

## 0.1.1a1 - 2026-10-26 (first public source alpha)

* Incorporated the independent `0.1.1rc1` review: strict URL and proxy configuration parsing, private POSIX database permissions, safer HTTP logs, erasure of direct pseudonymous hashes and language, role-based CLI audit actor, and inquiry-oriented `AskAction` JSON-LD.
* Escaped all `<` characters in embeddable JSON-LD script content to prevent a provider name from closing the script tag, including mixed-case closing tags.
* Published installation, architecture, API/MCP, security, privacy, contribution, provenance and limitation documentation under Apache-2.0. Added Linux and Windows CI with Python 3.11 and 3.13.
* The original `0.1.0` source and the review candidate remain preserved in the owner's project archive; dated review evidence is in `docs/history`.

This alpha has no public deployment, sender identity proof or completed legal review. See `LIMITATIONS.md` and `docs/TEST_RESULTS.md`.

## 0.1.0 - 2026-10-26 (not published)

First reference implementation.

* Request profile 0.1 with JSON Schemas for requests, provider profiles and responses.
* Dependency-free core: strict parsing, commitment rule, Unicode rules, schema interpreter checked against the `jsonschema` reference library.
* SQLite store with idempotency, duplicate detection, rate limits, kill switch, retention, export and erasure.
* Hash-chained audit log (later review clarified that identifiers may still be personal data).
* HTTP API (WSGI) with RFC 9727 API catalog, OpenAPI 3.1 and schema.org JSON-LD (`QuoteAction`).
* MCP binding (MCP Python SDK 2.x) with three tools.
* CLI inbox for reviewers.
* Demo with four fictional providers.

## 0.1.1rc1 (2026-10-26) — independent review candidate, unpublished
- Parse and validate base URL as an origin; reject lookalike plaintext hosts, credentials and query/fragment. Require real TOML boolean for proxy trust.
- Protect POSIX SQLite storage against world/group access and redact raw HTTP target/query logs.
- Clear direct pseudonymous contact/content hashes and language on request erasure; clarify remaining identifiers and external retention scheduling.
- Make CLI audit actor role-based rather than OS username.
- Replace misleading schema.org `QuoteAction` with inquiry-oriented `AskAction` (candidate semantic correction).
- Add 5 focused security/privacy regression tests, GitHub CI and contributor/release documentation.
- Existing original reference retained separately; the review's own test results excluded MCP tests in its environment.
