# Import: Sicherungen in den Bestand einsortieren

> Was ist das? Der Weg, wie deine verstreuten Quellordner (alte Sicherungen,
> ComfyUI-Outputs, Downloads) zu **einem** eindeutigen, datumssortierten
> Bestand werden. Dubletten werden dabei automatisch aussortiert — sichtbar,
> nicht still. (Regeln: ADR 0006/0019.)

## Voraussetzung

Kopierende und verschiebende Importe setzen zweierlei voraus (der Modus
„katalogisieren" braucht beides nicht): die eingeschaltete
**Library-Verwaltung** und die Bestands-Wurzel — beides in der GUI unter
**Admin → Konfiguration** (Haken „Library-Verwaltung", Feld „Media Library
(Import-Ziel)"; wirkt sofort, dort steht auch das älteste plausible Datum).
Alternativ direkt in der `config.toml`:

```toml
[library]
root = "/pfad/zum/bestand"
```

## Ablauf

**Admin → Quellen & Import:** Ordner wählen, Modus wählen,
Häufigkeit „einmal jetzt", **Aufnehmen**. Die Library-Seite ist in jedem
Modus gleich: Neues wird nach `bestand/JJJJ/MM/TT/` **kopiert**, die Kopie
per Hash gegen die Quelle verifiziert und sofort katalogisiert (kein
zusätzlicher Scan nötig). Der Modus bestimmt allein, was mit der **Quelle**
passiert (ADR 0031):

- **„kopieren"** — die Quelle wird **nie angefasst**, der Import ist rein
  lesend. Das Ergebnis je Datei (neu/Dublette/Fehler/…) steht im
  Import-Log (Admin → Aktivität); im Quellordner selbst ändert sich
  nichts. Der richtige Modus für fremde Ordner und Tool-Outputs.
- **„verschieben"** (mit ausdrücklicher Bestätigung) — erfolgreich
  Importiertes wird nach der Verifikation aus der Quelle **gelöscht**;
  der Ordner leert sich. Nur Nachschau-Fälle bleiben sichtbar liegen.
  Die Namen der Ausgangs-Ordner sind feste Bezeichner wie die
  Config-Werte (`kopieren`, `verschieben`, `katalogisieren`): sie bleiben
  in jeder Sprache gleich, damit fml sie in jeder Installation
  wiedererkennt; die Tabelle nennt die Bedeutung.

  | Ausgang | Bedeutung |
  | --- | --- |
  | `_dubletten/` | Inhalt ist (bit-identisch) schon im Bestand — **und** die Bestandskopie wurde frisch nachgehasht |
  | `_unbekanntes-format/` | Container nicht erkannt — dein Stolper-Ordner für fehlende Formate |
  | `_fehler/` | Lesefehler oder die Kopie ließ sich nicht verifizieren |
  | `_gesperrt/` | Hash steht auf der Sperrliste (in der Bibliothek abgelehnt) — wird nicht wieder importiert (ADR 0023/0041) |
  | `_ausgefiltert/` | von den **Import-Regeln** aussortiert (zu klein / zu groß / ausgeschlossenes Format / kein plausibles Datum, s. u.) — nach einer Regel-Änderung einfach neu einwerfen |

  Gelöscht wird also ausschließlich, was nachweislich bit-identisch im
  Bestand liegt und dessen Katalogeintrag gespeichert ist — alles andere
  bleibt als sichtbarer Rest zur Nachschau.
- **„katalogisieren"** — weder kopieren noch bewegen: nimmt Medien **am
  Ort** in den Katalog auf. Der einzige Modus, der keine Media Library
  braucht — und der einzige, der im Übersichtsmodus (Standard) erlaubt
  ist.

Große Läufe laufen als **Pipeline**: mehrere Vorarbeiter-Threads
erkennen und hashen voraus (auch die Gesundheitsprüfung von Bestandskopien
bei Dubletten läuft so parallel), kopiert und katalogisiert wird weiterhin
strikt der Reihe nach, gespeichert in Schüben. Dublettenlastige
Zweitlieferungen — der häufigste Fall — werden dadurch um ein Mehrfaches
schneller.

## Import-Regeln: Kleinkram und Halb-Unterstütztes draußen halten

Unter **Admin → Konfiguration → Media Library** lassen sich Regeln
setzen, die bei **jedem** Aufnahmeweg greifen — Import (kopieren/
verschieben), Katalogisieren und Watchordner:

- **Mindestgröße (kleinste Seite)**, z. B. `240` px: filtert eingebettete
  Archiv-Thumbnails und anderen Kleinkram, der keinen Wert hat.
- **Maximalgröße (längste Seite)**, z. B. `8000` px: filtert riesige
  Kontaktbögen/Thumbnail-Übersichten (zehntausende Pixel breit).
- **Formate ausschließen**, z. B. `psd, arw`: halb unterstützte Formate
  gar nicht erst aufnehmen. Kamera-RAW-Dateien (Sony ARW, Nikon NEF,
  Canon CR2, DNG) werden eigens erkannt statt als TIFF durchzurutschen.
- **Frühestes plausibles Datum** (`[import] min_date`, Standard
  2015-01-01): eine Datei, deren Erstelldatum weder aus den Metadaten
  noch aus dem Dateistempel plausibel ist (vor `min_date` oder in der
  Zukunft, z. B. 1.1.1970), wird **nicht aufgenommen** — sie gilt als
  Regel-Treffer wie ein zu kleines Bild. Diese Regel ist immer aktiv;
  wer Altes behalten will, senkt `min_date`.

Beide Maß-Regeln gelten nur für **Bilder mit bekannten Maßen** — Videos
nie, und ohne Maße wird nicht geraten. Beim Import (verschieben-Modus)
landen Treffer sichtbar in `_ausgefiltert/` (Grund im Import-Log); beim
Katalogisieren werden sie einfach übersprungen und im Report gezählt.
Nichts verschwindet still, und die Quelle wird im kopieren-Modus wie
immer nie angefasst.

Für Bestände, die **vor** den Regeln aufgenommen wurden, gibt es
**Admin → Wartung → „Import-Regeln auf den Bestand"**: zeigt erst, wie
viele Items die aktuellen Regeln träfen (aufgeschlüsselt nach Grund,
inklusive „ohne plausibles Datum"), und lehnt sie nach Bestätigung
gesammelt ab — die Dateien bleiben liegen, nur die Katalog-Einträge
verschwinden (umkehrbar über die Sperrliste). Hintergründe: ADR 0046
und ADR 0075.

## Watchordner (automatischer Import)

Mit Häufigkeit **„dauerhaft beobachten"** wird der Ordner zum
**Watchordner** (`[[watch]]`-Eintrag in der `config.toml`, ADR 0030 —
beliebig viele, Start automatisch beim App-Start): Eine Datei gilt als
fertig, wenn Größe und Zeitstempel über `quiet_seconds` stabil bleiben
(halbe Kopien werden nie angefasst) — dann läuft sie durch genau denselben
Import wie oben, mit derselben Modus-Semantik: „kopieren" liest nur,
„verschieben" leert den Ordner (Nachschau-Fälle bleiben liegen; „leere
Ordner löschen" räumt auf Wunsch leer gewordene Unterordner mit ab,
ADR 0033), „katalogisieren" nimmt am Ort auf. Bereits katalogisierte,
unveränderte Dateien überspringt der Watcher anhand von Größe und
Zeitstempel, ohne sie zu lesen (ADR 0042) — auch über Neustarts hinweg.
Einsatzmuster und Details je Modus: [admin.md](admin.md).
(Alte `[hotfolder]`-Configs werden beim Start automatisch als ein
Watchordner übernommen.)

## Datum

Einsortiert wird nach dem **Erstelldatum**: eingebettetes Datum aus den
Metadaten (falls vorhanden), sonst der ältere plausible Dateisystem-Stempel.
Gibt es kein plausibles Datum (vor `min_date`, z. B. 1.1.1970, oder in der
Zukunft), greift die Datumsregel von oben: die Datei wird **nicht
importiert** und landet sichtbar in `_ausgefiltert/` — statt in einem
falschen Datumsordner oder mit leerem Datum im Katalog. Untergrenze
einstellbar: `[import] min_date = "2015-01-01"`. Ein Ordner
`bestand/_unbekanntes-datum/` aus früheren Versionen bleibt, wie er ist:
seine Einträge kannst du über „Import-Regeln auf den Bestand" ablehnen
(Dateien bleiben liegen) oder mit gesenktem `min_date` und „Erstelldaten
nachtragen" ehrlich datieren.

## Report

Jeder Lauf endet mit einer Summenzeile („4 neu · 8.311 Dubletten · …", in
der Aktivität der Admin-Übersicht). Jede einzelne Datei steht in der
DB-Tabelle `import_log` (Zeitpunkt, Quelle, Ausgang, Ziel, Hash,
Datumsquelle).

## Sicherheit

- Eine Quelle gilt nur dann als Dublette, wenn die vorhandene Bestandsdatei
  **gesund** ist (frisch nachgehasht). Ist sie kaputt oder verschwunden, wird
  neu importiert (`repariert` im Log) — so kann das spätere Löschen der
  `_dubletten/`-Ordner keine einzige gute Kopie vernichten.
- Namenskollisionen (verschiedene Dateien, gleicher Name, gleicher Tag)
  bekommen ein Suffix: `name__2.ext`.
- Ein zweiter Lauf über denselben Ordner ist harmlos: Die Ausgangs-Ordner
  werden nicht erneut importiert.
