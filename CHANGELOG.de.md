# Changelog · Feral Media Library (fml)

> 🇬🇧 **English version:** [`CHANGELOG.md`](CHANGELOG.md)

Was sich zwischen den Snapshot-Releases geändert hat, aus Sicht der
Nutzer. Versionen sind Datums-Versionen (`JJJJ.MM` oder `JJJJ.MM.N`);
die laufende Instanz zeigt ihre Version in Admin → Übersicht.

## 2026.10 (2026-10-01)

fml arbeitet jetzt **leise im Hintergrund** und lässt sich **anhalten**;
was wartet, übersteht einen Neustart. Das Audio-Modul versteht die
gewöhnliche **Musiksammlung** (Interpret, Album, Genre), zeigt den
**Songtext mit Zeiten** beim Abspielen und tauscht **Zeitkommentare**
zwischen zwei fml aus. Dazu ein rechtes Panel, das sich wegklappen lässt,
ein Datum von Hand und Finder-Tags unter macOS.

### Nach dem Update

1. **Wie gewohnt mit `start.sh` bzw. `start.bat` starten.** Die
   Abhängigkeiten sind unverändert.
2. **Datenbank:** wird beim ersten Start automatisch auf Schema 33
   migriert (fünf neue Migrationen). Vorher ein Backup der
   `feral.sqlite` anlegen, wie bei jedem Update.
3. **Beim ersten Start laufen zwei Aufgaben einmal von selbst:**
   „Aussortierte neu prüfen" (ohne Aussortiertes sofort fertig) und, mit
   Audio-Modul, „Songtexte mit Zeiten nachholen" (nur Songs mit
   Untertitel-Spur).
4. **Musik im Bestand:** einmal **Admin → Wartung → „Neu interpretieren"**
   für Interpret, Album, Genre, das Jahr aus den Tags und Songtexte mit
   Zeiten aus ID3 `SYLT` oder LRC. Wer alte Musik hat, stellt vorher
   „Ältestes plausibles Datum" zurück (Admin → Konfiguration → Media
   Library, ab Werk 2015), sonst gilt ein Tag-Jahr wie 1987 als
   unplausibel.
5. **macOS, Finder-Tags im Bestand:** einmal **Admin → Wartung →
   „Re-Scan aller Fundorte"**.
6. **„Cache leeren" ist umgezogen:** Admin → Wartung hat jetzt eine eigene
   Karte **Cache** mit einer Zeile je Art.

### Neu: leise arbeiten, anhalten, weitermachen

