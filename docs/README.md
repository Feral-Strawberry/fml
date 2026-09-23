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

- [Architektur](architektur.md) — das technische Konzept in vier Bildern:
  Prozesse, Aufnahme mit zwei Metadaten-Schichten, Suchpfad, Installation und
  Lieferkette.
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
- [Datenbank-Schema](schema.md) — ER-Diagramm und alle Tabellen mit Spalten,
  Schlüsseln und Indexen, aus dem echten Schema erzeugt.
- [Ordner scannen](scanning.md) — einen ganzen Ordner rekursiv aufnehmen
  (`python -m feral.scan`). **Der erste Schritt mit Echtdaten.**
- [Import & Watchordner](import.md) — Quellordner in die datumsbasierte
  Media Library einsortieren (Modi kopieren / verschieben / nur
  katalogisieren, Dublettencheck, sichtbare Ausgänge, Import-Regeln) und
  Ordner dauerhaft beobachten lassen. **Der Alltagsweg, neue Medien
  aufzunehmen.**
- [Die Oberfläche (Web-GUI)](gui.md) — **Galerie** mit Sidebar-Facetten,
  Chip-Suche und gespeicherten Suchen, Detail-Panel, Lupe, Einzelbildansicht
  mit echtem Zoom, A/B-Vergleich, Workflow-Ansicht für ComfyUI-Medien,
  Kuratieren (Bewerten, Tags, Notizen, Ablehnen) und Sammel-Aktionen
  (`python -m feral.web` bzw. die Startskripte). **Der Alltag.**
- [Admin](admin.md) — eigene Seite unter `/admin` mit Übersicht,
  Konfiguration, Quellen & Import (Watchordner), Wartung (Re-Scan, Neu
  interpretieren, Rausverschieben, Import-Regeln auf den Bestand, …),
  Problemen mit Sperrliste, Rankings und Serverlog.
- [Rankings](rankings.md) — das optionale Ranking-Modul: Paarvergleich mit
  Elo-Bestenliste über eine gespeicherte Suche.
- [Mehrere Instanzen](instanzen.md) — parallele, unabhängige Galerien aus
  einem Programmordner (eigene DB + Port je Instanz): **Subgalerien einer
  Gesamt-Library**, ohne Dateien zu berühren. Start per
  `start.bat --config name.toml`.
- [Sicherheit](security.md) — wie fml mit **fremden** Bilddateien umgeht
  (untrusted Metadaten), Betriebsempfehlung, welche Abhängigkeiten installiert
  werden und wie sie geprüft werden (Lock mit Prüfsummen, Advisory-Check). **Vor der Weitergabe an andere lesen.**
- [Die Testsuite](tests.md) — was die gut 700 automatischen Tests (Python und
  Node-Tests der Oberfläche) absichern, wie man sie startet (`pytest -q`) und
  woran man das korrekte Ergebnis erkennt.
  **Nützlich als Installations-Check auf einem neuen Rechner.**
