# Audio-Modul

fml kann Musik und andere Audiodateien katalogisieren: mit allen
eingebetteten Metadaten, der Dauer und einem eigenen Player. Das
Modul ist **ab Werk aus**; wer nur Bilder und Videos verwaltet, merkt
davon nichts.

Was das Modul kann, in der Reihenfolge dieser Seite: eine eigene
**Audioansicht** als Liste mit dreifarbiger Wellenform, ein **Player** mit
Lautheitsangleich, „Alle abspielen" und Abspielleiste, **Zeitkommentare**
an Stellen im Song, das **Vergleichen** von zwei bis sechs Fassungen und
**Cover**, mit denen fertige Songs in die Galerie kommen. Dazu liest fml
die Metadaten von Suno, ComfyUI-Musik und eigenen Aufnahmen, misst
Lautheit und Wellenform und sucht auch im Songtext.

**Braucht ffmpeg** (wie Videos, Installation siehe README): ffprobe liefert
die Dauer, ffmpeg misst Lautheit und Wellenform, legt abspielbare Kopien
an und liest den Songtext mit Zeiten aus der Untertitel-Spur. Ohne ffmpeg
werden MP3, FLAC, Ogg, WAV, AIFF und CAF trotzdem mit allen Tags
aufgenommen. **M4A und Matroska nur mit Ton** liest fml ganz über ffprobe:
Ohne ffprobe fehlen dort die Tags, und die Datei gilt als Video, bis ein
Re-Scan mit installiertem ffmpeg sie nachholt.

## Einschalten

