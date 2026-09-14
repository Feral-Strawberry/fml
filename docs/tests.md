# Die Testsuite — was sie prüft und woran man erkennt, dass alles gut ist

> Was ist das? Das Projekt bringt eine automatische Testsuite mit: rund **480
> kleine Prüfprogramme**, die in wenigen Sekunden durchlaufen und jede zentrale
> Zusage der Software kontrollieren. Vor jeder Codeänderung, die eingecheckt
> wird, läuft die komplette Suite. Diese Seite erklärt, **wie man sie startet**,
> **was ein korrektes Ergebnis ist** und **was die einzelnen Testgruppen
> eigentlich absichern** — so, dass man es auch ohne Programmierhintergrund
> nachvollziehen kann.

## Tests starten

Einmalig die Entwicklungs-Abhängigkeiten installieren (im Projektordner):

```
pip install -r requirements-dev.txt
```

Dann:

```
pytest -q
```

## Woran erkenne ich das richtige Ergebnis?

Am Ende steht eine Zeile wie:

```
736 passed, 2 skipped in 9.8s
```

- **passed** = bestanden. Die genaue Zahl wächst mit dem Projekt; wichtig ist:
  **0 failed, 0 errors**.
- **skipped** ist in Ordnung: zwei Tests brauchen die Videowerkzeuge
  `ffmpeg`/`ffprobe` und überspringen sich selbst, wenn diese auf dem Rechner
  nicht installiert sind. Die App funktioniert dann trotzdem, nur ohne
  Video-Metadaten und Video-Vorschaubilder. Genauso überspringen sich die
  Oberflächen-Tests (Gruppe 9), wenn kein **Node.js** auf dem Rechner ist,
  und unter **Windows** ein Scan-Test, der einen Symlink braucht (das
  erlaubt Windows nur mit Adminrechten oder Entwicklermodus).
- Ein **failed** heißt fast nie „der Test ist kaputt", sondern: eine Änderung
  hat eine der unten beschriebenen Zusagen gebrochen. Genau dafür existiert der
  Test — er hat sozusagen Alarm geschlagen, bevor der Fehler bei echten Daten
  auffällt.

Ein wichtiges Prinzip: Die Tests arbeiten **nie mit deinen echten Daten**. Jeder
Test baut sich seine Eingaben selbst (zum Beispiel ein PNG Byte für Byte) und
räumt hinterher auf. Man kann die Suite also jederzeit gefahrlos laufen lassen.

## Die Testgruppen im Überblick

Die Suite ist entlang der Architektur geschnitten: jede Schicht der Software
hat ihre eigenen Tests. Wer die Schichten kennt (siehe
[extraction.md](extraction.md) und [interpretation.md](interpretation.md)),
findet sich hier sofort zurecht.

### 1. Fundament: Hashing, Datentypen, Formaterkennung

| Testdatei | Prüft |
|---|---|
| `test_hashing.py` | Der SHA-256-Fingerabdruck einer Datei ist korrekt und immer gleich — egal ob am Stück, häppchenweise oder direkt aus der Datei berechnet. |
| `test_types.py` | Ein Roh-Metadaten-Eintrag trägt **genau eines**: Text oder Binärdaten. Nie beides, nie keins. |
| `test_container.py` | Die Formaterkennung (an den ersten Bytes einer Datei) ordnet PNG, JPEG, WEBM usw. dem richtigen Lesemodul zu und meldet Unbekanntes sauber, statt zu raten. |
| `test_config.py` | Die Konfigurationsdatei wird korrekt gelesen und geschrieben; beim Speichern aus der GUI geht keine handgeschriebene Einstellung verloren; alte Konfigurationen (früheres `[hotfolder]`-Format) werden automatisch ins neue Watch-Quellen-Format überführt. |

**Warum das wichtig ist:** Der Hash ist die Identität jedes Mediums in der
Bibliothek. Dublettenerkennung, Import und später der Abgleich zwischen
Rechnern hängen daran. Wäre er falsch, wäre alles darüber falsch.

