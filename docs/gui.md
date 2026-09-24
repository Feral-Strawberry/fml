# Die Oberfläche (lokale Web-GUI)

> Was ist das? Die lokale Weboberfläche der Feral Media Library (fml):
> Bestand durchsehen und
> durchsuchen, Metadaten lesen, Ordner scannen/beobachten und die Wartung
> erledigen - alles ohne Kommandozeile. Drei-Spalten-Layout, dunkles
> Theme (umschaltbar auf hell).

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

**Topbar:** Mit Audio-Modul links der Umschalter **▦ Galerie | ♪ Audio**
(zwei Ansichten, eine Suche, siehe [Audio](audio.md#audioansicht)).
Suchfeld (Mitte), direkt daneben der **Sortier-Knopf** und die
**Dichte S/M/L** (die Leiste unter der Suche gehört den Chips), Aktivitäts-Anzeige
(pulsiert, wenn Scan/Wartung läuft - ein Link auf die Admin-Seite),
**Dark/Light-Umschalter** (Mond/Sonne; dieselbe Wahl gilt im Admin),
Admin-Knopf (ein echter Link nach `/admin`: Klick öffnet den Admin,
Mittelklick den Admin in einem zweiten Tab). Ist in der
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
Die Such-Grammatik versteht zusätzlich **englische
Aliasse** für ihre deutschen Reste: `file:` = `datei:`, `location:` =
`fundort:`, `portrait`/`square`/`landscape` = `hochformat`/`quadratisch`/
`querformat`, `-asc`/`-desc` = `-auf`/`-ab`, `external` = `extern` und
`unknown` = `unbekannt`. Beide Schreibweisen werden
immer verstanden, egal welche Sprache eingestellt ist; **kanonisch** (in
Chips, gespeicherten Suchen und serialisierten Ausdrücken) bleibt die
bisherige Schreibweise — gespeicherte Smart Folders bleiben unangetastet
gültig. Auch alle **vom Server erzeugten Texte** folgen
der UI-Sprache: Aktivitäts-Labels und Fortschritt im Admin-Dashboard,
Ergebnis-Zusammenfassungen („Import: 3 neu · 2 Dubletten"), Fehlermeldungen
der Such-Grammatik und alle übrigen Server-Fehler. Einzige Ausnahme:
Scan-Probleme, die VOR dem Update aufgezeichnet wurden, erscheinen
unverändert in ihrem alten (deutschen) Wortlaut — neue Einträge sind
sprachneutral gespeichert und werden beim Anzeigen übersetzt.

**Links - Quellen:** „Alle Medien", **Dubletten** (Items, die an mehreren
Pfaden auf der Platte liegen - das Panel zeigt alle Fundorte), deine
**gespeicherten Suchen**, die Gruppe **Bewertung** (genau n Sterne - auch gezielt
schlecht Bewertetes), **Medienart** (Bild · Video - nur die Arten,
die es im Bestand gibt; Chip `typ: video`; Audio hat mit dem Audio-Modul
eine eigene Ansicht, siehe [Audio](audio.md#audioansicht), in der Galerie
zählt „Audio" nur die fertigen Songs mit Cover), **Generator** (die Plattform, auf der die Datei
entstand: ComfyUI, A1111, Midjourney, Google, OpenAI, Adobe, Topaz - aus den
eingebetteten Metadaten bzw. Content Credentials, siehe
[Interpretation](interpretation.md#generator-erkennung-gemini-chatgpt-firefly--co-c2paxmp);
Chip `tool: google`, gleichbedeutend `generator: google`; ein Klick lässt
die Modell-Liste darunter im Kontext zählen), **Nach Modell** - inklusive **„(unbekanntes Modell)"**
für Medien ohne interpretiertes Modellfeld (Midjourney, Gemini, ChatGPT, …);
WAN-2.2-Zweistufen-Checkpoints (High-/Low-Noise) erscheinen als EIN Eintrag,
der Tooltip nennt beide Rohnamen und der Klick filtert auf beide -,
**Nach Jahr** (Erstelldatum; das Caret vor der Jahreszahl klappt die Monate
auf - Alt-Bestände bekommen ihr Datum per „Re-Scan: alle Fundorte"),
**Nach LoRA** (die beim Generieren benutzten LoRAs, meistgenutzte zuerst;
in den langen Listen Generator, Modell und LoRA stehen bei aktiven Chips die
Zeilen mit Treffern oben, die im Kontext leeren gedimmt unter einer
Trennzeile „keine Treffer mit diesem Filter · 106 Modelle" - ohne aktiven Chip gibt es
diese Zeile nicht).
Darunter liegt der Sammelblock **„Weitere Kriterien"** (ab Werk
zugeklappt, ein Klick auf die Überschrift klappt ihn auf; fml merkt sich
den Zustand je Browser) mit
**Nach Dateityp** (PNG, WEBP, Video-Container, …), **Nach Format**
(grobe Seitenverhältnis-Klassen: Hochformat / Quadratisch / Querformat /
Widescreen - zur Fehlersuche nach einem Import), **Nach Auflösung**
(Megapixel-Bereiche: unter 1 / 1-2 / 2-4 / über 4 MP), **Eingangsbild**
(mit/ohne - findet img2img- und Bild-zu-Video-Ergebnisse) und **Fundort**
(„in der Library" = mindestens eine Kopie liegt in der Media Library, „nur
extern" = nur am Ort katalogisiert, z. B. per `katalogisieren` von fremden
Platten; die Gruppe erscheint nur, wenn eine Media Library konfiguriert
ist). Ein Klick legt
einen **Chip** in die Suchleiste über der Galerie (siehe „Suchen").
Jede Gruppe lässt sich per Klick auf ihre Überschrift zuklappen. Ist in
einer zugeklappten Gruppe (oder im zugeklappten Block) ein Wert aktiv,
steht das im Kopf: **„· 1 aktiv"** - kein Filter wirkt unsichtbar.

**Klick-Regel wie in Lightroom (geändert im September 2026 - bitte lesen,
wenn du fml schon länger nutzt):**

- **Klick** auf einen Wert wählt ihn - ein Klick auf einen **anderen Wert
  derselben Gruppe ersetzt** die Auswahl (von „Google" zu „OpenAI"
  wechseln, ohne erst abzuwählen).
- **Cmd-Klick (Mac) bzw. Strg-Klick (Windows/Linux)** **fügt hinzu** und
  erweitert den Chip zum **ODER** („flux ODER krea").
- **Klick auf den aktiven (markierten) Wert** nimmt ihn wieder heraus.

Bis dahin erweiterte schon der einfache Klick zum ODER. Wer das ODER will,
hält jetzt die Taste - oder tippt es in die Suchleiste (`tool: google |
openai`). Das „+ Kriterium"-Popover und die Tipphilfe fügen weiterhin
hinzu. Der Hinweis steht als Tooltip an jeder Gruppenüberschrift und an
jeder Zeile - mit der Taste deines Systems (⌘ auf dem Mac, Strg sonst).
Und beim ersten Mal, wenn ein Klick eine bestehende Auswahl ersetzt,
erscheint kurz unter der Gruppe „Auswahl ersetzt · ⌘-Klick fügt hinzu
(ODER)" - höchstens dreimal, dann ist die Regel gelernt.

Die Zähler **filtern mit**: Sobald Chips aktiv sind, zeigt jede Gruppe, wie
viele Treffer ein Klick **im aktuellen Kontext** brächte - gerechnet gegen
die jeweils *anderen* Kriterien (die eigene Gruppe klammert sich aus, sonst
ließe sich kein ODER mehr aufbauen). Werte, die gerade nichts träfen,
werden **gedimmt statt versteckt** - sichtbar bleibt, was es gäbe.

Jede Gruppe lässt sich per Klick auf ihre Überschrift **ein-/ausklappen**
(bleibt gemerkt). Unten der Bibliotheks-Footer: Items und Gesamtgröße - mit
konfigurierter Media Library getrennt als **„Library X GB · gesamt Y GB"**
(Library = was physisch unter der Bestands-Wurzel liegt, gesamt = alles
Katalogisierte, auch Externes).

**Mitte - Galerie:** Virtualisiertes Grid (flüssig auch bei sehr großen
Beständen - nur sichtbare Kacheln sind im Speicher), neueste zuerst. Oben:
Breadcrumb mit den Such-Chips und dem Zähler; rechts daneben fest verankert
**✕ Filter zurücksetzen** (erscheint, sobald gefiltert wird - auch **Esc**
leert die Filter, wenn kein Overlay offen ist) und **⚡ Sammel-Aktion**.
War beim Filter- oder Sortierwechsel ein Medium ausgewählt und ist es
auch in der neuen Trefferliste enthalten, **springt die Galerie dorthin
zurück** statt oben neu zu beginnen - Esc aus der Seed-Varianten-Suche
führt so direkt zum zuletzt angeklickten Bild. Einzige Ausnahme ist der
Klick auf **„Alle Medien"** in der Sidebar: das ist die Reset-Taste, die
Galerie steht danach oben, ohne Auswahl.
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
einen Tool-/Container-Chip. Mit [Audio-Modul](audio.md) stehen auch
**fertige Songs** in der Galerie: Songs mit Cover, als Kachel aus dem
Coverbild mit ♪, Dauer und ▶ (Leertaste spielt, siehe
[Cover](audio.md#cover-fertige-songs-in-der-galerie)). **Klick** wählt ein Medium aus (Panel rechts),
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
dieses Bilds, nur der Seed variiert (nur bei Medien mit Seed; Suno,
Midjourney, ChatGPT & Co. schreiben keinen). Ideal zum Aufräumen und Vergleichen
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
**Anpassen / max. 100 % / 50 / 100 / 200 %**, **Mausrad** zoomt stufenlos,
**Doppelklick im Bild** springt zwischen Anpassen und 100 %, gezogen wird
mit der Maus. Die Prozente meinen **echte Pixel**: Bei 100 % entspricht
ein Bildpixel einem Bildschirmpixel - unabhängig von OS-Skalierung
(Windows 150 %, Retina-Macs) und Browser-Zoom. So ist 100 % überall
pixelscharf und die verlässliche Stufe, um Details und Artefakte zu
beurteilen. Die **zuletzt in der Zoomleiste gewählte Stufe wird
gemerkt** und gilt für jedes weitere Bild (wer immer 100 % will, wählt
es einmal). **max. 100 %** ist der Alltagsmodus für gemischte Bestände:
echte Größe, aber höchstens bildschirmfüllend - ein kleines Bild steht
pixelscharf in 100 %, ein großes Hochkantbild wird wie bei „Anpassen"
verkleinert, statt nach unten aus dem Bild zu laufen. Mausrad und Doppelklick erzeugen bildabhängige
Zwischenwerte und verändern die gemerkte Stufe bewusst nicht. Rechts steht das komplette Metadaten-Panel in breiter Form -
Bewerten (auch Tasten 1-5), Tags, Modell und Notizen funktionieren hier
genauso; mittelfristig kommen weitere Werkzeuge dazu (Metadaten bearbeiten,
Push-to-ComfyUI). **←/→** blättert in Grid-Reihenfolge; **Esc, Enter oder ✕**
führen zur Galerie zurück, die auf dem zuletzt betrachteten Bild steht.

**📂 Im Dateimanager anzeigen** (oben rechts, auch in der Lupe): öffnet
Explorer (Windows) bzw. Finder (macOS) mit markierter Datei. Liegt die
Datei an mehreren Fundorten, gilt eine feste Reihenfolge: **Library-
Bestand vor Watch-Quelle vor sonstigen Orten**, und nur Fundorte, an denen
die Datei noch liegt und deren Größe stimmt. Welcher Fundort das ist,
zeigt das Panel **Fundorte** (siehe unten). Der Inhalt wird vor dem
Öffnen **per SHA-256 verifiziert** (liegt am katalogisierten Pfad
inzwischen eine andere Datei, meldet der Knopf ehrlich „kein Fundort mehr
vorhanden" statt aufs falsche Bild zu zeigen) - bei Dateien über 64 MB
entfällt das Hashen, dort zählt allein die Größenprüfung, damit der Knopf
bei großen Videos nicht minutenlang hängt. Während der Server prüft,
zeigt der Knopf ⏳; kann Explorer die Datei nicht markieren (Windows-Pfad
über 259 Zeichen), öffnet fml nur den Ordner und sagt das (📁 + Hinweis).
Alles Weitere (umbenennen, endgültig löschen)
passiert bewusst dort: fml selbst fasst Dateien nie an. Hinweis: Das
Fenster öffnet sich auf dem Rechner, auf dem der Server läuft - im
normalen localhost-Betrieb ist das der eigene.

**Fundorte** (Panel, aufklappbar): alle Pfade, an denen fml die Datei
kennt, in derselben Reihenfolge, die der 📂-Knopf benutzt. Jede Zeile
trägt ein Herkunfts-Kürzel - **Library** (unter der Bestands-Wurzel),
**Quelle** (unter einer Watch-Quelle, typisch „katalogisieren") oder
**extern** - und vor dem Fundort, den „Im Dateimanager anzeigen" öffnet,
steht das **📂 als Knopf**: derselbe wie oben rechts in Lupe und
Einzelansicht, er zeigt die Datei markiert im Explorer/Finder (für Songs
ohne Cover der einzige Weg, sie haben keine Lupe und keine Einzelansicht). Fehlt die Datei dort, steht „(fehlt)" dahinter; liegt am
Pfad inzwischen eine andere Datei (Größe passt nicht), „(andere Datei an
diesem Pfad)".

Jeder Pfad ist ein **Breadcrumb**: Ein Klick auf ein Ordner-Segment öffnet
genau diesen Ordner im Dateimanager - **ohne** Markierung, bewusst anders
als der 📂-Knopf oben rechts. Ein Klick auf den **Dateinamen** (fett)
öffnet die Datei mit dem Programm, das das System diesem Dateityp
zuordnet (Photoshop, VLC, …). So kommt man auch an einen Zweit-Fundort,
etwa um Dubletten im Dateisystem selbst abzuräumen, ohne dass fml den
Ordner verwalten muss. Die Segmente sind erst beim Überfahren
unterstrichen; ein Fehler (Ordner weg, Datei weg) erscheint für vier
Sekunden an der Zeile. fml fasst dabei nichts an - was das geöffnete
Programm danach mit der Datei macht, entscheidest du dort. Weil das Panel
in Galerie und Einzelbildansicht dasselbe ist, gilt das an beiden
Stellen.

## A/B-Vergleich (zwei Bilder überblenden)

Varianten aus Edit-Workflows unterscheiden sich oft nur in Kleinigkeiten
(ein Finger, eine Kante, ein Artefakt) - nebeneinander sieht man das
kaum. Der Vergleich legt **zwei markierte Bilder deckungsgleich
übereinander** und deckt B mit einer **Wischkante** auf, wie in
ComfyUI-Edit-Workflows.

**Öffnen:** genau zwei Medien markieren (Strg/Cmd-Klick oder
Shift-Klick), dann **Taste `C`** oder der Knopf **⇆ Vergleichen** in der
Kopfzeile der Galerie (erscheint nur bei genau zwei markierten Medien).
Das zuerst markierte Bild ist **A** (links), das zweite **B** (rechts).

- **Wischkante:** mit der Maus oder dem Finger irgendwo im Bild ziehen;
  **`←`/`→`** verschieben sie in kleinen Schritten (mit Shift grob),
  **`Pos1`/`Ende`** ganz nach links/rechts.
- **Space** (oder der Knopf oben rechts) schaltet dreifach um: **Wisch →
  nur A → nur B → Wisch**. „nur A"/„nur B" zeigen ein Bild ganz - so
  entsteht der Blinkvergleich, bei dem selbst winzige Unterschiede
  „springen". **Tab** tauscht A und B (und damit das Bewertungsziel).
- **Zoom** wie in der Einzelbildansicht: Anpassen / max. 100 % / 50 / 100 / 200 %,
  Mausrad, `+`/`-`, Doppelklick springt zwischen Anpassen und 100 %. Die
  Prozente meinen echte Pixel, die gemerkte Zoomstufe ist dieselbe wie
  dort. Gezoomt scrollt man mit den Bildlaufleisten.
- **Entscheiden:** Über dem Bild steht für jede Seite Name, Maße und die
  **Rating-Punkte**; dazu **Ablehnen** (Item raus + Sperre, die Datei
  bleibt unangetastet). Die Tasten **`1`-`5`/`0`** und **`Entf`** wirken
  auf **A** - mit Tab holt man das andere Bild nach A. Nach dem Ablehnen
  schließt sich der Vergleich.
- **Ungleiche Maße:** Beide Bilder werden auf die Breite von A gebracht,
  oben rechts erscheint der Hinweis „Maße unterschiedlich".
- **Esc, Enter oder ✕** führen zur Galerie zurück; die Zweier-Auswahl
  bleibt bestehen.

Erste Version **nur für Bilder**: Ist ein Video dabei, öffnet sich der
Vergleich mit einem Hinweis statt der Bilder (Frame-synchrones Vergleichen
kommt später).

## Lupe (Vollbild)

Space oder Klick auf die Panel-Vorschau - das schnelle Vollbild zum Durchblättern. Großes Medium
(Videos spielen, animierte WEBP animieren), **`←`/`→` blättert** in
Grid-Reihenfolge (Nachbarn werden vorgeladen - gebaut für schnelles
Durchsehen à la Lightroom/IrfanView), `Pos1`/`Ende` springt zum
ersten/letzten Medium, `Space`/`Esc` schließt - die Übersicht steht danach auf dem zuletzt
betrachteten Medium. Panel und Galerie folgen beim Blättern automatisch.

**🕸 Workflow-Ansicht:** Bei ComfyUI-Medien (auch Videos!) schaltet der
Bild/Workflow-Umschalter oben auf den eingebetteten Node-Graphen um. Seit
September 2026 sieht er aus wie in ComfyUI selbst: Raster, Node-Farben aus
dem Workflow, **Slot- und Verbindungsfarben nach Datentyp** (MODEL lila,
CLIP gelb, CONDITIONING orange, LATENT rosa, IMAGE blau, VAE rot),
**Widgets als Pillen mit Name und Wert** (`seed 123456789`, `steps 20`,
`cfg 1`, `sampler_name euler`), Prompts als Textfelder, Gruppen mit
Titelbalken, **stumme Nodes gedimmt, Bypass magenta**, eingeklappte Nodes
als Titelbalken, und **Subgraphs als Kästen** („⧉ 2 Nodes · Klick öffnet") -
ein Klick zeigt das Innere mit Ein- und Ausgängen, „‹ zurück" führt hoch.
Ziehen verschiebt, das Mausrad zoomt. Der dritte Knopf **„Einzelbild"**
wechselt an gleicher Stelle in die Einzelbildansicht. „als .json laden"
lädt den **unveränderten** Original-Workflow herunter, der sich per
Drag&Drop direkt wieder in ComfyUI öffnen lässt. (Die Vorschau liest nur
das gespeicherte Workflow-JSON - sie braucht kein laufendes ComfyUI und
bricht nicht mit ComfyUI-Updates.)

*Widget-Namen:* ComfyUI speichert Widget-Werte ohne Namen. fml kennt die
Namen der Kernknoten (KSampler, Loader, Encoder, Latent, Video, …) und
liest sie, wenn vorhanden, direkt aus neueren Workflows
(`widgets_values_named`). Für Custom-Nodes holt ein kleines Werkzeug die
Namen aus deiner eigenen ComfyUI-Installation - einmal bei laufendem
ComfyUI ausführen, danach beschriftet die Vorschau auch diese Nodes:

```bash
python tools/dump_object_info.py            # ComfyUI unter http://127.0.0.1:8188
python tools/dump_object_info.py --url http://192.168.1.20:8188
```

Das Ergebnis liegt als `widgets.json` neben der Oberfläche und ist reine
Information über deine Installation (kein Code, nicht im Repo). Werte, für
die kein Name bekannt ist, stehen weiterhin nackt in der Pille - nie geraten.

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
  Library liegt oder nur am Ort katalogisiert wurde - fml löscht und verschiebt beim
  Ablehnen nichts (»Original heilig«). Die Ansicht springt dabei nicht an
  den Anfang: Die Scrollposition bleibt stehen, und die Auswahl rückt auf
  den **Nachfolger** an derselben Position — eine Seed-Serie lässt sich so
  mit Entf, Entf, Entf … zügig durchsortieren. Die Sperrliste merkt sich die
  letzten Fundorte der Datei. Entsperren: Admin → Probleme → Sperrliste
  (suchbar, seitenweise) → entsperren; nach einem erneuten Scan/Import ist
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

## Suche, gespeicherte Suche, Ranking: ein Gedanke

Alles in fml beginnt mit einer **Suchentscheidung**: Welche Medien will
ich gerade sehen? Drei Dinge bauen aufeinander auf, in dieser
Reihenfolge:

1. **Die Suche** ist EIN Zustand aus **Chips** über der Galerie.
   Sidebar-Klicks, getippte Begriffe und Filterausdrücke landen alle in
   diesen Chips; die Galerie zeigt immer genau das, was die Chips sagen.
2. **Eine gespeicherte Suche** ist dieser Zustand **mit Namen**. Ein
   Klick in der Sidebar lädt die Chips zurück, du siehst die Bilder und
   kannst die Chips weiter ändern. Das ☆ speichert: eine neue Suche oder,
   wenn du von einer gespeicherten Suche kommst, wahlweise **„»Name«
   überschreiben"** oder **„Als neue Suche speichern"**.
3. **Ein Ranking** ist eine gespeicherte Suche, **über die Duelle
   laufen** (Ranking-Modul, Standard aus). 🏆 legt es aus den aktuellen
   Chips an; ✎ im Ranking lädt seine Population als Chips in die Galerie
   (**Bearbeiten-Modus**), „Ranking speichern" führt zurück ins Ranking.
   Ein Ranking hat zwei Ansichten: die **Bestenliste** und den
   **Duell-Modus**.

Begriffe: Ein Kriterium in der Leiste heißt **Chip**; eine benannte
Suche heißt **gespeicherte Suche**; eine benannte Suche mit Duellen
heißt **Ranking** (nicht mehr „Arena"), ihre beiden Ansichten
**Bestenliste** und **Duell**. Die Abschnitte unten folgen dieser
Reihenfolge; die Rankings im Einzelnen beschreibt
[rankings.md](rankings.md).

## Suchen: EIN Suchzustand aus Chips

Die Suche ist **ein Zustand aus Chips** über der Galerie - Sidebar-Klicks,
Textbegriffe und getippte Ausdrücke landen alle im selben Zustand und
kombinieren sich, statt einander zu ersetzen:

```
[ Modell: flux | krea ✕ ] [ Text: wüste ✕ ] [ ★ ≥ 4 ✕ ] · 1.234   ☆ speichern · 🏆 Ranking · ✕ · ⚡
```

**☆ speichern**, **✕ Filter zurücksetzen** und **⚡ Sammel-Aktion** sitzen
als EINE Knopf-Gruppe rechts; reicht die Breite nicht, rutscht die Gruppe
geschlossen unter die Chips. Unterhalb von FullHD-Breite zeigen Zurücksetzen
und Sammel-Aktion nur noch ihr Icon (Hover verrät die Funktion) - kleine
Monitore bleiben aufgeräumt. Im Bearbeiten-Modus eines Rankings (siehe
[Rankings](rankings.md)) zeigen alle vier Knöpfe nur ihr Icon.

- **Tippen filtert live:** Ab dem dritten Zeichen filtert die Galerie nach
  kurzer Tipp-Pause (die Galerie IST die Trefferliste - Thumbnails statt
  Textausschnitte). **Enter** macht aus den Begriffen feste **Text-Chips**
  (`"…"` hält Wortfolgen zusammen; ein Anführungszeichen IM Wert schreibt
  man doppelt: `prompt: "sag ""hi"""`, ebenso den Apostroph in `'…'`:
  `prompt: 'don''t stop'`); mehrere Wörter sind UND-verknüpft. Auch der
  Chip-Editor und die Tipphilfe verstehen `"…"` (exakt) und `'…'`
  (enthält).
  Begriffe zählen als **Wortanfänge** (`wüs` findet „Wüste"; dank
  Volltextindex auch bei 250k in Millisekunden).
- **Sidebar-Klicks** werden Chips: ein Klick **ersetzt** die Auswahl der
  Gruppe, Cmd/Strg-Klick erweitert zum **ODER**, ein Klick auf einen
  aktiven Wert entfernt ihn (Lightroom-Regel, seit September 2026).
  Die Sidebar-Zähler rechnen dabei im aktuellen Kontext mit (leere Werte
  gedimmt); „mit/ohne Eingangsbild" ersetzen einander. Alle Zähler eines
  Suchzustands kommen aus **einem** Lauf, und der Server merkt sich das
  Ergebnis, bis sich am Bestand etwas ändert - der zweite Klick auf
  dieselbe gespeicherte Suche kostet nichts mehr.
- **Getippte Filterausdrücke** (siehe oben, Enter) werden in Chips zerlegt -
  getippt und geklickt ist garantiert dasselbe.
- **Klick auf einen Chip** öffnet ihn zum Bearbeiten: Werte entfernen oder
  ergänzen (ODER), „ausschließen" macht aus dem Chip eine Negation
  (weder-noch); ✕ am Chip entfernt das Kriterium. Alles auf einmal leert
  **„✕ Filter zurücksetzen"** rechts in der Kopfzeile - oder **Esc**
  (wenn gerade kein Overlay offen ist) bzw. „Alle Medien" in der Sidebar.
- **☆ speichern** öffnet den Speicherdialog (Vorschau + Trefferzahl + Name)
  und legt den ganzen Zustand als gespeicherte Suche ab; kam der Zustand
  aus einer gespeicherten Suche, bietet er „»Name« überschreiben" und „Als
  neue Suche speichern" an.
- **🏆 Ranking** (nur bei eingeschaltetem Ranking-Modul, auch ohne Chips)
  legt aus den Chips ein **neues Ranking** an (Paarvergleich mit
  Bestenliste), siehe [Rankings](rankings.md).
- **„+ Kriterium"** (neben den Chips) öffnet den **Baukasten**: alle
  Kategorien in der Reihenfolge der Sidebar (Bewertung, Medienart,
  Generator, Modell, LoRA, Jahr, Dateityp, Format, Auflösung,
  Eingangsbild, Fundort), danach, was es nur hier gibt (Tags, Text,
  **Dauer** - Eingabe wie `dauer:`, z. B. `>120` oder `1:00-3:00`, gilt für
  Audio und Video -, Eckwerte, Rohdaten-Suche, Dateiname, Sortierung) mit
  Wertelisten und **Zählern im aktuellen Kontext**. Mehrere Werte anklicken
  = ODER-Chip; „ausschließen" macht Negativ-Kriterien; die Rohdaten-Suche
  ist das Opt-in für Treffer in Workflow-JSONs (`raw:`).
- **Tipphilfe:** Beim Tippen schlägt das Suchfeld passende Facetten vor
  („Modell: flux.1-dev (1.234)", „Tag: favorit (56)", …). ↑/↓ wählt,
  **Enter übernimmt den Vorschlag als Chip** - Enter ohne Auswahl macht wie
  gehabt Text-Chips. Grammatik lernen ist damit optional. Trifft das Wort
  eine **Medienart genau** („audio", „Bild", „video", englisch „image"),
  ist diese Zeile schon ausgewählt: Enter ergibt `typ: video`. Ganz unten
  steht dann die Zeile **„Volltext: video"** - ein Pfeil dorthin, und Enter
  sucht wie gewohnt im Volltext. Liegt die Medienart in der anderen Ansicht
  („audio" in der Galerie), steht dort statt eines Chips **„Ansicht: →
  Audioansicht"**: Enter wechselt die Ansicht, die Suche bleibt.

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

## Filterausdrücke (für Fortgeschrittene)

Die Suchleiste versteht auch Filterausdrücke - sie
zeigen sofort das gefilterte Grid. Prädikate sind UND-verknüpft, `-` negiert;
**mehrere Werte in einem Prädikat** trennt ` | ` (Pipe mit Leerzeichen) als
ODER:

```
model: flux -tag: wip rating>=4
model: flux | krea rating>=4
container: png -has: workflow
prompt: "red hair" rating=0
prompt: 'new york' -prompt: 'at night'
year: 2022 | unbekannt sort: created
```

`model: flux | krea` heißt Flux ODER Krea; `-tag: wip | alt` heißt weder
`wip` noch `alt`. ODER gibt es nur bei Werte-Prädikaten - Vergleiche
(`rating>=`, `width>=` …) bilden Bereiche über `>=`/`<=`-Paare. Die
Direktive **`sort: <schlüssel>`** (einmal pro Ausdruck) legt die Sortierung
fest und wird mit der Suche gespeichert: `added` (hinzugefügt), `created`
(Erstelldatum), `size`, `name`, `container`, `rating`, `duration` (Dauer,
Audio und Video). Die Richtung dreht
ein Suffix: `sort: created-auf` (älteste zuerst), `sort: name-ab` (Z–A) -
englisch als `-asc`/`-desc` (`sort: created-asc`).
Ohne Suffix gilt die sinnvolle Standardrichtung (Neuestes/Größtes/Bestes
zuerst, Namen A–Z); Unbewertete und Undatierte bleiben in beiden
Richtungen am Ende.

`feld: wert` sucht als Teilstring, `feld: "wert"` exakt, `feld: 'zwei
wörter'` als **mehrteiliger Teilstring** (»enthält«: `prompt: 'new york'`
findet auch „a view of New York at night", `prompt: "new york"` nur den
Prompt, der genau so lautet); `rating=0` heißt unbewertet; erlaubte Felder sind die der [Schicht 2](interpretation.md) plus
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
außerhalb katalogisiert; braucht eine konfigurierte Library),
`text:` (freier Begriff - kuratierte Suche über interpretierte Felder,
Dateinamen und manuelle Schicht; genau die Semantik der Live-Suche:
`text: ball text: wüste`), `raw:` (wie `text:`, aber **zusätzlich in den
Roh-Metadaten** - findet z. B. Node-Namen im Workflow-JSON: `raw: ipadapter`),
`datei:` (englisch `file:`; gezielt der **Dateiname** der Fundorte, ohne
Verzeichnis - Teilstring, mit `"…"` exakt; praktisch für metadatenlose
Bestände wie Midjourney-Exporte und natürlich auch in Ranking-Ausdrücken
nutzbar), `typ:` (englisch `type:`; Medienart `bild`/`video`/`audio`),
`dauer:` (englisch `duration:`; Sekunden oder m:ss mit Vergleich oder als
Bereich: `dauer: >120`, `dauer: 60-180`, siehe [Audio-Modul](audio.md))
und die Medien-Eckwerte `width`/`height`/`fps` mit Vergleich (z. B.
`width>=1920 fps>=24`). Gespeicherte
Suchen sind dynamisch: ausgewertet wird bei jedem Öffnen.

## Gespeicherte Suchen

Jede Suche - egal ob aus Sidebar-Klicks, Textbegriffen oder getippten
Ausdrücken zusammengesetzt - lässt sich mit dem **☆ neben den Chips**
speichern. Das ☆ öffnet den **Speicherdialog**: er zeigt die Chips als
Vorschau, die aktuelle Trefferzahl, einen Hinweis, falls eine Sortierung
mitgespeichert wird, und fragt nach dem Namen. Die Suche erscheint links unter „Gespeicherte Suchen" mit
Live-Zähler; ein Klick lädt sie **als Chips zurück** (alles bleibt
bearbeitbar) und zeigt ihre Bilder, ohne weiteren Modus. Die Liste steht
sofort, die Zähler kommen kurz danach („…" solange sie rechnen): nach dem
Serverstart oder einem Import werden sie einmal frisch gezählt, danach
kommen sie aus dem Speicher, bis sich am Bestand etwas ändert.

Solange die Chips genau der geladenen Suche entsprechen, ist ihre Zeile in
der Sidebar hervorgehoben. Ändert man einen Chip, geht die Markierung aus:
ab da ist es eine freie Suche, nichts wird unbemerkt überschrieben. Drückt
man dann ☆, sagt der Dialog **„Aus der gespeicherten Suche »Name«"**, der
Name ist vorbelegt, und es gibt zwei klar benannte Wege:

- **»Name« überschreiben** sichert die aktuellen Chips als neue Fassung
  dieser Suche; ein geänderter Name benennt sie dabei um.
- **Als neue Suche speichern** legt eine zweite Suche an und lässt die
  alte, wie sie war.

Der Ursprung endet mit „Alle Medien", Esc, dem Leeren der Chips oder dem
Laden einer anderen Suche. Gelöscht wird über das ✕ an der Sidebar-Zeile
(zweiter Klick bestätigt). Eine mitgegebene Sortierung (`sort:` bzw. der
Sortier-Knopf) wird mitgespeichert und beim Laden wiederhergestellt.

## Rankings: eine gespeicherte Suche mit Duellen

Bei eingeschaltetem Ranking-Modul (Admin → Konfiguration → Module) steht
in der Chip-Leiste **🏆 Ranking**: Es legt aus den aktuellen Chips ein
neues Ranking an (ohne Chips: die ganze Bibliothek) und öffnet es. In der
Sidebar erscheinen Rankings in der Gruppe **Rankings** mit ihrer
Population als Zähler; Klick öffnet die Bestenliste. ✎ im Ranking lädt
die Population in die Galerie, die Kopfzeile schaltet in den
Bearbeiten-Modus, „Ranking speichern" führt zurück. Alles Weitere
(Bestenliste, Duell-Modus, „Beide raus", Elo-Scores):
[rankings.md](rankings.md).

## Admin

Der Knopf oben rechts führt direkt in den **Admin** (ein echter Link nach
`/admin`: Lesezeichen, Mittelklick und Rechtsklick → neuer Tab). Das
frühere Schnellmenü mit Wartungsaktionen gibt es nicht mehr; Re-Scan, Neu
interpretieren und Thumbnail-Cache leeren stehen unter Admin → Wartung,
Dark/Light sitzt als Mond/Sonne-Knopf neben dem Sprachumschalter.

Der **Admin** ist seit ADR 0074 eine **eigene Seite** unter `/admin` mit
Seitennavigation links (Übersicht, Konfiguration, Quellen & Import,
Wartung, Probleme, Rankings, Logs) und dem Aktivitäts-Widget unten
in der Navigation - auf jeder Seite sichtbar, was gerade läuft oder wartet.
Jede Seite hat eine Adresse (`/admin/logs` …), Browser-Zurück und
-Vorwärts funktionieren; „Zurück zur Bibliothek" ist ein normaler
Seitenwechsel (die Galerie kommt aus dem Verlaufscache des Browsers oder
startet frisch). Galerie und Admin dürfen in zwei Tabs nebeneinander
laufen; die Galerie holt sich Kennzahlen, Übersichtsmodus-Badge und
Instanzname frisch, sobald ihr Tab wieder sichtbar wird.

Details: [admin.md](admin.md). Nach abgeschlossenen Aufgaben aktualisieren
sich Galerie und Zähler von selbst - schonend: Die Kacheln bleiben stehen,
neue Bilder (z. B. aus einem Watchordner neben ComfyUI) rücken oben ein
und schieben den Rest, Scrollposition und Auswahl bleiben am Bild. Nur
Kacheln, deren Inhalt sich geändert hat, werden neu gefüllt.

## Tastatur

| Taste | Wirkung |
| --- | --- |
| `Space` | Lupe öffnen/schließen |
| `Enter` / Doppelklick | Einzelbildansicht öffnen/schließen |
| `C` | A/B-Vergleich zweier markierter Bilder öffnen |
| `+` / `-` | Zoomen (Einzelbildansicht, Vergleich) |
| `1`–`5` / `0` | Bewerten / Bewertung löschen (Toggle) |
| `←` / `→` | Blättern - in Übersicht und Lupe; Wischkante im Vergleich |
| `↑` / `↓` | Eine Zeile hoch/runter (Übersicht) |
| `Entf` | Auswahl ablehnen (Item raus + Sperre, Datei bleibt) |
| `Pos1` / `Ende` | Erstes/letztes Medium (Lupe); Wischkante ganz links/rechts (Vergleich) |
| `Tab` / `Space` | Vergleich: A und B tauschen / Wisch → nur A → nur B |
| `Esc` | Obersten Dialog schließen, sonst offenes Overlay (Lupe, Einzelbild) - sonst: **Filter zurücksetzen** |

### Dialoge und hängende Anfragen

Dialoge (Neues Ranking, Speichern, Sammel-Aktion, Ablehnen - im Admin nur noch
Ordner-Auswahl und Bestätigung) dürfen übereinander liegen: die
Ordner-Auswahl öffnet sich über der Seite bzw. einer Bestätigung, ein
Abbruch lässt die bisherige Eingabe stehen. `Esc` schließt immer nur den obersten
Dialog. Ein Wechsel der Ansicht (Lupe, Einzelbild, Vergleich, Ranking auf
oder zu) schließt alle offenen Dialoge der Galerie; der Admin hat als
eigene Seite einen eigenen Dialog-Stapel.

Lesende Anfragen an den Server (Galerie-Seiten, Details, Zähler) brechen
nach 60 Sekunden ab, Thumbnails nach 20 Sekunden, und melden das als
normalen Fehler; Galerie-Seiten und Thumbnails versuchen es danach von
selbst erneut. Schreibende Aktionen (Import, Wartung, Rausverschieben)
haben kein Zeitlimit. Ein Video, das der Browser nicht öffnen kann, zeigt
in Lupe, Einzelbild und Panel den Hinweis „Keine Vorschau verfügbar" statt
einer schwarzen Fläche. Kennt fml den Codec (Schicht 2, Feld `video_codec`),
fragt der Player den Browser schon VOR dem Laden: Bei ProRes, 10-bit-H.264
oder HEVC in Firefox erscheint der Poster-Frame mit „Dieser Browser kann
ProRes (HQ, 10-bit) nicht abspielen …" — kein Stream, kein schwarzer Player
mit Ton. Der Codec steht auch in der Kopfzeile von Panel, Lupe und
Einzelbild; `codec: prores` im Suchfeld findet alle Betroffenen
([interpretation.md](interpretation.md#video-codec-und-abspielbarkeit)).

## Wichtig / Grenzen (Stand jetzt)

- **„Nur katalogisieren" kopiert nichts.** Dieser Modus nimmt Dateien dort
  auf, wo sie liegen. Der Import (Kopieren in die datumsbasierte Media
  Library, mit Dublettencheck und Watchordnern) ist der Weg daneben -
  siehe [import.md](import.md).
- **Video-Metadaten brauchen ffprobe** (Teil von ffmpeg, siehe
  [extraction.md](extraction.md)). Ohne ffprobe werden Videos trotzdem
  katalogisiert; ein erneuter Scan nach der Installation holt die Metadaten nach.
- **Welche Videos der Browser abspielt:** fml liefert Videos unverändert
  aus (kein Umkodieren, „Original heilig"); ob ein Codec läuft, entscheidet
  deshalb der **Browser**, nicht fml. Der Player fragt ihn vor dem Laden und
  zeigt bei Nein den Poster-Frame mit Hinweis. Stand 2026 (Browser ändern
  sich, im Zweifel gilt die Antwort des Browsers):

  | Codec / Container | Chrome, Edge | Firefox | Safari (macOS) |
  |---|---|---|---|
  | H.264 8-bit 4:2:0 (MP4, MOV) | ja | ja | ja |
  | H.264 10-bit, 4:2:2, 4:4:4 (High 10 & Co.) | nein | nein | nein |
  | HEVC / H.265 | mit Hardware-Decoder | je nach System (Windows: „HEVC-Videoerweiterungen", macOS: neuere Versionen, Linux: nein) | ja |
  | VP8 / VP9 (WebM) | ja | ja | ja (macOS 11+) |
  | AV1 | ja | ja | nur neuere Apple-Chips |
  | **ProRes (MOV, Topaz-Export)** | nein | nein | **ja** |
  | DNxHD, Motion JPEG, andere Zwischencodecs | nein | nein | nein |
  | MKV-Container | teilweise | nein | nein |

  Mac-Nutzer mit Safari sind vom ProRes-Problem also nicht betroffen; in
  Chrome und Firefox hilft nur ein anderer Player (📂 im Dateimanager
  anzeigen) oder ein H.264-Export. Welche Codecs im eigenen Bestand
  stecken, zeigt `codec: prores` im Suchfeld bzw. das
  [Diagnose-Kommando](scanning.md#diagnose-video-codecs-im-bestand); beim
  Aufnehmen erscheint das Problem unter Admin → Probleme (Art `playback`).
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
