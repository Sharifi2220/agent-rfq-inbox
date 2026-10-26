# OpenQuote Lite request profile 0.1

Status: draft for pilot use, 2026-10-26. The key words MUST, MUST NOT, SHOULD and MAY are used as in RFC 2119.
The JSON Schemas in `src/openquote_lite/schemas/` are normative; this text explains them and adds the rules a schema cannot express.

## 1. Scope

OpenQuote Lite standardises **one** action between a person's agent and a service provider: *please get back to us about this need*. It covers a request for a quote, a site visit, a callback, an availability answer or documents.

Out of scope in 0.1, deliberately: prices, offers and cost estimates, appointment booking, orders, payments, attachments, identity verification of agents, emergencies.

## 2. Roles

| Role | Description |
|---|---|
| Requester | The person who needs the service. Always a human. |
| Sending agent | Software acting for the requester (personal AI agent, assistant, script). Its name is recorded and never trusted as identity. |
| Provider endpoint | An OpenQuote Lite instance run by or for one provider. |
| Reviewer | A person at the provider who decides on every request. |

## 3. Discovery

A provider SHOULD publish all three, generated from the same profile file:

1. `GET /api/v0/profile`: the provider profile (`provider-profile.schema.json`) plus `verification.status = "self_declared"` and an `endpoint` block.
2. schema.org JSON-LD on its website: a `LocalBusiness` with `makesOffer` and a `potentialAction` of type `AskAction` whose `target` is an `EntryPoint` (`urlTemplate`, `httpMethod: POST`, `contentType` and `encodingType` `application/json`).
3. `GET /.well-known/api-catalog` (RFC 9727): `application/linkset+json` with profile `https://www.rfc-editor.org/info/rfc9727`, linking the OpenAPI description (`service-desc`), the profile (`service-meta`) and the health endpoint (`status`).

Profile statements are self-declared. Agents MUST NOT present them as verified.

A sending agent SHOULD read the profile first and only send requests whose `service_id`, location and `wanted` types the profile covers.

## 4. Request document

`POST /api/v0/quote-requests` with `Content-Type: application/json`, UTF-8, at most 32 KiB by default.

| Field | Rule |
|---|---|
| `openquote` | MUST be `"0.1"`. |
| `idempotency_key` | 16-128 characters `[A-Za-z0-9._:-]`. Generated once per request by the sender and reused unchanged on retries. |
| `service.service_id` | One of the ids in the profile. |
| `service.summary` | 3-200 characters, single line, the requester's words. |
| `service.details` | Optional, up to 4000 characters, may contain line breaks. |
| `service.urgency` | `as_soon_as_possible`, `within_2_weeks` or `flexible`. There is no emergency value. |
| `service.object` | Optional equipment description: `kind`, `manufacturer`, `model`, `year_installed`, `notes`. |
| `service.requirements` | Optional, up to 10 items of 300 characters, kept exactly as written. |
| `location` | `country` (ISO 3166-1 alpha-2) and `postal_code` are required, `locality` optional. No street address. |
| `timing` | Optional wish window: `earliest_date`, `latest_date` (`YYYY-MM-DD`), `notes`. Never a booking. |
| `wanted` | 1-5 unique values of `quote`, `site_visit`, `callback`, `availability`, `documents`. |
| `requester` | `name` and `preferred_contact` (`email` or `phone`) required; the preferred channel's value MUST be present. Optional `language` (e.g. `de`, `de-AT`) and `is_business`. |
| `submitted_via` | `channel` (`agent` or `human`), optional `agent_name`, `agent_operator`. |
| `authorization` | `requested_by_person: true` and `contact_allowed: true`, both mandatory. |

No other fields are allowed at any level.

### 4.1 Text rules

All strings are normalised to Unicode NFC and trimmed. The endpoint MUST reject (`invalid_characters`) strings containing C0/C1 control characters, DEL, bidirectional embeddings, overrides or isolates (U+202A-U+202E, U+2066-U+2069), U+2028/U+2029 or an embedded U+FEFF. Line breaks and tabs are allowed only in `service.details`, `service.object.notes` and `timing.notes`. ZWJ, ZWNJ, LRM and RLM remain allowed because Persian, Arabic and emoji text need them.

