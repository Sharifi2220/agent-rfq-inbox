# Unabhängige Gegenprüfung — OpenQuote Lite

**Stand:** 26. Oktober 2026  
**Prüfobjekt:** Original v0.1.0 aus Google Drive, Thema 41-12, plus getrennte lokale Review-Fassung 0.1.1rc1  
**Entscheidungsstatus:** Entwicklungsprototyp; **NICHT FREI FÜR GITHUB-VERÖFFENTLICHUNG ODER PRODUKTIVBETRIEB**.

## Herkunft und Reproduzierbarkeit
- 38/38 Originaldateien lokal aus den Drive-Dateien rekonstruiert; **38 SHA-256 und 38 Dateigrößen stimmen** mit dem Originalmanifest überein (206.735 Byte).
- Originalsuite auf Python 3.13: **99 PASS / 2 SKIP** (beide wegen nicht installiertem MCP SDK). Claudes 105/105 unter 3.11/3.13 sind externe Testevidenz; hier nicht erneut reproduziert.
- Nach Review-Korrekturen plus fünf unabhängigen Tests: **104 PASS / 2 SKIP** auf Python 3.13. Keine echten Kunden, kein Windows, kein externes MCP-SDK, kein GitHub-CI-Lauf und kein öffentlicher Server getestet.
- Quellstand und Prüfmaterial wurden als separate lokale, reproduzierbare Release-Vorbereitung erstellt; die Originaldateien in Drive bleiben unverändert.

## Festgestellte Punkte und Bearbeitungsstand

| ID | Priorität | Verifizierter Befund v0.1.0 | Änderung in 0.1.1rc1 | Weiter offen |
|---|---|---|---|---|
| S-01 | Hoch | `base_url.startswith('http://localhost')` akzeptiert auch `http://localhost.evil.test`; `trust_proxy = "false"` wird durch `bool(str)` zu True. | URL-Parser mit Origin-/Hostname-Prüfung und strenge TOML-Boolean-Prüfung, Regressionen. | Realer Proxy-Test. |
| S-02 | Hoch | POSIX-Standard-umask kann lokale SQLite-Datei mit Modus 0644 anlegen; darin stehen Kontaktdaten. | Private Datenordner-/Datenbankrechte erzwingen (0700/0600), Regression. | Windows-ACL, bestehende Installationen, Backup/WAL. |
| S-03 | Mittel | Eingehender HTTP-Anfragepfad wird geloggt; Query-Strings und unbekannte Pfade können sensible Werte enthalten. | Logging auf bekannte Route begrenzen, IDs und Querys redigieren; Regression. | Externe Proxy-Logs. |
| D-01 | Hoch | `erase()` entfernt Payload/PLZ, lässt aber `contact_hash`, `content_hash` und Sprachfeld bestehen. Absolutaussage „Audit enthält keine Personendaten“ ist falsch: IDs und `cli:<OS-Nutzername>` können identifizierbar sein. | Direktpseudonyme/Sprachfeld leeren, CLI-Akteur rollenbasiert, Datenschutzdoku präzisiert. | Audit-Korrelation, WAL, Backup, berechtigte Aufbewahrung, Identitätsprüfung für Auskunft/Löschung. |
| D-02 | Mittel | „Automatisches Löschen“ ist irreführend: `purge` funktioniert nur nach externem Aufruf. | Doku klargestellt. | Cron/Task Scheduler, operativer Nachweis. |
| I-01 | Mittel | `schema.org/QuoteAction` bedeutet Preis nennen/schätzen, nicht Anfrage an einen Betrieb. | `AskAction` im JSON-LD der Review-Fassung, Tests angepasst. | Fachlicher Test in echten Clients; mögliche bessere Modellierung prüfen. |
| R-01 | Hoch, offen | Berechtigungs-/Identitätsnachweis basiert nur auf selbst gesetzten Consent-Flags; fremde Kontakte können eingereicht werden. | Keine Schein-Authentifizierung ergänzt. | Vor externem Pilot Missbrauchsmodell, Identitäts- und Kontaktverifikation prüfen. |
| R-02 | Mittel, offen | Statuszugriff allein mit zufälliger Anfrage-ID (Bearer-ähnlich). | Unverändert. | Einordnung und ggf. Token/Scope. |
| R-03 | Offen | Kein Slow-Client-Test, Windows-Test, Reverse-Proxy-Abnahmetest oder echter Claude-Desktop-Test. | GitHub CI-Entwurf ergänzt. | Durchführung und dokumentierte Abnahme. |

## Standards und Recht — Primärquellen
- RFC 9727 erlaubt die `/.well-known/api-catalog`-Entdeckung als Linkset; die Schnittstelle ist für HTTPS-Endpunkte gedacht: https://www.rfc-editor.org/rfc/rfc9727.html
- `schema.org/QuoteAction` bedeutet eine Schätzung mit Preis; für Anfrage an einen Betrieb ist `AskAction` semantisch naheliegender: https://schema.org/QuoteAction ; https://schema.org/AskAction
- EU-Kommission: rückbeziehbare Pseudonyme sind personenbezogene Daten: https://commission.europa.eu/law/law-topic/data-protection/information-business-and-organisations/application-gdpr_en
- Österreichisches KSchG § 5 Abs. 2: für dem Vertrag zugrunde gelegte Kostenvoranschläge gilt deren Richtigkeit im Zweifel als gewährleistet: https://www.ris.bka.gv.at/eli/bgbl/1979/140/P5/NOR12031487. Keine pauschale Aussage „Angebot ist verbindlich“ ableiten.

## Empfehlung
1. Review-Fassung getrennt halten, nicht still Original v0.1.0 überschreiben.
2. GitHub **privat** vorbereiten erst nach Eigentümerentscheidung; keine öffentliche Veröffentlichung ohne Name, Lizenz, Inhaberschaft, Meldekanal und Security/Privacy-Gates.
3. Codex den verbleibenden Laufzeit- und Drive-Sync-Auftrag geben, danach menschliches Release-Gate.

## Quellen innerhalb des Projekts
- `01_THEMEN/41-12_OpenQuote-Lite/STATUS.md`
- `02_QUELLCODE/openquote-lite/` und `MANIFEST_SHA256_openquote-lite-0.1.0.txt`
- `03_TESTS_UND_NACHWEISE/TESTBERICHT_v0.1.0_2026-10-26.md`
