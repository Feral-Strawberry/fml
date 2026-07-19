# Die Oberfläche (lokale Web-GUI)

> Was ist das? Die lokale Weboberfläche der Feral Media Library (fml):
> Bestand durchsehen und
> durchsuchen, Metadaten lesen, Ordner scannen/beobachten und die Wartung
> erledigen - alles ohne Kommandozeile. Seit Block 3.0 im Drei-Spalten-Layout
> (dunkles Theme, umschaltbar).

## Starten

Der Alltagsweg sind die Startskripte (`start.bat` doppelklicken bzw.
`./start.sh`) — sie richten beim ersten Mal die Umgebung ein und öffnen
den Browser, sobald der Server bereit ist. Von Hand:

```bash
source .venv/bin/activate
python -m feral.web
```

Dann im Browser öffnen: **http://127.0.0.1:8765**

Optionen: `--config config.toml` (welche Instanz), `--port`, `--host
127.0.0.1` (Standard: nur lokal erreichbar), `--db` (überschreibt den
DB-Pfad aus der Config), `--browser` (öffnen, sobald der Server
antwortet — nutzen die Startskripte). Der Port kann dauerhaft in der
Config stehen (`[web] port`; Vorrang: `--port` > `$PORT` > Config > 8765).
**Mehrere parallel laufende Instanzen** (je Instanz eigene Config + DB +
Port, Start per `start.bat --config name.toml`): [instanzen.md](instanzen.md).

## Aufbau

**Topbar:** Suchfeld (Mitte), direkt daneben der **Sortier-Knopf** und die
**Dichte S/M/L** (seit 2026-07-11 hier oben - die Leiste unter der Suche
gehört den Chips), Bestandszähler (Items · Gesamtgröße), Aktivitäts-Anzeige
(pulsiert, wenn Scan/Wartung läuft - Klick öffnet das Admin-Dashboard),
Admin-Knopf (Klick öffnet das Schnellmenü - dort sitzt seit 2026-07-16 auch
der einzige Dark/Light-Umschalter, das separate ◐-Icon ist weg). Ist in der
Konfiguration ein
**Instanzname** gesetzt, steht er hier als farbige Pille (dazu Tab-Titel und
Favicon-Farbpunkt - unterscheidet parallel laufende Instanzen). Läuft fml im
**Übersichtsmodus** (Standardzustand, ADR 0041), steht hier außerdem das
Badge **„👁 Übersichtsmodus"**: fml katalogisiert und kuratiert nur -
Dateien werden nie kopiert, verschoben oder gelöscht. Freischalten der
dateischreibenden Wege: Admin → Konfiguration → **Library-Verwaltung**
(siehe [admin.md](admin.md)).

