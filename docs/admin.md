# Admin (eigene Seite unter `/admin`)

> Was ist das? Der Verwaltungsbereich der Feral Media Library — eine
> **eigene Seite** unter `/admin` (ADR 0074), erreichbar über den
> Admin-Knopf oben rechts, die Aktivitäts-Anzeige
> oder direkt per Adresse. Der Knopf ist ein echter Link: Mittelklick
> öffnet den Admin in einem zweiten Tab (Import beobachten, dabei
> sichten), Lesezeichen und Browser-Zurück funktionieren. Links eine
> Seitennavigation mit **sieben Seiten**, unten darin das
> **Aktivitäts-Widget** (was gerade läuft, wartet, ob der Arbeitsprozess
> lebt — auf jeder Seite sichtbar, Klick führt zur Übersicht), darunter
> Instanzname, Schema-Version und Port. Auf schmalen Fenstern (unter
> 960 px) wird die Navigation eine Icon-Leiste. „Zurück zur Bibliothek"
> ist ein normaler Seitenwechsel; die Galerie startet danach frisch bzw.
> aus dem Verlaufscache des Browsers.

## Seiten

1. **Übersicht** (`/admin/overview`) — Bestand, laufende Arbeit und
   Systemzustand, in vier festen Reihen:
   - **Bestand:** Kennzahl-Kacheln mit Quoten-Balken (Items mit „+N heute",
     mit konfigurierter Media Library **„Library X GB / katalogisiert gesamt
     Y GB"** — was physisch unter der Bestands-Wurzel liegt vs. alles
     Katalogisierte (ADR 0041, I2) —, mit Metadaten, interpretiert, Thumbnails
     mit Cache-Größe, DB-Größe mit WAL). Daneben drei Felder:
     **Zusammensetzung nach Typ** (Stapelbalken mit Tabellen-Legende;
     darunter Bilder und Videos je mit Anteil an der Stückzahl und
     belegtem Speicher über den ganzen Bestand — die Summe ist „katalogisiert
     gesamt"), **Zuwachs der letzten 30 Tage** (Säulen je Tag,
     heute hervorgehoben) und **Jahrgänge** nach Erstelldatum. Die Zahlen
     kommen aus **derselben Quelle** wie die Galerie-Übersicht (ADR 0029).
   - **Aktivität:** die laufende Aufgabe mit Balken, Dateizähler,
     Durchsatz (Dateien/s) und Restzeit; darunter der **Trichter** „wo
     fällt was ab" (betrachtet → Medien → aufgenommen → mit Metadaten →
     interpretiert, Abfälle dazwischen, Fehlschläge rot — nur bei
     Aufgaben mit Datei-Report: Import, Scan, Re-Scan), **„Neu in diesem
     Lauf"** mit Durchsatz-Kurve der letzten drei Minuten, die
     **Warteschlange** mit Namen und der **Verlauf** der zuletzt erledigten
     Aufgaben mit Dauer (Fehlschläge rot).
   - **System:** sechs Zustandskacheln — Arbeitsprozess (läuft/bereit/
     abgestürzt, Pool-Größe), Werkzeuge (`ffprobe`/`ffmpeg`, mit
     Installationshinweis bei Fehlen), Datenbank (Größe, Schema, WAL),
     **Speicherplatz** des Datenbank-Laufwerks als Ring mit Prozentzahl,
     aktive Parser mit Version, Instanz (Name, Port, Übersichtsmodus/
     Library-Verwaltung, fml-/Python-/SQLite-Version, Laufzeit) — und die
     Pfade von Datenbank, Logs und Media Library. Die fml-Version ist die
     Datums-Version des Releases (`2026.09`); ein Anhang `+dev` heißt
     „Arbeitsstand nach diesem Release", also kein veröffentlichter Stand.
     Daneben stehen die direkten Laufzeit-Pakete **Pillow, fastapi, uvicorn,
     starlette, anyio, pydantic**
     mit ihrer tatsächlich installierten Version. Weicht sie vom Pin in
     `requirements.txt` ab oder fehlt ein Paket, wird der Chip gelb, die
     Kachel bekommt den Warn-Punkt und darunter steht der Befehl zum
     Nachziehen. Wer über `start.sh`/`start.bat` startet, sieht das nie:
     die Skripte installieren geänderte Pins vor dem Start selbst. Der
     Hinweis betrifft nur handgepflegte venvs und Direktstarts mit
     `python -m feral.web`.
   - **Hinweiskarten** mit Absprung: verwaiste Fundorte → Wartung, offene
     Probleme → Probleme, Sperrlisten-Einträge → Probleme, beobachtete
     Quellen → Quellen.