- **Zwei Knöpfe in der Kopfzeile der Galerie** (und im Aktivitäts-Widget
  des Admins) für alle Hintergrundaufgaben. **Leistung:** Blitz = Normal,
  Blatt = **Leise** (ein Prozess mit niedrigster Priorität für Prozessor,
  Platte und Speicher, auch ffmpeg rechnet mit einem Thread; unter Windows
  hart auf einen Kern begrenzt). **Anhalten** („Zz"): Die Warteschlange
  hält an der nächsten Datei an und setzt beim zweiten Klick dort fort.
  Beides wirkt sofort, ohne Neustart; den Startwert legt `[performance]
  background` fest.
- **Die Warteschlange übersteht Neustarts:** Wird fml beendet, hält die
  laufende Aufgabe an der nächsten Datei an, alles Wartende wird
  gesichert. Beim nächsten Start geht es dort weiter.
- **Watchordner haben Vorrang:** Neue Dateien aus einem Watchordner kommen
  vor wartende Langläufer; ein laufendes Einlesen gibt dafür an der
  nächsten Datei ab und läuft danach weiter.
- **Vorschaubilder vor Analysen:** Sichtbare Kacheln und Anzeigebilder
  kommen zuerst, Audio-Analysen beim Blättern reihen sich dahinter ein.
- **Prozesszahl:** Die Automatik nimmt bis 4 Kerne einen Prozess, sonst
  Kerne − 2. Eine geänderte Prozesszahl wirkt ohne Neustart.

### Neu im Audio-Modul

- **Musiksammlung:** Interpret, Album-Interpret, Album, Titel- und
  CD-Nummer, Jahr und Genre aus ID3, Vorbis, WAV und M4A. In der
  Audioansicht drei neue Gruppen in der Seitenleiste (Interpret, Album,
  Genre), die Suche kennt `interpret:`, `artist:`, `album:` und `genre:`,
  und die Sortierung **„Album"** spielt ein Album in seiner Reihenfolge.
  Ein Klick auf ein Album sortiert von selbst danach. Die Listenzeile
  zeigt „Interpret · Album".
- **Songtext mit Zeiten:** Songs aus Suno V6 tragen ihren Text Zeile für
  Zeile mit Zeiten in einer Untertitel-Spur; fml liest sie, dazu ID3
  `SYLT` und LRC im Songtext-Tag. Unter der Welle der Abspielleiste steht
  die Zeile, die gerade läuft, davor der Abschnitt („Chorus · …"). Auf
  der Welle jeder Listenzeile markieren Beschriftungen die Abschnitte, und
  im Detailpanel läuft der Songtext mit; ein Klick auf eine Zeile springt
  dorthin.
- **Zeitkommentare austauschen:** Sammel-Aktion → Zeitkommentare →
  **Exportieren** schreibt eine Datei, die ein anderes fml unter Admin →
  Wartung → **Zeitkommentare importieren** übernimmt, mit Vorschau und
  einem Herkunfts-Etikett an jedem Kommentar. Songs findet fml über die
  Datei selbst, bei Suno-Songs auf Wunsch auch über die Song-ID. Derselbe
  Import zweimal ändert nichts.
- **Eigene Reihenfolge je gespeicherter Suche:** Sortierung **„Manuell"**
  in der Audioansicht; Zeilen am Dateinamen ziehen oder mit Alt+↑ / Alt+↓
  verschieben. „Alle abspielen" folgt dieser Reihenfolge.
- **Jahr aus den Tags als Datum:** Ohne eingebettetes Datum zählt das Jahr
  aus den Tags vor dem Dateistempel. Eine gerippte CD von 1987 steht dann
  unter 1987, nicht unter dem Tag des Rippens.
- **True Peak oder Sample Peak:** `[audio] true_peak = false` misst den
  Sample Peak und halbiert etwa die Analysezeit; der Lautheitsangleich
  hält dann 1 dB mehr Abstand. Standard bleibt True Peak.

### Neu für alle

- **Rechtes Panel:** Ein Klick auf eine Überschrift klappt den Abschnitt
  ein (KURATIERT, GENERATION, WORKFLOW, Zeitkommentare, DATEI). Der
  schmale Streifen am rechten Fensterrand oder die Taste **P** klappt das
  ganze Panel weg, die Galerie bekommt sofort mehr Spalten. Beides wird
  gemerkt. Roh-Metadaten und Fundorte stehen jetzt ganz unten.
- **Datum von Hand:** Feld unter KURATIERT und Zeile **„Datum"** der
  Sammel-Aktion, für alle Medien: `1997`, `1997-05`, `1997-05-12` oder
  `12.05.1997`, so genau wie eingegeben. Es gewinnt gegen Metadaten und
  Dateistempel und übersteht jeden Re-Scan; Leeren holt das abgeleitete
  Datum zurück. Die Datei bleibt unverändert.
- **Finder-Tags (macOS):** Die farbigen Markierungen aus dem Finder werden
  beim Import und beim Scan zu normalen Tags, mit Farbpunkt auf Kachel,
  Listenzeile und im Panel. Der Import kopiert außerdem die erweiterten
  Dateiattribute mit, sodass die Kopie in der Library ihre Finder-Tags
  behält. fml liest nur und schreibt nie in den Finder zurück.
- **Aussortierte neu prüfen:** Geänderte Import-Regeln wirken auch
  rückwärts auf das, was beim Katalogisieren aussortiert wurde: nach dem
  Speichern im Admin, beim Start nach einer Änderung in der `config.toml`
  oder per Knopf unter Admin → Wartung. Ein Neu-Scan ist nicht nötig.
- **Admin → Probleme:** Dateien ohne Vorschaubild (typisch: beschädigt
  nach vielen Backups) lassen sich direkt **ablehnen**, einzeln oder alle
  dieser Art. Die Datei bleibt liegen.
- **Admin → Wartung, Karte Cache:** Thumbnails, Audio-Analysen,
  Audio-Wiedergabekopien und Anzeigebilder je mit Anzahl, Größe, Ort und
  **Löschen**. Alles davon entsteht bei Bedarf neu.

### Fehlerbehebungen

- **Aktivität:** Re-Scan, Ordner-Scan und Watchordner melden ihr eigenes
  Ergebnis („Katalogisiert: n neu · m bekannt"). Vorher konnte eine
  Aufgabe die Zusammenfassung der vorigen zeigen.
- **Import-Regeln:** Der Hinweistext zum ältesten plausiblen Datum
  beschreibt jetzt, was die Regel wirklich tut.
- **Lupe:** Der Hinweis am unteren Rand versprach „Enter =
  Einzelbildansicht"; in der Lupe hat Enter keine Funktion. Der Hinweis
  ist korrigiert.
- **Doku:** Nach dem Einschalten des Audio-Moduls nimmt „Re-Scan aller
  Fundorte" keine Musik auf, anders als bisher beschrieben. Einmal
  katalogisierte Ordner noch einmal aufnehmen (Admin → Quellen & Import);
  Watchordner holen die Musik von selbst nach.

### Sicherheit und Robustheit

Vor diesem Release wurde alles, was seit 2026.09.3 dazukam, noch einmal
gegen präparierte Dateien und unglückliche Abläufe geprüft:

- **Ein kaputter Tag bricht keinen Lauf mehr ab.** Ein Song mit einer
  unsinnigen Genre- oder Titelnummer konnte Einlesen und „Neu
  interpretieren" an dieser Datei abbrechen. Jetzt fällt nur die Deutung
  dieser einen Datei aus.
- **Songtext mit Zeiten und Finder-Tags sind gedeckelt** (Textlänge,
  Zeilenzahl, Zeilenlänge, Zahl der Untertitel-Spuren). Präparierte Tags
  enden in Sekundenbruchteilen, statt den Hintergrund zu blockieren.
- **Importe überstehen einen Neustart richtig.** Ein Import mit kopieren
  oder verschieben, der beim Beenden lief oder wartete, meldete danach
  jede Datei als Fehler; im Modus verschieben landeten die restlichen
  Quelldateien dabei im Ordner `_fehler` der Quelle. Verloren ging nichts.
  Nur Katalogisieren war nie betroffen.
- **Anhalten mitten in einem Ordner-Import** schließt die schon
  importierten Dateien ab. Vorher erschienen sie beim Fortsetzen als
  Dubletten.
- **Übersichtsmodus über den Neustart:** Ein gesicherter Import kommt
  nicht zurück, wenn inzwischen der Übersichtsmodus gilt.
- **Cache löschen** entfernt nur noch Dateien, die fml selbst angelegt
  hat, nie einen ganzen Ordner. Ein falsch eingetragener Cache-Pfad in der
  `config.toml` kann so keine eigenen Dateien mehr kosten.
- **Probleme ablehnen** gilt serverseitig nur für „kein Vorschaubild".
- **Fremde Webseiten können nichts mehr auslösen.** Einige
  Admin-Aktionen (Cache löschen, Probleme quittieren) konnte eine fremde
  Seite im selben Browser blind anstoßen, solange fml lief. Jetzt muss
  jede ändernde Anfrage von fmls eigener Oberfläche stammen. Hinter einem
  Reverse-Proxy den `Host`-Kopf unverändert durchreichen.
- **Kommentar-Import:** höchstens 2.000 Kommentare je Song.
- **Vorschaubilder vor Analysen** greift jetzt wirklich: Die Analyse beim
  Blättern lief bisher gleichrangig mit den Kacheln.
- Abhängigkeiten: unverändert, alle 22 Pakete ohne offene Meldung.

## 2026.09.3 (2026-09-25)

fml liest jetzt **Kodak Photo CD**: die Bilder von den Foto-CDs der
90er, in voller Auflösung. Dazu zwei Korrekturen im Audio-Modul und mehr
Robustheit unter Windows.

### Nach dem Update

1. **Wie gewohnt mit `start.sh` bzw. `start.bat` starten.** Abhängigkeiten
   und Datenbank-Schema sind unverändert.
2. **Photo-CD-Dateien, die bisher aussortiert wurden** (Ausgangs-Ordner
   „unbekanntes Format" des Watch-Ordners), einfach noch einmal in den
   Watch-Ordner legen bzw. den Scan-Ort neu scannen.

### Neu: Kodak Photo CD

- **`.PCD`-Dateien** werden erkannt, katalogisiert und angezeigt, in der
  größten Stufe der Datei: **3072×2048** (bzw. 1536×1024). Hochformate
  werden gedreht, wie auf der CD vermerkt.
- **Erstelldatum aus der CD:** Der Scanzeitpunkt steht im Kopf der Datei
  und wird zum Datum des Bildes, auch wenn der Dateistempel längst
  verloren ist. Im Detailpanel stehen dazu Scanner, Filmtyp und Fotolabor.
- **Schnell ab dem zweiten Mal:** Das große Bild rechnet fml beim ersten
  Öffnen (ein bis zwei Sekunden) und legt es dann verlustfrei als PNG im
  Cache ab (`cache/preview` neben der Datenbank, rund 11 MB je Bild;
  jederzeit löschbar, Ort über `[cache] preview`).

### Fehlerbehebungen

- **Audio: Der Pause-Knopf** in der Liste und in der Abspielleiste
  reagiert während der Wiedergabe zuverlässig. Vorher ging ein Klick auf
  ❚❚ oft ins Leere, die Leertaste funktionierte.
- **Audio: Die Seitenleisten-Gruppe „Songtext"** heißt jetzt „mit Songtext"
  / „ohne Songtext" statt „mit Gesang" / „instrumental": Sie sagt nur, ob
  ein Songtext in der Datei steckt, nicht, ob gesungen wird.
- **Windows:** ffmpeg und ffprobe öffnen keine kurz aufblitzenden
  Konsolenfenster mehr, und der Server stürzt nicht mehr ab, wenn seine
  Ausgabe umgeleitet ist (etwa beim Start ohne Konsole).
- **Übersichtsmodus:** Admin → Quellen zeigt keine falsche Warnung
  „kein Import-Ziel" mehr.

### Für Installationen ohne Konsole

- **`--exit-when-idle MINUTEN`:** Der Server beendet sich selbst, wenn so
  lange keine fml-Seite mehr offen war und keine Aufgabe läuft oder wartet
  (mindestens 2 Minuten).
- **`--help-dir ORDNER`:** Ein Ordner mit `index.html`, etwa eine eigene
  Anleitung: fml zeigt dann oben rechts ein **?**, das sie in einem Fenster
  über der Bibliothek öffnet.

### Sicherheit

- **Photo CD liest fml mit eigenem, gedeckeltem Decoder:** höchstens
  16 MiB je Datei, begrenzte Zeilenzahl, die Suche nach Zeilenmarken läuft
  in C. Eine präparierte Datei endet schnell, statt die Thumbnail-Prozesse
  zu blockieren. Dauerhafter Test mit verbogenen Dateien.

## 2026.09.2 (2026-09-24)

fml kann jetzt auch **Musik**: Das neue **Audio-Modul** nimmt Songs von
Suno, aus ComfyUI oder eigene Aufnahmen auf, zeigt sie in einer eigenen
Audioansicht mit Wellenform und bringt einen Player mit, der zum
Vergleichen von Fassungen gebaut ist. Das Modul ist ab Werk aus; wer nur
Bilder und Videos verwaltet, bekommt eine aufgeräumtere Seitenleiste, den
Filter nach Medienart und die Dauer von Videos.

### Nach dem Update

1. **Wie gewohnt mit `start.sh` bzw. `start.bat` starten.** Die
   Abhängigkeiten sind unverändert.
2. **Datenbank:** wird beim ersten Start automatisch auf Schema 28
   migriert (vier neue Migrationen). Vorher ein Backup der
   `feral.sqlite` anlegen, wie bei jedem Update.
3. **Optional, einmal Admin → Wartung → „Re-Scan aller Fundorte":** gibt
   schon aufgenommenen Videos ihre Dauer (für `dauer:` und die Sortierung
   nach Dauer).
4. **Musik aufnehmen:** Admin → Konfiguration → Module → **Audio-Modul**
   einschalten, dann für bestehende Scan-Orte einmal „Re-Scan aller
   Fundorte". Watchordner prüfen übersprungene Audiodateien von selbst neu.
   Für Dauer, Lautheit, Wellenform und das Abspielen von AIFF/CAF wird
   **ffmpeg** gebraucht (wie für Videos).

### Highlights: das Audio-Modul

- **Formate:** MP3, FLAC, Ogg/Opus, WAV (auch RF64/BW64), AIFF, CAF und
  M4A bzw. MKA/WEBM nur mit Ton. Jeder Tag und jeder Chunk wird
  unverändert gespeichert, eingebettete Cover nur beschrieben. Die
  Medienart kommt aus den tatsächlichen Spuren: ein MP4 nur mit Ton ist
  Audio, nicht mehr fälschlich Video.
- **Was fml aus Musik liest:** Titel, Songtext, Tempo, Tonart und die
  Technik der Tonspur. **Suno:** Song-ID, die Erstellzeit als
  Mediendatum und die Suno-Version aus den Content Credentials
  (`Suno v4.5`, `Suno v5` …). **ComfyUI-Musik** (YuE, ACE-Step, MiniMax
  Music): Stil-Prompt, Songtext, Seed und Modell. Logic-Pro-Bounces und
  iPhone-Sprachmemos werden erkannt. Der **Songtext ist in der
  Volltextsuche**: eine Zeile daraus findet alle Fassungen eines Songs.
- **Audioansicht:** Umschalter **▦ Galerie | ♪ Audio** oben links; beide
  Ansichten teilen sich die Suche. Die Songs stehen als Liste über die
  volle Breite, jede Zeile mit **dreifarbiger Wellenform** (Bass, Mitten,
  Höhen) auf einer gemeinsamen Zeitachse, Lautheit in LUFS, Bewertung und
  Kommentarzahl. Gleiche Namensanfänge sind abgedunkelt, damit das
  Unterscheidende ins Auge springt.
- **Player:** Jede Zeile hat ihren **eigenen Abspielkopf**, es spielt
  immer genau eine: vier Fassungen lassen sich Refrain gegen Refrain
  anhören. **Lautheitsangleich** auf -14 LUFS (Standard an), damit nicht
  die lautere Fassung gewinnt; Tempo ohne Tonhöhenänderung, A–B-Schleife,
  **„Alle abspielen"** wie eine CD, eine Abspielleiste, die beim Wechsel in
  die Galerie weiterläuft, und die Medientasten der Tastatur. AIFF, CAF
  und ALAC bekommen beim ersten Abspielen eine verlustfreie FLAC-Kopie im
  Cache, nur wenn der Browser das Format nicht selbst kann.
- **Zeitkommentare** wie bei SoundCloud: **K** setzt „Chorus" oder „Stimme
  kippt" an die Stelle des Abspielkopfs. Pins unter der Wellenform
  springen per Klick genau dorthin, beim Abspielen blenden die Texte ein,
  und die Suche findet sie.
- **Vergleichen:** 2 bis 6 Songs markieren, **C** drücken: die Liste
  engt sich auf sie ein, die Wellen werden größer, die Kommentare stehen
  als Text da. Bewerten und Ablehnen wie gewohnt, **Esc** führt an
  dieselbe Stelle der vollen Liste zurück.
- **Cover und fertige Songs:** Ein Bild aus der eigenen Bibliothek als
  Cover macht einen Song „fertig". Er erscheint dann auch **in der
  Galerie**, als Kachel mit ♪ und Dauer, mit Einzelansicht und Player; das
  Cover zeigen auch Abspielleiste und Medientasten. In die Dateien wird
  nichts geschrieben.
- **Musik-Playlist nebenbei:** Normale Musik (ohne KI-Erzeuger) zeigt ihr
  eingebettetes Albumbild in der Liste, der Abspielleiste und bei den
  Medientasten; die Standardbilder von Suno & Co. bleiben draußen. In die
  Galerie kommt ein Song weiterhin nur mit einem gewählten Cover. Stumme
  Vorschau-Videos im Detailpanel und in Rankings halten die Musik nicht
  an, und in einem Ranking bleibt die Abspielleiste sichtbar.
- **Lautheit und Wellenform** misst fml im Hintergrund nach jedem Import;
  Admin → Wartung → „Audio analysieren" holt Fehlendes nach.
- Rankings bleiben bei Bildern und Videos; Songs sind nie dabei.

### Verbesserungen für alle

- **Seitenleiste aufgeräumt:** neue Gruppe **Medienart** (Bild · Video,
  mit Modul auch Audio). Dateityp, Format, Auflösung, Eingangsbild und
  Fundort stehen jetzt im Block **„Weitere Kriterien"**, der ab Werk
  zugeklappt ist; ist darin ein Wert aktiv, zeigt der Kopf „· 1 aktiv".
  Das „+ Kriterium"-Popover folgt derselben Reihenfolge und kennt
  Medienart, Generator und Dauer.
- **Neue Filter:** `typ:` (`bild`, `video`, `audio`; englisch `type:`)
  und `dauer:` (`dauer: >120`, `dauer: <=3:30`, `dauer: 60-180`; englisch
  `duration:`), dazu die Sortierung **nach Dauer**. Videos zeigen ihre
  Dauer im Detailpanel, in der Lupe und in der Einzelansicht.
- **Tipphilfe:** trifft ein Wort genau eine Medienart („video"), steht
  sie vorn, darunter die Volltextsuche.
- **Import-Regel „Formate/Endungen ausschließen"** trifft auch die
  Dateiendung, beim Import wie im Bestandswerkzeug: `lang` hält
  Sprachdateien von Programmen fern, auch wenn ihr Inhalt zufällig wie
  ein bekanntes Format aussieht.
- **„🎲 Seed-Varianten suchen"** erscheint nur noch bei Medien, die
  einen Seed haben.

### Fehlerbehebungen

- **Admin → Übersicht** zeigte dieselbe Platte manchmal doppelt, wenn
  während der Anzeige ein anderer Prozess schrieb. Laufwerke werden jetzt
  an ihrer Geräte-ID erkannt.

### Sicherheit und Doku

- **ffmpeg und ffprobe öffnen nur noch lokale Dateien:** Eine präparierte
  Video- oder Audiodatei kann sie nicht mehr zu Netzzugriffen bringen, und
  ein Dateiname, der mit `-` beginnt, wird nie als Option gelesen.
- Der neue **Audio-Parser** ist gegen abgeschnittene Dateien und gefälschte
  Längenangaben gedeckelt und mit zehntausenden verstümmelten Dateien
  geprüft.
- **`SECURITY.md`** nennt die Lieferkette jetzt gleich am Anfang: jedes
  installierte Paket benannt und per Prüfsumme gesichert, automatische
  Prüfungen gegen die Schwachstellen-Datenbank OSV, und wie man selbst
  nachprüft (`python tools/check_advisories.py`).
- Neue Seite **Audio-Modul** in der Doku; README und Bedienungs-Doku
  beschreiben Audio, Cover und die neue Seitenleiste.
- `config.example.toml` nennt die Log-Präfixe so, wie das Log sie
  schreibt (`slow:`, `cold:`).

## 2026.09.1 (2026-09-23)

Ein Sicherheits- und Sorgfalts-Release: Jedes Paket, das fml auf deinem
Rechner installiert, ist jetzt benannt, auf eine feste Version gepinnt und
per Prüfsumme gesichert.

### Nach dem Update

1. **Wie gewohnt mit `start.sh` bzw. `start.bat` starten.** Die Skripte
   installieren die Abhängigkeiten neu, diesmal im Prüfsummen-Modus, und
   räumen die frühere Installationsart von fml selbst auf. Mehr ist nicht
   zu tun.
2. **Wer von Hand installiert:** `python -m pip install --require-hashes
   --only-binary=:all: -r requirements.txt` und die `.pth`-Zeile aus dem
   README (Abschnitt „Für Entwickler"); `pip install -e .` wird nicht mehr
   gebraucht.

### Sicherheit

- **Keine unbenannten Pakete mehr.** `requirements.txt` ist ein
  vollständiger Lock: alle Laufzeit-Pakete, direkte wie indirekte und pip
  selbst, mit fester Version und SHA-256-Prüfsummen. Die Startskripte
  installieren im Prüfsummen-Modus: pip verweigert jedes nicht gelistete
  Paket und jede veränderte Datei.
- **Nichts wird mehr aus Quellcode gebaut.** Installiert werden nur fertige
  Pakete; die Startskripte laden weder Build-Werkzeuge noch ein ungepinntes
  „neuestes" pip nach.
- **anyio 4.14.2** behebt drei Sicherheitsmeldungen der Vorversion
  (Prozess-Gruppen, hängende Prozess-Pools, TLS-Hostnamen). fml nutzt diese
  Funktionen nicht direkt, aktualisiert aber trotzdem.
- **starlette, anyio und pydantic** sind jetzt als direkte Abhängigkeiten
  gepinnt und dokumentiert; fml nutzt sie im Code, bisher kamen sie nur
  indirekt über fastapi.
- Automatische Prüfungen stellen sicher, dass das so bleibt: Ein Import
  ohne benannte Abhängigkeit, ein Paket ohne Prüfsumme oder ohne
  Dokumentation macht die Testsuite rot.

### Doku

- Neue Seite **Architektur** mit vier Diagrammen: Prozesse, Weg einer Datei
  in den Katalog, Weg einer Suche zur Galerie, Installation und
  Lieferkette.
- Die **Sicherheits-Doku** beschreibt alle Prüfungen rund um die
  Abhängigkeiten, die Test-Doku die neuen Wächter-Tests, das README den
  geprüften Installationsweg.
- Neue **Schema-Referenz** der Datenbank mit ER-Diagramm, aus dem echten
  Schema erzeugt.
- `DEPENDENCIES.md` listet jedes installierte Paket mit Rolle; die
  Admin-Übersicht zeigt die sechs direkten Laufzeit-Pakete mit Version.

## 2026.09 (2026-09-14)

Der größte Sprung seit dem ersten Release: 45 Pull Requests seit
2026.07.3. Die ComfyUI-Workflow-Vorschau zeigt jetzt den Graphen, wie
man ihn aus ComfyUI kennt, der Admin-Bereich ist komplett neu gebaut,
Metadaten aus Gemini/ChatGPT/Firefly/Topaz und modernen
ComfyUI-Vorlagen werden erkannt, dazu spürbar mehr Tempo und ein
Dutzend Fehlerbehebungen aus dem Praxisbetrieb mit 70.000 Medien. Die Testsuite ist von 487 auf 736
Tests gewachsen, erstmals mit Regressionstests für die Oberfläche.

### Nach dem Update

1. **Abhängigkeiten aktualisieren:** `pip install -r requirements.txt`
   (`start.sh` / `start.bat` erledigen das selbst). Die Pins für
   fastapi und uvicorn wurden angehoben; Admin → Übersicht warnt
   gelb, wenn die installierten Pakete abweichen.
2. **Datenbank:** wird beim ersten Start automatisch auf Schema 24
   migriert (zwei neue Migrationen). Vorher ein Backup der
   `feral.sqlite` anlegen, wie bei jedem Update.
3. **Einmal Admin → Wartung → „Re-Scan aller Fundorte":** holt die
   neuen Roh-Metadaten in den Bestand (C2PA-Manifeste für die
   Generator-Erkennung, Stream-Eckwerte für den Video-Codec).
4. **Einmal Admin → Wartung → „Neu interpretieren":** der
   ComfyUI-Parser v11 findet Steps/Sampler/CFG in modernen Vorlagen,
   dazu Topaz, Midjourney-Modelle und Video-Codecs. Unveränderte
   Items werden übersprungen, der Lauf ist schnell.
5. **Optional:** Wartung → „Import-Regeln auf den Bestand" zeigt jetzt
   auch Items ohne plausibles Erstelldatum und räumt sie auf Wunsch
   aus dem Katalog (siehe Datumsregel unten).

### Highlights

- **ComfyUI-Workflows sehen aus wie in ComfyUI**. Die
  Workflow-Ansicht in der Lupe war bisher ein Kastenschema; jetzt
  zeigt sie den Graphen so, wie man ihn aus ComfyUI kennt: Typfarben
  an Slots und Links, Widgets als Pillen mit Namen und Wert, Prompts
  und Notizen als Textfeld, Bypass und Mute markiert, eingeklappte
  Nodes, Gruppen, Subgraphs zum Aufklappen mit Rückweg. Wer einen
  Workflow wiederfinden will, erkennt ihn auf einen Blick, ohne
  ComfyUI zu öffnen. Weiterhin reines SVG aus dem eingebetteten
  Workflow, ohne Frontend-Abhängigkeit. Widget-Namen der eigenen
  Custom Nodes zieht `tools/dump_object_info.py` einmal aus der
  eigenen ComfyUI-Instanz.
- **Admin-Bereich komplett neu**. Der Admin
  ist ein eigenes Dokument unter `/admin` mit Seitennavigation:
  Übersicht, Wartung, Probleme, Quellen & Import, Konfiguration,
  Rankings, Logs. Browser-Zurück funktioniert, Lesezeichen auch, das
  Aktivitäts-Widget mit Warteschlange steht auf jeder Seite. Keine
  Overlays mehr: Rausverschieben und Import-Regeln sind Karten mit
  drei Schritten (Ziel → Vorschau → Scharf). Probleme je Fehlerart mit
  ehrlichem Zähler, Sperrliste seitenweise mit Suche über Pfad, Hash
  und Grund. Konfiguration mit Erklärung je Einstellung,
  Badge „sofort" / „Neustart" und Speicherleiste. Das Schnellmenü in
  der Galerie entfällt, der Admin-Knopf ist ein Link, Dunkel/Hell hat
  einen eigenen Knopf in der Topbar.
- **Metadaten besser erkannt**. Bilder aus Gemini, ChatGPT/DALL-E/Sora, Adobe Firefly,
  Google Fotos, Midjourney (V7, Niji 6) und Topaz-Nachbearbeitung
  werden an ihren eingebetteten Herkunftsdaten (C2PA, XMP) erkannt und
  stehen in der neuen Sidebar-Gruppe „Generator"; Topaz zählt als
  Modell. Der ComfyUI-Parser findet Steps, Sampler, CFG und Scheduler
  jetzt auch in modernen Vorlagen mit Subgraphen und getrennten
  Sampler-Knoten (Flux, Wan, LTX); Steps ist der erste Chip im Panel.
  Videos tragen Codec, Profil und Pixelformat als Suchfelder. Nennt
  eine Datei ihren Erzeuger selbst (A1111, ComfyUI), hat das Vorrang.
- **A/B-Vergleich**. Zwei markierte Bilder liegen
  deckungsgleich übereinander, Taste `C` oder Knopf „Vergleichen".
  Wischkante per Maus oder Pfeiltasten, `Tab` tauscht A und B
  (Blinkvergleich), Zoom in echten Pixeln, Bewerten und Ablehnen
  direkt aus der Ansicht.
- **Schneller, stabiler, weniger Hänger**. Langläufer (Scan, Import, Neu
  interpretieren, Thumbnails) laufen in einem eigenen Worker-Prozess
  mit sichtbarer Warteschlange und Fortschritt; die Oberfläche bleibt
  währenddessen flüssig. Galerie-Seiten bei großen Beständen 1,1 s →
  3 ms, Sidebar-Zähler aus einem Aufruf statt drei, Listen erscheinen
  vor den Zahlen, Bestenliste 106 ms → 3 ms. Verlassene Videos geben
  ihre Verbindung frei und der Server erkennt abgebrochene Streams,
  große Dateien blockieren nichts mehr. Nicht abspielbare Videos
  (ProRes, DNxHD, 10-bit) zeigen Poster plus Hinweis statt einer
  schwarzen Bühne. Duelle und Bewertungen gehen nicht mehr verloren.
- **Gespeicherte Suche und Ranking nach einem Muster**. Ein Ranking ist eine benannte Suche, über die Duelle
  laufen: 🏆 legt es aus den aktuellen Chips an, ✎ im Ranking lädt
  seine Population in die Galerie zum Bearbeiten und führt zurück.
  Gespeicherte Suchen: Klick zeigt sie an, nach einer Änderung bietet
  ☆ „»Name« überschreiben" oder „Als neue Suche speichern". Die
  Sidebar markiert, was gerade geladen ist.
- **Rankings: „Beide raus"**. Nimmt beide Items dauerhaft aus
  dem Ranking; in der Bestenliste stehen sie gedimmt am Ende mit
  „Wieder rein".

### Verbesserungen

- Galerie: „Alle Medien" setzt nach oben, alle anderen Suchwechsel
  springen zum ausgewählten Bild zurück. Bei Watchordnern rückt
  ein neues Bild oben ein, ohne dass die Kacheln flackern; Auswahl und
  Scrollposition bleiben am Bild.
- Einzelbild und Vergleich: Zoomstufe „max. 100 %", echte Pixel, aber
  höchstens bildschirmfüllend.
- Im Dateimanager anzeigen: Fundorte in fester Rangfolge
  (Library vor Quelle vor extern), Windows markiert die Datei über die
  Shell-API und holt das Explorer-Fenster nach vorn, Pfade als
  klickbare Breadcrumbs (Ordner öffnen, Datei öffnet ihr Programm),
  keine Minutenhänger mehr bei Dateien über 64 MB.
- Sidebar: Listen erscheinen sofort, Zähler folgen; alle Zähler
  eines Suchzustands aus einem Aufruf statt drei, zweiter Klick auf
  dieselbe Suche gratis. Lange Listen (Generator, Modell, LoRA)
  zeigen Treffer oben, im Kontext Leeres gedimmt darunter.
- Galerie-Seiten bei großen Beständen 1,1 s → 3 ms, Thumbnails
  bleiben beim Scrollen flüssig.
- Admin-Kennzahlen, die die Platte zählen (verwaiste Fundorte,
  Cache-Größe), sind ein gemerkter Stand mit Uhrzeit, der Neustarts
  überlebt, statt 7,6 s je Seitenaufruf.
- Übersicht zeigt Bilder und Videos je mit Anteil und Speicher; die
  Instanz-Kachel nennt die installierten Versionen von Pillow,
  fastapi und uvicorn und warnt bei Abweichung vom Pin.
- Topbar aufgeräumt: Bestandszähler nur noch im Sidebar-Fuß,
  keine ADR-Nummern mehr in sichtbaren Texten.
- Topaz-Nachbearbeitung zählt als Modell (`Topaz Photo AI`,
  `Topaz Gigapixel`, `Topaz Video AI`) mit Rohfeldern für Version,
  Upscale-Faktor und Quellgröße.
- Serverlog: Erstberechnungen nach dem Start stehen als `cold:`,
  vorgeholte Duell-Paarungen als `background:`, nur warme langsame
  Anfragen bleiben Warnungen. Die Schwelle ist eine
  Einstellung, live ohne Neustart.
- Dialoge dürfen übereinander liegen (Ordnerwahl über
  Rausverschieben), Esc schließt von oben nach unten, Eingaben bleiben
  erhalten.
- Videos: Codec, Profil und Pixelformat sind Suchfelder
  (`codec: prores`), Scan und Import melden nicht abspielbare Videos
  als Problem, `python -m feral.diagnose video-codecs` gibt einen
  Überblick über den Bestand ohne Re-Scan.
- Datumsregel als Import-Regel: Dateien ohne
  plausibles Erstelldatum (vor `min_date` oder in der Zukunft) landen
  auf allen Aufnahmewegen in `_ausgefiltert/` statt in
  `_unbekanntes-datum`; der Start-Backfill feuert nur noch, wenn er
  etwas datieren kann.
- Phrasen in Feld-Prädikaten: `prompt: 'new york'` sucht den
  mehrteiligen Teilstring; `"…"` bleibt exakt, nackte Wörter bleiben
  Teilstring.

### Fehlerbehebungen

- Duelle, Bewertungen, Tags und Notizen gingen intermittierend verloren
  („SQLite objects created in a thread …"): Schreibverbindung war an
  einen Thread gebunden.
- Unter Windows hing die Oberfläche 10 bis 30 s, sobald eine Aufgabe
  startete: Sperre wurde über blockierendes IPC gehalten.
- Admin-Dashboard lud bei jedem Poll alle Kennzahlen neu (Poll-Sturm,
  10 % CPU im Leerlauf).
- Beim Start wurde bei jedem Serverstart ein Backfill für nicht
  datierbare Items eingereiht; `min_date` wurde dabei
  ignoriert.
- Lupe legte sich über die offene Einzelansicht.
- Thumbnails blieben leer, wenn vier Anfragen hingen: Zeitlimits für
  alle Leseanfragen; Video-Bühne blieb bei Fehlern schwarz.
- Verworfene `<video>`-Elemente hielten ihre Verbindung offen, bis
  keine mehr frei war (Panel, Lupe, Einzelbild, Ranking).
- Explorer öffnete bei Pfaden mit Leerzeichen ein leeres Fenster oder
  den Dokumente-Ordner.
- Ein-Datei-Scans aus dem Watchordner waren schneller als der
  Status-Poll, die Galerie frischte nicht auf.
- Placeholder im Chip-Editor war am ersten Anführungszeichen
  abgeschnitten.
- Übersicht zeigte eine unbeschriftete GB-Zahl neben „Videos".
- Pillow-Warnung „Corrupt EXIF data" in zwei Tests eingefangen.

### Für Betreiber und Entwickler

- Abhängigkeiten: fastapi 0.141.1, uvicorn 0.52.4, pytest 9.1;
  Pillow bleibt 12.3.0. Vor jedem Export läuft ein Advisory-Check
  gegen OSV, Dependabot liefert Sicherheits-Updates.
- Serverlog, Konsole und `DEPENDENCIES.md` sind immer englisch,
  unabhängig von der Browser-Sprache; Präfixe `slow:` / `cold:` /
  `background:` / `aborted:`.
- Neue Einstellung `[performance] slow_request_ms` (Standard 250,
  0 = nie warnen).
- Versionsanzeige: die Instanz zeigt die Datums-Version des Releases,
  ein Arbeitsstand danach trägt `+dev`.
- Migrationen 0023 (`ranking_scores.eliminated`) und 0024
  (`app_state` für gemerkte Kennzahlen mit Herkunftsstempel).
- Neue CLI: `python -m feral.diagnose video-codecs --db feral.sqlite`.
- Tests: Node-Regressionstests der ES-Module ohne npm,
  Testsuite unter Windows lauffähig, 736 Tests.
- Entfernt: Schnellmenü in der Galerie, Topbar-Bestandszähler,
  Temp-Tabelle `arena_pop`.

## 2026.07.3 (2026-07-19)

- Galerie springt nach einem Suchwechsel zum ausgewählten Bild zurück.
- Erstelldatum mit Uhrzeit; Sortierung „Erstellt" ist innerhalb eines
  Tages stabil.
- „Im Dateimanager anzeigen" prüft den Fundort per Hash vor dem Öffnen
  und normalisiert den Pfad.
- READMEs erklären die ADR-Verweise.

## 2026.07.2 (2026-07-19)

- Beispiel-Config startet im Übersichtsmodus; Testzahlen in der Doku
  korrigiert.

## 2026.07 (2026-07-19)

Erstes öffentliches Release.
