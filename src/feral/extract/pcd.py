"""Kodak Photo CD (``.PCD``, Image Pac) — Schicht 1 + Bild-Decoder (#208).

Stdlib-Eigenbau nach dem Muster von ``psd.py``: Pillow liest nur die Stufe
Base (768×512); die höheren Stufen 4Base (1536×1024) und 16Base
(3072×2048) liegen als Huffman-kodierte Differenzen zur hochgerechneten
kleineren Stufe in der Datei. Referenzen: ImageMagick ``coders/pcd.c``,
hpcdtoppm.

Aufbau (Sektoren à 2048 Bytes):

- Sektor 1: IPI-Kopf (``PCD_IPI``) — Scanzeit, Scanner, Film, Labor;
  bei 0xE02 die Bildattribute (Bits 0–1 Drehung, Bits 2–3 höchste
  Stufe), bei 0xE03 der Endsektor von 4Base.
- Sektor 96: Base als PhotoYCC, je zwei Luma-Zeilen, dann je eine halbe
  Chroma-Zeile C1 und C2.
- Sektor 388: Huffman-Tabelle + Luma-Differenzen für 4Base.
- Endsektor 4Base + 12: drei Tabellen (Y, C1, C2) + Differenzen für 16Base.

``extract`` ist rein und defensiv (Container → Datenobjekte, Warnungen
statt Ausnahmen). ``render`` liefert das Bild in der höchsten Stufe als
Pillow-Image — für Anzeige (/api/preview) und Thumbnails.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageChops

from .types import ContainerExtraction, RawMetadataItem

SECTOR = 0x800
IPI_OFFSET = SECTOR               # Kennung ``PCD_IPI`` bei Byte 2048
SIGNATURE = b"PCD_IPI"
BASE_SECTOR = 96
BASE_W, BASE_H = 768, 512
FOUR_BASE_SECTOR = 388
SIXTEEN_BASE_GAP = 12             # Tabellen 16Base: Endsektor 4Base + 12

# Deckel für präparierte Dateien (Release-QA 2026.09.3): ein Image Pac mit
# 16Base hat ≈ 5 MB (64Base liegt in eigenen IPE-Dateien) — mehr wird nie
# gelesen, und die Zahl der Zeilen je Stufe ist gedeckelt (_decode_deltas).
MAX_BYTES = 16 * 1024 * 1024

_ATTR_OFFSET = 0xE02
_STOP_4BASE_OFFSET = 0xE03

# Stufen laut Bildattribut (Bits 2–3); 64Base (Pro Photo CD, eigene
# IPE-Dateien) wird wie 16Base behandelt.
_LEVELS = {0: ("Base", 1), 1: ("4Base", 2), 2: ("16Base", 4), 3: ("64Base", 4)}

# Textfelder des IPI-Kopfs: (Schlüssel, Offset, Länge). Offsets an echten
# Image Pacs geprüft (Kodak-Filmscanner 2000, 1996).
_IPI_TEXT = (
    ("product_type", 0x816, 20),
    ("scanner_vendor", 0x82A, 20),
    ("scanner_product", 0x83E, 16),
    ("scanner_firmware", 0x84E, 4),
    ("scanner_firmware_date", 0x852, 8),
    ("scanner_serial", 0x85A, 20),
    ("piw_manufacturer", 0x870, 20),
    ("photofinisher", 0x8A5, 60),
)
_SCAN_TIME = 0x80D
_MODIFY_TIME = 0x811
_IPI_LENGTH = 0xE10               # bis inkl. Bildattribute


def is_pcd(head: bytes) -> bool:
    """Photo-CD-Kennung an Byte 2048 (``head`` muss so weit reichen)."""
    return head[IPI_OFFSET:IPI_OFFSET + len(SIGNATURE)] == SIGNATURE


def _attributes(ipi: bytes) -> tuple[int, int]:
    """(Drehung 0–3, Faktor gegenüber Base 1/2/4) aus dem Bildattribut."""
    attr = ipi[_ATTR_OFFSET] if len(ipi) > _ATTR_OFFSET else 0
    return attr & 0x03, _LEVELS[(attr >> 2) & 0x03][1]


def _text(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("latin-1").strip()


def extract(source: str | Path) -> ContainerExtraction:
    """Roh-Metadaten eines Image Pac: der IPI-Kopf byte-treu, dazu seine
    Textfelder und die Scanzeit als ``CreateDate`` (Datums-Kaskade)."""
    result = ContainerExtraction(container="pcd", media_kind="image")
    try:
        with open(source, "rb") as fh:
            ipi = fh.read(_IPI_LENGTH)
    except OSError as exc:
        result.warnings.append(f"Lesefehler: {exc}")
        return result
    if not is_pcd(ipi) or len(ipi) < _IPI_LENGTH:
        result.warnings.append("Kein vollständiger PCD_IPI-Kopf.")
        return result

    result.items.append(RawMetadataItem(
        source="pcd:ipi", keyword=None, text=None,
        data=ipi[IPI_OFFSET:], encoding="binary"))
    for key, offset, length in _IPI_TEXT:
        value = _text(ipi[offset:offset + length])
        if value:
            result.items.append(RawMetadataItem(
                source="pcd:ipi", keyword=key, text=value, data=None,
                encoding="latin-1"))
    for key, offset in (("CreateDate", _SCAN_TIME), ("ModifyDate", _MODIFY_TIME)):
        stamp = int.from_bytes(ipi[offset:offset + 4], "big")
        if stamp:
            when = datetime.fromtimestamp(stamp, tz=timezone.utc)
            result.items.append(RawMetadataItem(
                source="pcd:ipi", keyword=key,
                text=f"{when:%Y:%m:%d %H:%M:%S}", data=None, encoding="utf-8"))

    rotation, factor = _attributes(ipi)
    w, h = BASE_W * factor, BASE_H * factor
    result.width, result.height = (h, w) if rotation in (1, 3) else (w, h)
    return result


# --- Bild-Decoder -----------------------------------------------------------

class PcdError(ValueError):
    """Image Pac nicht dekodierbar (abgeschnitten, Tabellen kaputt)."""


def _rounded_avg(a: Image.Image, b: Image.Image) -> Image.Image:
    """(a + b + 1) >> 1 pro Pixel, in C: ImageChops.add rundet ab, also
    über die invertierten Bilder (255 − ⌊(255−a + 255−b)/2⌋ = ⌈(a+b)/2⌉)."""
    return ImageChops.invert(
        ImageChops.add(ImageChops.invert(a), ImageChops.invert(b), 2.0))


def _shifted(img: Image.Image, dx: int, dy: int) -> Image.Image:
    """Um ein Pixel nach links (dx=1) bzw. oben (dy=1) verschoben; die
    letzte Spalte/Zeile wird wiederholt."""
    w, h = img.size
    out = img.copy()
    out.paste(img.crop((dx, dy, w, h)), (0, 0))
    return out


def upsample(img: Image.Image) -> Image.Image:
    """Verdoppeln wie Kodak/ImageMagick: gerade Positionen übernehmen das
    Original, ungerade den gerundeten Mittelwert der Nachbarn, der Rand
    wird wiederholt. Die Differenzen der nächsten Stufe beziehen sich auf
    genau diese Vorhersage — eine andere Interpolation gäbe Säume."""
    w, h = img.size
    wide = img.resize((2 * w, h), Image.NEAREST)
    wide = _rounded_avg(wide, _shifted(wide, 1, 0))
    tall = wide.resize((2 * w, 2 * h), Image.NEAREST)
    return _rounded_avg(tall, _shifted(tall, 0, 1))


def _read_base(data: bytes) -> tuple[Image.Image, Image.Image, Image.Image]:
    start = BASE_SECTOR * SECTOR
    size = BASE_W * BASE_H * 3 // 2
    raw = data[start:start + size]
    if len(raw) < size:
        raise PcdError("Base-Stufe abgeschnitten")
    y = bytearray()
    c1 = bytearray()
    c2 = bytearray()
    half = BASE_W // 2
    step = 2 * BASE_W + 2 * half
    for pos in range(0, size, step):
        y += raw[pos:pos + 2 * BASE_W]
        c1 += raw[pos + 2 * BASE_W:pos + 2 * BASE_W + half]
        c2 += raw[pos + 2 * BASE_W + half:pos + step]
    return (Image.frombytes("L", (BASE_W, BASE_H), bytes(y)),
            Image.frombytes("L", (half, BASE_H // 2), bytes(c1)),
            Image.frombytes("L", (half, BASE_H // 2), bytes(c2)))


def _read_tables(data: bytes, pos: int, count: int) -> tuple[list, int]:
    """``count`` Huffman-Tabellen ab Byte ``pos`` → Nachschlagetabellen
    über 16 Bit (Index = nächste 16 Bits): (Länge, Differenz als
    Offset-Byte ``key ^ 0x80``). Code-Längen > 16 gibt es nicht."""
    tables = []
    for _ in range(count):
        if pos >= len(data):
            raise PcdError("Huffman-Tabelle abgeschnitten")
        entries = data[pos] + 1
        pos += 1
        lengths = [0] * 65536
        keys = bytearray(65536)
        for _ in range(entries):
            chunk = data[pos:pos + 4]
            if len(chunk) < 4:
                raise PcdError("Huffman-Tabelle abgeschnitten")
            length = chunk[0] + 1
            if length > 16:
                raise PcdError("Huffman-Code länger als 16 Bit")
            code = int.from_bytes(chunk[1:3], "big") >> (16 - length) << (16 - length)
            span = 1 << (16 - length)
            lengths[code:code + span] = [length] * span
            keys[code:code + span] = bytes([chunk[3] ^ 0x80]) * span
            pos += 4
        tables.append((lengths, keys))
    return tables, pos


# Vor der Null einer Sync-Marke stehen 23 Einsen, also mindestens zwei
# volle 0xFF-Bytes direkt vor dem Byte mit der Null. Die Suche danach läuft
# in C (re) — eine Datei aus lauter 0xFF kostet so Millisekunden statt
# Minuten Python-Schleife.
_SYNC_CANDIDATE = re.compile(rb"\xff\xff[^\xff]")


def _find_sync(data: bytes, bit: int) -> int:
    """Bitposition der nächsten Sync-Marke (23 Einsen + 0) ab ``bit``;
    -1, wenn keine mehr kommt."""
    pos = max(0, (bit >> 3) - 3)
    while True:
        m = _SYNC_CANDIDATE.search(data, pos)
        if m is None:
            return -1
        k = m.end() - 1                         # Byte mit der Null
        ones = 8 - ((~data[k]) & 0xFF).bit_length()
        s = 8 * k + ones - 23
        if s >= bit and s >= 0:
            byte, off = divmod(s, 8)
            window = int.from_bytes(data[byte:byte + 5].ljust(5, b"\x00"), "big")
            if (window >> (16 - off)) & 0xFFFFFF == 0xFFFFFE:
                return s
        pos = m.start() + 1


def _decode_deltas(data: bytes, pos: int, tables: list, width: int,
                   height: int) -> tuple[bytearray, bytearray, bytearray, int]:
    """Differenzen einer Stufe ab Byte ``pos``: jede Zeile beginnt mit Sync
    (24 Bit), Ebene (2 Bit: 0 = Y, 2 = C1, 3 = C2), Zeilennummer (13 Bit)
    und einem Füllbit; dann folgen ``width`` (Chroma: ``width/2``)
    Huffman-Codes. Ergebnis: Offset-Byte-Ebenen (0x80 = keine Änderung)
    für Y (width×height) und C1/C2 (halbe Größe) + Endposition."""
    luma = bytearray(b"\x80") * (width * height)
    half = width // 2
    chroma = (bytearray(b"\x80") * (half * (height // 2)),
              bytearray(b"\x80") * (half * (height // 2)))
    bit = 8 * pos
    end = len(data)
    rows = 0
    # Obergrenze: Y + C1 + C2 höchstens je eine Zeile pro Bildzeile (echte
    # Dateien brauchen 2×, Chroma halbiert) — Wiederholungen enden hier.
    while rows <= 3 * height:
        rows += 1
        bit = _find_sync(data, bit)
        if bit < 0:
            break
        byte, off = divmod(bit + 24, 8)
        head = int.from_bytes(data[byte:byte + 3], "big") >> (8 - off) & 0xFFFF
        plane, row = head >> 14, (head >> 1) & 0x1FFF
        if row >= height:
            break
        bit += 40
        if plane == 0:
            target, start, count, table = luma, row * width, width, tables[0]
        elif plane in (2, 3) and len(tables) == 3:
            target = chroma[plane - 2]
            start, count, table = (row >> 1) * half, half, tables[plane - 1]
        else:
            continue                        # unbekannte Ebene: nächste Sync
        lengths, keys = table
        # Heißschleife: 16-Bit-Fenster aus einem Akku, der byteweise
        # nachgefüllt wird.
        byte, off = divmod(bit, 8)
        acc = int.from_bytes(data[byte:byte + 8], "big")
        nbits = 64 - off
        byte += 8
        acc &= (1 << nbits) - 1
        o = start
        stop = start + count
        while o < stop:
            if nbits < 16:
                if byte >= end:
                    break
                acc = (acc << 32) | int.from_bytes(data[byte:byte + 4], "big")
                byte += 4
                nbits += 32
            idx = (acc >> (nbits - 16)) & 0xFFFF
            length = lengths[idx]
            if not length:
                break                       # kein gültiger Code: Resync
            target[o] = keys[idx]
            o += 1
            nbits -= length
            acc &= (1 << nbits) - 1
        bit = 8 * byte - nbits
    return luma, chroma[0], chroma[1], bit >> 3


def _apply(img: Image.Image, deltas: bytearray) -> Image.Image:
    """Pixel + Differenz, auf 0..255 begrenzt (Offset-Byte − 128)."""
    delta = Image.frombytes("L", img.size, bytes(deltas))
    return ImageChops.add(img, delta, 1.0, -128)


def render(source: str | Path, *, max_factor: int = 4) -> Image.Image:
    """Image Pac in der höchsten vorhandenen Stufe (höchstens
    ``max_factor`` × Base) als RGB-Bild, Drehung angewandt."""
    with open(source, "rb") as fh:
        data = fh.read(MAX_BYTES)
    if not is_pcd(data):
        raise PcdError("keine PCD_IPI-Kennung")
    rotation, factor = _attributes(data)
    factor = min(factor, max_factor)
    y, c1, c2 = _read_base(data)
    c1, c2 = upsample(c1), upsample(c2)                 # 768×512
    if factor >= 2:
        y = upsample(y)
        tables, pos = _read_tables(data, FOUR_BASE_SECTOR * SECTOR, 1)
        dy, _, _, end = _decode_deltas(data, pos, tables, 2 * BASE_W, 2 * BASE_H)
        y = _apply(y, dy)
        if factor >= 4:
            stop = int.from_bytes(data[_STOP_4BASE_OFFSET:_STOP_4BASE_OFFSET + 2], "big")
            sector = stop + SIXTEEN_BASE_GAP if stop else end // SECTOR + SIXTEEN_BASE_GAP
            y, c1, c2 = upsample(y), upsample(c1), upsample(c2)
            tables, pos = _read_tables(data, sector * SECTOR, 3)
            dy, d1, d2, _ = _decode_deltas(data, pos, tables, 4 * BASE_W, 4 * BASE_H)
            y, c1, c2 = _apply(y, dy), _apply(c1, d1), _apply(c2, d2)
    while c1.size != y.size:                            # Chroma auf volle Größe
        c1, c2 = upsample(c1), upsample(c2)
    ycc = Image.merge("RGB", (y, c1, c2)).tobytes()
    # PhotoYCC → RGB über Pillows eigenen Entpacker (derselbe wie für Base).
    img = Image.frombytes("RGB", y.size, ycc, "raw", "YCC;P")
    if rotation == 1:
        img = img.transpose(Image.ROTATE_90)
    elif rotation == 2:
        img = img.transpose(Image.ROTATE_180)
    elif rotation == 3:
        img = img.transpose(Image.ROTATE_270)
    return img
