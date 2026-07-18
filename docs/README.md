# Benutzer- & Funktionsdoku

> 🇬🇧 **English version:** [`en/`](en/) — übersetzt aus diesen deutschen
> Quellen (Deutsch ist die einzige gepflegte Quelle).


Diese Doku beschreibt **pro Funktion**, *was sie tut und wie man sie
verwendet* — ohne Architektur-Begründungen. Sie ist so geschrieben, dass
Zwischenstände an Tester weitergegeben werden können.


Zum Namen: Das Projekt heißt **Feral Media Library** — davon kommt das in
dieser Doku verwendete Kürzel **fml**. Entwickelt wird es von **Feral
Strawberry** (zugleich der Name der GitHub-Organisation).

## Funktionsblöcke

- [Metadaten-Extraktion (Schicht 1)](extraction.md) — liest alle eingebetteten
  Roh-Metadaten aus einer Mediendatei. PNG, JPEG/WEBP/GIF/BMP/TIFF (Pillow) und
  Video (ffprobe) umgesetzt.
- [Metadaten-Interpretation (Schicht 2)](interpretation.md) — macht aus den
  Roh-Metadaten durchsuchbare Felder (Prompt, Modell, Seed, …); läuft beim Scan
  mit und rückwirkend per `python -m feral.interpret`.
- Content-Hashing — die stabile Identität eines Items
  (in [extraction.md](extraction.md) mitbeschrieben).
- [Persistenz / Datenbank](persistence.md) — wie extrahierte Daten gespeichert
  und wieder abgefragt werden.
- [Ordner scannen](scanning.md) — einen ganzen Ordner rekursiv aufnehmen
  (`python -m feral.scan`). **Der erste Schritt mit Echtdaten.**
- [Import & Watchordner](import.md) — Quellordner kopierend in die
  datumsbasierte Media Library einsortieren (Dublettencheck, sichtbare
  Ausgänge) und Ordner dauerhaft beobachten lassen. **Der Alltagsweg,
  neue Medien aufzunehmen.**
- [Die Oberfläche (Web-GUI)](gui.md) — **Galerie** mit Vorschaubildern und
  Detailansicht, Ordner per Klick wählen, scannen, beobachten und durchsuchen
  (`python -m feral.web`). **Bequemste Variante zum Testen.**
- [Admin & Wartung](admin.md) — DB-Status, Wartungsaktionen (Neu-Interpretieren,
  Re-Scan, Integritätscheck, …), Scan-Probleme und Config-Bearbeitung in der GUI.
- [Mehrere Instanzen](instanzen.md) — parallele, unabhängige Galerien aus
  einem Programmordner (eigene DB + Port je Instanz): **Subgalerien einer
  Gesamt-Library**, ohne Dateien zu berühren. Start per
  `start.bat --config name.toml`.
- [Sicherheit](security.md) — wie Feral mit **fremden** Bilddateien umgeht
  (untrusted Metadaten), Betriebsempfehlung und welche Abhängigkeiten man aktuell
  halten sollte. **Vor der Weitergabe an andere lesen.**
- [Die Testsuite](tests.md) — was die ~240 automatischen Tests absichern, wie
  man sie startet (`pytest -q`) und woran man das korrekte Ergebnis erkennt.
  **Nützlich als Installations-Check auf einem neuen Rechner.**
