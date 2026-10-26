# Data protection notes for operators

This is engineering guidance, not legal advice. Have the setup reviewed for your jurisdiction before going live.

## What is stored

| Data | Where | How long |
|---|---|---|
| Full request (name, contact, postal code, free text) | `requests.payload` | until `privacy erase` or the retention period (default 180 days) |
| Metadata (service id, urgency, status, timestamps) | `requests` | retention period |
| Pseudonymous hashes of client address and contact (HMAC with the instance secret) | `rate_events`, `requests.contact_hash` | 2 days (rate events), retention period |
| Idempotency keys | `idempotency` | 7 days |
| Daily rejection counters (code only) | `counters` | 400 days |
| Audit entries (event, pseudonymous request id, status/reason codes, acting role) | `audit_log` | retained; pseudonymous ids may remain personal data |

The bundled HTTP server does not log client IP addresses, query strings, or request ids. Proxies, hosting servers and application infrastructure may maintain independent logs; configure them separately.

## Built-in support

* Data minimisation: only postal code instead of street address; no attachments; requester free text is never sent back to agents.
* Information duty: the profile requires `privacy_notice_url`; it is published in the profile and JSON-LD so agents can show it to the person.
* Right of access: `openquote-lite privacy export <id>`.
* Erasure support: `openquote-lite privacy erase <id> --yes` removes payload, postal code, contact/content hashes, and language. Metadata and pseudonymous audit entries remain; this is not automatically full GDPR erasure in every case.
* Retention: `openquote-lite privacy purge --yes` deletes requests older than `retention_days` **only when called**; schedule this command externally (e.g. daily). No background scheduler is included.

## Points to clarify with a legal adviser

* Legal basis for processing requests (likely pre-contractual steps at the person's request) and the content of the privacy notice.
* Retention period suitable for your business; whether requests that became orders move to another system.
* Agents acting for third parties: the request carries the person's confirmation, but the reviewer should confirm directly with the person before acting.
* Consumer law on cost estimates: in Austria § 5(2) KSchG the correctness of a cost estimate underlying a consumer contract is deemed guaranteed unless expressly stated otherwise. OpenQuote Lite therefore never transmits prices or estimates; any estimate is given by a person, outside the tool.

**Additional limitations:** SQLite WAL pages, storage snapshots, filesystem recovery and backups may retain deleted values. Data erasure must be designed operationally and legally, not inferred solely from a SQL UPDATE or DELETE. Audit request IDs may remain linkable to a person; a lawful basis and retention schedule for the audit trail are still required.
