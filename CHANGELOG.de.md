# Changelog · Feral Media Library (fml)

> 🇬🇧 **English version:** [`CHANGELOG.md`](CHANGELOG.md)

Was sich zwischen den Snapshot-Releases geändert hat, aus Sicht der
Nutzer. Versionen sind Datums-Versionen (`JJJJ.MM` oder `JJJJ.MM.N`);
die laufende Instanz zeigt ihre Version in Admin → Übersicht.

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