**Sprache (DE/EN):** Ohne eigenes Zutun folgt die Oberfläche der
Browser-Sprache (Deutsch bei `de*`, sonst Englisch). Der Knopf **DE/EN**
in der Topbar (auch als Auswahl unter Admin → Konfiguration → Oberfläche)
schaltet hart um: Einmal gesetzt, gilt die Wahl in diesem Browser dauerhaft
und übersteuert die Browser-Sprache; der Wechsel lädt die Seite neu. Die
Sprache gehört zum Betrachter (Browser), nicht zur Instanz - zwei Rechner
können dieselbe Instanz in verschiedenen Sprachen ansehen (ADR 0054).
Die Such-Grammatik versteht seit Block M.3 zusätzlich **englische
Aliasse** für ihre deutschen Reste: `file:` = `datei:`, `location:` =
`fundort:`, `portrait`/`square`/`landscape` = `hochformat`/`quadratisch`/
`querformat`, `-asc`/`-desc` = `-auf`/`-ab`, `external` = `extern` und
`unknown` = `unbekannt`. Beide Schreibweisen werden
immer verstanden, egal welche Sprache eingestellt ist; **kanonisch** (in
Chips, gespeicherten Suchen und serialisierten Ausdrücken) bleibt die
bisherige Schreibweise — gespeicherte Smart Folders bleiben unangetastet
gültig. Seit Block M.2 folgen auch alle **vom Server erzeugten Texte**
der UI-Sprache: Aktivitäts-Labels und Fortschritt im Admin-Dashboard,
Ergebnis-Zusammenfassungen („Import: 3 neu · 2 Dubletten"), Fehlermeldungen
der Such-Grammatik und alle übrigen Server-Fehler. Einzige Ausnahme:
Scan-Probleme, die VOR dem Update aufgezeichnet wurden, erscheinen
unverändert in ihrem alten (deutschen) Wortlaut — neue Einträge sind
sprachneutral gespeichert und werden beim Anzeigen übersetzt.

**Links - Quellen:** „Alle Medien", **Dubletten** (Items, die an mehreren
Pfaden auf der Platte liegen - das Panel zeigt alle Fundorte), deine
**gespeicherten Suchen**, die Gruppe **Bewertung** (genau n Sterne - auch gezielt
schlecht Bewertetes), **Nach Modell** - inklusive **„(unbekanntes Modell)"**
für Medien ohne interpretiertes Modellfeld (Midjourney, Gemini, ChatGPT, …);
WAN-2.2-Zweistufen-Checkpoints (High-/Low-Noise) erscheinen als EIN Eintrag,
der Tooltip nennt beide Rohnamen und der Klick filtert auf beide -,
**Nach Jahr** (Erstelldatum; das Caret vor der Jahreszahl klappt die Monate
auf - Alt-Bestände bekommen ihr Datum per „Re-Scan: alle Fundorte"),
**Nach LoRA** (die beim Generieren benutzten LoRAs, meistgenutzte zuerst),
**Nach Dateityp** (PNG, WEBP, Video-Container, …), **Nach Format**
(grobe Seitenverhältnis-Klassen: Hochformat / Quadratisch / Querformat /
Widescreen - zur Fehlersuche nach einem Import), **Nach Auflösung**
(Megapixel-Bereiche: unter 1 / 1-2 / 2-4 / über 4 MP), **Eingangsbild**
(mit/ohne - findet img2img- und Bild-zu-Video-Ergebnisse) und **Fundort**
(„in der Library" = mindestens eine Kopie liegt in der Media Library, „nur
extern" = nur am Ort indiziert, z. B. per `katalogisieren` von fremden
Platten; die Gruppe erscheint nur, wenn eine Media Library konfiguriert
ist). Ein Klick legt
einen **Chip** in die Suchleiste über der Galerie (siehe „Suchen"); ein
Klick auf einen **zweiten Wert derselben Gruppe** erweitert den Chip zum
ODER („flux ODER krea"), ein Klick auf einen aktiven (markierten) Wert
nimmt ihn wieder heraus.

Die Zähler **filtern mit**: Sobald Chips aktiv sind, zeigt jede Gruppe, wie
viele Treffer ein Klick **im aktuellen Kontext** brächte - gerechnet gegen
die jeweils *anderen* Kriterien (die eigene Gruppe klammert sich aus, sonst
ließe sich kein ODER mehr aufbauen). Werte, die gerade nichts träfen,
werden **gedimmt statt versteckt** - sichtbar bleibt, was es gäbe.

Jede Gruppe lässt sich per Klick auf ihre Überschrift **ein-/ausklappen**
(bleibt gemerkt). Unten der Bibliotheks-Footer: Items und Gesamtgröße - mit
konfigurierter Media Library getrennt als **„Library X GB · gesamt Y GB"**
(Library = was physisch unter der Bestands-Wurzel liegt, gesamt = alles
Indizierte, auch Externes).

**Mitte - Galerie:** Virtualisiertes Grid (flüssig auch bei sehr großen
Beständen - nur sichtbare Kacheln sind im Speicher), neueste zuerst. Oben:
Breadcrumb mit den Such-Chips und dem Zähler; rechts daneben fest verankert
**✕ Filter zurücksetzen** (erscheint, sobald gefiltert wird - auch **Esc**
leert die Filter, wenn kein Overlay offen ist) und **⚡ Sammel-Aktion**.
War beim Filter- oder Sortierwechsel ein Medium ausgewählt und ist es
auch in der neuen Trefferliste enthalten, **springt die Galerie dorthin
zurück** statt oben neu zu beginnen - Esc aus der Seed-Varianten-Suche
führt so direkt zum zuletzt angeklickten Bild.
Der **Sortier-Knopf** (Hinzugefügt / Erstellt /
Dateiname / Dateigröße / Container / Bewertung - Unbewertete und Undatierte
zuletzt) und die **Dichte S/M/L** sitzen oben in der Topbar neben dem
Suchfeld. Der Sortier-Knopf öffnet ein kleines Menü;
ein **zweiter Klick auf den aktiven Eintrag dreht die Richtung** (Pfeil
↑/↓ am Knopf und am Chip). Die Sortierung ist Teil des Suchzustands: eine
andere Wahl als der Standard „Hinzugefügt" erscheint als Sortier-Chip neben
den Filtern und wird mit einer gespeicherten Suche **mitgespeichert**; das
Laden einer Suche stellt auch ihre Sortierung wieder her. Die zuletzt im
Menü gewählte Sortierung **merkt sich fml im Browser**: Sie gilt überall
dort weiter, wo keine Suche einen eigenen Sortier-Chip mitbringt — auch
nach einem Neustart und nach „✕ Filter zurücksetzen". Videos tragen ein VIDEO-Badge, jede Kachel
einen Tool-/Container-Chip. **Klick** wählt ein Medium aus (Panel rechts),
**Space** öffnet die Lupe (schnelles Durchblättern), **Doppelklick oder Enter** die Einzelbildansicht (Zoom + Metadaten); **Pfeiltasten** bewegen die Auswahl auch in der Übersicht (←/→ ein Medium, ↑/↓ eine Zeile).

**Rechts - Detail-Panel:** Immer sichtbar. Von oben nach unten: Vorschau
(Klick → Lupe) · Dateiname, Typ, Format, Größe, **Rating-Punkte** ·
**KURATIERT** (deine Tags und Notizen) · **GENERATION** (die
interpretierten Felder: Modell, Sampler/Steps/CFG, Seed mit Klick-Kopieren,
Prompt/Negativ - mit Badge, welcher Parser sie erzeugt hat; ein
Negativ-Prompt, der wortgleich zum Prompt ist, wird nicht angezeigt -
manche Workflows lassen die beiden für uns nicht unterscheiden, und
zweimal derselbe Text wäre nur Rauschen. Unten **„🎲 Seed-Varianten
suchen"**: baut eine exakte Chip-Suche nach derselben Generierung -
Prompt, Negativ, Modell, LoRAs, Sampler, Scheduler, Steps, CFG und Größe
dieses Bilds, nur der Seed variiert. Ideal zum Aufräumen und Vergleichen
von Seed-Serien; zu streng? Einzelne Chips entfernen lockert die Suche) ·
**WORKFLOW**
(bei ComfyUI-Medien: „Node-Graph ansehen" und „als .json laden"; bei
A1111-Bildern mit Badge „ComfyUI · erzeugt" - siehe Workflow-Ansicht - plus
**„A1111-Infotext kopieren"**: der unveränderte Infotext für PNG Info /
txt2img in A1111 und Forge) ·
aufklappbar **Roh-Metadaten** (Schicht 1, byte-treu mit Quell-Label) und
**Fundorte** · **DATEI** (Format, Größe, **Erstellt** - das Erstelldatum
mit Uhrzeit (UTC), nach dem „Nach Jahr" gruppiert und die Sortierung
„Erstellt" sekundengenau ordnet; „ohne Datum" heißt: kein plausibles Datum
gefunden, nur Datum ohne Uhrzeit: die Uhrzeit ließ sich für den
Alt-Bestand nicht mehr sicher ermitteln -, Hinzugefügt, Hash). Medien ohne
erkannte Generierungs-Daten zeigen einen Hinweis - die Roh-Schicht bleibt
immer einsehbar.

**Panelbreiten:** Die Trennlinien links und rechts der Galerie lassen sich
**ziehen** (z. B. Sidebar breiter für lange Modellnamen, rechtes Panel breiter
für Querformat-Bilder); Doppelklick auf die Trennlinie stellt den Standard
wieder her. Die Wahl bleibt gespeichert.

## Einzelbildansicht (Zoom + Metadaten)

**Doppelklick oder Enter** öffnet das ausgewählte Medium in der
Einzelbildansicht - der Arbeitsansicht mit echtem Zoom: Stufen
**Anpassen / 50 / 100 / 200 %**, **Mausrad** zoomt stufenlos,
**Doppelklick im Bild** springt zwischen Anpassen und 100 %, gezogen wird
mit der Maus. Die Prozente meinen **echte Pixel**: Bei 100 % entspricht
ein Bildpixel einem Bildschirmpixel - unabhängig von OS-Skalierung
(Windows 150 %, Retina-Macs) und Browser-Zoom. So ist 100 % überall
pixelscharf und die verlässliche Stufe, um Details und Artefakte zu
beurteilen. Die **zuletzt in der Zoomleiste gewählte Stufe wird
gemerkt** und gilt für jedes weitere Bild (wer immer 100 % will, wählt
es einmal); Mausrad und Doppelklick erzeugen bildabhängige
Zwischenwerte und verändern die gemerkte Stufe bewusst nicht. Rechts steht das komplette Metadaten-Panel in breiter Form -
Bewerten (auch Tasten 1-5), Tags, Modell und Notizen funktionieren hier
genauso; mittelfristig kommen weitere Werkzeuge dazu (Metadaten bearbeiten,
Push-to-ComfyUI). **←/→** blättert in Grid-Reihenfolge; **Esc, Enter oder ✕**
führen zur Galerie zurück, die auf dem zuletzt betrachteten Bild steht.

**📂 Im Dateimanager anzeigen** (oben rechts, auch in der Lupe): öffnet
Explorer (Windows) bzw. Finder (macOS) mit markierter Datei - dem ersten
noch existierenden Fundort, dessen Inhalt vor dem Öffnen **per SHA-256
verifiziert** wird (liegt am katalogisierten Pfad inzwischen eine andere
Datei, meldet der Knopf ehrlich „kein Fundort mehr vorhanden" statt aufs
falsche Bild zu zeigen; bei großen Videos kann die Prüfung einen Moment
dauern). Alles Weitere (umbenennen, endgültig löschen)
passiert bewusst dort: fml selbst fasst Dateien nie an. Hinweis: Das
Fenster öffnet sich auf dem Rechner, auf dem der Server läuft - im
normalen localhost-Betrieb ist das der eigene.

## Lupe (Vollbild)

Space oder Klick auf die Panel-Vorschau - das schnelle Vollbild zum Durchblättern. Großes Medium
(Videos spielen, animierte WEBP animieren), **`←`/`→` blättert** in
Grid-Reihenfolge (Nachbarn werden vorgeladen - gebaut für schnelles
Durchsehen à la Lightroom/IrfanView), `Pos1`/`Ende` springt zum
ersten/letzten Medium, `Space`/`Esc` schließt - die Übersicht steht danach auf dem zuletzt
betrachteten Medium. Panel und Galerie folgen beim Blättern automatisch.

**🕸 Workflow-Ansicht:** Bei ComfyUI-Medien (auch Videos!) schaltet der
Bild/Workflow-Umschalter oben auf den eingebetteten Node-Graphen um - Nodes
mit Titeln, Farben, Widget-Werten und Verbindungen; ziehen verschiebt, das
Mausrad zoomt. Der dritte Knopf **„Einzelbild"** wechselt an gleicher
Stelle in die Einzelbildansicht. „als .json laden" lädt den **unveränderten** Original-Workflow
herunter, der sich per Drag&Drop direkt wieder in ComfyUI öffnen lässt.
(Die Vorschau liest nur das gespeicherte Workflow-JSON - sie braucht kein
laufendes ComfyUI und bricht nicht mit ComfyUI-Updates.)

**A1111-Bilder** bekommen dieselbe Ansicht: aus den interpretierten Feldern
wird ein minimaler, echter ComfyUI-Graph erzeugt (Checkpoint → LoRAs →
Prompt/Negativ → KSampler → Decode) - die Leiste sagt ehrlich „aus dem
A1111-Infotext erzeugt". Der Download ist direkt in ComfyUI ladbar
(Sampler-Namen übersetzt, Datei-Endungen sind Vermutung); Hires-Fix,
ADetailer & Co. bildet der Graph bewusst nicht ab - dafür gibt es
**„A1111-Infotext kopieren"** im Detail-Panel.

## Kuratieren (Bewerten, Tags, Notizen)

Alles Manuelle ist eine eigene Schicht - strikt getrennt von dem, was aus den
Dateien extrahiert wurde.

- **Mehrere auswählen:** **Shift-Klick** markiert einen Bereich,
  **Strg/Cmd-Klick** nimmt einzelne Kacheln dazu oder heraus. Bewertung,
  Tags und Modell-Zuweisung wirken dann auf die **ganze Auswahl** (das
  Panel zeigt einen Hinweis mit der Anzahl).
- **Bewerten:** Tasten `1`–`5` auf das ausgewählte Medium (in Übersicht und
  Lupe), `0` löscht, dieselbe Zahl nochmal ebenfalls (Toggle). Oder die
  Punkte im Panel-Kopf bzw. unten in der Lupe anklicken. Kacheln zeigen die
  Sterne als kleine Punktreihe.
- **Modell zuweisen:** Eingabefeld unter KURATIERT (mit Vorschlägen aus dem
  Bestand) - für Medien ohne verwertbare Metadaten (Midjourney-Screenshot-
  Ära & Co.). Das manuelle Modell **übersteuert** das erkannte in „Nach
  Modell" und allen Modell-Filtern; leeres Feld entfernt es wieder. Die
  GENERATION-Sektion zeigt weiterhin unverändert, was extrahiert wurde.
- **Tags:** Im Panel unter KURATIERT eintippen und Enter - bereits vergebene
  Tags werden beim Tippen vorgeschlagen (dein Vokabular). ✕ am Tag löst ihn
  vom Medium; im Vokabular bleibt er erhalten.
- **Notizen:** Freitext im Panel; speichert beim Verlassen des Feldes.
- **Ablehnen (ersetzt Löschen):** Taste **Entf** auf die Auswahl (auch
  Multiselect). Ein Dialog nennt die Anzahl und erklärt die Folgen; nach
  Bestätigung verschwindet das Medium aus der Bibliothek
  (samt Bewertung/Tags/Notizen) und sein Hash kommt auf die **Sperrliste** -
  ein Re-Import wird verhindert (sichtbarer Ausgang `_gesperrt/` im
  Quellordner). **Die Datei selbst bleibt unangetastet**, egal ob sie in der
  Library liegt oder nur indiziert wurde - fml löscht und verschiebt beim
  Ablehnen nichts (»Original heilig«). Die Ansicht springt dabei nicht an
  den Anfang: Die Scrollposition bleibt stehen, und die Auswahl rückt auf
  den **Nachfolger** an derselben Position — eine Seed-Serie lässt sich so
  mit Entf, Entf, Entf … zügig durchsortieren. Die Sperrliste merkt sich die
  letzten Fundorte der Datei. Entsperren: Admin-Dashboard → Probleme →
  „Ansehen & aufräumen" → entsperren; nach einem erneuten Scan/Import ist
  das Medium vollständig wieder da (nur die frühere Kuratierung nicht).

## Sammel-Aktion: alle Treffer auf einmal (⚡)

Für „diese Suche eingrenzen, dann ALLE Treffer taggen/bewerten" gibt es den
Knopf **⚡ Sammel-Aktion** rechts in der Kopfzeile über der Galerie (neben
„Filter zurücksetzen"). Er öffnet einen Dialog, der
zeigt, was getroffen wird (die Chips + Trefferzahl), und fünf Aktionen
anbietet - egal ob 50 oder 20.000 Treffer:

- **Basisbewertung** (1-5 ★): füllt **nur Unbewertete** - bereits vergebene
  Bewertungen bleiben unangetastet. Nichts wird zerstört.
- **Tag anhängen:** alle Treffer bekommen den Tag (wer ihn schon hat, wird
  übersprungen - die Zusammenfassung sagt ehrlich, wie viele).
- **Modell setzen:** wie die Modell-Zuweisung im Panel, nur für alle Treffer
  (überschreibt ein vorhandenes manuelles Modell).
- **Notiz anhängen:** der Text wird an vorhandene Notizen **angehängt**
  (neue Zeile), nie überschrieben.
- **Ablehnen:** alle Treffer aus dem Katalog nehmen + Hashes sperren (wie
  Entf, s. o. - die Dateien bleiben unangetastet). Wirkt bewusst auch auf
  Bewertete und läuft **allein**, nicht kombiniert mit anderen Aktionen.

Gibt es gerade eine Multiselect-Auswahl, fragt der Dialog, ob die Aktion auf
die **Auswahl (N)** oder auf **alle Treffer (M)** wirken soll. Ohne Chips
wirkt sie ehrlich auf die ganze Bibliothek - die Zahl steht groß im Dialog.
Der Anwenden-Knopf fragt beim ersten Klick noch einmal nach
(„Wirklich anwenden auf …?"), der zweite Klick führt aus. Danach zeigt der
Dialog eine Zusammenfassung, und Grid + Seitenleiste frischen sich auf.

## Gespeicherte Suchen

Jede Suche - egal ob aus Sidebar-Klicks, Textbegriffen oder getippten
Ausdrücken zusammengesetzt - lässt sich mit dem **☆ neben den Chips**
speichern. Das ☆ öffnet den **Speicherdialog**: er zeigt die Chips als
Vorschau, die aktuelle Trefferzahl, einen Hinweis, falls eine Sortierung
mitgespeichert wird, und fragt nach dem Namen. Die Suche erscheint links
unter „Gespeicherte Suchen" mit Live-Zähler; ein Klick lädt sie **als
Chips zurück** (alles bleibt bearbeitbar). Ist eine gespeicherte Suche
geladen, wird der Dialog zur Pflege: **Überschreiben** sichert den
bearbeiteten Stand (ein geänderter Name benennt dabei um), **Als neue
Suche speichern** legt eine Kopie an, **Löschen** entfernt sie (zweiter
Klick bestätigt). Das ✕ an der Sidebar-Zeile löscht wie gehabt direkt.
Eine mitgegebene Sortierung (`sort:` bzw. der Sortier-Knopf) wird
mitgespeichert und beim Laden wiederhergestellt.

**Für Fortgeschrittene:** Die Suchleiste versteht auch Filterausdrücke - sie
zeigen sofort das gefilterte Grid. Prädikate sind UND-verknüpft, `-` negiert;
**mehrere Werte in einem Prädikat** trennt ` | ` (Pipe mit Leerzeichen) als
ODER:

```
model: flux -tag: wip rating>=4
model: flux | krea rating>=4
container: png -has: workflow
prompt: "red hair" rating=0
year: 2022 | unbekannt sort: created
```

`model: flux | krea` heißt Flux ODER Krea; `-tag: wip | alt` heißt weder
`wip` noch `alt`. ODER gibt es nur bei Werte-Prädikaten - Vergleiche
(`rating>=`, `width>=` …) bilden Bereiche über `>=`/`<=`-Paare. Die
Direktive **`sort: <schlüssel>`** (einmal pro Ausdruck) legt die Sortierung
fest und wird mit der Suche gespeichert: `added` (hinzugefügt), `created`
(Erstelldatum), `size`, `name`, `container`, `rating`. Die Richtung dreht
ein Suffix: `sort: created-auf` (älteste zuerst), `sort: name-ab` (Z–A) -
englisch als `-asc`/`-desc` (`sort: created-asc`).
Ohne Suffix gilt die sinnvolle Standardrichtung (Neuestes/Größtes/Bestes
zuerst, Namen A–Z); Unbewertete und Undatierte bleiben in beiden
Richtungen am Ende.

`feld: wert` sucht als Teilstring, `feld: "wert"` exakt; `rating=0` heißt
unbewertet; erlaubte Felder sind die der [Schicht 2](interpretation.md) plus
`tag:`, `container:`, `has:` (`has: workflow` = eingebetteter Workflow,
`has: model` = Schicht-2-Feld vorhanden - **`-has: model`** findet Medien
**ohne** erkanntes Modell), `format:` (grobe Seitenverhältnis-Klassen
`quadratisch`/`hochformat`/`querformat`/`widescreen` - englisch
`square`/`portrait`/`landscape`/`widescreen`), `mp:`
(Megapixel-Bereiche `<1`/`1-2`/`2-4`/`>4`), `year:`/`month:`
(Erstelldatum: `year: 2022`, `month: 2022-07`, `year: unbekannt` -
englisch `year: unknown`),
`fundort:` (englisch `location:`; `library` = mindestens ein Fundort
liegt in der Media Library, `extern` - englisch `external` - = nur
außerhalb indiziert; braucht eine konfigurierte Library),
`text:` (freier Begriff - kuratierte Suche über interpretierte Felder,
Dateinamen und manuelle Schicht; genau die Semantik der Live-Suche:
`text: ball text: wüste`), `raw:` (wie `text:`, aber **zusätzlich in den
Roh-Metadaten** - findet z. B. Node-Namen im Workflow-JSON: `raw: ipadapter`),
`datei:` (englisch `file:`; gezielt der **Dateiname** der Fundorte, ohne
Verzeichnis - Teilstring, mit `"…"` exakt; praktisch für metadatenlose
Bestände wie Midjourney-Exporte und natürlich auch in Arena-Ausdrücken
nutzbar)
und die Medien-Eckwerte `width`/`height`/`fps` mit Vergleich (z. B.
`width>=1920 fps>=24`). Gespeicherte
Suchen sind dynamisch: ausgewertet wird bei jedem Öffnen.

## Suchen: EIN Suchzustand aus Chips

Die Suche ist **ein Zustand aus Chips** über der Galerie - Sidebar-Klicks,
Textbegriffe und getippte Ausdrücke landen alle im selben Zustand und
kombinieren sich, statt einander zu ersetzen:

```
Bibliothek / [ Modell: flux | krea ✕ ] [ Text: wüste ✕ ] [ ★ ≥ 4 ✕ ] · 1.234   ☆ speichern · ✕ · ⚡
```

**☆ speichern**, **✕ Filter zurücksetzen** und **⚡ Sammel-Aktion** sitzen
als EINE Knopf-Gruppe rechts; reicht die Breite nicht, rutscht die Gruppe
geschlossen unter die Chips. Unterhalb von FullHD-Breite zeigen Zurücksetzen
und Sammel-Aktion nur noch ihr Icon (Hover verrät die Funktion) und das
Präfix „Bibliothek /" wird ausgeblendet - kleine Monitore bleiben aufgeräumt.

- **Tippen filtert live:** Ab dem dritten Zeichen filtert die Galerie nach
  kurzer Tipp-Pause (die Galerie IST die Trefferliste - Thumbnails statt
  Textausschnitte). **Enter** macht aus den Begriffen feste **Text-Chips**
  (`"…"` hält Wortfolgen zusammen; ein Anführungszeichen IM Wert schreibt
  man doppelt: `prompt: "sag ""hi"""`); mehrere Wörter sind UND-verknüpft.
  Begriffe zählen als **Wortanfänge** (`wüs` findet „Wüste"; dank
  Volltextindex auch bei 250k in Millisekunden).
- **Sidebar-Klicks** werden Chips: ein zweiter Wert derselben Gruppe
  erweitert zum **ODER**, ein Klick auf einen aktiven Wert entfernt ihn.
  Die Sidebar-Zähler rechnen dabei im aktuellen Kontext mit (leere Werte
  gedimmt); „mit/ohne Eingangsbild" ersetzen einander.
- **Getippte Filterausdrücke** (siehe oben, Enter) werden in Chips zerlegt -
  getippt und geklickt ist garantiert dasselbe.
- **Klick auf einen Chip** öffnet ihn zum Bearbeiten: Werte entfernen oder
  ergänzen (ODER), „ausschließen" macht aus dem Chip eine Negation
  (weder-noch); ✕ am Chip entfernt das Kriterium. Alles auf einmal leert
  **„✕ Filter zurücksetzen"** rechts in der Kopfzeile - oder **Esc**
  (wenn gerade kein Overlay offen ist) bzw. „Alle Medien" in der Sidebar.
- **☆ speichern** öffnet den Speicherdialog (Vorschau + Trefferzahl + Name)
  und legt den ganzen Zustand als gespeicherte Suche ab; geladene Suchen
  lassen sich dort überschreiben, umbenennen, kopieren und löschen.
- **„+ Kriterium"** (neben den Chips) öffnet den **Baukasten**: alle
  Kategorien (Modell, LoRA, Tags, Bewertung, Text, Jahr, Dateityp, Format,
  Auflösung, Eingangsbild, Eckwerte, Rohdaten-Suche, Dateiname, Sortierung) mit
  Wertelisten und **Zählern im aktuellen Kontext**. Mehrere Werte anklicken
  = ODER-Chip; „ausschließen" macht Negativ-Kriterien; die Rohdaten-Suche
  ist das Opt-in für Treffer in Workflow-JSONs (`raw:`).
- **Tipphilfe:** Beim Tippen schlägt das Suchfeld passende Facetten vor
  („Modell: flux.1-dev (1.234)", „Tag: favorit (56)", …). ↑/↓ wählt,
  **Enter übernimmt den Vorschlag als Chip** - Enter ohne Auswahl macht wie
  gehabt Text-Chips. Grammatik lernen ist damit optional.

Gesucht wird **kuratiert**: über die interpretierten Felder (Prompt,
Modell, Seed, Sampler, …), den **Dateinamen** (bei metadatenarmen Quellen
wie Midjourney oft das Einzige, was das Bild beschreibt) und **deine
manuelle Schicht** (Tags, Notizen, manuelles Modell - ein vergebener Tag
ist sofort findbar). **Nicht** in der Standard-Suche: Negativ-Prompts (wer
„hund" sucht, will keine Bilder, die ausdrücklich keinen Hund zeigen
sollen - gezielt: `negative_prompt: hund`) und die
Roh-Metadaten/Workflow-JSONs (Opt-in: die Kategorie **Rohdaten-Suche** im
„+ Kriterium"-Baukasten bzw. `raw: begriff`).
Für die manuelle Schicht: **`rating>=4`** (auch `<=`, `=`) findet nach
deinen Sternen, **`tag: xyz`** nach deinen Tags. Die **Dubletten-Ansicht**
bleibt eine eigene Ansicht außerhalb der Chips.

**Scrollen in gefilterten Ansichten ist flott** (ADR 0048): Beim Setzen
eines Filters wird die Trefferliste einmal aufgebaut (bei sehr großen
Beständen ein kurzer Moment), danach kosten Tiefscrollen und
Scrollleisten-Sprünge praktisch nichts mehr - egal wie tief. Der Server
merkt sich die Liste, bis sich am Bestand etwas ändert (Import, Bewertung,
Re-Scan, …); danach baut der nächste Zugriff sie automatisch frisch.
Während ein Import läuft, ändert sich der Bestand laufend - dann ist das
Scrollen vorübergehend wieder so gemächlich wie früher, zeigt dafür aber
immer den frischen Stand.

## Schnellmenü + Admin-Konsole

Der Knopf oben rechts öffnet das **Schnellmenü**: Absprung ins
Admin-Dashboard, die häufigsten Wartungsaktionen (Re-Scan, Neu
interpretieren, Thumbnail-Cache leeren) und der Theme-Umschalter - ohne
die Bibliothek zu verlassen. Esc oder Klick daneben schließt.

Das **Admin-Dashboard** (aus dem Schnellmenü oder über die
Aktivitäts-Anzeige) ist EINE Seite mit Regionen:

1. **Überblick:** Kennzahlen des Bestands (Items, Metadaten, Thumbnail-
   Cache, DB-Größe, Parser, ffprobe/ffmpeg) und daneben die **Aktivität**
   der laufenden Aufgabe mit Live-Fortschritt.
2. **Quellen & Import:** EIN Aufnahme-Formular (Ordner + Modus
   kopieren / verschieben / katalogisieren + „einmal jetzt" / „dauerhaft
   beobachten") und die Liste der Watchordner.
3. **Wartung:** kleine Knöpfe nach Funktionsbereich - Re-Scan, verwaiste
   Fundorte, Thumbnails, Integritätscheck, VACUUM, Neu interpretieren,
   Erstelldaten nachtragen, Suchindex neu aufbauen.
4. **Probleme:** Zusammenfassung mit Overlay zum Quittieren (nach Fehlerart
   gruppiert, ehrliche Zahlen); dort auch die Sperrliste (abgelehnte Medien
   wieder entsperren).
5. **Konfiguration:** Media Library (wirkt sofort), ältestes plausibles
   Datum, Thumbnail-Größe (legt `config.toml.bak` an; kommentierte
   Referenz ist `config.example.toml`).

Details: [admin.md](admin.md). „Zurück zur Bibliothek" oben links (oder
`Esc`) schließt das Dashboard. Nach abgeschlossenen Aufgaben aktualisieren
sich Galerie und Zähler von selbst.

## Tastatur

| Taste | Wirkung |
| --- | --- |
| `Space` | Lupe öffnen/schließen |
| `Enter` / Doppelklick | Einzelbildansicht öffnen/schließen |
| `+` / `-` | Zoomen (Einzelbildansicht) |
| `1`–`5` / `0` | Bewerten / Bewertung löschen (Toggle) |
| `←` / `→` | Blättern - in Übersicht und Lupe |
| `↑` / `↓` | Eine Zeile hoch/runter (Übersicht) |
| `Entf` | Auswahl ablehnen (Item raus + Sperre, Datei bleibt) |
| `Pos1` / `Ende` | Erstes/letztes Medium (Lupe) |
| `Esc` | Offenes Overlay schließen (Lupe, Dialoge, Admin) - sonst: **Filter zurücksetzen** |

## Wichtig / Grenzen (Stand jetzt)

- **„Nur katalogisieren" kopiert nichts.** Dieser Modus nimmt Dateien dort
  auf, wo sie liegen. Der Import (Kopieren in die datumsbasierte Media
  Library, mit Dublettencheck und Watchordnern) ist der Weg daneben -
  siehe [import.md](import.md).
- **Video-Metadaten brauchen ffprobe** (Teil von ffmpeg, siehe
  [extraction.md](extraction.md)). Ohne ffprobe werden Videos trotzdem
  katalogisiert; ein erneuter Scan nach der Installation holt die Metadaten nach.
- **TIFF und PSD** zeigt kein Browser nativ — Galerie, Lupe und
  Einzelbildansicht rendern dafür serverseitig ein JPEG (das Original bleibt
  unangetastet). PSD nutzt das eingebettete Composite. PSDs, die **ohne
  „Maximale Kompatibilität"** gespeichert wurden, tragen keinen Composite (nur
  die Ebenen) — sie zeigen ehrlich „Keine Vorschau verfügbar" statt eines
  falschen weißen Bildes. Wer sie sehen will, speichert sie in Photoshop einmal
  mit „Maximale Kompatibilität" neu. **PDF** wird nur katalogisiert (kein
  Extraktor, ADR 0051).
- **Nur für dich gedacht:** Der Server bindet standardmäßig nur an `localhost` und
  hat keine Zugriffsbeschränkung - nicht ungeschützt ins Netz stellen.
- **Immer nur ein Schreiber:** Lass nicht gleichzeitig die GUI und einen
  CLI-Scan auf dieselbe DB los (ADR 0007).
