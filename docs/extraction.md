# Metadaten-Extraktion (Schicht 1)

> Was tut sie? Sie öffnet eine Mediendatei, erkennt das Format und zieht **alle**
> eingebetteten Metadaten **unverändert** heraus — den ComfyUI-Workflow, die
> A1111-Parameter, eingebettetes EXIF usw. Sie *deutet* die Werte noch nicht
> (kein „das ist der Seed"); das macht später Schicht 2. Was nicht gedeutet ist,
> ist trotzdem vollständig gespeichert.

**Stand:** Umgesetzt sind **PNG** (Eigenbau), **JPEG/WEBP/TIFF/GIF/BMP** (über
Pillow), **PSD/PSB** (Eigenbau) und **Video WEBM/MKV/MP4/MOV** (über das
System-Programm `ffprobe`). PDF wird *erkannt*, aber nicht extrahiert
(bewusst gestrichen, ADR 0051). Die Deutung der Werte macht
[Schicht 2](interpretation.md).

## Verwendung

```python
from feral.extract import extract

result = extract("/pfad/zu/bild.png")

print(result.container)      # "png"
for item in result.items:
    print(item.source, "|", item.keyword, "=>", (item.text or item.data))
print(result.warnings)       # leere Liste, wenn alles sauber war
```

### Ergebnis: `ContainerExtraction`

| Feld | Bedeutung |
|------|-----------|
| `container` | erkannter Container-Typ, z. B. `"png"` (über Magic Bytes, nicht über die Dateiendung) |
| `items` | Liste der gefundenen Roh-Metadaten-Einträge, in Fundreihenfolge |
| `warnings` | nicht-fatale Auffälligkeiten (z. B. CRC-Fehler, abgeschnittene Datei). Leere Liste = sauber |

### Ein Eintrag: `RawMetadataItem`

| Feld | Bedeutung |
|------|-----------|
| `source` | woher der Eintrag stammt, z. B. `"png:tEXt"`, `"png:iTXt"`, `"png:eXIf"` |
| `keyword` | Schlüssel im Chunk, z. B. `"parameters"` (A1111) oder `"workflow"` (ComfyUI); `None`, wenn keiner |
| `text` | der Textwert, unverändert — bei textuellen Einträgen |
| `data` | die rohen Bytes — bei binären Einträgen (z. B. EXIF) |
| `encoding` | wie der Text dekodiert wurde (`"latin-1"`, `"utf-8"`) bzw. `"binary"` |
| `compressed` | `True`, wenn der Wert komprimiert vorlag und hier entpackt wurde |

Es ist immer **genau eines** von `text` oder `data` gesetzt.

## Was bei PNG gelesen wird

- **`tEXt`** — unkomprimierter Text (A1111 schreibt seine Parameter hierhin).
- **`zTXt`** — komprimierter Text (wird automatisch entpackt).
- **`iTXt`** — internationaler/UTF-8-Text (ComfyUI legt hier Workflow/Prompt ab),
  optional komprimiert.
- **`eXIf`** — eingebettetes EXIF, als rohe Bytes übernommen.

## Was bei JPEG/WEBP/GIF/BMP/TIFF gelesen wird (über Pillow)

Alle Metadaten-Segmente, die Pillow beim Öffnen im Container findet — z. B.
eingebettetes **EXIF** und **XMP**, das **ICC-Profil**, **Kommentare**
(JPEG-COM, GIF-Comment) sowie technische Container-Werte (Animations-`loop`,
`duration`, `dpi`). Quelle-Label ist z. B. `"webp:info"`, das Keyword der
Pillow-Info-Schlüssel (`"exif"`, `"xmp"`, `"comment"`, …). Binäres bleibt
byte-exakt, Text bleibt unverändert.

## Was bei PSD/PSB gelesen wird (Eigenbau)

Photoshop-Dateien tragen ihre Metadaten in den **Image Resource Blocks**.
Übernommen werden die bekannten Metadaten-Ressourcen, byte-exakt: **XMP**
(als Text — damit greift der XMP-Parser von Schicht 2 automatisch), **EXIF**,
**IPTC** und das **ICC-Profil**, dazu aus dem Header Maße, Farbmodus
(RGB/CMYK/Lab …) und Bittiefe. Quell-Label: `"psd:8bim"` bzw. `"psd:header"`.
Eingebettete Vorschau-Thumbnails und Werkzeug-Einstellungen (Druck, Raster,
Hilfslinien) sind keine Metadaten und werden übersprungen. Bestände, die vor
dieser Erweiterung katalogisiert wurden: einmal **Admin → Wartung →
„Re-Scan aller Fundorte"** ausführen.

## Was bei Video gelesen wird (über ffprobe)

Alle **Container-Tags** aus dem Format-Kopf und den einzelnen Streams, z. B.
`ENCODER` oder `COMMENT` bei WEBM. Quell-Label: `"matroska:format.tag"` bzw.
`"matroska:stream0.tag"` (analog `"isobmff:…"` für MP4/MOV).

> **Voraussetzung:** `ffprobe` (Teil von **ffmpeg**) muss installiert sein —
> macOS `brew install ffmpeg`, Debian/Ubuntu `apt install ffmpeg`, Windows
> `winget install ffmpeg`. **Fehlt es, ist das kein Fehler:** Videos werden
> trotzdem katalogisiert (Hash + Fundort); ein erneuter Scan nach der
> Installation holt die Metadaten nach.

## Robustheit

Die Extraktion **stürzt bei kaputten Dateien nicht ab**. Probleme (falsche
Signatur, CRC-Fehler, abgeschnittene Chunks, fehlendes Datei-Ende, ungültiges
UTF-8) landen als Text in `warnings`; soweit möglich werden die Inhalte trotzdem
übernommen (bei kaputter Dekodierung verlustfrei als Roh-Bytes). Eine Datei, die
sich gar nicht lesen lässt, ist später ein Fall für den `_failed`-Ordner.

## Hashing (Identität eines Items)

Jede Datei bekommt ihre stabile Identität über ihren **SHA-256-Datei-Hash**:

```python
from feral.hashing import hash_file
ident = hash_file("/pfad/zu/bild.png")   # 64-stelliger Hex-String
```

Dieser Hash trägt zugleich Dublettencheck, Wiederherstellung und Sync.

## EXIF-Textfelder (WEBP/JPEG)

Zusätzlich zum byte-exakten EXIF-Binärblock werden die **String-Tags** des
EXIF-Haupt-IFD als lesbare Einträge abgelegt (ADR 0016). ComfyUI speichert bei
WEBP Prompt und Workflow genau dort (`Model="prompt:{…}"`,
`Make="workflow:{…}"`) — diese Einträge bekommen das eingebettete Label als
Keyword und sind damit für Interpretation, Suche und Workflow-Ansicht sichtbar.
Bestände, die vor dieser Erweiterung gescannt wurden: einmal
**Admin → Wartung → „Re-Scan aller Fundorte"** ausführen.
