# Sicherheit

> Kurzfassung für Nutzer und Tester: Was Feral tut, damit **fremde Bilddateien**
> das Werkzeug nicht als Angriffsweg missbrauchen können — und was du selbst im
> Blick behalten solltest.


## Bedrohungsmodell

Solange du **nur eigene** Bilder verwaltest, ist das hier Hintergrundwissen.
Sobald du **fremde Dateien** importierst (fremde Sammlungen, heruntergeladene
Bilder, ein geteilter Watchordner) oder das Werkzeug **weitergibst**, gilt:

> **Jede in einer Datei eingebettete Metadate ist nicht vertrauenswürdig.**

Wer eine Bild-/Videodatei baut, bestimmt jeden EXIF-/XMP-/PNG-Text-Chunk und
jedes eingebettete ComfyUI-/A1111-Workflow-JSON frei — auch mit bösartigem
Inhalt. Feral behandelt diese Daten deshalb wie eine Formulareingabe aus dem
Internet: nie blind vertrauen.

## Wogegen Feral schützt

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
  **Zahlen**, sodass kein Wert aus dem SVG ausbrechen kann.

## Restrisiken & Betriebsempfehlung

- **Nur an `localhost` binden.** Feral ist eine lokale Einzelnutzer-Anwendung.
  Betreibe den Server nicht offen im Netz erreichbar — es gibt bewusst keine
  Anmeldung/Mandantentrennung.
- **Host-Wächter gegen DNS-Rebinding.** Auch ein nur an `localhost`
  gebundener Server ist im Browser angreifbar, wenn eine bösartige Webseite
  ihre Domain per DNS auf `127.0.0.1` umbiegt. Feral weist deshalb jeden
  Request ab, dessen `Host`-Header nicht `localhost`/`127.0.0.1`/`::1`
  ist (400). Wer per `--host` bewusst weiter bindet (z. B. für Zugriff
  über ein privates VPN wie Tailscale), öffnet diese Liste automatisch —
  dann gilt umso mehr die Empfehlung darüber. Alle Antworten tragen
  zusätzlich `X-Content-Type-Options: nosniff`.
- **Der Ordner-Browser ist mächtig.** Die Admin-Oberfläche kann Verzeichnisse
  auf dem ganzen Rechner auflisten (für die Auswahl von Quell-/Zielordnern). Das
  ist gewollt, aber ein Grund mehr, den Server nicht nach außen zu öffnen.
- **Neue Formate = neue Prüfung.** PSD/PDF-Vorschau und weitere Parser sind noch
  offen; wenn sie kommen, gelten dieselben Regeln (Parser deckeln, Ausgabe
  escapen).

## Abhängigkeiten im Blick behalten

Feral hält die Abhängigkeitsfläche bewusst **winzig** (Projektregel
„Standardbibliothek bevorzugen"; Details in
[`DEPENDENCIES.md`](../DEPENDENCIES.md)) — drei Laufzeit-Pakete plus
ein optionales System-Programm. Trotzdem gilt: **wer das Werkzeug betreibt,
sollte diese wenigen Abhängigkeiten aktuell halten**, denn sie verarbeiten die
fremden Dateien mit:

| Was | Version (gepinnt) | Warum im Blick behalten |
|-----|-------------------|-------------------------|
| **Pillow** | `12.3.0` | Öffnet fremde Bilddateien (JPEG/WEBP/TIFF/…). Bildparser sind ein klassisches Ziel für Sicherheitslücken — bei einer Pillow-CVE **zeitnah aktualisieren**. |
| **fastapi** | `0.136.3` | Web-Backend der lokalen Oberfläche. |
| **uvicorn** | `0.49.0` | ASGI-Server; bewusst ohne `[standard]`-Extras (kleinere transitive Fläche). |
| **ffmpeg/ffprobe** | System (optional) | Liest fremde Video-Container. Kein pip-Paket — über den Paketmanager des Systems aktuell halten. Ohne ffmpeg werden Videos nur katalogisiert. |
| pytest (nur Entwicklung) | `~=8.0` | Nicht im Laufzeit-Pfad. |

Praktisch: die gepinnten Versionen sorgen für reproduzierbare Installationen;
beim Update einer Abhängigkeit die Pin-Version in `requirements.txt` anheben und
die Tests laufen lassen (`pytest -q`). Ein Blick auf Sicherheitsmeldungen zu
**Pillow** und **ffmpeg** lohnt sich am ehesten, weil beide direkt fremde
Binärdaten anfassen.

## Ein Problem gefunden?

Feral ist ein privates Lernprojekt ohne formalen Sicherheitsprozess. Wenn dir
beim Testen etwas auffällt (eine Datei, die die Oberfläche seltsam reagieren
lässt, ein Absturz beim Import), heb die Datei auf und gib Feral Strawberry
Bescheid — am einfachsten als GitHub-Issue; wer den kurzen Draht hat, nutzt
den. Die Datei ist als reproduzierbarer Testfall wertvoller als jeder
Bugreport aus dem Kopf.