### 4.2 Commitment rule

A request MUST NOT try to create a commitment. If any key at any depth, compared case-insensitively after removing `_`, `-` and spaces, matches the list in `validation.COMMITMENT_KEYS` (for example `accepted_price`, `confirmOrder`, `payment_token`, `booking`, `iban`, `signature`), the endpoint MUST reject the whole request with `commitment_not_allowed`. It MUST NOT silently drop the field.

Free text cannot be policed this way. Reviewers treat everything in the request as information from an untrusted sender.

## 5. Processing order and errors

0. Transport checks (HTTP binding): `415 unsupported_media_type`, `411 length_required`, `413 payload_too_large`, before the body is read.
1. Intake paused → `503 paused`.
2. Client attempt budget (every attempt counts, valid or not) → `429 rate_limited` with `Retry-After`.
3. Strict JSON (single object, no duplicate keys, no NaN/Infinity, depth ≤ 8) → `400 invalid_json`.
4. Commitment rule → `422 commitment_not_allowed`.
5. Text rules → `422 invalid_characters`.
6. Schema → `422 validation_failed` with `details[]` (`path`, `code`, `message`).
7. Semantics: missing preferred contact → `422 missing_contact`; impossible date, `latest_date` before yesterday, `earliest_date` more than two years ahead or reversed window → `422 invalid_date`.
8. Profile: `422 service_not_offered`, `422 outside_service_area`, `422 wanted_not_supported` (none of the wanted types accepted; a partial overlap is accepted and flagged `partially_supported`).
9. Idempotency: same key and same normalised body → `200` with the original receipt and `replayed: true`; same key, different body → `409 idempotency_conflict`.
10. Contact budget per day and global budget per day → `429 rate_limited`.
11. Identical content (service, location, requester name/email/phone) within 24 hours under a new key → `409 duplicate_request`. The response does not reveal the earlier request id.
12. Stored → `201` receipt.

Other errors: `405 method_not_allowed`, `404 not_found`, `500 internal_error` (without internal details).

## 6. Receipt

A receipt (`responses.schema.json#/$defs/receipt`) MUST contain `status: "received"`, `next_step: "human_review"`, `is_quote: false`, `is_commitment: false`, a fixed-wording `message` in German or English (by `requester.language`), a `notice` that this is not an emergency channel (plus the provider's `emergency_note`, if any), and a `status_url`.

A receipt MUST NOT contain any free text from the request. Sending agents MUST NOT describe a receipt to the person as a quote, price, appointment or order confirmation.

## 7. Status

`GET /api/v0/quote-requests/{request_id}` returns `received`, `in_review`, `follow_up_planned`, `declined` (with `decline_reason`: `outside_service_area`, `service_not_offered`, `no_capacity`, `duplicate`, `other`) or `closed`, again with `is_quote: false` and `is_commitment: false`. The request id (144 random bits) works as a capability; status documents contain no personal data. Lookups are rate limited per client.

Internal reviewer states and allowed transitions:

```
new ──▶ in_review ──▶ follow_up_planned ──▶ closed
 │          │                │
 ├──────────┴──▶ declined ◀──┘ ──▶ closed
 └──▶ spam (public: declined/other)
```

## 8. MCP binding

Tool names: `get_provider_profile` (read-only), `request_quote`, `get_request_status` (read-only). `request_quote` takes flat parameters that map one-to-one to the request document, plus two booleans `person_requested_this` and `person_agreed_to_be_contacted`; if either is false the tool refuses before anything is sent. Protocol errors are returned as tool errors carrying the error document.

## 9. Versioning

The `openquote` field carries the protocol version. Additive, backwards-compatible changes keep the `/api/v0` path. Breaking changes get a new version string and a new path prefix.

## 10. Planned (non-normative)

* A2A binding: an Agent Card at `/.well-known/agent-card.json` with a `request_quote` skill, mapped onto the same request document.
* Optional confirmation of the requester's contact address (double opt-in) before a request reaches the inbox.
* Structured, explicitly non-binding answers from the provider, signed off by a person.
* Linking `service.object` to a digital building or equipment record.
