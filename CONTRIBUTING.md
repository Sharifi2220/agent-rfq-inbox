# Contributing

OpenQuote Lite is a small, human-reviewed request channel for service providers. Contributions should retain its **single, non-binding action**: receiving a request; no pricing promises, appointments, contracting, payments or autonomous outreach.

1. Use Python 3.11 or 3.13 in a virtual environment and install `python -m pip install -e ".[mcp,test]"`.
2. Run `python -m pytest -q`. GitHub Actions runs the same suite on Windows and Ubuntu for both Python versions.
3. Use fictional data. Never commit real customer requests, secrets, generated database files or credentials.
4. Propose protocol changes in an issue, add interoperability tests, and mark breaking changes.
5. Human approval stays mandatory before anything beyond intake. `submitted_via` and consent booleans are declarations, not identity proof.
6. Send potential vulnerabilities through the [private reporting form](https://github.com/Sharifi2220/agent-rfq-inbox/security/advisories/new). Do not open public issues containing exploitable details or secrets.

The initial source was AI-assisted. Do not add an author or copyright-holder name without evidence. Contributions are accepted under Apache-2.0; document any third-party code and its license.
