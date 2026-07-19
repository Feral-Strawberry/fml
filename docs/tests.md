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
480 passed, 2 skipped in 4.2s
```

- **passed** = bestanden. Die genaue Zahl wächst mit dem Projekt; wichtig ist:
  **0 failed, 0 errors**.
- **skipped** ist in Ordnung: zwei Tests brauchen die Videowerkzeuge
  `ffmpeg`/`ffprobe` und überspringen sich selbst, wenn diese auf dem Rechner
  nicht installiert sind. Die App funktioniert dann trotzdem, nur ohne
  Video-Metadaten und Video-Vorschaubilder.
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
| `test_image_pillow.py` | JPEG/WEBP/GIF & Co.: eingebettete EXIF/XMP-Daten und Kommentare kommen unverändert heraus. |
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
| `test_web_engine.py` | Der interne Arbeiter, der alle Schreibvorgänge nacheinander abarbeitet: eine abstürzende Aufgabe reißt ihn nicht mit; überwachte Ordner (Watch-Quellen) erkennen neue Dateien erst, wenn sie „zur Ruhe gekommen" sind (fertig kopiert). |
| `test_web_app_static.py` | Die Oberfläche wird korrekt ausgeliefert, und der Browser bekommt nach einem Update keine veraltete Version aus dem Zwischenspeicher. |
| `test_admin.py` | Das Admin-Dashboard meldet korrekte Kennzahlen; Scan-Probleme lassen sich erfassen und auflösen; verwaiste Datenbankeinträge (Datei existiert nicht mehr) werden gefunden und aufgeräumt. |

### 8. Vorschaubilder (Thumbnails)

`test_thumbs.py` prüft: Vorschaubilder halten die Größengrenze ein, kleine
Bilder werden nicht künstlich vergrößert, animierte Dateien nehmen das erste
Bild, Videos laufen über `ffmpeg`. Für kaputte Dateien wird ein Merkzettel
(„Fail-Marker") abgelegt, damit nicht bei jedem Anzeigen erneut vergeblich
gerechnet wird. Und: Die parallele Erzeugung über mehrere Prozessorkerne
liefert **exakt dasselbe Ergebnis** wie die einfache Erzeugung nacheinander —
so kann die schnelle Variante nie stillschweigend von der korrekten abweichen.

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

## Für Tester: Wann sollte ich die Suite laufen lassen?

Im Normalfall gar nicht — die Tests laufen vor jedem Einchecken von Änderungen.
Sinnvoll ist ein Lauf, wenn du das Projekt **frisch auf einem neuen Rechner**
eingerichtet hast und wissen willst, ob die Umgebung stimmt (Python-Version,
Abhängigkeiten, optional ffmpeg): `pytest -q` — steht am Ende `passed` ohne
`failed`, ist die Installation in Ordnung.
