# Test evidence for v0.1.1a1

Date: 2026-10-26. Local host: Windows. The tests use fictional providers and synthetic requests.

| Environment | Command | Result |
|---|---|---|
| Windows, Python 3.11.15, MCP SDK 2.3.0 | `python -m pytest -o addopts='' -q` | 111 passed, 0 skipped |
| Windows, Python 3.13.13, MCP SDK 2.3.0 | same | 111 passed, 0 skipped |
| Windows, Python 3.15.1, MCP SDK 2.3.0 | same | 111 passed, 0 skipped |
| Windows, clean Python 3.11.15 virtual environment | install built wheel without optional dependencies; run `openquote-lite --version` and load packaged schema | passed |
| Windows | `uv build` | wheel and source distribution built |
| Windows, Python 3.11.15 and 3.13.13 | `uv pip check` and `python -m compileall -q src tests` | passed; 36 installed packages compatible in each environment |

The suite covers validation and schema conformance, service behavior, the local SQLite inbox, HTTP WSGI and loopback requests, MCP tools and a stdio subprocess, audit-chain concurrency, CLI operations and the fictional four-provider demo. The MCP stdio test exercises the protocol with the SDK; it does not constitute a Claude Desktop application test.

GitHub Actions is configured for Ubuntu and Windows with Python 3.11 and 3.13. CI results must be read from the run for the release commit; local Windows results do not imply Linux success.

Remaining evidence gaps: public TLS reverse proxy, real agent clients, real businesses, Windows ACL review, WAL and backup erasure, sender verification, and legal review. See [limitations](../LIMITATIONS.md).