### 2. Schicht 1 — Roh-Metadaten aus Dateien lesen

| Testdatei | Prüft |
|---|---|
| `test_png_extractor.py` | Der selbst gebaute PNG-Leser findet alle Text-Bausteine (dort stecken A1111-Parameter und ComfyUI-Workflows), entpackt komprimierte Teile und behält die Reihenfolge bei. |
| `test_image_pillow.py` | JPEG/WEBP/GIF & Co.: eingebettete EXIF/XMP-Daten und Kommentare kommen unverändert heraus; C2PA-Manifeste (JPEG-APP11 über mehrere Segmente, WebP-RIFF-Chunk) werden byte-treu zusammengesetzt. |
| `test_video_ffprobe.py` | Video-Container (WEBM, MP4, …): die von `ffprobe` gelieferten Metadaten werden korrekt übernommen; fehlt `ffprobe`, gibt es eine Warnung statt eines Absturzes. |

**Die eigentliche Pointe dieser Gruppe:** Mehr als die Hälfte dieser Tests
füttert die Leser absichtlich mit **kaputten Dateien** — abgeschnitten,
Prüfsummenfehler, zerstörte Zeichen, fehlendes Dateiende. Das korrekte
Verhalten ist immer: **nicht abstürzen**, sondern retten, was lesbar ist, und
das Problem als Warnung vermerken. Bei einem Bestand von 250.000 über Jahre
gewachsenen Dateien ist die beschädigte Datei der Normalfall, nicht die
Ausnahme — und eine einzige dürfte niemals einen kompletten Scan abbrechen.

### 3. Schicht 2 — Metadaten verstehen (der größte Block)

| Testdatei | Prüft |
|---|---|
| `test_interpret.py` (48 Tests) | Die Parser machen aus Roh-Metadaten durchsuchbare Felder: Prompt, Modell, LoRAs, Seed, … — für A1111/Forge-Texte und für ComfyUI-Workflow-Graphen in all ihren Bauformen. |
| `test_interpret_xmp.py` | XMP-Daten: Midjourney-Beschreibungen, Google-AI-Kennzeichnung, Lightroom-Sternebewertungen. |
| `test_interpret_provenance.py` | Generator aus Content Credentials: Gemini, ChatGPT, OpenAI-API, Azure, Firefly, Photoshop, Sora, Bing werden an ihren belegten Kennzeichen erkannt, Prioritäten stimmen (Azure vor OpenAI, ChatGPT vor Sora), Rohstrings kommen exakt heraus, unbekannte Manifeste heißen ehrlich `c2pa`. |
| `test_reparse.py` | Das rückwirkende Neu-Interpretieren des ganzen Bestands: findet bisher Unverstandenes, ändert bei Wiederholung nichts doppelt und ersetzt veraltete Ergebnisse, wenn ein Parser verbessert wurde. |

**Warum so viele Tests?** Fast jeder einzelne Test hier ist ein **konservierter
Realfall**: eine Workflow-Bauform, die irgendwann in echten Dateien auftauchte
und erst nicht verstanden wurde (verschachtelte Knoten, LoRA-Lader in fünf
Varianten, zusammengesetzte Text-Ketten, Graphen unter falschem Namen, …).
Wird ein Parser weiterentwickelt, garantieren diese Tests, dass **kein früher
gelöster Fall wieder kaputtgeht**. So blieb messbar: von 1320 Medien ohne
erkannten Prompt blieben nach den Parser-Ausbauten noch 23 übrig — und das
bleibt auch so.

Zwei Spezialfälle verdienen Erwähnung: Ein Test prüft, dass ein Workflow-Graph
mit **Ringverweisen die Software nicht einfrieren** kann (Endlosschleifen-
Schutz), und mehrere prüfen, dass Parser bei fremden Daten „nicht zuständig"
melden, statt Unsinn zu erfinden.

