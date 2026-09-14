# Ordner scannen

> Was tut sie? Sie geht rekursiv durch einen Ordner und nimmt jede Mediendatei in
> die Bibliothek auf: erkennen → hashen → [Metadaten extrahieren](extraction.md) →
> [interpretieren](interpretation.md) → [speichern](persistence.md). Danach ist
> der Bestand durchsuchbar — auch gezielt nach Prompt, Modell oder Seed.

> **Wichtig:** Der Scanner **liest** nur und **kopiert/verschiebt nichts**. Er
> katalogisiert die Dateien dort, wo sie liegen. (Der spätere Import mit Kopieren
> in eine datumsbasierte Struktur ist ein eigener Schritt.)

## Aufruf

```bash
python -m feral.scan /pfad/zum/ordner --db ./feral.sqlite
```

- `root` (Pflicht): der Ordner, der rekursiv durchsucht wird.
- `--db` (optional): Pfad zur SQLite-Datei (Standard `./feral.sqlite`). Wird bei
  Bedarf angelegt.
- `--quiet` (optional): keine Zwischen-Fortschrittsausgabe.

## Beispielausgabe

Die Konsolenausgabe ist wie das Serverlog immer englisch (technischer
Unterbau, Issue #35); die Web-GUI zeigt dieselben Zahlen in der Sprache
der Oberfläche.

```
Scan finished for: /media/ai-bilder
  files seen         : 12877
  of which media     : 12450
    newly added      : 12450
    already known    : 0
    with metadata    : 9980
    interpreted      : 8100
    extractor pending: 120
  skipped (no container)   : 427
  filtered (import rules)  : 0
  blocked (block list)     : 0
  with warnings      : 14
  failed             : 0
```

## Was die Zahlen bedeuten

| Zeile | Bedeutung |
|-------|-----------|
| **files seen** | alle Dateien im Ordnerbaum |
| **of which media** | als bekannter Container erkannt (PNG, JPEG, WEBP, …) |
| **newly added** / **already known** | Hash war neu bzw. schon in der DB (Dublette oder Re-Scan) |
| **with metadata** | es wurden eingebettete Metadaten gefunden |
| **interpreted** | [Schicht 2](interpretation.md) hat strukturierte Felder erkannt (Prompt, Seed, Modell, …) |
| **extractor pending** | erkannt, aber der Extraktor ist noch nicht gebaut (aktuell PSD und PDF). Die Datei ist trotzdem **katalogisiert** und bekommt ihre Metadaten automatisch, sobald der Extraktor da ist |
| **skipped (no container)** | kein bekannter Container (z. B. `.txt`, macOS `._`-Dateien) |
| **filtered** / **blocked** | Import-Regeln bzw. Sperrliste haben die Datei ausgelassen |
| **failed** | Datei nicht lesbar o. ä. — wird unten im Lauf aufgelistet |

## Eigenschaften

- **Wiederholbar (idempotent):** Denselben Ordner nochmal scannen erzeugt keine
  Duplikate; bereits bekannte Dateien werden nur als „bekannt" gezählt.
- **Bricht nicht ab:** Eine kaputte Datei beendet den Scan nicht — sie landet unter
  „failed".
- **Dubletten fallen automatisch an:** bit-identische Dateien an verschiedenen Orten
  werden als **ein** Item mit mehreren Fundorten geführt.

## Diagnose: Video-Codecs im Bestand

Welcher Codec steckt in meinen Videos — und warum spielt der Browser manche
nur mit Ton? Das beantwortet ein Kommando für den ganzen Katalog, ohne eine
Datei zu suchen und ohne Neu-Scan:

```bash
python -m feral.diagnose video-codecs --db ./feral.sqlite
```

Es geht über die Fundorte aller Videos, ruft `ffprobe` nur auf den
Datei-Kopf (auch bei 4 GB unter einer Sekunde) und druckt eine Tabelle:
Codec · Profil · Pixelformat · Browser (`ok` / `eingeschränkt` / `NEIN`) ·
Anzahl Dateien · Beispielpfad. Nichts wird geschrieben.

- `--min-size 1G` — nur Videos ab dieser Größe (`500M`, `2G`, …).
- `--from-db` — liest die Felder `video_codec`/`video_profile`/`pixel_format`
  aus Schicht 2 statt ffprobe zu rufen (Sekundenbruchteile; setzt einen
  Re-Scan nach der Extraktor-Erweiterung voraus — Videos ohne Feld stehen
  als „unbekannt — Re-Scan nötig").
- `--quiet` — keine Fortschrittsausgabe.

Beispiel:

```
Codec   Profile  Pixel format  Browser  Files  Example
------  -------  ------------  -------  -----  --------
prores  HQ       yuv422p10le   NO       212    /media/2026/07/12/topaz_4k.mov
h264    High     yuv420p       ok       1830   /media/2026/07/12/clip.mp4
hevc    Main 10  yuv420p10le   limited  4      /media/2026/05/01/wan.mp4

videos in the catalog: 2046 · probed: 2046
```

Dieselbe Einschätzung landet beim Katalogisieren/Import als Problem der Art
`playback` unter Admin → Probleme; im Suchfeld findet `codec: prores` die
Dateien ([interpretation.md](interpretation.md#video-codec-und-abspielbarkeit)).