**Admin → Konfiguration → Module → Audio-Modul** („Audio katalogisieren")
oder in der `config.toml`:

```toml
[audio]
enabled = true
```

Die Einstellung wirkt sofort für den nächsten Scan und Import.
Watchordner prüfen beim Einschalten Audiodateien, die sie vorher als
„unbekanntes Format" übersprungen haben, gleich neu. Ordner, die nur
**einmal** katalogisiert wurden, nimmst du noch einmal auf (**Admin →
Quellen & Import**, „nur katalogisieren", „einmal jetzt"): Bekanntes wird
übersprungen, die Musik kommt dazu. „Re-Scan aller Fundorte" reicht dafür
nicht, er prüft nur Dateien, die schon im Katalog stehen.

**Aus** heißt: Audiodateien gelten als unbekanntes Format und werden nicht
aufgenommen, genau wie ohne das Modul. Das gilt auch für M4A-Dateien und
Matroska-Dateien nur mit Tonspur, die früher fälschlich als Video
erschienen. Schon aufgenommene Audio-Items bleiben im Katalog, sind aber
unsichtbar: die Galerie zeigt dann kein Audio, auch keine Songs mit
Cover, und den Umschalter zur Audioansicht gibt es nur mit Modul. Wieder
einschalten, und alles ist da.

## Audioansicht

Mit Modul steht oben links neben dem Logo der Umschalter **▦ Galerie |
♪ Audio**. Beide Ansichten teilen sich die Suche: die Chips bleiben beim
Wechsel stehen, nur der **Grundbereich** wechselt. `tag: regenzeit` zeigt
in der Galerie die Bilder, in der Audioansicht die Songs dazu. Einzige
Ausnahme ist die **Medienart**: sie gilt immer innerhalb der Ansicht.
Werte, die es in der neuen Ansicht nicht gibt, fallen beim Wechsel weg
(„Bild" verschwindet beim Wechsel zu Audio). „Audio" bleibt beim Wechsel
in die Galerie stehen und zeigt dort die fertigen Songs mit Cover.

- **Galerie** = Bilder, Videos und **fertige Songs**: Songs mit Cover
  (siehe [Cover](#cover-fertige-songs-in-der-galerie)).
- **Audio** = alle Audio-Items, als **Liste über die volle Breite**.

Ein Chip schaltet die Ansicht nie um. Steht in der Galerie `typ: audio`,
zeigt sie nur die fertigen Songs (mit Cover); gibt es keine, bleibt sie
leer und zeigt „Audio liegt in der Audioansicht" mit einem Knopf zum
Wechseln (umgekehrt genauso für Bilder in der Audioansicht).
Tippt man „audio" ins Suchfeld der Galerie, bietet die Tipphilfe **→
Audioansicht** an: Enter wechselt die Ansicht, die Suche bleibt, wie sie
war. Die Wahl der Ansicht merkt sich der Browser.

**Eine Zeile** zeigt ▶, den **Dateinamen** (in Suno landen Kommentare im
Songtitel und damit im Dateinamen), **Interpret · Album** aus den Tags,
bei KI-Musik ohne diese Tags den Erzeuger (Modell, sonst Werkzeug),
die Dauer, die Lautheit (LUFS), die Bewertung und unter 💬 die Zahl der
Zeitkommentare. Hat ein Song ein Cover, steht es klein vor dem Namen.
Beginnt ein Name wie der darüber, ist der gemeinsame Anfang abgedunkelt: bei „Regenzeit v3 refrain lauter" und
„Regenzeit v3 refrain leiser" springt so das Unterscheidende ins Auge.
Der volle Name steht im Tooltip. Ist die Mitte schmal (kleines Fenster,
Sidebar und Detailpanel offen), weichen Erzeuger und Lautheit, damit der
Name Platz hat.

Unter jeder Zeile liegt die **Wellenform in drei Farben**, erklärt in der
Legende über der Liste (der Tooltip sagt mehr):

| Farbe | Band | Was man dort hört |
|---|---|---|
| Blau | Bass, unter 200 Hz | Kick, Bassline |
| Grün | Mitten, 200 Hz bis 2 kHz | Stimme, Gitarre, Klavier, Flächen |
| Hell | Höhen, über 2 kHz | Becken, Hi-Hats, S-Laute |

Jedes Band ist in seiner eigenen Stärke gezeichnet, die Höhe ist der
Pegel. Wo eine Farbe hervortritt, dominiert dieser Bereich: viel Blau
heißt, Bass und Kick drücken (typisch Refrain oder Drop), breites Grün
heißt Gesang und Harmonie vorn (Strophe, Bridge), viel Hell eine helle,
luftige oder zischelnde Stelle. Wirkt eine Fassung dumpf oder scharf,
sieht man es oft schon am Anteil von Hell.

Alle Zeilen teilen sich **eine Zeitachse**: Die volle Breite ist der
längste Song der Liste, ein kürzerer Song endet entsprechend
früher. Das Lineal über der Liste zeigt die Minuten. So stehen Refrains
verschiedener Fassungen sichtbar untereinander. Der schon gespielte Teil
ist hell, der rote Strich ist der **Abspielkopf** der Zeile. Ein Klick in
die Wellenform spielt die Zeile ab dieser Stelle.

**Bedienen:**

| Taste / Maus | Wirkung |
|---|---|
| ↑ / ↓ | Zeile wechseln |
| Alt+↑ / Alt+↓ | Zeile eine Stelle verschieben (nur Sortierung „Manuell", siehe [Eigene Reihenfolge](#eigene-reihenfolge-einer-gespeicherten-suche)) |
| Leertaste, ▶, Doppelklick | Abspielen / Pause (die Leertaste auch direkt nach einem Klick auf einen Knopf wie ⏮ oder ≈ Lautheit) |
| ← / → | Abspielkopf der Zeile 5 Sekunden zurück / vor (mit Shift 1 Sekunde) |
| Klick in die Wellenform | ab dieser Stelle abspielen |
| 1 bis 5, 0 | Sterne setzen / entfernen (auch Klick auf die Punkte der Zeile) |
| K | Zeitkommentar an der Stelle des Abspielkopfs der Zeile |
| Klick auf einen Kommentar-Pin ▲ | ab dem Kommentar abspielen |
| Entf | Ablehnen |
| Shift-/⌘- bzw. Strg-Klick | mehrere Zeilen auswählen, wie in der Galerie |
| C | die markierten Songs vergleichen (2 bis 6, siehe „Vergleichen") |
| Esc | im Vergleich: zurück zur vollen Liste |

Es spielt immer **genau eine** Zeile, aber **jede Zeile hat ihren eigenen
Abspielkopf**. Wer eine andere startet, pausiert die erste; sie merkt
sich ihre Stelle, beim nächsten ▶ geht es dort weiter. So lassen sich vier
Fassungen Refrain gegen Refrain anhören: jede einmal an den Refrain
setzen, dann reihum ▶. Die Pfeiltasten verschieben den Abspielkopf der
ausgewählten Zeile auch, wenn sie gerade nicht spielt.

**Welle oder Angaben.** Der Regler **☰ S M L** oben in der Kopfzeile
bestimmt die Darstellung der Liste. Es leuchtet immer genau ein Knopf:

- **S, M, L** zeigen die Zeile wie oben beschrieben, mit Wellenform in
  kleiner, mittlerer oder großer Höhe („Welle"). Das ist zum Hören und
  zum Vergleichen von Fassungen da.
- **☰** („Angaben") zeigt flache Zeilen ohne Wellenform, dafür mit eigenen
  Spalten: Titel, Interpret, Album, Nr., Jahr, Genre, Dauer, Bewertung
  und die Zahl der Zeitkommentare. Es passen zwei- bis dreimal so viele
  Songs auf den Bildschirm. Sie ist zum Durchsehen und Verwalten einer
  Sammlung da.

In „Angaben" steht in der ersten Spalte der **Titel aus der Datei**;
fehlt er, der Dateiname. Der Dateiname steht immer im Tooltip. Fehlt der
Interpret, stehen in seiner Spalte abgesetzt Modell oder Werkzeug, damit
KI-Songs nicht leer aussehen. Die Lautheit und das Abdunkeln gleicher
Namensanfänge gibt es nur in „Welle". Ein Klick auf S, M oder L holt die
Wellenform zurück. In der Galerie gibt es ☰ nicht, dort regelt S/M/L wie
bisher die Kachelgröße und behält seine Wahl.

Alles andere bleibt gleich: ▶ in der Zeile, Auswahl, Bewerten, Ablehnen,
„Alle abspielen" und die Tasten. Zum Springen im Song dient in „Angaben"
die Wellenform der Abspielleiste, dort stehen auch die Zeitkommentare.
**C** vergleicht auch aus „Angaben" heraus: Der Vergleich zeigt immer
Wellenformen, nach Esc ist die Liste wieder flach. Wird die Mitte eng,
weichen zuerst Genre, Jahr und Nr., dann das Album. Die Wahl merkt sich
der Browser.

**▶ Alle abspielen** (oben rechts in der Audioansicht) spielt die ganze
Liste in der aktuellen Sortierung, jeden Song von vorn, wie eine CD. Die
Reihenfolge wird beim Start **eingefroren**: Wer danach weiter sucht oder
umsortiert, ändert die laufende „CD" nicht. Startet man zwischendurch
einen Song, der nicht dazugehört, endet „Alle abspielen"; einer aus der
Reihe setzt sie dort fort.

Die **Sidebar** zählt je Ansicht: „Alle Medien", gespeicherte Suchen,
Modelle, Jahre und alle anderen Gruppen zählen in der Audioansicht nur
Audio, in der Galerie nur Bilder und Videos. Gruppen ohne Sinn für die
Ansicht verschwinden (LoRA, Format, Auflösung, Eingangsbild, Rankings in
der Audioansicht; die Medienart hätte dort nur eine Zeile). Songs gehören
nie in ein [Ranking](rankings.md), auch nicht mit Cover: zum Vergleichen
und Bewerten gibt es hier eigene Werkzeuge. Neu in der
Audioansicht ist die Gruppe **Songtext**: „mit Songtext" (`has: lyrics`) und
„ohne Songtext" (`-has: lyrics`). Sie sagt nur, ob ein Songtext in der Datei
hinterlegt ist, nicht, ob gesungen wird: Viele Songs mit Gesang tragen
keinen Songtext. Auch das „+ Kriterium"-Popover zeigt nur
die passenden Kategorien. Eine **Sammel-Aktion** aufs Suchergebnis trifft
genau das, was die Ansicht zeigt.

Das Detailpanel rechts zeigt zum ausgewählten Song Metadaten, Songtext
und Rohdaten wie gewohnt.

## Welche Formate

| Format | Erkennung | Was gelesen wird |
|---|---|---|
| MP3 | ID3v2-Tag oder MPEG-Frame am Anfang | ID3v2 (2.2 bis 2.4), APEv2 und ID3v1 am Ende |
| FLAC | `fLaC`, auch mit ID3v2 davor | Vorbis-Kommentar, Bilder, APPLICATION-Blöcke, das vorangestellte ID3v2 |
| Ogg (Opus, Vorbis, FLAC) | `OggS` | Vorbis-Kommentar bzw. OpusTags, auch über mehrere Seiten |
| WAV (auch RF64/BW64) | `RIFF`/`RF64`/`BW64` + `WAVE` | `LIST/INFO`, `bext`, `iXML`, `_PMX`, `id3 `, `C2PA`, `cue` u. a., auch hinter den Audiodaten |
| AIFF/AIFC | `FORM` + `AIFF`/`AIFC` | `NAME`, `AUTH`, `ANNO`, `COMT`, `APPL`, `ID3 ` u. a. |
| CAF (z. B. Logic-Bounce) | `caff` | `info`-Chunk, weitere Chunks roh |
| M4A, MKA/WEBM nur mit Ton | wie Video, aber ohne Videospur | Tags über ffprobe |

Die Medienart kommt aus den **tatsächlichen Spuren**, nicht aus Endung
oder Container: ein MP4 mit Bild ist Video, ein MP4 nur mit Ton ist Audio.
Ein eingebettetes Cover zählt nicht als Bildspur.

## Was gespeichert wird

Jeder Tag-Frame und jeder Chunk landet **unverändert** als eigener
Rohmetadaten-Eintrag (Schicht 1), in der Reihenfolge der Datei, auch
doppelte Schlüssel. Das Detailpanel zeigt sie unter „Roh-Metadaten" mit ihrer
Herkunft, z. B.:

| Quelle · Schlüssel | Bedeutung |
|---|---|
| `id3v2:TXXX · prompt` | benutzerdefinierter Text, hier ein ComfyUI-Prompt |
| `id3v2:COMM · eng:` | Kommentar (Sprache `eng`, leere Beschreibung) |
| `id3v2:USLT · eng:` | Songtext |
| `id3v2:TIT2` | Titel |
| `id3v2:GEOB · application/c2pa` | eingebettetes Objekt, hier ein C2PA-Manifest (byte-treu) |
| `flac:comment · prompt` | Vorbis-Kommentar (Schreibweise des Schlüssels bleibt) |
| `ogg:comment · TITLE` | Kommentar in Ogg/Opus |
| `riff:INFO · ICMT` | WAV-Kommentar |
| `aiff:NAME`, `caf:info · title` | Titel in AIFF bzw. CAF |

**Bilder** (Cover in ID3, FLAC, Ogg, APEv2) werden nicht als Bytes
gespeichert, sondern nur beschrieben: MIME-Typ, Bildtyp, Größe und
SHA-256. Die Bilder bleiben in der Datei.

Dazu kommen die **technischen Fakten** aus ffprobe: Dauer, Codec,
Samplerate, Kanäle, Bittiefe und Bitrate (Quelle z. B. `mp3:format`,
`mp3:stream0`). Fehlt ffprobe, werden die Tags trotzdem gelesen; nur die
Dauer fehlt dann (Ausnahme M4A und Matroska, siehe oben).

## Was fml aus Musik liest

Aus den Rohdaten macht fml durchsuchbare Felder (Schicht 2). Das läuft beim
Scan mit und für schon Aufgenommenes über **Admin → Wartung → Neu
interpretieren**, ohne Neuimport.

**Aus jeder Musikdatei:** Titel (`title`), Songtext (`lyrics`), Tempo
(`bpm`), Tonart (`key`) aus den üblichen Tags (ID3, Vorbis-Kommentar,
WAV-INFO, M4A), dazu die Technik der Tonspur: `audio_codec`,
`sample_rate`, `channels`, `bit_depth`. Der **Songtext ist in der
Volltextsuche**: eine Zeile daraus ins Suchfeld tippen findet alle
Fassungen eines Songs, die denselben Text tragen.

**Songtext mit Zeiten:** Songs aus Suno V6 tragen ihren Songtext Zeile für
Zeile mit Zeiten in einer Untertitel-Spur, samt Abschnitten wie `[Verse]`
oder `[Chorus]`. fml liest diese Spur (M4A, Matroska mit nur Ton), dazu
ID3 `SYLT` (in Millisekunden) und LRC-Text (`[01:23.45]Zeile`) im
Songtext-Tag; aus LRC im Tag wird der normale Songtext ohne Zeitstempel.
Zu sehen ist das an drei Stellen:

- **Mittig unter der Welle der Abspielleiste** steht klein die Zeile, die
  gerade läuft, davor der Abschnitt („Chorus · Sing it loud“). In Pausen ohne
  Gesang (Solo, Bridge) bleibt sie leer: Eine Zeile steht höchstens so
  lange da, wie man sie ungefähr singt, und verschwindet, sobald ein neuer
  Abschnitt beginnt. Bei sehr schnellem, mehrstimmigem Gesang ist schon
  die Spur selbst durcheinander; das zeigt fml dann so, wie es kommt.
- **Auf der Welle jeder Listenzeile** markieren schmale Beschriftungen die
  Abschnitte; liegen zwei dicht beieinander, wird die erste gekürzt (voller
  Name im Tooltip). Der Abschnitt, in dem der Abspielkopf steht, erscheint
  ganz und in Akzentfarbe. Wie viel davon zu sehen ist, hängt an der Größe:
  **L** zeigt Marken und Beschriftung, **M** nur die gestrichelten Marken,
  **S** keine Abschnitte. Den Namen des laufenden Abschnitts zeigt immer
  die Abspielleiste. Instrumentale Abschnitte (Solo, Lead-Gitarre,
  Intro) haben bei Suno keine eigene Zeit, sie tragen die des nächsten
  gesungenen Worts; fml schätzt ihren Anfang an das Ende der letzten
  gesungenen Zeile davor (nach **Neu interpretieren**).
- **Im Detailpanel** (GENERATION → Songtext) laufen die Zeilen beim
  Abspielen mit; ein Klick auf eine Zeile springt dorthin. Wer das nicht
  braucht, klappt den Abschnitt zu.

Songs, die schon vor fml 2026.10 im Katalog waren, holt fml einmal von
selbst nach (Aufgabe „Songtexte mit Zeiten nachholen“ beim ersten Start mit
eingeschaltetem Audio-Modul, nur Songs mit Untertitel-Spur; braucht
ffmpeg). Für `SYLT` und LRC reicht **Neu interpretieren**.

**ComfyUI-Musik** (YuE2, MiniMax Music 3, ACE-Step 1.0/1.5): Der
Stil-Text (bei YuE2 `style`, bei ACE-Step `tags`, bei MiniMax `caption`)
wird `prompt`, der Songtext `lyrics`, dazu Seed, Modell und bei ACE-Step
1.5 BPM und Tonart. Texte, die über einen eigenen Textknoten hereinkommen,
werden aufgelöst. Es reicht der eingebettete `prompt`; Läufe über die API
schreiben keinen `workflow`.

**Suno:** Suno schreibt `made with suno; created=…; id=…` in den Kommentar
(MP3, WAV, M4A) und die Song-Adresse `suno.com/song/…`. Daraus werden
`tool: suno` und die `song_id`. Die **Erstellzeit des Songs wird das
Mediendatum** (nicht die Download-Zeit). Neuere Downloads (seit etwa
August 2026) tragen Content Credentials mit dem internen Modellnamen; fml
übersetzt ihn in die Version, z. B. `chirp-auk` → `Suno v4.5`,
`chirp-crow` → `Suno v5`, `chirp-hawk` → `Suno v6`. Songtext und Titel
kommen aus den normalen Tags. Den **Style-Prompt schreibt Suno nicht in
die Datei**; er fehlt deshalb. Downloader wie rs-suno (`SUNO_STYLE`,
`SUNO_MODEL`, `SUNO_PARENT`) und SunoSync (`SUNO_UUID`) werden gelesen,
soweit ihre Tags eindeutig sind.

**Content Credentials** erkennt fml auch in Audio: im ID3-Tag (MP3,
FLAC), im WAV-Chunk `C2PA` und in der `uuid`-Box von M4A/MP4.

**Eigene Aufnahmen:** Logic-Pro-Bounces (WAV) bekommen `creator_tool:
Logic Pro` (bzw. den genauen Programmnamen aus dem Broadcast-Wave-Kopf),
Sprachmemos vom iPhone `creator_tool: Voice Memos`.

Suchbeispiele: `tool: suno`, `model: "Suno v5"`, `bpm: 120`,
`audio_codec: flac`, `has: lyrics`.

## Musiksammlung: Interpret, Album, Genre

Für eine gewöhnliche Musiksammlung (etwa gerippte CDs als MP3) liest fml
aus den Tags:

| Feld | Aus | Beispiel |
|---|---|---|
| Interpret (`artist`) | ID3 `TPE1`, Vorbis `ARTIST`, WAV `IART`, M4A | `Nena` |
| Album-Interpret (`album_artist`) | ID3 `TPE2`, Vorbis `ALBUMARTIST`, M4A | `Various Artists` |
| Album (`album`) | ID3 `TALB`, Vorbis `ALBUM`, WAV `IPRD`, M4A | `99 Luftballons` |
| Titel- und CD-Nummer (`track`, `disc`) | `TRCK`/`TPOS`, `TRACKNUMBER`/`DISCNUMBER` | `3` (aus `3/12`) |
| Jahr (`year`) | ID3 `TDRC`/`TYER`, Vorbis `DATE`, WAV `ICRD`, M4A | `1983` |
| Genre (`genre`) | ID3 `TCON`, Vorbis `GENRE`, WAV `IGNR`, M4A | `Pop` |

Alte ID3v1-Tags (am Dateiende, höchstens 30 Zeichen) zählen nur, wo ein
ID3v2-Tag fehlt; ihre Genre-Nummern (und die Schreibweise `(17)` in
ID3v2) werden zu Namen. Das Jahr wird zum Datum des Songs, siehe
[Datum eines Songs](#datum-eines-songs).

**Seitenleiste (nur Audioansicht):** drei neue Gruppen, alphabetisch.

- **Interpret**: der Album-Interpret, wo das Tag ihn nennt, sonst der
  Interpret des Titels. So landet ein Sampler geschlossen unter
  „Various Artists", statt in hundert Einzelnamen zu zerfallen.
- **Album**: ein Klick zeigt das Album; zusammen mit einem Interpreten
  lassen sich gleichnamige Alben („Greatest Hits") auseinanderhalten.
- **Genre**: ab Werk zugeklappt (Klick auf die Überschrift klappt auf).

Gruppen, für die es in keinem Song Tags gibt, erscheinen gar nicht. Die
Zähler filtern mit wie überall: Nach einem Klick auf einen Interpreten
stehen dessen Alben oben.

**Suche:**

- `interpret: "Nena"` (englisch `albumartist:`) — dieselbe Regel wie die
  Gruppe: Album-Interpret, sonst Interpret.
- `artist: nena` — nur der Interpret des einzelnen Titels, also auch
  Nenas Titel auf Samplern.
- `album: luftballons`, `genre: pop`.
- Interpret, Album und Genre stehen außerdem in der **Volltextsuche**.

**Sortierung „Album"** (`sort: album`, nur in der Audioansicht):
Interpret → Album → CD → Titelnummer, bei gleicher oder fehlender
Titelnummer der Dateiname (gerippte CDs heißen meist `01 Titel.mp3`). Ein
Album läuft so in seiner Reihenfolge, auch mit **▶ Alle abspielen**. Songs
ohne diese Tags stehen am Ende.

**Ein Album anklicken** (Gruppe Album oder ein `album:`-Chip) sortiert die
Liste automatisch nach Album, **solange in der Suchleiste kein
Sortier-Chip steht**. Ohne Chip gilt sonst die zuletzt im Sortier-Menü
gewählte Sortierung (siehe [Oberfläche](gui.md)); ein Album-Chip hat
Vorrang davor. Steht ein Sortier-Chip (im Menü gewählt oder aus einer
gespeicherten Suche), gewinnt er. Wer beim Album also etwas anderes will,
wählt es im Sortier-Menü, auch „Hinzugefügt"; es erscheint dann als Chip.
Die Galerie und Suchen ohne Album-Chip bleiben unverändert.

**Bestand nachziehen:** Für schon aufgenommene Musik einmal **Admin →
Wartung → Neu interpretieren**; die Tags liegen schon im Katalog, ein
Neuimport ist nicht nötig. Zwei Ausnahmen brauchen die Datei selbst:
Content Credentials in **M4A/MP4**, die vor fml 2026.09.2 aufgenommen
wurden (einmal „Re-Scan aller Fundorte", weil der Baustein erst seitdem
gesichert wird), und der Songtext mit Zeiten aus der Untertitel-Spur
(holt fml von selbst nach, siehe oben).

## Musik-Angaben von Hand

Neue Songs (etwa aus Suno) tragen weder Interpret noch Album, ältere
Rips manchmal falsche. Im Detailpanel stehen deshalb bei Songs unter
**KURATIERT** acht Felder: **Titel, Interpret, Album-Interpret, Album,
Nr., CD, Jahr, Genre**. Sie sind mit dem geltenden Wert vorbelegt und
stehen nur dort, nicht noch einmal bei den übrigen Metadaten.

- **Setzen:** Wert eintippen, dann Enter oder das Feld verlassen (Tab
  springt ins nächste Feld). Der Wert überdeckt den aus der Datei und
  trägt danach **✎ von Hand**.
- **Zurücknehmen:** das Feld leeren oder auf **✎ von Hand** klicken. Dann
  gilt wieder der Wert aus der Datei.
- **Mehrere Werte** bei Interpret und Genre mit `;` trennen
  (`Anna; Bert`).
- **Mehrere Songs auf einmal:** Zeilen auswählen (Shift- oder
  Strg/⌘-Klick), dann wirkt eine Eingabe auf alle. Felder, deren Werte in
  der Auswahl voneinander abweichen, zeigen „(verschieden)" und bleiben
  unberührt, solange man nichts eintippt. Am bequemsten geht das in der
  Darstellung „Angaben". Bei mehr als 200 Songs läuft die Änderung als
  Aufgabe im Hintergrund, die Liste frischt sich danach auf.

Die geänderten Zeilen der Liste zeigen den neuen Wert sofort. Die
**Reihenfolge und der Filter** der Liste bleiben dabei stehen, auch wenn
ein Song nach der Änderung woanders einsortiert wäre oder nicht mehr zur
Suche passte: So bleibt die Auswahl beim Nachpflegen, wo sie ist. Mit dem
nächsten Laden (neue Suche, andere Sortierung) stimmt die Liste wieder.

**Die Datei bleibt unverändert.** fml schreibt nichts in die Tags, die
Angaben liegen im Katalog. Überall sonst gilt der gesetzte Wert wie ein
Wert aus der Datei: in der Liste, in der Seitenleiste (Interpret, Album,
Genre), in der Suche (`artist:`, `album:`, `genre:`, `interpret:`,
Volltext) und in der Sortierung „Album". „Neu interpretieren" und ein
Re-Scan lassen die Angaben stehen. Wird ein Song abgelehnt, gehen seine
Angaben mit.

Ein Wert, den die Datei mitbringt, lässt sich überdecken, aber nicht
ersatzlos ausblenden: Ein geleertes Feld zeigt wieder den Wert aus der
Datei.

Erlaubt sind Nummern von 1 bis 9999, ein vierstelliges Jahr und Text bis
300 Zeichen. Das **Jahr von Hand** wird zum Datum des Songs, siehe
[Datum eines Songs](#datum-eines-songs).

### Angaben mit einem anderen fml austauschen

Was einmal nachgepflegt ist, wandert als Datei in ein anderes fml, auf
demselben Weg wie die Zeitkommentare (siehe
[Kommentare mit einem anderen fml austauschen](#kommentare-mit-einem-anderen-fml-austauschen)):

**Exportieren:** Songs auswählen oder eine Suche eingrenzen, die
**Sammel-Aktion** öffnen, in der Zeile „Austausch" das Häkchen
**Musik-Angaben** setzen (auf Wunsch zusätzlich **Zeitkommentare**) und
auf **Exportieren** klicken. In der Datei stehen **nur Angaben von
Hand**, nie Werte aus den Tags: Die stecken ohnehin in der Musikdatei.

**Importieren:** auf der anderen Seite **Admin → Wartung → Austausch
importieren**. Die Vorschau zählt je Song und Feld:

- **neu**: hier steht noch keine Angabe von Hand. Wird übernommen, auch
  wenn die Datei hier einen anderen Tag-Wert trägt (ihn zu überdecken ist
  der Zweck).
- **gleich**: hier steht schon derselbe Wert von Hand. Wird übersprungen.
- **abweichend**: hier steht ein **anderer** Wert von Hand. Der eigene
  Wert bleibt stehen; die Vorschau listet diese Fälle mit beiden Werten.
  Nur mit dem Häkchen **„Abweichende eigene Angaben überschreiben"**
  gewinnt die Datei.

Übernommene Angaben tragen im Panel **✎ von Hand**, der Tooltip nennt die
Herkunft. Derselbe Import zweimal ändert nichts. Die Songs werden wie bei
den Kommentaren über die Datei selbst gefunden, Suno-Songs notfalls über
die Suno-Song-ID (nur mit Häkchen).

## Eigene Reihenfolge einer gespeicherten Suche

Zum Probehören einer geplanten Playlist lässt sich die Reihenfolge der
Songs **von Hand** festlegen. Die Reihenfolge gehört zu einer
[gespeicherten Suche](gui.md), nicht zum Song: derselbe Song kann in zwei
Playlists an verschiedenen Stellen stehen.

### Zwei Dinge, die getrennt gespeichert werden

| Was | Wie wird es gespeichert? |
|---|---|
| **Die Reihenfolge selbst** (welcher Song an welcher Stelle) | **Automatisch, sofort** bei jedem Verschieben. Kein ☆ nötig. |
| **Dass die Suche beim Öffnen in dieser Reihenfolge startet** | Nur mit **☆ → »Name« überschreiben**. Das speichert den Sortier-Chip „Manuell" in der Suche. |

Wer nur umsortiert und nie ☆ drückt, verliert nichts: Die Reihenfolge ist
gespeichert, die Suche öffnet aber mit der normalen Sortierung. Dann einmal
„Manuell" im Sortier-Menü wählen, und die eigene Reihenfolge ist wieder da.

### Einmal einrichten

1. Songs taggen, z. B. `release candidate`.
2. Suche `tag: "release candidate"` eingeben und mit **☆ speichern** ablegen,
   z. B. als „CD 2026".
3. Die gespeicherte Suche links unter „Gespeicherte Suchen" öffnen.
4. Im Sortier-Menü **„Manuell"** wählen (siehe unten, wann es da ist).
5. Songs in die gewünschte Reihenfolge bringen (nächster Abschnitt).
6. **☆ → »CD 2026« überschreiben.** Der Dialog zeigt „Die Sortierung wird
   mitgespeichert: Manuell". Ab jetzt öffnet „CD 2026" immer in der
   eigenen Reihenfolge.

### Umsortieren

- Den **Dateinamen** einer Zeile auf eine andere Zeile ziehen: auf die obere
  Hälfte = davor, auf die untere = dahinter.
- Oder eine Zeile auswählen und mit **Alt+↑ / Alt+↓** eine Stelle
  verschieben.
- Solange das geht, steht über der Liste „Reihenfolge: Name ziehen oder
  Alt+↑/↓". Klappt ein Verschieben nicht, steht die Meldung an derselben
  Stelle.
- **▶ Alle abspielen** spielt die Liste genau in dieser Reihenfolge.

### Wann es „Manuell" gibt

„Manuell" steht nur im Sortier-Menü, wenn **alles** davon zutrifft:

- die Audioansicht ist offen (nicht die Galerie),
- eine gespeicherte Suche ist geöffnet,
- ihre Chips stehen noch genau so, wie sie gespeichert sind.

Wer danach etwas anderes sucht (tippt, in der Seitenleiste klickt, „Alle
Medien" wählt), hat die gespeicherte Suche verlassen. „Manuell" verschwindet
dann, und die Liste sortiert wieder wie vorher. Die Reihenfolge bleibt
gespeichert; ein Klick auf die gespeicherte Suche bringt sie zurück.

### Was mit der Reihenfolge passiert

- **Neu getaggte Songs** hängen sich hinten an, in der Reihenfolge, in der
  sie aufgenommen wurden.
- **Verliert ein Song den Tag**, fällt er aus der Liste; bekommt er ihn
  zurück, steht er wieder an seiner alten Stelle.
- **☆ → Als neue Suche speichern** legt eine neue Suche mit **eigener,
  leerer** Reihenfolge an; die alte Suche behält ihre.
- **Gespeicherte Suche löschen** löscht auch ihre Reihenfolge.
- Einen Export (etwa `.m3u`) gibt es bewusst nicht; die Reihenfolge dient
  dem Planen und Probehören.

## Datum eines Songs

Das Datum eines Songs (Sortierung „Erstellt", Seitenleiste „Nach Jahr",
`year:`) kommt aus dieser Reihenfolge:

1. **von Hand gesetzt** (Feld unter KURATIERT oder Zeile „Datum" der
   Sammel-Aktion, siehe [Oberfläche](gui.md)) — gewinnt immer;
2. ein **eingebettetes Datum**, z. B. Sunos Erstellzeit;
3. das **Jahr**: von Hand gesetzt (siehe
   [Musik-Angaben von Hand](#musik-angaben-von-hand)), sonst aus den Tags
   (ID3 `TDRC`/`TYER`, Vorbis `DATE`, M4A `©day`), meist das
   Erscheinungsjahr. Es gilt nur als Jahr: die Anzeige ist „1987", nicht
   „1987-01-01";
4. der **Dateistempel**.

Die [Datumsregel](import.md) gilt auch für das Tag-Jahr: Ein Jahr vor dem
eingestellten ältesten Datum (ab Werk 2015) gilt als unplausibel, dann
zählt der Dateistempel. Wer alte Musik einliest, stellt das Datum vorher
entsprechend zurück („Ältestes plausibles Datum" unter Admin →
Konfiguration → Media Library)
und lässt danach **Neu interpretieren** laufen. Beim Import mit Kopieren
landet ein Song mit Tag-Jahr im Ordner `1987/01/01` der Library.

Für ein **Jahr von Hand** gilt die Datumsregel nicht: Eine bewusste
Eingabe zählt auch vor dem ältesten plausiblen Datum. Es steht an der
Stelle des Tag-Jahrs, verliert also gegen ein eingebettetes Datum (Sunos
Erstellzeit). Wer dort ein anderes Datum will, setzt das Datum von Hand.

## Dauer (auch für Videos)

Jedes Audio- und Video-Item hat eine **Dauer** in Sekunden. Sie steht im
Detailpanel, in der Lupe und in der Einzelansicht. Videos, die vor fml
2026.09.2 aufgenommen wurden, bekommen ihre Dauer mit einem **Re-Scan
aller Fundorte**.

## Suchen und Sortieren

Diese Filter gelten unabhängig vom Modul:

- **`typ:`** (englisch `type:`) — Medienart: `bild`, `video`, `audio`
  (englisch `image`, `video`, `audio`). `typ: audio`, `-typ: bild`,
  `typ: video | audio`.
  Klickbar als Sidebar-Gruppe **Medienart**, im „+ Kriterium"-Baukasten
  und in der Tipphilfe.
- **`dauer:`** (englisch `duration:`) — Dauer mit Vergleich in Sekunden
  oder als Minuten:Sekunden: `dauer: >120`, `dauer: <=3:30`,
  `dauer: 60-180` (Bereich, inklusiv). Mehrere Werte mit ` | ` sind ODER.
  Items ohne Dauer (Bilder) passen nie, auch nicht verneint:
  `-dauer: >120` findet Kurzes, nicht alle Bilder.
- **Sortierung „Dauer"** (`sort: duration`): Längstes zuerst,
  `sort: duration-auf` Kürzestes zuerst; Medien ohne Dauer stehen in
  beiden Richtungen am Ende.
- **Sortierung „Album"** (`sort: album`) und **„Manuell"** gibt es nur in
  der Audioansicht, siehe [Musiksammlung](#musiksammlung-interpret-album-genre)
  und [Eigene Reihenfolge](#eigene-reihenfolge-einer-gespeicherten-suche).

Beispiel: `typ: audio dauer: >120 sort: duration`.

## Wiedergabe

In der Audioansicht spielt die Zeile selbst (siehe oben); das
Detailpanel zeigt dort nur Metadaten und Songtext, keinen zweiten Player.
Wo ein Song ohne Zeile erscheint (im Detailpanel der Galerie und in der
Einzelansicht eines Songs mit Cover), steht ein kleiner Player mit derselben
Wellenform (auf die Länge des Songs gestreckt), ▶, Stelle und Dauer; er
spielt nie von selbst und ist derselbe Abspielkopf wie die Zeile. Startet
irgendwo ein Video mit Ton (Lupe, Einzelansicht), pausiert der Song, und
umgekehrt. Stumme Vorschau-Videos im Detailpanel und in Rankings lassen die
Musik laufen.

**Eine Lupe gibt es für Songs nicht, eine Einzelansicht nur mit Cover**
(siehe [Cover](#cover-fertige-songs-in-der-galerie)): Die Liste mit Player
und Detailpanel kann mehr. „Node-Graph ansehen" im Detailpanel öffnet für
ComfyUI-Songs die Lupe mit dem Workflow. Die Datei markiert im
Finder/Explorer zeigt der 📂-Knopf vor dem bevorzugten Fundort im
Detailpanel (Abschnitt Fundorte). Enter öffnet in der Audioansicht nichts.

**Abspielleiste.** Sobald ein Song läuft, erscheint unten die Leiste: ⏮
(in den ersten drei Sekunden: der vorige Song von „Alle abspielen";
danach: zurück an den Anfang), ▶/❚❚, ⏭ (nächster Song von „Alle abspielen"), Name und
Position in der Reihe, die Wellenform des Songs mit Klick zum Springen
und rechts die Optionen:

- **≈ Lautheit** gleicht die Lautheit an (Standard: an). Jeder Song wird
  auf -14 LUFS gebracht, damit beim Vergleichen nicht die lautere Fassung
  gewinnt; die Leiste zeigt, um wie viel dB. Laute Songs werden leiser,
  leise nur so weit lauter, dass der True Peak unter -1 dBTP bleibt (sonst
  übersteuert es; mit Sample Peak gemessen unter -2 dBFS, siehe unten). Die Wellenformen zeigen die angeglichene Höhe: was man
  sieht, hört man. Die Einstellung gilt für alle Songs und bleibt
  gespeichert. Die Datei selbst ändert sich nie.
- **Tempo** reihum 1,00× → 1,25× → 1,50×, **ohne** die Tonhöhe zu ändern:
  zum schnellen Vorhören.
- **⟲ A–B** wiederholt einen Bereich: erster Klick setzt A an der
  Abspielstelle, zweiter Klick setzt B, der Bereich läuft dann in
  Schleife; dritter Klick hebt sie auf. Der Bereich ist in den
  Wellenformen markiert.
- **✕** beendet die Wiedergabe und blendet die Leiste aus; die Stelle
  bleibt gemerkt.

Die Leiste **läuft beim Wechsel in die Galerie weiter**: Man kann Bilder
sichten, während „Alle abspielen" durchläuft. Auch in einem geöffneten
[Ranking](rankings.md) bleibt sie unten stehen, man kann also Duelle klicken
und dabei Musik hören. Die laufende Zeile ist in
der Liste hervorgehoben.

**Medientasten** der Tastatur (Play/Pause, vor, zurück) und die
Mediensteuerung des Betriebssystems bedienen den Player, auch wenn das
Browserfenster im Hintergrund liegt. Sie zeigen den Dateinamen als Titel.

Browser spielen MP3, FLAC, WAV, M4A (AAC) und meist auch Ogg/Opus. **AIFF**
spielt nur Safari, **CAF** kein Browser, **ALAC** in M4A nur Safari. Für
diese drei legt fml eine **abspielbare Kopie** an: verlustfreies FLAC,
das jeder Browser spielt, und zwar **erst beim ersten Abspielen** und
**nur, wenn der Browser das Format nicht selbst kann**: Safari spielt
AIFF und ALAC direkt und bekommt deshalb keine Kopie. Das erste ▶ dauert
dadurch einen Moment länger (ein 3-Minuten-Song braucht auf einem
aktuellen Mac etwa 0,2 Sekunden, auf einem kleinen Heimserver etwa
eine), danach spielt der Song sofort. Das Original bleibt unangetastet;
die Kopie liegt im Cache (Standard `cache/audio` neben der Datenbank, in
der `config.toml` als `[cache] audio`) und lässt sich jederzeit neu
erzeugen. Sie ist verlustfrei und etwa halb so groß wie ein AIFF. Klappt
auch die Kopie nicht (etwa ohne ffmpeg oder bei fehlender Datei), zeigen Zeile, Player und Leiste ehrlich
„Wiedergabe nicht möglich"; die Fundorte im Detailpanel führen zur Datei.

## Zeitkommentare

Ein Zeitkommentar hängt an einer **Stelle im Song**, wie bei SoundCloud:
„Chorus" bei 1:40, „Stimme kippt" bei 2:15. Kommentare gehören zur
manuellen Schicht wie Bewertung und Tags; in die Datei wird nichts
geschrieben.

**Anlegen** geht immer an der Stelle des Abspielkopfs:

- **K** in der Audioansicht: für die ausgewählte Zeile, an ihrem eigenen
  Abspielkopf (der auch steht, wenn sie nicht spielt: mit ←/→ an die
  Stelle schieben, dann K). In der Galerie meint K den Song der
  Abspielleiste.
- **💬** in der Abspielleiste: für den laufenden Song.
- **＋ Kommentar an der Abspielstelle** im Detailpanel.

Es öffnet sich eine kleine Eingabe mit der Stelle davor. **Enter**
speichert (auch ein Klick daneben, wenn Text drinsteht), **Esc** verwirft.

**Sehen und springen:** Jeder Kommentar ist ein kleiner Pin ▲ unter der
Wellenform, in der Liste, im Player und in der Abspielleiste. Mit der
Maus darüber steht der Text da, ein Klick spielt genau ab dort. Hängt in
zwei Fassungen „Chorus" am Refrain, ist Refrain gegen Refrain je ein
Klick.

**Beim Abspielen blenden die Kommentare ein:** eine Sekunde, bevor die
Stelle kommt, erscheint der Text über der Wellenform und bleibt fünf
Sekunden danach stehen. Wer anhält, sieht ihn weiter. Liegen mehrere
Kommentare dicht beieinander, stehen sie übereinander.

**Im Detailpanel** stehen alle Kommentare des Songs unter
„Zeitkommentare": Klick auf eine Zeile spielt ab dort, **Doppelklick auf
den Text** ändert ihn (Enter speichert, Esc bricht ab), **✕** löscht.

**Suchen:** Kommentare sind Teil der normalen Suche. Wer „Streicher"
sucht, findet auch den Song, an dem „Streicher setzen ein" hängt.

### Kommentare mit einem anderen fml austauschen

Zwei Leute mit je eigenem fml können sich Kommentare schicken, als Datei
(Mail, USB-Stick, Cloud-Ablage).

**Exportieren:** In der Audioansicht die Songs auswählen oder eine Suche
eingrenzen, dann die **Sammel-Aktion** öffnen und in der Zeile
„Austausch" auf **Exportieren** klicken (Häkchen „Zeitkommentare"
gesetzt). Es entsteht eine Datei `fml-austausch-JJJJ-MM-TT.json` mit allen
Kommentaren dieser Songs. Hier ändert sich dabei nichts. Dieselbe Datei
kann auch die Musik-Angaben von Hand mitnehmen, siehe
[Angaben mit einem anderen fml austauschen](#angaben-mit-einem-anderen-fml-austauschen).

**Importieren** geht auf der anderen Seite unter **Admin → Wartung →
Austausch importieren**, in drei Schritten:

1. **Datei und Herkunft:** die Datei wählen und eintragen, von wem die
   Kommentare stammen (z. B. einen Namen).
2. **Vorschau:** Wie viele Songs gefunden wurden, wie viele Kommentare neu
   und wie viele schon da sind, und welche Songs es hier nicht gibt.
3. **Übernehmen.** Jeder übernommene Kommentar trägt die Herkunft als
   kleines Etikett (im Panel, am Pin, beim Einblenden).

**Wie fml die Songs findet:** über die Datei selbst (ihren Hash). Eine
Datei, die unverändert kopiert, gezippt oder verschickt wurde, wird auf
jedem Rechner gefunden. Hat jemand die Datei verändert (Tags in einem
Player oder Tag-Editor bearbeitet, neu heruntergeladen, in ein anderes
Format umgewandelt), ist es für fml eine andere Datei. Für **Suno-Songs**
gibt es dann eine zweite Chance über die Suno-Song-ID: Diese Treffer
zeigt die Vorschau eigens, übernommen werden sie nur mit dem Häkchen
„Auch Songs übernehmen, die nur über die Suno-ID gefunden wurden".

**Doppeltes gibt es nicht:** Ein Kommentar an derselben Stelle mit
demselben Text wird übersprungen. Derselbe Import zweimal ändert nichts,
und Kommentare, die hin- und zurückgeschickt werden, verdoppeln sich
nicht.

**Das Dateiformat** (für Neugierige): JSON mit `"format":
"fml-exchange"` und `"version": 1`; je Song `file_hash`, `name`
(nur als Hinweis), `duration`, gegebenenfalls `suno_ids`, dazu wahlweise
die Liste `comments` mit `at_ms` (Stelle in Millisekunden), `text`,
`created_at`, `updated_at` und der Abschnitt `fields` mit den
Musik-Angaben von Hand (`{"artist": ["…"], "album": ["…"]}`); ganz oben
stehen außerdem `exported_at` und die Liste `items` mit den Songs. fml
nimmt höchstens 20 MB, 50.000 Songs und 200.000 Kommentare je Datei, 2.000
Kommentare je Song und Kommentartexte bis 2.000 Zeichen; für die
Musik-Angaben gelten dieselben Grenzen wie bei der Eingabe von Hand.

Dateien im älteren Format `fml-time-comments` (nur Kommentare, bis fml
2026.10) lassen sich weiterhin importieren. Umgekehrt liest ein älteres
fml das neue Format nicht: Beide Seiten brauchen den aktuellen Stand.

## Vergleichen

Für die engere Wahl: **2 bis 6 Songs markieren** (Shift- oder ⌘-/Strg-Klick)
und **C** drücken oder oben rechts **⇆ Vergleichen** klicken. Die Liste
**engt sich auf diese Songs ein** und vergrößert die Zeilen: höhere
Wellenform, und die **Zeitkommentare stehen als Text** über der Welle
(liegen zwei dicht beieinander, stehen sie übereinander). Die Zeitachse
ist jetzt der längste der verglichenen Songs, damit die Wellen die volle
Breite nutzen. Bei mehr als sechs markierten Songs ist der Knopf gesperrt.

- **Lautheit angleichen** ist im Vergleich **immer zuerst an**, damit nicht
  die lautere Fassung gewinnt. Der Schalter oben rechts schaltet ihn für
  diesen Vergleich um; die eigene Einstellung kommt nach dem Vergleich
  unverändert zurück.
- **Die Zeilen sind der Player:** Die Abspielleiste unten ist im Vergleich
  ausgeblendet, damit mehr Platz für Wellen und Kommentare bleibt. Tempo
  und A–B-Loop stellt man vorher in der Leiste ein; das Tempo gilt im
  Vergleich weiter. Nach Esc ist die Leiste wieder da.
- **Bedienen wie in der Liste:** ↑/↓ wechselt die Zeile, Leertaste spielt,
  ←/→ schiebt den Abspielkopf, 1 bis 5 bewertet, **Entf lehnt ab**, K legt
  einen Kommentar an, Tags und Notizen im Detailpanel. Ausgewählt ist
  dabei immer nur die aktuelle Zeile: eine Bewertung trifft nur sie.
- **Abgelehnte Songs** verschwinden sofort aus dem Vergleich, die Zeile
  darunter rückt nach.
- **Esc** (oder **✕ Vergleich beenden**) bringt die volle Liste zurück, an
  **derselben Scrollstelle**. Die übrigen Songs bleiben markiert: **C**
  vergleicht sie gleich noch einmal. Filter und Suche bleiben, wie sie
  waren. Eine neue Suche, eine andere Sortierung oder der Wechsel in die
  Galerie beendet den Vergleich ebenfalls.

Beispiel: sechs Suno-Kandidaten markieren, C, jede Fassung an den Refrain
setzen und reihum anhören, zwei mit Entf ablehnen, die übrigen vier
bewerten, Esc.

In der Galerie vergleicht C weiterhin **zwei Bilder** übereinander (A/B mit
Wischkante); in der Audioansicht gibt es diesen Bildvergleich nicht.

## Cover: fertige Songs in der Galerie

Ein Song ist **fertig**, sobald er ein **Cover** hat: ein Bild aus der
eigenen Bibliothek, zum Beispiel ein in ComfyUI erzeugtes Artwork. Mit
Cover erscheint der Song zusätzlich **in der Galerie**, zwischen Bildern
und Videos. Alle übrigen Fassungen bleiben in der Audioansicht.

**Setzen:** Song auswählen (in der Liste, der Galerie oder der
Einzelansicht), ganz oben im Detailpanel auf **🖼 Cover wählen …**.
Der Dialog zeigt Bilder der Bibliothek und startet mit `typ: bild` und den
**Tags des Songs** (ODER-verknüpft): Hat der Song den Tag `regenzeit`,
stehen die Bilder mit diesem Tag vorn. Chips entfernt ✕, das Feld
daneben sucht wie das Suchfeld der Galerie: ein Wort filtert schon beim
Tippen (ab drei Zeichen) nach Text, Enter macht daraus einen Chip,
Ausdrücke wie `model: flux` gehen auch. Bild anklicken,
**Als Cover setzen** (oder Doppelklick aufs Bild). Tipp: dem Artwork
gleich beim Erzeugen denselben Tag geben wie dem Song.

Danach ist das Cover das Gesicht des Songs: Es steht **oben im
Detailpanel** wie das Vorschaubild eines Bildes, in allen Ansichten,
direkt darunter **✓ Finalisiert** mit **Ändern …** und **Entfernen**.
Auch die Abspielleiste zeigt es links vom Titel, ebenso die Medientasten
des Systems.

- **Nichts wird in Dateien geschrieben.** fml merkt sich nur, welches Bild
  zu welchem Song gehört. Audiodatei und Bild bleiben unverändert.
- **In der Galerie** zeigt die Kachel das Coverbild mit **♪ und der
  Dauer**; ▶ auf der Kachel und die Leertaste spielen den Song, die
  Abspielleiste erscheint wie gewohnt. **Doppelklick oder Enter** öffnet
  die **Einzelansicht**: großes Cover, darunter der Player, rechts das
  Detailpanel. ←/→ blättert wie gewohnt durch die Galerie.
- **Cover entfernen**, das Coverbild **ablehnen** (Entf) oder sperren:
  Der Song verlässt die Galerie und ist nur noch in der Audioansicht. Aus
  der Einzelansicht heraus geht es dann zurück in die Übersicht.
- **Eingebettete Cover** zählen nie als Cover: Sie bringen keinen Song in
  die Galerie und machen ihn nicht „fertig". Im Detailpanel stehen sie klein
  und blass unter **Datei** („Eingebettetes Bild“).
- **Normale Musik** (ohne erkannten KI-Erzeuger, etwa ein gekauftes Album)
  zeigt ihr eingebettetes Bild trotzdem als **Anzeigebild**: klein vor dem
  Namen in der Liste, in der Abspielleiste und bei den Medientasten des
  Systems. So taugt die Audioansicht als Musik-Playlist, während man in der
  Galerie Bilder sichtet oder Duelle klickt. Songs von Suno, ComfyUI & Co.
  zeigen ihr mitgeliefertes Standardbild nicht; sie bekommen erst mit einem
  gewählten Cover ein Bild. Ein gesetztes Cover geht immer vor.
- Mit ausgeschaltetem Audio-Modul zeigt die Galerie auch Songs mit Cover
  nicht; die Cover bleiben gespeichert.

## Lautheit und Wellenform

Nach jedem Import (und beim Einschalten des Moduls) misst fml im
Hintergrund jede Audiodatei einmal durch:

- **Lautheit** nach EBU R128: integrierte Lautheit in LUFS, Lautheits-
  umfang (LRA) in LU und True Peak in dBTP. Sie steht im Detailpanel
  unter „Datei", z. B. `-9,0 LUFS · LRA 6,1 LU · True Peak -0,3 dBTP`.
  **True Peak oder Sample Peak** (`[audio] true_peak` in der
  `config.toml`, Standard `true`): True Peak schätzt auch die Spitzen
  zwischen den Abtastwerten (vierfache Überabtastung) und ist das Maß
  fürs Mastering, kostet aber knapp die Hälfte der ganzen Messzeit. Mit
  `true_peak = false` misst fml den Sample Peak (in dBFS, Anzeige
  `Sample Peak -0,3 dBFS`): Die Messung dauert etwa halb so lange, was bei
  großen Sammlungen auf langsamen Rechnern Tage sparen kann; der
  Lautheitsangleich hält dafür 1 dB mehr Abstand (-2 dBFS). Die
  Einstellung gilt für neue Messungen, fertige behalten ihren Wert.
  Zur Einordnung: Streamingdienste spielen um -14 LUFS ab; ein Song mit
  -9 LUFS ist deutlich lauter gemastert. Die Liste zeigt die integrierte
  Lautheit als eigene Spalte; der Player gleicht sie an (siehe
  „Wiedergabe").
- **Wellenform in drei Bändern**: Bass (unter 200 Hz), Mitten (200 Hz bis
  2 kHz) und Höhen (über 2 kHz), wie in DJ-Software. Jedes Band ist in
  seiner eigenen Höhe gezeichnet, der Bass hinten, die Höhen vorn: Wo
  Blau dominiert, drückt der Bass, wo Hell hervortritt, zischen Becken
  und Stimme. Die Daten liefert `/api/audio/analysis/<hash>`. Solange
  eine Messung noch läuft, zeigt die Zeile eine Grundlinie.

Beides ist abgeleitet und liegt im selben Cache wie die abspielbaren
Kopien. **Admin → Wartung → Audio analysieren** erzeugt fehlende
Messungen, versucht Fehlgeschlagenes erneut (auch gescheiterte Kopien,
beim nächsten Abspielen) und rechnet nach einem Update neu, wenn sich das
Messverfahren geändert hat. Dauerhafte Fehler stehen unter
**Admin → Probleme** (Art `audio`).

## Grenzen (Stand jetzt)

- „Alle abspielen" nimmt höchstens die ersten 5000 Songs der Liste.
- Udio: die Abstammung (`ext v…`, `remix v…` im Dateinamen) wird noch
  nicht gedeutet; Suchen im Dateinamen geht (`datei: "ext v"`).
- Beilagedateien (Sidecars wie `request.json` von YuE2 oder die JSON von
  ACE-Step) werden noch nicht gelesen.
- Rankings vergleichen nur Bilder und Videos; Songs sind nie dabei,
  auch nicht mit Cover oder mit `typ: audio`.
