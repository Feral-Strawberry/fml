# Admin-Dashboard (in der Web-GUI)

> Was ist das? Ein **einziges Dashboard** (Knopf oben rechts → Schnellmenü →
> Admin-Dashboard) mit allem, was zur Verwaltung nötig ist — ohne Terminal und
> ohne Seitenwechsel. Die Regionen liegen als Kacheln in einem Raster über die
> volle Bildschirmbreite: oben der Überblick-Streifen (Kennzahlen **und**
> Aktivität), darunter drei Spalten (Quellen & Import | Wartung, Probleme |
> Konfiguration). Auf schmalen Fenstern stapeln die Kacheln; die Kopfzeile
> „Springe zu …“ scrollt dann zur gewünschten Region (ADR 0029, 0034).

## Regionen

1. **Überblick** — zweigeteilt (ADR 0034): links die Kennzahlen des Bestands
   (Items gesamt, mit konfigurierter Media Library dazu **„Library X GB /
   indiziert gesamt Y GB"** — was physisch unter der Bestands-Wurzel liegt
   vs. alles Indizierte (ADR 0041, I2) —, wie viele Metadaten tragen, wie
   viele interpretiert sind,
   Thumbnail-Cache, DB-Größe (+WAL), verwaiste Fundorte, offene Probleme;
   dazu `ffprobe`/`ffmpeg`-Status und die aktiven Schicht-2-Parser), rechts
   die **Aktivität**: der Live-Fortschritt der laufenden Aufgabe
   (Import/Scan/VACUUM …) mit Zählern in derselben Optik. Die Zahlen kommen
   aus **derselben Quelle** wie die Galerie-Übersicht (ADR 0029).
2. **Quellen & Import** — die Watchordner, EIN Import-Formular (einmal
   jetzt / dauerhaft beobachten) und „Katalogisieren ohne Kopieren"
   (Scannen am Ort) — siehe unten.
3. **Wartung** — kleine Knöpfe, nach Funktionsbereich gruppiert (siehe unten).
4. **Probleme** — eine einzeilige Zusammenfassung („⚠ N offene Probleme ·
   M Sperrlisten-Einträge"). **Ansehen & aufräumen …** öffnet ein Overlay,
   **nach Fehlerart gruppiert** mit ehrlichen Zählern: je Art die jüngsten
   Einträge + „alle N dieser Art quittieren"; der Alle-Knopf nennt die echte
   Gesamtzahl („Alle 2013 quittieren") — auch tausende Fehler (Laufwerks-
   Scan) bleiben so bedienbar (ADR 0034, Block N). Darunter die Sperrliste:
   abgelehnte Medien (ADR 0041) mit gemerktem Fundort, entsperren erlaubt
   den Re-Import — die Datei selbst wurde beim Ablehnen nie angefasst.
5. **Konfiguration** — die `config.toml` aus der GUI bearbeiten.

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

Die Region „Quellen & Import" hat **ein** Aufnahme-Formular: Pfad (eintippen
oder 📁-Ordnerwahl mit Durchklicken und Dateizahl je Ordner) + **Modus** +
**Häufigkeit** (`einmal jetzt` / `dauerhaft beobachten`). Die drei Modi
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
beobachten" macht ihn zum **Watchordner** in der Liste darüber.

## Watchordner — der Zweck

Jeder Watchordner (Liste oben in der Region, ADR 0030) wird laufend
beobachtet; neue Dateien werden nach einer Ruhezeit von selbst in die Media
Library importiert (kopiert in die `JJJJ/MM/TT`-Struktur, mit Dublettencheck
und Hash-Verifikation). An jeder Karte lässt sich der Modus später ändern
(wieder mit Abfrage), per ✕ nimmst du den Ordner aus der Überwachung (löscht
keine Dateien). Der **Modus** je Ordner:

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