2. **Konfiguration** (`/admin/config`) — die `config.toml` aus der GUI
   bearbeiten (siehe unten): fünf Karten, je Einstellung Label, Eingabe,
   Erklärung darunter und ein Badge **sofort** oder **Neustart**;
   Änderungen sammeln sich in der **Speicherleiste** am unteren Rand.
   Dazu **Sprache** und **Darstellung** (Dunkel/Hell), die sofort und nur
   für diesen Browser gelten.
3. **Quellen & Import** (`/admin/sources`) — oben EIN Aufnahme-Formular
   (einmal jetzt / dauerhaft beobachten), darunter die Watchordner als
   Karten mit Live-Zählern — siehe unten.
4. **Wartung** (`/admin/maintenance`) — vier Karten (Rohdateien,
   Thumbnails, Datenbank, Neubewertung) mit begründender Kennzahl oben und
   je Aktion einer Zeile: Titel, Erklärung, Knopf, **Zustand direkt in der
   Zeile** (läuft mit Balken · in der Warteschlange mit Position · zuletzt
   ✓ Ergebnis mit Uhrzeit). Darunter drei eigene Karten mit derselben
   Logik in drei Schritten und Scharfschalten: **Abgelehnte
   rausverschieben**, **Import-Regeln auf den Bestand** und **Verwaiste
   Fundorte aufräumen** — siehe „Wartungsaktionen".
5. **Probleme** (`/admin/issues`) — je Fehlerart eine Karte mit ehrlichem
   Zähler, den jüngsten Einträgen und „alle N dieser Art quittieren"; der
   Alle-Knopf oben nennt die echte Gesamtzahl. Darunter die **Sperrliste**
   als eigene Karte: getrennt geladen, **seitenweise** (100 je Seite) mit
   **Suche** über Pfad, Hash und Grund — siehe „Probleme und Sperrliste".
6. **Rankings** (`/admin/arenas`) — Tabelle der Rankings (Name,
   Ausdruck, Population, Duelle, Items mit Score, angelegt am) mit
   **Löschen** nach Bestätigungsdialog; darunter „Ranking-Scores neu
   berechnen" — siehe „Rankings".
