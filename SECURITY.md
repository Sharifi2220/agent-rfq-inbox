# Security model of OpenQuote Lite 0.1

This document lists what the software protects against, how, and what it does **not** cover. Report vulnerabilities through [GitHub private vulnerability reporting](https://github.com/Sharifi2220/agent-rfq-inbox/security/advisories/new). Please do not open public issues with exploit details or personal data.

Supported version: `0.1.1a1` source alpha. There is no production deployment or security response service-level commitment.

## Assets

* Personal data in requests (names, contact details, postal codes, free text).
* The provider's attention: an inbox that a person reads.
* The provider's reputation: nothing may look like a quote or commitment it did not give.
* Integrity of the request history.

## Threats and controls

| Threat | Control in 0.1 | Residual risk |
|---|---|---|
| Flooding / spam to the inbox | Attempt budget per client (every attempt counts), per-contact daily budget, global daily cap, duplicate detection, kill switch (`pause`), size limit, rejections only counted, not stored | Distributed spam from many addresses can still fill the global cap; the cap protects the people, not availability |
| An agent smuggles a commitment ("I accept the price") | Commitment keys reject the whole request; fixed-wording receipts; `is_quote` / `is_commitment` always false | Free text can still claim anything; reviewers are told to treat it as untrusted |
| Prompt injection through request text into the provider's own AI tools | Requester text is never echoed to agents; CLI marks it as untrusted content; no AI runs inside OpenQuote Lite | If a provider pipes requests into an autonomous agent with tools, that agent must treat them as untrusted input |
| Unicode spoofing (Trojan-source style) | Bidi overrides/isolates and control characters rejected; NFC normalisation | Homoglyphs (e.g. Cyrillic letters) are not detected |
| Requests on behalf of someone else (fake contact data) | `authorization` confirmations required; reviewer contacts the person before any commitment | No contact verification in 0.1 (planned: optional double opt-in) |
| Replay of a copied request | Idempotency keys, 24-hour duplicate detection | A replay with altered content is a new request and counts against budgets |
| Status enumeration / data leakage | 144-bit random request ids, status documents without personal data, rate-limited lookups | Whoever holds a request id can see its coarse status |
| Malformed or hostile JSON | Strict parser: no duplicate keys, no NaN, depth ≤ 8, 32 KiB limit, schema with `additionalProperties: false` everywhere | - |
| SSRF / malware via links or attachments | The software never fetches URLs and accepts no attachments | Reviewers may still click links in free text |
| Tampering with history | Hash-chained audit log, `audit verify`, `audit head` to anchor the chain outside the database | Someone with write access to the database can rebuild the whole chain; only external anchors detect this |
| Information leakage in errors | Generic `internal_error`; built-in server logs omit client IP addresses and request ids | Reverse proxies and external WSGI servers may log separately |
| Client IP spoofing via proxy headers | `X-Forwarded-For` ignored unless `trust_proxy = true`; then the right-most hop is used | Misconfigured proxies weaken per-client limits |
| Supply chain | Core has zero runtime dependencies; MCP binding optional | The MCP SDK and its dependencies are outside this project's control |

## Not covered in 0.1

* Transport security: run behind a TLS reverse proxy. The built-in server binds to `127.0.0.1` by default and has no slow-client protection.
* Authentication of sending agents (e.g. signed agent cards, HTTP message signatures): planned.
* Remote administration: there is none; the inbox is operated locally via the CLI.
* Encryption at rest: use disk encryption on the host.
* Availability guarantees and backups: the operator's responsibility.

## Operator checklist

1. HTTPS only, behind a reverse proxy; `base_url` set to the public `https://` URL.
2. Data directory on a local, encrypted, backed-up disk; on POSIX the code requires mode 0700 for the data directory and 0600 for the SQLite file (enforce Windows ACLs separately).
3. `privacy purge --yes` scheduled daily; `audit head` stored outside the host weekly.
4. Profile reviewed: correct services, area, privacy notice URL and emergency note.
5. Staff briefed: request text is untrusted; never confirm prices or dates without speaking to the person.