### 4. Datenbank und Schema-Fortschreibung

| Testdatei | Prüft |
|---|---|
| `test_db.py` | Gespeichert wird byte-genau (auch Sonderzeichen); ein erneuter Scan derselben Datei erzeugt **keine Duplikate**; dieselbe Datei an einem zweiten Ort wird als zweiter **Fundort** desselben Mediums erfasst, nicht als neues Medium. |
| `test_migrations.py` | Die Datenbank-Schemaänderungen (nummerierte Migrationsdateien) sind lückenlos; eine frische und eine über Monate mitgewachsene Datenbank landen garantiert beim **identischen** Stand; auch zwei gleichzeitig startende Programme migrieren genau einmal. |

**Warum das wichtig ist:** Die Migrations-Tests sind die Versicherung dafür,
dass ein Update der Software eine bestehende Bibliothek **nie** beschädigt —
egal, auf welchem alten Stand sie war.

### 5. Die Pipelines: Scannen und Importieren

| Testdatei | Prüft |
|---|---|
| `test_scan.py` | Der komplette Ablauf erkennen → hashen → auslesen → interpretieren → speichern liefert die richtigen Zählungen; eine unlesbare Datei wird als „Scan-Problem" vermerkt statt den Lauf abzubrechen. |
| `test_importer.py` (27 Tests) | Der Import-Workflow mit allen Sicherheitsgarantien (siehe [import.md](import.md)). |

Die Import-Tests sind die wohl wichtigsten der ganzen Suite, denn hier geht es
um **„niemals Daten verlieren"**. Jeder Test ist eine Garantie in Prosa:

- Dateien werden **kopiert, nie verschoben**, und die Kopie wird per Hash gegen
  das Original verifiziert; schlägt das fehl, landet die Datei sichtbar im
  Fehler-Ausgang.
- Eine **Dublette** (schon vorhandenes Medium) wird nicht erneut kopiert — aber
  nur, wenn die vorhandene Kopie nachweislich gesund ist. Ist die
  Bestandskopie beschädigt, wird sie **repariert statt verworfen**.
- Quelldateien werden erst dann in den „erledigt"-Ordner bewegt, **nachdem**
  die Datenbank den Import dauerhaft gespeichert hat. Ein Absturz mittendrin
  kann so nie Dateien „verlieren".
- Namenskollisionen bekommen ein Suffix; Dateien ohne verlässliches Datum
  landen in einem eigenen Nachbehandlungs-Ordner; ein eingebettetes
  Aufnahmedatum schlägt das Dateisystem-Datum.
- Was bewusst gelöscht wurde, steht auf einer **Sperrliste** und wird nicht
  still wieder importiert.

### 6. Manuelle Ebene: Bewertungen, Tags, Notizen

`test_manual.py` prüft Sternebewertungen, Tags und Notizen (setzen, ändern,
entfernen, doppelt setzen ist harmlos). Der wichtigste Einzeltest stellt
sicher, dass die manuelle Ebene **niemals in die extrahierten Daten
hineinschreibt**: Was aus der Datei kam und was du selbst gesetzt hast, bleibt
strikt getrennt gespeichert. Nur so kann ein erneuter Scan nie deine
Bewertungen überschreiben — und nur so bleibt sichtbar, welche Information
welche Herkunft hat.

### 7. Web-Oberfläche: Suche, Filter, Motor

