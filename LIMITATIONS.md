# Current alpha limitations

This is a source-code alpha for local evaluation. It is not a production service.

* Sender identity and the two authorization booleans are unverified. A public endpoint would need stronger abuse prevention and a clear consent process.
* A random request ID acts like a bearer token for coarse status. It is not separately scoped or authenticated.
* The built-in HTTP server has no TLS or slow-client protection. Reverse-proxy configuration, forwarded-header sanitization and infrastructure logging are not covered by local tests.
* `privacy purge` only runs when the operator schedules it. Erasure leaves some metadata and pseudonymous audit identifiers, and cannot clear copies in WAL, backups or logs on its own.
* POSIX permissions are checked for new data directories and database files. Windows ACLs and existing installations need operator verification.
* No real customer, real business, Claude Desktop application, or public reverse-proxy pilot has been completed.
* The `AskAction` JSON-LD model has not been proven discoverable by real agents.
* A real deployment needs a privacy notice, retention plan and qualified legal review for its jurisdiction.

These limits are tracked in [SECURITY.md](SECURITY.md) and [docs/PRIVACY.md](docs/PRIVACY.md).
