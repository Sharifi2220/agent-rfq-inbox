# Release gates — not yet authorized or completed

This repository is a **review candidate**, not a public release. Do not push to a public repository, publish a package, start a public service or invite real customers based on this bundle alone.

## Owner decisions (open)
- [ ] Working name/trademark clearance across intended countries (OpenQuote Lite is provisional).
- [ ] Confirm Apache-2.0 license, actual copyright holder and LICENSE/NOTICE attribution.
- [ ] Approve the target repository, publication and public description.
- [ ] Establish a private security-reporting channel before release.
- [ ] Approve any real pilot and privacy notice / data-controller responsibilities.

## Engineering gates (open)
- [ ] CI executes with MCP SDK under Python 3.11 / 3.13 on Windows and Ubuntu.
- [ ] Claude Desktop MCP end-to-end (stdio and/or Streamable HTTP) and any target clients.
- [ ] TLS reverse proxy, header sanitization, proxy/client-IP trust and slow-client/DoS test.
- [ ] Data protection: request authentication or abuse mitigation, rights handling, audit retention/legal basis, backups/WAL and deletion, role access, Windows ACL.
- [ ] External dependency/license scan, packaging checks and reproducible source release.
- [ ] Confirm `AskAction` description / structured-data semantics and actual discovery behavior in intended agents.
- [ ] Review applicable laws with a qualified specialist before a real/public pilot.

Passing a unit-test suite is not evidence that any of these gates is complete.