| Testdatei | Prüft |
|---|---|
| `test_filters.py` | Die Filtersprache der Suchleiste (`model: flux`, `rating>=4`, `-tag: test`, `mp:`, `format:`, …) wird korrekt zerlegt und liefert die richtigen Treffermengen; Tippfehler in Feldnamen werden abgelehnt statt still ignoriert. |
| `test_web_library.py` (53 Tests) | Galerie-Seiten kommen in der richtigen Reihenfolge und Sortierung; die Volltextsuche findet Prompts, Dateinamen und Wortanfänge; die Detailansicht zeigt alle drei Informationsebenen; Modell-Zähler in der Seitenleiste stimmen. |
| `test_web_media.py` (22 Tests) | Auslieferung von Mediendateien (ADR 0069 Nachtrag): Range-Anfragen liefern genau die angeforderten Bytes, unerfüllbare Bereiche enden mit 416, HEAD sendet nur Kopfzeilen — und wenn der Browser die Verbindung trennt, hört der Server nach höchstens einem weiteren Häppchen auf zu lesen, statt ein 4-GB-Video zu Ende zu streamen. |
| `test_web_engine.py` | Die Warteschlange und der echte Arbeitsprozess (ADR 0067): Aufgaben laufen nacheinander im Kindprozess, eine abstürzende Aufgabe reißt ihn nicht mit, ein sterbender Prozess wird gemeldet und neu gestartet, Doppelklicks werden abgewiesen, kurze Schreibgriffe warten nicht hinter Langläufern, jede Aufgabe steht im Serverlog; überwachte Ordner (Watch-Quellen) erkennen neue Dateien erst, wenn sie „zur Ruhe gekommen" sind (fertig kopiert). |
| `test_web_app_static.py` | Die Oberfläche wird korrekt ausgeliefert, und der Browser bekommt nach einem Update keine veraltete Version aus dem Zwischenspeicher. |
| `test_admin.py` | Der Admin meldet korrekte Kennzahlen (inkl. Übersichts-Zahlen: Art, Jahrgänge, Zuwachs, Speicherplatz); Scan-Probleme lassen sich erfassen und auflösen; verwaiste Datenbankeinträge (Datei existiert nicht mehr) werden gefunden und aufgeräumt. |

### 8. Vorschaubilder (Thumbnails)

