# Sicherheit

> Kurzfassung für Nutzer und Tester: Was fml tut, damit **fremde Bilddateien**
> das Werkzeug nicht als Angriffsweg missbrauchen können — und was du selbst im
> Blick behalten solltest.


## Bedrohungsmodell

Solange du **nur eigene** Bilder verwaltest, ist das hier Hintergrundwissen.
Sobald du **fremde Dateien** importierst (fremde Sammlungen, heruntergeladene
Bilder, ein geteilter Watchordner) oder das Werkzeug **weitergibst**, gilt:

> **Jede in einer Datei eingebettete Metadate ist nicht vertrauenswürdig.**

Wer eine Bild-/Videodatei baut, bestimmt jeden EXIF-/XMP-/PNG-Text-Chunk und
jedes eingebettete ComfyUI-/A1111-Workflow-JSON frei — auch mit bösartigem
Inhalt. fml behandelt diese Daten deshalb wie eine Formulareingabe aus dem
Internet: nie blind vertrauen.

## Wogegen fml schützt

**Eingabe / Parser (beim Scan & Import):**

- **PNG-Text-Chunks** werden mit **gedeckelter Dekompression** gelesen: ein
  winziger, absichtlich zu Gigabytes aufblähbarer `zTXt`/`iTXt`-Chunk
  („zlib-Bombe") wird bei 64 MiB abgebrochen, verworfen und protokolliert — er
  kann den Import nicht per Speicherüberlauf abschießen.
- **XMP** (eingebettetes XML) wird ohne DTD/Entity-Auflösung gelesen; ein Paket
  mit `<!DOCTYPE`/`<!ENTITY` (z. B. „billion laughs") wird übergangen. Externe
  Entities holt der Parser generell nicht (kein XXE, kein Netzwerkzugriff).
- **Bilder** öffnet Pillow mit seinem eingebauten Schutz gegen
  Dekompressionsbomben; ein Extraktor-Fehler an einer kaputten/bösartigen Datei
  stoppt nie den ganzen Lauf — die Datei landet als Problemfall, der Scan geht
  weiter.
- **ComfyUI-Workflow-Graphen** werden mit Zyklus-Schutz ausgewertet — ein
  absichtlich verketteter/zyklischer Graph läuft nicht in eine Endlosschleife.

**Verarbeitung / Datenbank:**

- Alle Datenbank-Abfragen sind **parametrisiert** — kein Metadaten- oder
  Suchtext wird je in SQL zusammengesetzt. Die Volltextsuche (FTS5) quotet die
  Suchbegriffe, Feld- und Sortier-Namen kommen aus festen Whitelists.

**Anzeige (in der Browser-Oberfläche):**

- Jeder aus einer Datei stammende Text (Prompt, Roh-Metadaten, Dateiname, Tags,
  Suchtreffer) wird beim Einsetzen in die Seite **HTML-escaped** — eingebetteter
  Schadcode wird als Text angezeigt, nicht ausgeführt.
- Die Workflow-Graph-Vorschau erzwingt für alle Koordinaten aus dem fremden JSON
  **Zahlen**, sodass kein Wert aus dem SVG ausbrechen kann; Farbwerte aus dem
  JSON werden nur als Hex-Farbe übernommen.
- Das **Serverlog** enthält Dateinamen und Pfade fremder Dateien. Steuerzeichen
  darin (Zeilenumbruch, `\r`, ANSI-Sequenzen, Unicode-Bidi-Zeichen) werden
  beim Schreiben sichtbar gemacht (`\n`, `\x1b`, `\u202e`): keine gefälschte
  Logzeile, keine Terminal-Steuerung, keine gedrehte Anzeige. Die Log-Seite im
  Admin liest ausschließlich die zwei festen Logdateien und escaped jede Zeile.

**Absprünge ins Dateisystem:**

- **„Im Dateimanager anzeigen"** öffnet nur Fundorte, die fml für dieses Item
  kennt, und prüft den Inhalt vorher per SHA-256 (bei Dateien über 64 MB per
  Größe) — ein untergeschobener Fremdinhalt am katalogisierten Pfad wird nicht
  präsentiert. Pfade werden normalisiert.
- Die **Fundort-Breadcrumbs** (Ordner öffnen, Datei im zugeordneten Programm
  öffnen) nehmen keinen freien Pfad entgegen: erlaubt sind nur die in der
  Datenbank gespeicherten Fundorte des Items bzw. deren Ordner. fml öffnet nur;
  was das Programm danach tut, entscheidet der Anwender dort.
- **Medien-Auslieferung** (`/api/media`): nur katalogisierte Dateien über
  ihren Hash, Range-Anfragen mit genau einem Bereich, abgebrochene Streams
  beenden das Lesen sofort — ein Browser kann den Server nicht mit
  halboffenen Video-Streams blockieren.

## Restrisiken & Betriebsempfehlung

- **Nur an `localhost` binden.** fml ist eine lokale Einzelnutzer-Anwendung.
  Betreibe den Server nicht offen im Netz erreichbar — es gibt bewusst keine
  Anmeldung/Mandantentrennung.
- **Host-Wächter gegen DNS-Rebinding.** Auch ein nur an `localhost`
  gebundener Server ist im Browser angreifbar, wenn eine bösartige Webseite
  ihre Domain per DNS auf `127.0.0.1` umbiegt. fml weist deshalb jeden
  Request ab, dessen `Host`-Header nicht `localhost`/`127.0.0.1`/`::1`
  ist (400). Wer per `--host` bewusst weiter bindet (z. B. für Zugriff
  über ein privates VPN wie Tailscale), öffnet diese Liste automatisch —
  dann gilt umso mehr die Empfehlung darüber. Alle Antworten tragen
  zusätzlich `X-Content-Type-Options: nosniff`.
- **Der Ordner-Browser ist mächtig.** Die Admin-Oberfläche kann Verzeichnisse
  auf dem ganzen Rechner auflisten (für die Auswahl von Quell-/Zielordnern). Das
  ist gewollt, aber ein Grund mehr, den Server nicht nach außen zu öffnen.
- **Neue Formate = neue Prüfung.** Die TIFF/PSD-Vorschau läuft über Pillow
  (serverseitig gerendertes JPEG, Original unangetastet); PDF wird nur
  katalogisiert. Für jeden weiteren Parser gelten dieselben Regeln (Parser
  deckeln, Ausgabe escapen).

## Abhängigkeiten im Blick behalten

fml hält die Abhängigkeitsfläche bewusst **winzig** (Projektregel
„Standardbibliothek bevorzugen"; Details in
[`DEPENDENCIES.md`](../DEPENDENCIES.md)): sechs direkte Laufzeit-Pakete,
neun transitive, dazu pip und ein optionales System-Programm. **Jedes davon
ist benannt:** `requirements.txt` ist ein vollständiger Lock mit fester
Version und SHA-256-Hashes je Paket, und die Startskripte installieren im
Hash-Prüfmodus nur fertige Wheels. pip weigert sich, ein nicht genanntes
Paket oder eine veränderte Datei zu installieren, und es wird nichts aus
Quellcode gebaut. Trotzdem gilt: **wer das Werkzeug betreibt,
sollte diese wenigen Abhängigkeiten aktuell halten**, denn sie verarbeiten die
fremden Dateien mit:

| Was | Version (gepinnt) | Warum im Blick behalten |
|-----|-------------------|-------------------------|
| **Pillow** | `12.3.0` | Öffnet fremde Bilddateien (JPEG/WEBP/TIFF/…). Bildparser sind ein klassisches Ziel für Sicherheitslücken — bei einer Pillow-CVE **zeitnah aktualisieren**. |
| **fastapi** | `0.141.1` | Web-Backend der lokalen Oberfläche. |
| **uvicorn** | `0.52.4` | ASGI-Server; bewusst ohne `[standard]`-Extras (kleinere transitive Fläche). |
| **starlette** | `1.6.0` | Unterbau von fastapi; liefert die Medien-Streams mit Range und Abbruch aus. |
| **anyio** | `4.14.2` | Thread-Pool für Medien-Streams; 4.14.2 behebt drei Meldungen der Vorversion. |
| **pydantic** | `2.13.4` | Anfrage-Modelle der Oberfläche; bringt `pydantic-core` (kompiliert) mit. |
| transitive Pakete | im Lock | annotated-doc, annotated-types, click, colorama (nur Windows), h11, idna, pydantic-core, typing-extensions, typing-inspection; Rolle je Paket in `DEPENDENCIES.md`. |
| **pip** | `26.2.1` | Der Installer selbst ist gepinnt; die Startskripte bringen das pip im venv auf genau diese Version. |
| **ffmpeg/ffprobe** | System (optional) | Liest fremde Video-Container. Kein pip-Paket — über den Paketmanager des Systems aktuell halten. Ohne ffmpeg werden Videos nur katalogisiert. |
| pytest (nur Entwicklung) | `9.1.1` | Nicht im Laufzeit-Pfad; mit seinen vier Abhängigkeiten ebenfalls gelockt. |

Praktisch: die gepinnten Versionen sorgen für reproduzierbare Installationen;
beim Update einer Abhängigkeit die `# direct`-Zeile in `requirements.txt`
anheben, `python tools/lock_deps.py` erzeugt Lock und Hashes neu, dann die
Tests laufen lassen (`pytest -q`). Ein Blick auf Sicherheitsmeldungen zu
**Pillow** und **ffmpeg** lohnt sich am ehesten, weil beide direkt fremde
Binärdaten anfassen.

Diese Prüfungen laufen, ohne dass der Betreiber etwas tun muss:

- **Installation nur aus dem Lock.** Die Startskripte installieren mit
  `--require-hashes` und `--only-binary=:all:`: pip vergleicht jede
  heruntergeladene Datei mit ihrer Prüfsumme im Lock, verweigert jedes
  nicht gelistete Paket und baut nichts aus Quellcode. pip selbst wird auf
  die gepinnte Version gebracht, nicht auf „die neueste".
- **Wächter-Tests** (`tests/test_dependencies.py`): Die Testsuite wird rot,
  wenn Code ein Fremdpaket importiert, das keine direkte Abhängigkeit ist,
  wenn ein Eintrag im Lock keine feste Version oder keine Prüfsumme hat,
  wenn ein gelocktes Paket in `DEPENDENCIES.md` fehlt oder wenn die
  installierte Umgebung vom Lock abweicht.
- **Advisory-Check** (`python tools/check_advisories.py`): fragt die offene
  Schwachstellendatenbank [OSV](https://osv.dev) nach jedem gelockten
  Paket, pip eingeschlossen, plus allem, was im venv installiert ist.
- **Export-Sperre:** Vor jedem Public-Snapshot läuft dieser Check
  automatisch; mit einer offenen Meldung wird nicht veröffentlicht.
- **Dependabot** (GitHub): Alerts und automatische Sicherheits-Updates
  sind eingeschaltet. Weil jedes transitive Paket im Lock steht, schlägt
  Dependabot Updates auch für diese vor.
- **Instanz-Kachel** im Admin: zeigt die installierte Version der sechs
  direkten Laufzeit-Pakete und warnt, wenn sie vom Pin abweicht.

## Ein Problem gefunden?

fml ist ein privates Lernprojekt ohne formalen Sicherheitsprozess. Wenn dir
beim Testen etwas auffällt (eine Datei, die die Oberfläche seltsam reagieren
lässt, ein Absturz beim Import), heb die Datei auf und gib Feral Strawberry
Bescheid — am einfachsten als GitHub-Issue; wer den kurzen Draht hat, nutzt
den. Die Datei ist als reproduzierbarer Testfall wertvoller als jeder
Bugreport aus dem Kopf.
