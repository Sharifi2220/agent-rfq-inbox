# Codex — kurzer Restauftrag, OpenQuote Lite 41-12

**Einstieg:** Root-`AGENTS.md` im Research Lab, `00_MASTER/STATUS.md`, `00_MASTER/THEMEN_INDEX.md`, dann `01_THEMEN/41-12_OpenQuote-Lite/STATUS.md`. Nicht mit 41-05 vermischen. Drive ist maßgeblich.

1. Übernimm das von ChatGPT unabhängig geprüfte **Review-Kandidatenpaket 0.1.1rc1**; prüfe die Unterschiede gegen das bytegenau bestätigte Original v0.1.0, übernimm nur verifizierte Korrekturen. Kein Blind-Merge.
2. Wiederhole Tests unter Python 3.11/3.13 mit MCP-SDK auf Linux und Windows; führe Claude-Desktop-stdio-Probe durch. Prüfe Testzahl und Berichte echte SKIPs. Analysiere in der Review-Fassung auch Proxy/TLS, Windows-ACL, Retention/SQLite-WAL, Audit und echten status polling.
3. Lege Quell- und Review-Artefakte **im vorhandenen Themenordner** ab (separate versionierte Review-Fassung, Code-Manifest/Testbericht), ohne Original v0.1.0 zu überschreiben. Aktualisiere die aktive Themen-`STATUS.md` in-place mit Ergebnis und Blockern. Trage `41-12` in `00_MASTER/THEMEN_INDEX.md` sowie `CHANGELOG.md` in-place nach; Rückleseprüfung.
4. Überprüfe die Entwicklerpräsentation und den GitHub-Readiness-Status. Keine Veröffentlichung, keine Repository-Freischaltung, kein Deployment, kein echter Betriebskontakt und keine globale Rechteänderung ohne ausdrückliche Freigabe des Inhabers. Lizenz/Name/Copyright bleiben OFFEN.
5. Liefere einen knappen PASS/FAIL-Bericht mit Dateipfaden, SHA-256 und den noch nötigen Inhaberentscheidungen.