`test_thumbs.py` prüft: Vorschaubilder halten die Größengrenze ein, kleine
Bilder werden nicht künstlich vergrößert, animierte Dateien nehmen das erste
Bild, Videos laufen über `ffmpeg`. Für kaputte Dateien wird ein Merkzettel
(„Fail-Marker") abgelegt, damit nicht bei jedem Anzeigen erneut vergeblich
gerechnet wird. Und: Die parallele Erzeugung über mehrere Prozessorkerne
liefert **exakt dasselbe Ergebnis** wie die einfache Erzeugung nacheinander —
so kann die schnelle Variante nie stillschweigend von der korrekten abweichen.

### 9. Oberfläche im Kleinen: die JavaScript-Module in Node

Die Bedienoberfläche ist in JavaScript-Modulen geschrieben (Galerie, Lupe,
Einzelansicht, Admin, Suche). Seit 2026-09 laufen dafür eigene Tests
**ohne Browser**: Node.js führt die Module gegen eine winzige Nachbildung
der Browser-Seite aus (`tests/js/`), pytest startet sie mit
(`test_frontend_modules.py`). Voraussetzung ist ein installiertes
**Node.js ab Version 20.6** — fehlt es, werden genau diese Tests
übersprungen, der Rest der Suite läuft normal.

| Testdatei | Prüft |
|---|---|
| `tests/js/dom.test.mjs` | Die Browser-Nachbildung selbst: Seite aus `index.html` aufbauen, Elemente finden, Tastatur-/Klick-Ereignisse in der richtigen Reihenfolge. |
| `tests/js/overlays.test.mjs` | Lupe und Einzelansicht: Leertaste/Enter/Esc in allen Kombinationen — nie zwei Vollbild-Ebenen gleichzeitig; ein Video wird beim Schließen entfernt (spielt nicht doppelt weiter); Video-Fehler zeigt den Hinweis, Schließen bricht die laufende Anfrage ab, `view-changed` beim Öffnen/Schließen. |
| `tests/js/zoom.test.mjs` | Zoomstufe „max. 100 %": kleines Bild in echten Pixeln, großes wie Anpassen, Gerätepixel (dpr 2), Gedächtnis über Bilder hinweg, Gesten starten aus der effektiven Skala, Doppelklick führt nach 100 %. |
| `tests/js/workflow.test.mjs` | Workflow-Vorschau im ComfyUI-Look: Slot-/Link-Farben je Datentyp, Maße und Palette, Widget-Beschriftung (benannt vor Instanz-Dump vor Kern-Tabelle, sonst roh), Bypass/Mute/eingeklappt, Gruppen, Subgraph-Kasten und Innenansicht, Härtung gegen fremdes Workflow-JSON. |
| `test_dump_object_info.py` | Das Werkzeug reduziert ComfyUIs `object_info` auf Widget-Namen je Node-Typ in der richtigen Reihenfolge (Seed-Zusatz, required vor optional) und verträgt Müll. |
| `tests/js/sidebar.test.mjs` | Sidebar-Facette „Generator": Plattform-Zeilen mit Anzeigename und Zähler, Gruppe steht über „Nach Modell", bei aktivem Chip leere Zeilen gedimmt unter der Trennzeile „keine Treffer mit diesem Filter" (auch in der Modell-Liste), Klick erzeugt genau einen `chip-toggle` mit exaktem `tool:`-Prädikat, Suchzustand geht als Filter an die Zähler. |
| `tests/js/gallery.test.mjs` | Galerie: nach einem Filterwechsel springt sie zum zuletzt gewählten Bild zurück; „Alle Medien" führt nach oben ohne Auswahl; kommt im Watchordner ein Bild dazu, bleiben die alten Kacheln stehen und das neue rückt oben ein. |
| `tests/js/dialogs.test.mjs` | Dialog-Stapel der Galerie (ADR 0069): versteckte Dialoge (Speichern) hängen am Stapel, Esc schließt, ein Ansichtswechsel schließt alle Dialoge über ihre Schließfunktion; Zeitlimit lesender Anfragen mit übersetzter Meldung. |
| `tests/js/picker.test.mjs` | Ordner-Auswahl im Admin-Dokument: öffnen, abbrechen, erneut öffnen, wählen, übernehmen — der gewählte Ordner steht im Feld, Esc schließt nur den obersten Dialog, es bleiben keine Tastatur-Fallen zurück; dasselbe in der Rausverschieben-Karte (kein Dialog darunter), auch nach einem Seitenwechsel. |
| `tests/js/status.test.mjs` | Geteilter Status-Poller (ADR 0074): das Topbar-Badge der Galerie ist ein Link nach `/admin`, zeigt den übersetzten Aufgabennamen (nie „[object Object]“), zählt die Warteschlange, markiert einen abgestürzten Arbeitsprozess; `engine-idle` feuert nur an der Flanke laufend→leer, „Aufgabe fertig“ nur bei geänderter `finished_seq`. |
| `tests/js/admin_shell.test.mjs` | Admin-Dokument: Router (unbekannter Slug → Übersicht, Klick auf Navi-Link → pushState + Seite, Browser-Zurück rendert die vorige, Modifier-Klick und Galerie-Link gehen am Router vorbei), sieben Seiten in fester Reihenfolge, Aktivitäts-Widget in allen Zuständen, Instanz-Pille, Schema/Port. |
| `tests/js/admin_overview.test.mjs` | Seite Übersicht: Kennzahl-Kacheln mit Quoten, Zusammensetzung/Zuwachs/Jahrgänge, Aktivität mit Trichter und Verlauf, Neuladen nur bei fertiger Aufgabe, System-Kacheln (Speicherplatz-Ring, Parser, Instanz), Hinweiskarten mit Links. |
| `tests/js/admin_overview_pending.test.mjs` | Übersicht in zwei Stufen: Kennzahlen/Diagramme sofort, teure Zahlen (Fundorte, Thumbnail-Cache) zeigen „…“ und einen Prüfhinweis, bis `/api/admin/info` da ist; keine Einblend-Animation. |
| `tests/js/admin_logs.test.mjs` | Seite Logs: beide Dateien sofort (je ein Aufruf mit `?file=`), „nur WARNING und höher“ als `?level=warning`, Zeilenzahl und Auffrischen je Datei, Einfärbung, ehrliche Leermeldung, Zeilenumbruch/untereinander (im Browser gemerkt), Auffrischen nach fertiger Aufgabe. |
| `tests/js/admin_issues.test.mjs` | Seite Probleme (A3, #66): je Fehlerart eine Karte mit Zähler und „jüngste n von N", Alle-Knopf mit echter Zahl, Quittieren meldet die Zahl und lädt neu; Sperrliste getrennt geladen, seitenweise (100) mit Zurück/Weiter und Bereich, Suche mit „n Treffer von gesamt", Entsperren einzeln und alle (nur nach Bestätigung). |
| `tests/js/admin_maintenance.test.mjs` | Seite Wartung (A3): vier Karten mit Aktionszeilen, Zustand je Zeile aus dem Status-Poll (läuft mit Balken → Warteschlange mit Position → zuletzt ✓), Einreihen und synchrone Aktionen inline, Rausverschieben-, Import-Regeln- und Aufräum-Karten mit zweistufigem Schärfen (Aufräumen: Bereich, Vorschau nur auf Knopfdruck, Bereichswechsel entwertet), DB-Aufteilung nur auf Knopfdruck und ehrlich „nicht verfügbar" ohne dbstat. |
| `tests/js/admin_arenas.test.mjs` | Seite Rankings (A3): Tabelle mit allen Spalten, Löschen nur nach Bestätigungsdialog, Scores neu berechnen mit Inline-Ergebnis. |
| `tests/js/context.test.mjs` | Bearbeiten-Modus für Rankings (ADR 0081/#133): „Bearbeiten: 🏆 Name" vorn, Kopfzeile `editing`, Speichern nur bei Abweichung ohne `sort:`, Umbenennen sichert nur den Namen, ✕ zurück ins Ranking; gespeicherte Suche öffnet keinen Modus. |
| `tests/js/savedialog.test.mjs` | Speicherdialog (#133): ohne Ursprung nur Speichern; aus geladener Suche Ursprung im Dialog, Name vorbelegt, „»Name« überschreiben" (PUT) und „Als neue Suche speichern" (POST), Ursprung endet beim Leeren. |
| `tests/js/admin_dialogs.test.mjs` | Dialog-Stapel des Admin-Dokuments: Picker über der Bestätigung, Esc von oben nach unten, Ordnerwahl der Rausverschieben-Karte (Abbruch lässt das Feld stehen, Wahl übernimmt), Schließen von außen löst das Picker-Promise, Bestätigungsdialog (Ja/Abbrechen/Esc). |

**„Erwartet rot":** Einige dieser Tests beschreiben Verhalten, das erst noch
gebaut wird (sie tragen die Nummer des zugehörigen Issues im Namen). Sie
laufen mit, ihr Scheitern gilt als bestanden — bis der Fehler behoben ist.
Dann meldet der Test das ausdrücklich und wird zum normalen Test. So sind
bekannte Fehler von Anfang an als Prüfung festgehalten.

Eine einzelne Datei lässt sich auch direkt starten:

```
node --import ./tests/js/setup.mjs tests/js/overlays.test.mjs
```

## Zwei Muster, die immer wiederkehren

Wer die Suite liest, stößt ständig auf dieselben zwei Ideen:

1. **Idempotenz** („zweimal ausführen = einmal ausführen"): Re-Scan, erneutes
   Interpretieren, Migrationen, Tag setzen — alles darf beliebig wiederholt
   werden, ohne dass Duplikate oder Schäden entstehen. Das ist das billigste
   Sicherheitsnetz für alles, was über einen 250.000-Dateien-Bestand läuft.
2. **Äquivalenz** („die schnelle Variante muss dasselbe liefern wie die
   einfache"): Parallel-Thumbnails gegen sequenzielle, Stream-Hash gegen
   Ganzes-Hash. So lassen sich Performance-Umbauten wagen, ohne Korrektheit
   zu riskieren.

## Prüfprotokoll Oberfläche (einmal pro Etappe im Browser)

Die Node-Tests sehen keine Pixel: kein echtes Scrollen, keine Video-
Fehlercodes, kein Rendering. Deshalb wird **einmal pro abgeschlossener
Etappe** (nicht pro Handgriff) diese feste Klickliste im Browser
abgearbeitet — gegen einen Sandbox-Server mit synthetischem Bestand, nie
gegen die echte Bibliothek. Das Ergebnis steht als eine Zeile in der
PR-Beschreibung: `Prüfprotokoll: bestanden` oder `Prüfprotokoll: P4
abweichend — …`.

**Vorbereitung:** Server mit Testbestand starten (mindestens zwei
Seiten Bilder, ein Video, ein Watchordner im Katalogisieren-Modus),
Browser-Konsole und Netzwerk-Reiter offen.

| Nr. | Schritt | Erwartet |
|---|---|---|
| P1 | Seite laden | Zähler in der Kopfzeile, Kacheln erscheinen, keine Fehler in der Konsole |
| P2 | Galerie bis ans Ende scrollen und zurück; Dichte S/M/L umschalten | keine dauerhaft leeren Kacheln, Scrollposition bleibt beim Dichtewechsel sinnvoll |
| P3 | Bild anklicken, Pfeiltasten, Shift-Klick, Strg/Cmd-Klick | Ring folgt der Auswahl, Panel zeigt das Bild, Mehrfachauswahl zählt richtig |
| P4 | Leertaste, Enter, Esc in allen Kombinationen; in Lupe und Einzelansicht ←/→ blättern; Video öffnen und schließen | nie zwei Vollbild-Ebenen zugleich, Video spielt einmal und stoppt beim Schließen, Blättern zieht die Auswahl mit |
| P5 | Suchtext tippen, Chip entfernen, Facette in der Sidebar klicken, dann „Alle Medien" | Trefferzahl folgt, Chips stimmen, „Alle Medien" führt nach oben ohne Auswahl |
| P6 | Bild in den Watchordner legen, warten | neues Bild erscheint oben, alte Kacheln bleiben stehen, Auswahl bleibt am gewählten Bild |
| P7 | Admin öffnen (`/admin`); Ordner-Picker: öffnen, abbrechen, erneut öffnen, wählen, übernehmen; Rausverschieben-Karte mit Picker; Esc; Browser-Zurück | gewählter Ordner steht im Feld, Esc schließt nur den obersten Dialog, die Seite bleibt bedienbar, Zurück führt zur vorigen Admin-Seite bzw. Galerie |
| P8 | Sprache umschalten (EN/DE) und zurück | Oberfläche wechselt komplett, Zustand bleibt |
| P9 | Konsole und Netzwerk durchsehen | keine JavaScript-Fehler, keine 5xx-Antworten |

Fällt ein Schritt durch, wird der Befund als Issue festgehalten (mit
Schrittnummer) und — wo die Node-Tests ihn hätten sehen können — als
„erwartet roter" Test in `tests/js/` ergänzt.

## Für Tester: Wann sollte ich die Suite laufen lassen?

Im Normalfall gar nicht — die Tests laufen vor jedem Einchecken von Änderungen.
Sinnvoll ist ein Lauf, wenn du das Projekt **frisch auf einem neuen Rechner**
eingerichtet hast und wissen willst, ob die Umgebung stimmt (Python-Version,
Abhängigkeiten, optional ffmpeg): `pytest -q` — steht am Ende `passed` ohne
`failed`, ist die Installation in Ordnung.
