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

GitHub Actions [run 40322892688](https://github.com/Sharifi2220/agent-rfq-inbox/actions/runs/40322892688) completed successfully for commit `4a15cdcfa51510fe47ffbbfc9113992f12fd0d28`: Ubuntu and Windows, Python 3.11 and 3.13. Each of the four jobs passed 111 tests, `pip check`, `compileall`, and wheel/source-distribution build. This documents the first full source commit; a documentation-only follow-up commit will have its own CI run.

Remaining evidence gaps: public TLS reverse proxy, real agent clients, real businesses, Windows ACL review, WAL and backup erasure, sender verification, and legal review. See [limitations](../LIMITATIONS.md).