> Löst die alten Doppelungen auf: früher gab es einen einzelnen Hotfolder
> **und** einen getrennten In-place-Watcher (ADR 0030 revidiert ADR 0025) —
> und in der Oberfläche standen „Überwachte Quellen" und „Feste Scan-Orte"
> als konkurrierende Ordner-Listen nebeneinander (Feral Strawberry, 2026-07-09:
> „versteht kein Mensch"). Jetzt: **EIN** Ordner-Konzept, die Watchordner.
> Die früheren „Festen Scan-Orte" (`[[scan.locations]]`) sind ersatzlos
> gestrichen; durchnavigiert wird überall im 📁-Ordner-Dialog, der immer bei
> den neutralen Einstiegspunkten Projektordner/Home/Laufwerke startet und die
> Dateizahl je Ordner zeigt. Das frühere „Scannen" ist der Modus
> „nur katalogisieren" im Aufnahme-Formular.

## Wartungsaktionen (nach Funktionsbereich)

Alle Aktionen laufen über die interne Warteschlange (immer nur ein Schreiber);
Fortschritt und Ergebnis erscheinen unter **Aktivität**.

**Rohdateien**
- **Re-Scan aller Fundorte** — alle bekannten, noch existierenden Fundorte erneut
  einlesen (idempotent). Sinnvoll nach ffmpeg-Installation oder wenn Dateien sich
  geändert haben könnten.
- **Verwaiste Fundorte aufräumen** — Pfad-Einträge entfernen, deren Datei nicht
  mehr existiert. **Items und Metadaten bleiben**, Mediendateien werden nie
  angefasst. Der Knopf fragt zuerst **wo**: „überall" oder „nur unter
  Ordner …" (ADR 0033). Vorsicht mit „überall", wenn gerade eine externe
  Platte/ein NAS ausgehängt ist — deren Fundorte sähen wie verwaist aus.
  (Seit ADR 0033 selten nötig: Verschiebe-Importe räumen die Fundort-Zeile
  einer bewegten Quelle automatisch mit ab.)
- **Abgelehnte rausverschieben …** — der **einzige** Weg neben dem Import,
  auf dem fml Dateien bewegt (ADR 0041). Öffnet einen Dialog mit ehrlichen
  Zahlen: wie viele abgelehnte Dateien (Sperrliste mit gemerkten Pfaden)
  noch **in der Media Library** liegen, wie viele GB, plus Beispiel-Pfade.
  Zielordner wählen (muss außerhalb der Library liegen) → zweistufig
  bestätigen → die Dateien wandern in eine Datumsstruktur `JJJJ/MM/TT/`
  unter dem Ziel (Kollisionen bekommen `__2`-Suffixe, wie beim Import).
  Sicherheiten: Vor jedem Anfassen wird der **Hash verifiziert** — fehlt
  die Datei oder wurde sie von Hand ersetzt, wird das nur gemeldet und
  nichts angefasst. Jede Datei (auch übersprungene) steht im Import-Log;
  die Sperrliste merkt sich den neuen Ort. Externe (nur indizierte)
  Fundorte sind nie Kandidaten. Danach entscheidet der Dateimanager —
  endgültiges Löschen passiert bewusst außerhalb von fml.
- **Import-Regeln auf den Bestand** — wendet die konfigurierten
  Import-Regeln (Mindest-/Maximalgröße, ausgeschlossene Formate — siehe
  [Import-Doku](import.md) und ADR 0046) rückwirkend auf den Katalog an:
  erst eine ehrliche Vorschau (wie viele Items, aufgeschlüsselt nach
  Grund), dann nach Klick auf „jetzt ablehnen" das Sammel-Ablehnen über
  die Sperrliste. Dateien bleiben unangetastet; Entsperren macht einzelne
  Items wieder importierbar. Alt-Bestände, deren RAW-Dateien (ARW/NEF/
  DNG/CR2) noch als TIFF katalogisiert sind, werden beim Format-Ausschluss
  trotzdem getroffen (Dateiendungs-Match) — ein Re-Scan ist dafür nicht
  nötig, korrigiert die Container-Label aber dauerhaft. Gängige
  Schreibweisen wie `tif` oder `jpg` werden auf die internen Namen
  (`tiff`, `jpeg`) abgebildet.

**Thumbnails**
- **Thumbnails erstellen** — fehlende erzeugen und fehlgeschlagene **erneut
  versuchen** (wichtig nach ffmpeg-Installation); dauerhafte Fehler erscheinen
  mit Grund unter Probleme (kind `thumbnail`). Dieser Knopf ist der EINZIGE
  Weg mit erneutem Versuch: Die automatischen Läufe nach Import/Watch
  erzeugen nur Fehlende und lassen bekannte Fehlschläge samt quittierter
  Probleme in Ruhe — quittiert bleibt quittiert, auch über Neustarts und
  Config-Speichern hinweg.
- **Cache leeren** — alle Vorschaubilder inkl. Fehler-Marker löschen; sie
  regenerieren sich beim Ansehen.

**Datenbank**
- **Integritätscheck** — `PRAGMA integrity_check` + WAL eindampfen.
- **VACUUM** — Datenbank kompaktieren (nach großen Lösch-/Umbauaktionen).

**Neubewertung vorhandener Daten** (alles rückwirkend, ohne Datei-Zugriff)
- **Neu interpretieren** — Schicht-2-Parser rückwirkend über den ganzen Bestand.
  Nach neuen/verbesserten Parsern.
- **Erstelldaten nachtragen** — fehlende Aufnahme-/Erstelldaten (`media_date`)
  aus Metadaten/Datei ergänzen; ergänzt außerdem bei Alt-Einträgen mit
  reinem Datum die **Uhrzeit** (aus Metadaten immer, aus dem Datei-Stempel
  nur, wenn er noch denselben Tag nennt). Läuft bei Bedarf auch beim
  Start automatisch.
- **Suchindex neu aufbauen** — den FTS5-Volltextindex komplett neu erzeugen.

## Erststart (frische Installation)

Ohne `config.toml` zeigt der Ordner-Browser als ersten Einstiegspunkt den
**Projekt-/Arbeitsordner** (statt ins Leere) — von dort lässt sich durchklicken.
Es werden **keine** Medienordner automatisch angelegt. Für den echten Betrieb in
der Konfiguration eine Media Library und Quellen setzen.

## Konfiguration bearbeiten

Media Library (Import-Ziel), **Library-Verwaltung** (der Übersichtsmodus-
Schalter, siehe oben), ältestes plausibles Datum, Thumbnail-Größe/
-Prozesse, Oberflächen-Optionen und die **Instanz** lassen sich direkt
bearbeiten; **Speichern** schreibt die `config.toml`. (Watchordner werden
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

- Media Library, Library-Verwaltung, Instanzname und Akzentfarbe wirken **sofort**.
- Port, Thumbnail-Größe und DB-Pfad wirken **nach Neustart** des Servers.
- **Achtung:** Kommentare in einer von Hand gepflegten `config.toml` überleben
  das Speichern aus der GUI nicht. Vorher wird automatisch ein Backup
  `config.toml.bak` angelegt; die kommentierte Referenz ist
  [`config.example.toml`](../config.example.toml).