7. **Logs** (`/admin/logs`) — beide Serverlog-Dateien sofort sichtbar
   (siehe „Aktivität, Warteschlange und Serverlog").

> Im Admin gibt es keine Overlays, nur zwei Dialoge (Ordnerwahl,
> Bestätigung). Übersicht und Wartung laden in zwei Stufen: Kennzahlen und Diagramme
> sofort, der Systemzustand (Werkzeuge, Datenbank, Parser) einen Moment
> später — bis dahin steht dort „…".
>
> **Verwaiste Fundorte und Cache-Größe** werden beim Seitenladen NICHT
> gezählt (bei großen Beständen mehrere Sekunden Plattenarbeit), sondern
> als **gemerkter Stand mit Uhrzeit** gezeigt („Stand 18:23"). Gezählt
> wird auf Klick — **Fundorte prüfen** und **Cache zählen** in der
> Wartung — und nach passenden Aufgaben von selbst im Hintergrund
> (Aufnahme, Re-Scan, Rausverschieben, Aufräumen → Fundorte; Thumbnails
> erstellen, Cache leeren, Import-Regeln → Cache); solange das läuft,
> steht „wird geprüft …", und die Seite holt den neuen Stand von allein.
> Der Stand **überlebt Neustarts** (in der Datenbank gemerkt, ältere
> Stände mit Datum: „Stand 12.09. 18:23"); er gehört zu diesem Rechner und
> Cache-Ordner — eine mitgenommene Datenbank zeigt auf dem anderen Rechner
> wieder „?". „?" heißt: noch nie gezählt.

## Übersichtsmodus und Library-Verwaltung (Standard: Hände weg)

Ab Werk läuft die Feral Media Library (fml) im **Übersichtsmodus**: Sie
katalogisiert und kuratiert nur —
**Dateien werden nie kopiert, verschoben oder gelöscht** (die
Hände-weg-Garantie, ADR 0041). Gesperrt sind alle dateischreibenden Wege:
der kopieren-/verschieben-Import (auch als Watchordner) und „Abgelehnte
rausverschieben". Möglich bleiben `katalogisieren`, Ablehnen und das gesamte
Kuratieren. Ein Badge „👁 Übersichtsmodus" in der Kopfzeile zeigt den Zustand;
gesperrte Stellen erklären das ehrlich („Im Übersichtsmodus deaktiviert —
Library-Verwaltung in der Konfiguration einschalten").

Wer eine Media Library aufbauen will, schaltet in der Konfiguration einmal
bewusst die **Library-Verwaltung** ein (`[library] verwaltung = true` — auch
per Checkbox in Admin → Konfiguration; wirkt sofort, ohne Neustart).
Bestehende Configs mit gesetzter `library.root` oder kopieren/verschieben-
Watchordnern gelten als bewusst eingerichtet: Dort ist der Schalter
automatisch an, solange er nicht ausdrücklich auf `false` steht.

## Ordner aufnehmen — EIN Formular für alles

Die Seite „Quellen & Import" hat **ein** Aufnahme-Formular in der Karte
ganz oben: Pfad (eintippen oder 📁-Ordnerwahl mit Durchklicken und
Dateizahl je Ordner) + **Modus** + **Häufigkeit** (`einmal jetzt` /
`dauerhaft beobachten`). Die drei Modi
(ADR 0031), überall mit derselben Bedeutung:

- **kopieren (Original bleibt)** — Kopie in die Media Library; die Quelle
  wird **nie** angefasst. Sicher für fremde Output-Verzeichnisse.
- **verschieben (Ordner leeren)** — Erfolgsfälle werden nach dem Import aus
  der Quelle gelöscht; Dubletten/Fehler/Unbekanntes bleiben in sichtbaren
  Ausgangs-Ordnern liegen (Nachschau). Immer mit Sicherheitsabfrage.
- **nur katalogisieren (am Ort)** — nimmt die Medien dort auf, wo sie
  liegen; weder kopieren noch bewegen. Braucht keine Media Library —
  die entwicklerfreundliche „nur in die Daten aufnehmen"-Option.

„einmal jetzt" verarbeitet den Ordner sofort einmalig; „dauerhaft
beobachten" macht ihn zum **Watchordner** unter dem Formular.

## Watchordner — der Zweck

Jeder Watchordner (Karten unter dem Formular, ADR 0030) wird laufend
beobachtet; neue Dateien werden nach einer Ruhezeit von selbst in die Media
Library importiert (kopiert in die `JJJJ/MM/TT`-Struktur, mit Dublettencheck
und Hash-Verifikation). Jede Karte zeigt Name, Pfad, Zustand
(beobachtet / aus / nicht gefunden) und zwei **Live-Zähler**: wie viele
Dateien gerade **warten** (in der Ruhezeit) und wie viele seit dem
Serverstart **importiert** wurden; die Zähler laufen mit jedem Status-Poll
mit, ohne Neuladen. An jeder Karte lässt sich der Modus später ändern
(wieder mit Abfrage), **Stoppen/Beobachten** schaltet die Überwachung, per
**✕ Entfernen** nimmst du den Ordner aus der Überwachung (löscht keine
Dateien). Der **Modus** je Ordner:

- **kopieren** — für **stehende Watcher** auf die Output-Ordner diverser
  ComfyUI-/Tool-Installationen: neue Medien werden fortlaufend in die Media
  Library kopiert, die Originale bleiben **unangetastet** am Ort (ADR 0031 —
  es wird nichts einsortiert oder bewegt).
- **verschieben** — als **Archiv-Aufräum-Werkzeug**: kippe hunderte Altordner
  der Reihe nach in den Ordner; erfolgreich Importiertes wird aus der Quelle
  **gelöscht** (der Inhalt ist ja bereits eine Kopie aus Backups), der Ordner
  bleibt leer. Nur Dubletten/Fehler/Unbekanntes/Gesperrtes bleiben liegen.
  Der Wechsel auf „verschieben" verlangt eine ausdrückliche Bestätigung und
  ist nur mit gesetzter Media Library (`[library] root`) aktiv.
  Zusätzlich je Ordner: **„leere Ordner löschen"** (ADR 0033) — nach jedem
  Lauf werden leer gewordene Unterordner der Quelle entfernt (Datumsordner-
  Bäume verschwinden mit ihren Medien). Ordner mit nur Systemdateien
  (.DS_Store, Thumbs.db & Co.) gelten als leer; die Quell-Wurzel und die
  Ausgangs-Ordner (`_importiert` …) bleiben immer stehen. Standard: aus —
  behalten will man Unterordner z. B., wenn ComfyUI fest in bestimmte
  Unterordner rendert.
- **katalogisieren** — nimmt Neues am Ort in die Bibliothek auf, ohne zu
  kopieren oder zu bewegen (In-place-Watcher, ADR 0031).

Änderungen wirken sofort (Config wird geschrieben, Watcher neu aufgesetzt);
beim App-Start werden alle konfigurierten, existierenden Ordner automatisch
überwacht. Feineinstellungen (Ruhezeit/Poll-Intervall je Ordner) stehen als
`[[watch]]`-Einträge in der `config.toml`.

**Neustarts sind billig** (ADR 0042): Jeder Watcher merkt sich Größe +
Änderungszeit der katalogisierten Dateien in der Datenbank und überspringt
beim nächsten Start alles Unveränderte, ohne den Inhalt zu lesen — auch
riesige Watch-Bestände sind nach einem Serverneustart sofort wieder
bedienbar. Nur neue oder geänderte Dateien laufen durch die Pipeline. Wer
dem Stat-Vergleich in einem Zweifelsfall nicht traut: **„Re-Scan aller
Fundorte"** (Wartung) prüft weiterhin jeden Dateiinhalt per Hash. Die
allererste Runde nach dem Update ist einmalig noch langsam (das Gedächtnis
füllt sich beim ersten Durchlauf).

> Es gibt **EIN** Ordner-Konzept, die Watchordner. Frühere Configs mit
> `[hotfolder]` werden beim Start als Watchordner übernommen; „Feste
> Scan-Orte" (`[[scan.locations]]`) gibt es nicht mehr. Das frühere
> „Scannen" ist der Modus „nur katalogisieren" im Aufnahme-Formular.
> Durchnavigiert wird überall im 📁-Ordner-Dialog, der bei den
> Einstiegspunkten Projektordner/Home/Laufwerke startet und die Dateizahl
> je Ordner zeigt.

## Wartungsaktionen (nach Funktionsbereich)

Langläufer laufen über die interne Warteschlange in einem eigenen
Arbeitsprozess (Abschnitt „Aktivität, Warteschlange und Serverlog"). Jede
Aktion ist eine **Zeile** mit Titel, Erklärung, Knopf und ihrem Zustand:
**läuft** (mit Zähler, Dauer und Balken), **in der Warteschlange ·
Position n** oder **zuletzt ✓ Ergebnis · Uhrzeit** aus dem Verlauf der
Engine (nach einem Neustart leer — das Log hat alles). Während eine Aktion
läuft oder wartet, ist ihr Knopf gesperrt. Synchrone Aktionen (Aufräumen,
Cache leeren) schreiben ihr Ergebnis sofort in die Zeile.

Die Kennzahl oben in jeder Karte begründet die Aktionen darunter; die
billigen Zahlen stehen sofort. Verwaiste Fundorte und Cache-Größe sind
ein **gemerkter Stand mit Uhrzeit** (Kasten oben) mit eigenem Knopf im
Meter — **Fundorte prüfen** bzw. **Cache zählen**; „?" heißt noch nie
gezählt, „wird geprüft …" heißt eine Hintergrund-Zählung läuft.

**Rohdateien** — Kennzahl: verwaiste Fundorte (Anteil an allen Fundorten),
gemerkter Stand; **Fundorte prüfen** zählt überall neu.
- **Re-Scan aller Fundorte** — alle bekannten, noch existierenden Fundorte
  erneut einlesen (idempotent). Sinnvoll nach ffmpeg-Installation oder wenn
  Dateien sich geändert haben könnten.
- Aufräumen verwaister Fundorte ist eine eigene Karte (unten).

**Thumbnails** — Kennzahl: Cache-Dateien gegen Items (grob; Fehler-Marker
zählen mit) und Cache-Größe, gemerkter Stand; **Cache zählen** liest den
Cache-Ordner neu.
- **Thumbnails erstellen** — fehlende erzeugen und fehlgeschlagene **erneut
  versuchen** (wichtig nach ffmpeg-Installation); dauerhafte Fehler
  erscheinen mit Grund unter Probleme (Art `thumbnail`). Dieser Knopf ist
  der EINZIGE Weg mit erneutem Versuch: die automatischen Läufe nach
  Import/Watch erzeugen nur Fehlende und lassen quittierte Fehlschläge in
  Ruhe.
- **Cache leeren** — alle Vorschaubilder inkl. Fehler-Marker löschen; sie
  regenerieren sich beim Ansehen.

**Datenbank** — Kennzahl: Dateigröße, WAL, Schema-Version. Der Knopf
**Aufteilung berechnen** zeigt, woraus die Datei besteht (Roh-Blobs,
Items + Fundorte, Schicht 2, Suchindex, Sonstiges, frei) — er liest dafür
die ganze Datei (bei GB-Dateien Sekunden) und läuft deshalb nur auf
Klick. Fehlt dem SQLite-Build die dafür nötige `dbstat`-Tabelle (je nach
Plattform des Python-Builds), gibt es den Knopf gar nicht, nur den
Hinweis „nicht verfügbar".
- **Integritätscheck** — `PRAGMA integrity_check` + WAL eindampfen.
- **VACUUM** — Datenbank kompaktieren (nach großen Lösch-/Umbauaktionen);
  „frei" in der Aufteilung ist, was VACUUM zurückholt.

**Neubewertung** (alles rückwirkend, ohne Datei-Zugriff) — Kennzahl:
interpretierte Items je Parser (mit Parser-Version), dazu Items mit
Roh-Metadaten ohne Interpretation (Vorrat für neue Parser) und Items ohne
Erstelldatum.
- **Neu interpretieren** — Schicht-2-Parser rückwirkend über den ganzen
  Bestand. Nach neuen/verbesserten Parsern. Unveränderte Ergebnisse werden
  übersprungen — ein erneuter Lauf über 70.000 Items dauert deshalb
  Sekunden; die Zusammenfassung nennt interpretierte Items und Felder.
- **Erstelldaten nachtragen** — fehlende Aufnahme-/Erstelldaten
  (`media_date`) aus Metadaten/Datei ergänzen; ergänzt bei Alt-Einträgen
  mit reinem Datum die **Uhrzeit**. Nutzt das konfigurierte `[import]
  min_date`. Items ohne plausibles Datum bleiben ehrlich ohne Datum; die
  Zusammenfassung nennt ihre Zahl. Loswerden: „Import-Regeln auf den
  Bestand", behalten: `min_date` senken.
- **Suchindex neu aufbauen** — den FTS5-Volltextindex komplett neu erzeugen.

### Abgelehnte rausverschieben (eigene Karte)

Der **einzige** Weg neben dem Import, auf dem fml Dateien bewegt (ADR
0041). Drei Schritte nebeneinander:

1. **Zielordner** — eintippen oder per 📁 wählen; muss außerhalb der Media
   Library liegen.
2. **Vorschau** — ehrliche Zahlen vom Server: wie viele abgelehnte Dateien
   (Sperrliste mit gemerkten Pfaden) noch **in der Media Library** liegen,
   wie viele GB, Beispiel-Pfade, nicht mehr auffindbare Pfade. „Vorschau
   aktualisieren" holt sie neu.
3. **Ausführen** — erst das Häkchen „Scharf: Ziel und Vorschau geprüft"
   (nur wählbar mit Ziel und Treffern), dann der rote Knopf „N Dateien
   verschieben". Die Aufgabe läuft im Worker; ihr Fortschritt erscheint in
   einem Laufkasten unter den Schritten, im Widget links und in der
   Übersicht.

Die Dateien wandern in eine Datumsstruktur `JJJJ/MM/TT/` unter dem Ziel
(Kollisionen bekommen `__2`-Suffixe, wie beim Import). Vor jedem Anfassen
wird der **Hash verifiziert** — fehlt die Datei oder wurde sie ersetzt,
wird das nur gemeldet. Jede Datei steht im Import-Log; die Sperrliste
merkt sich den neuen Ort. Externe (nur am Ort katalogisierte) Fundorte sind nie
Kandidaten. Im Übersichtsmodus ist die Karte gesperrt.

### Import-Regeln auf den Bestand (eigene Karte)

Wendet die konfigurierten Import-Regeln (Mindest-/Maximalkante,
ausgeschlossene Formate, Erstelldatum ab `min_date` — siehe
[Import-Doku](import.md), ADR 0046 und ADR 0075) rückwirkend auf den
Katalog an, in drei Schritten:

1. **Regeln** — die aktiven Regeln aus der Konfiguration, mit Absprung
   dorthin.
2. **Vorschau** — wie viele Items träfen die Regeln, aufgeschlüsselt nach
   Grund (zu klein, zu groß, Format, ohne Datum). Beim Öffnen der Seite
   bereits berechnet; „Bestand prüfen" rechnet neu **und schaltet erst
   das Häkchen frei**.
3. **Ablehnen** — Häkchen „Scharf: Vorschau geprüft", dann „N Treffer
   ablehnen". Ablehnen markiert nur (Sperrliste, umkehrbar); Dateien
   bleiben liegen und werden erst über „Abgelehnte rausverschieben"
   bewegt.

Alt-Bestände, deren RAW-Dateien (ARW/NEF/DNG/CR2) noch als TIFF
katalogisiert sind, werden beim Format-Ausschluss trotzdem getroffen
(Dateiendungs-Match). Gängige Schreibweisen wie `tif` oder `jpg` werden
auf die internen Namen (`tiff`, `jpeg`) abgebildet.

### Verwaiste Fundorte aufräumen (eigene Karte)

Entfernt Pfad-Einträge, deren Datei nicht mehr existiert. **Items und
Metadaten bleiben**, Mediendateien werden nie angefasst — nur die
Pfad-Buchhaltung geht. Dieselben drei Schritte wie bei den beiden Karten
darüber:

1. **Bereich** — „überall" oder „nur unter Ordner" (Pfad eintippen oder
   per 📁 wählen; ADR 0033). Vorsicht mit „überall", wenn gerade eine
   externe Platte oder ein NAS ausgehängt ist — deren Fundorte sähen wie
   verwaist aus; dann lieber pfad-bezogen.
2. **Vorschau** — „Fundorte prüfen" zählt im gewählten Bereich (prüft jede
   Fundort-Datei, bei großen Beständen Sekunden) und zeigt Beispielpfade.
   Läuft nur auf Klick, nie beim Seitenladen; „überall" ist zugleich der
   neue gemerkte Stand der Rohdateien-Karte. Jede Änderung am Bereich
   entwertet die Vorschau.
3. **Aufräumen** — Häkchen „Scharf: Bereich und Vorschau geprüft", dann
   „N Fundorte aufräumen"; das Ergebnis steht in der Karte, die Kennzahl
   der Rohdateien-Karte wird nachgezogen.

## Probleme und Sperrliste

Oben die Zusammenfassung („N offene Probleme in K Arten") mit dem
Alle-Knopf, der die **echte Gesamtzahl** nennt (ADR 0034). Darunter **je
Fehlerart eine Karte**: Zähler, die jüngsten 20 Einträge („jüngste 20 von
2013"), je Eintrag „quittieren", unten „alle N dieser Art quittieren".
Quittieren meldet die Zahl der quittierten Einträge und lädt die Karten
neu. Arten: `failed` (nicht aufgenommen), `warning` (Extraktor-Warnung),
`thumbnail` (kein Vorschaubild) und `playback` (Video, das kein bzw. nur
mancher Browser abspielt — ProRes, 10-bit-H.264, HEVC; siehe
[interpretation.md](interpretation.md#video-codec-und-abspielbarkeit)).

Die **Sperrliste** (abgelehnte Medien, ADR 0041) ist eine eigene Karte und
wird **getrennt** von den Problemen geladen — bei nur katalogisierten
Laufwerken sind es tausende Einträge:

- **Seitenweise**, 100 je Seite, mit „Zurück/Weiter" und Bereich
  („101–200"); der Zähler kommt vom Server und ist nie gedeckelt.
- **Suche** über gemerkten Pfad, Hash und Grund (Tippen sucht nach kurzer
  Pause, Enter sofort); Treffer stehen als „n Treffer von gesamt".
- **Entsperren** je Eintrag erlaubt den Re-Import; „Alle N entsperren …"
  fragt vorher nach. Abgelehnte Dateien liegen unverändert an ihrem
  gemerkten Fundort — Ablehnen hat sie nie angefasst.

## Rankings

Tabelle aller Rankings des Ranking-Moduls (ADR 0045): Name, Ausdruck
(leer = alle Medien), Population (Items, die der Ausdruck trifft), Duelle,
Items mit Score, angelegt am. **Löschen** lebt hier und fragt in einem
Bestätigungsdialog nach — es entfernt das Ranking mit allen Duellen und
Scores, unwiederbringlich. Darunter **Ranking-Scores neu berechnen**
(Elo-Replay über das Duell-Log aller Rankings, Rescan-Prinzip) mit
Inline-Ergebnis. Angelegt wird ein Ranking nur in der Galerie (🏆 in der
Chip-Leiste, die Population entsteht aus den Chips, siehe
[Rankings](rankings.md)). **Bearbeiten** je Zeile springt in die Galerie
in den Bearbeiten-Modus dieses Rankings, derselbe Weg wie ✎ im Ranking.

## Aktivität, Warteschlange und Serverlog

Lange Aufgaben (Import, Scan, Re-Scan, Neu interpretieren, Suchindex,
Erstelldaten, Thumbnails, VACUUM …) laufen **in einem eigenen
Arbeitsprozess** neben dem Webserver. Die Oberfläche bleibt dabei
bedienbar: Blättern, Suchen, Bewerten, Tags und Notizen gehen sofort, auch
während ein 70.000er-Lauf rechnet. Nur wenn die Datenbank kurz exklusiv
gesperrt ist (VACUUM, Integritätscheck), kommt bei einem Schreibgriff die
Meldung „gerade beschäftigt" — kurz warten, erneut versuchen.

- **Aktivität** (Übersicht, zweite Reihe): laufende Aufgabe mit
  Fortschritt (`Interpretieren 12.400/70.000`), Dauer, Durchsatz und
  Trichter; darunter die **Warteschlange** mit den Namen aller wartenden
  Aufgaben und der **Verlauf** der zuletzt erledigten (Dauer, Ergebnis;
  nur im Speicher — nach einem Neustart beginnt er leer, das Log hat
  alles). Das Widget unten in der Navigation und der Punkt in der
  Kopfzeile der Galerie zeigen dasselbe in Kurzform (`+2` = zwei
  wartende).
- **Mehrfachklick** stapelt nichts: eine Aufgabe, die schon läuft oder
  wartet, wird nicht erneut eingereiht (Hinweis „läuft bereits").
  Automatische Nachläufer (Thumbnails nach einem Import) dürfen einmal
  hinter einen laufenden Lauf.
- **Arbeitsprozess abgestürzt** (rot markiert): die laufende Aufgabe wird als
  abgebrochen gemeldet, wartende bleiben erhalten, der nächste Auftrag
  startet den Prozess neu. Was passiert ist, steht im Serverlog.
- **Serverlog**: Ordner `logs/` neben der Datenbank, zwei rotierende
  Dateien (`fml-web.log` für den Webserver, `fml-worker.log` für die
  Aufgaben; je höchstens 5 × 5 MB). Jede Aufgabe steht mit Start,
  Fortschritt, Dauer, Ergebnis und Fehlern (mit Traceback) darin. Die
  Seite **Logs** zeigt beide Dateien sofort nebeneinander (auf schmalen
  Fenstern untereinander), je Datei mit Größe, Zeilenzahl 100/500/2000,
  **Auffrischen** und dem Schalter **„nur WARNING und höher"** (der Filter
  läuft auf dem Server, Traceback-Zeilen bleiben bei ihrer Meldung);
  WARNING-Zeilen sind gelb, ERROR rot, die neueste Zeile steht unten. Oben
  auf der Seite: **Zeilenumbruch** (Standard an) und **untereinander**
  statt nebeneinander — beides merkt sich der Browser. Nach
  jeder fertigen Aufgabe frischen beide Fenster von selbst auf — der erste
  Blick bei „hängt das?". **Das Log ist immer englisch**, unabhängig von
  der Sprache der Oberfläche: Es ist das, was fremde Nutzer in Bug-Reports
  einfügen. Aufgaben stehen darin unter ihrem Schlüssel (`taskScan`,
  `sumReparse` …), nicht unter dem übersetzten Namen. Anfragen, die länger
  als eine Viertelsekunde brauchen, stehen als `slow:` mit Endpunkt, Dauer,
  Bytes und der Zahl gleichzeitig laufender Anfragen (`concurrent`) darin. **Startabfragen
  sind absichtlich toleranter geloggt:** Kennzahlen, gespeicherte Suchen,
  Rankings und Modell-Liste werden nach dem Serverstart (und nach jedem
  Import) einmal frisch berechnet — das dauert bei großen Beständen
  einige Sekunden und ist kein Fehler. Solche Zeilen stehen als `cold:`
  mit dem Grund (`first computation since server start`, `recomputed after
  a write`) im Log; danach kommen die Zahlen aus dem Speicher, bis
  sich am Bestand etwas ändert. Dasselbe gilt für die Sidebar-Zähler
  einer Suche: der erste Klick auf eine gespeicherte Suche rechnet
  (`cold:`), jeder weitere kommt aus dem Speicher. Ebenso tolerant: Paare des Duells,
  die das Frontend im Hintergrund vorholt, während das aktuelle Duell
  läuft — bei Rankings mit vielen Filterkriterien kostet jede Paarung einen
  Filterlauf, auf den niemand wartet. Solche Zeilen stehen als
  `background:` im Log; nur ein sichtbares Laden bleibt eine
  `slow:`-Warnung. Bricht der
  Browser einen Medien-Stream ab (Video gewechselt, Ansicht geschlossen),
  hört der Server sofort auf zu lesen und schreibt `aborted: …
  (client gone)`; die Zahl `concurrent` zählt also nur lebende Anfragen.

## Erststart (frische Installation)

Ohne `config.toml` zeigt der Ordner-Browser als ersten Einstiegspunkt den
**Projekt-/Arbeitsordner** (statt ins Leere) — von dort lässt sich durchklicken.
Es werden **keine** Medienordner automatisch angelegt. Für den echten Betrieb in
der Konfiguration eine Media Library und Quellen setzen.

## Konfiguration bearbeiten

Fünf Karten: **Media Library** (Import-Ziel, **Library-Verwaltung** als
Übersichtsmodus-Schalter, ältestes plausibles Datum, Import-Regeln),
**Thumbnails & Leistung** (Größe, Prozesse, volle Leistung,
Langsam-Schwelle), **Oberfläche**, **Instanz** und **Module**. Jede
Einstellung hat ein Label, die Eingabe, eine kurze Erklärung darunter und
ein Badge: **sofort** wirkt beim Speichern, **Neustart** erst nach einem
Neustart des Servers. Änderungen sammeln sich in der **Speicherleiste**
am unteren Rand, die nur erscheint, solange etwas ungespeichert ist
(„N Änderungen · Speichern · Verwerfen"); **Verwerfen** stellt den
gespeicherten Stand wieder her, Fehler vom Server stehen direkt in der
Leiste. **Sprache** und **Darstellung** (Dunkel/Hell) in der Karte
„Oberfläche" sind Sache des Browsers (ADR 0054): sie wirken sofort, ohne
Speichern, gelten nur für diesen Browser, nicht für die Instanz, und
zählen deshalb nie als Änderung in der Leiste.

**Langsam-Schwelle** (Karte „Thumbnails & Leistung", `[performance]
slow_request_ms`, ADR 0076): Ab dieser Antwortzeit meldet fml eine
Anfrage als `slow:` (Warnung im Log und in der Konsole). Der Standard
250 ms passt zu einem Desktop mit NVMe; die Auswahl empfiehlt Profile
(Laptop mit SATA-SSD 600 ms, Chromebook/USB-Platte/NAS 1 500 ms) oder
einen eigenen Wert. **Nie warnen** (0) lässt langsame Anfragen ab 250 ms
nur noch als Info in der Logdatei stehen. Kaltstart-Läufe (`cold:`) und
vorgeholte Anfragen bleiben immer Info. Wirkt sofort, ohne Neustart. (Watchordner werden
**nicht** hier gepflegt, sondern direkt in „Quellen & Import" — sie landen als
`[[watch]]`-Einträge in derselben Datei. Ordner-Listen gibt es in der
Konfiguration bewusst keine mehr.)

**Instanz** (praktisch, wenn mehrere fml-Instanzen parallel laufen — je
Instanz eigene Config-Datei und eigene Datenbank; Anleitung und
Subgalerie-Anwendungsfall: [instanzen.md](instanzen.md)): ein **Name** erscheint
als Badge in der Topbar und im Tab-Titel, eine eigene **Akzentfarbe** färbt
die Oberfläche und setzt einen Farbpunkt ins Favicon — so sind zwei Tabs auf
einen Blick unterscheidbar. Der **Port** legt fest, wo diese Instanz läuft
(leer = 8765); beim Start gewinnt `--port` vor `$PORT` vor der Config.
`start.bat` öffnet den Browser automatisch auf dem tatsächlich verwendeten
Port, sobald der Server erreichbar ist.

- Media Library, Library-Verwaltung, Import-Regeln, Langsam-Schwelle,
  Instanzname, Akzentfarbe und Modul-Schalter wirken **sofort** (Badge).
- Port, Thumbnail-Größe, Prozesse und DB-Pfad wirken **nach Neustart**
  des Servers.
- **Achtung:** Kommentare in einer von Hand gepflegten `config.toml` überleben
  das Speichern aus der GUI nicht. Vorher wird automatisch ein Backup
  `config.toml.bak` angelegt; die kommentierte Referenz ist
  [`config.example.toml`](../config.example.toml).
