"""Kodak Photo CD (#208): Erkennung, Schicht 1, Decoder bis 16Base.

Fixtures werden programmatisch gebaut (keine Binärdateien): IPI-Kopf, Base als
PhotoYCC, dazu Huffman-Tabellen und Differenz-Bitströme nach dem Aufbau,
den ``pcd.py`` beschreibt.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from feral.extract import container, pcd
from feral.thumbs import generate_thumbnail, render_preview

SECTOR = pcd.SECTOR
SCAN_TIME = 844_128_000            # 1996-10-01 00:00:00 UTC

# Huffman-Tabelle der Tests: '0' → 0, '10' → +5, '11' → −3.
_CODES = {0: "0", 5: "10", -3: "11"}


def _table() -> bytes:
    out = bytearray([len(_CODES) - 1])
    for key, code in _CODES.items():
        seq = int(code.ljust(16, "0"), 2)
        out += bytes([len(code) - 1, seq >> 8, seq & 0xFF, key & 0xFF])
    return bytes(out)


def _row(plane: int, row: int, deltas: list[int]) -> str:
    """Sync (23 Einsen + 0), Ebene, Zeile, Füllbit, Codes, Byte-Auffüllung."""
    bits = "1" * 23 + "0" + format(plane, "02b") + format(row, "013b") + "0"
    bits += "".join(_CODES[d] for d in deltas)
    return bits + "0" * (-len(bits) % 8)


def _bits(bits: str) -> bytes:
    return int(bits, 2).to_bytes(len(bits) // 8, "big") if bits else b""


def _section(tables: int, rows: list[tuple[int, int, list[int]]], height: int) -> bytes:
    """Tabellen + Zeilen + End-Sync (Zeile == Höhe)."""
    stream = "".join(_row(p, r, d) for p, r, d in rows) + _row(0, height, [])
    return _table() * tables + b"\x00\x00" + _bits(stream)


def make_pcd(path: Path, *, level: int = 2, rotation: int = 0,
             luma=lambda x, y: 100, c1: int = 156, c2: int = 137,
             rows4: list | None = None, rows16: list | None = None) -> Path:
    data = bytearray(b"\xff" * SECTOR)
    ipi = bytearray(0xE10 - SECTOR)
    ipi[0:7] = b"PCD_IPI"
    ipi[0x0D:0x11] = SCAN_TIME.to_bytes(4, "big")
    ipi[0x11:0x15] = SCAN_TIME.to_bytes(4, "big")
    ipi[0x2A:0x2F] = b"KODAK"
    ipi[0x3E:0x4E] = b"FilmScanner 2000"
    ipi[0xA5:0xB0] = b"Fotolabor A"
    data += ipi
    data += bytes(pcd.BASE_SECTOR * SECTOR - len(data))
    for y in range(0, pcd.BASE_H, 2):
        for yy in (y, y + 1):
            data += bytes(luma(x, yy) for x in range(pcd.BASE_W))
        data += bytes([c1]) * (pcd.BASE_W // 2) + bytes([c2]) * (pcd.BASE_W // 2)
    if level >= 1:
        data += b"\xff" * (pcd.FOUR_BASE_SECTOR * SECTOR - len(data))
        data += _section(1, rows4 or [], 2 * pcd.BASE_H)
        data += b"\xff" * (-len(data) % SECTOR)
    stop = len(data) // SECTOR
    if level >= 2:
        data += b"\xff" * ((stop + pcd.SIXTEEN_BASE_GAP) * SECTOR - len(data))
        data += _section(3, rows16 or [], 4 * pcd.BASE_H)
    data[0xE02] = rotation | (level << 2)
    data[0xE03:0xE05] = stop.to_bytes(2, "big")
    path.write_bytes(bytes(data))
    return path


def _luma(img: Image.Image) -> Image.Image:
    return img.convert("YCbCr").split()[0]


# --- Erkennung + Schicht 1 --------------------------------------------------

def test_sniff_needs_signature_at_2048():
    head = b"\xff" * SECTOR + b"PCD_IPI"
    assert container.sniff_container(head) == "pcd"
    # Nur die 0xFF-Füllung (ohne Kennung) ist KEIN PCD.
    assert container.sniff_container(b"\xff" * (SECTOR + 7)) != "pcd"


def test_extract_ipi_fields_and_dimensions(tmp_path):
    result = container.extract(make_pcd(tmp_path / "a.pcd"))
    assert result.container == "pcd" and result.media_kind == "image"
    assert (result.width, result.height) == (3072, 2048)
    texts = {i.keyword: i.text for i in result.items if i.text}
    assert texts["scanner_vendor"] == "KODAK"
    assert texts["scanner_product"] == "FilmScanner 2000"
    assert texts["photofinisher"] == "Fotolabor A"
    # Scanzeit speist die Datums-Kaskade (Schlüssel wie EXIF/XMP).
    assert texts["CreateDate"] == "1996:10:01 00:00:00"
    raw = [i for i in result.items if i.data is not None]
    assert raw and raw[0].source == "pcd:ipi" and raw[0].data.startswith(b"PCD_IPI")


def test_extract_rotation_swaps_dimensions(tmp_path):
    result = pcd.extract(make_pcd(tmp_path / "r.pcd", level=1, rotation=1))
    assert (result.width, result.height) == (1024, 1536)


def test_extract_truncated_file_warns(tmp_path):
    path = tmp_path / "kurz.pcd"
    path.write_bytes(b"\xff" * SECTOR + b"PCD_IPI" + b"\x00" * 10)
    result = pcd.extract(path)
    assert result.warnings and result.width is None


# --- Decoder ----------------------------------------------------------------

def test_upsample_matches_kodak_interpolation():
    img = Image.frombytes("L", (2, 2), bytes([10, 20, 30, 50]))
    out = pcd.upsample(img).tobytes()
    assert list(out) == [10, 15, 20, 20,
                         20, 28, 35, 35,
                         30, 40, 50, 50,
                         30, 40, 50, 50]


def test_apply_clips():
    img = Image.frombytes("L", (2, 1), bytes([250, 3]))
    deltas = bytearray([10 ^ 0x80, (-5 & 0xFF) ^ 0x80])
    assert list(pcd._apply(img, deltas).tobytes()) == [255, 0]


def test_base_matches_pillow(tmp_path):
    path = make_pcd(tmp_path / "b.pcd", level=0, luma=lambda x, y: (x + y) % 256)
    ours = pcd.render(path)
    with Image.open(path) as pillow:
        assert ours.size == pillow.size == (768, 512)
        assert ours.tobytes() == pillow.convert("RGB").tobytes()


def test_4base_luma_deltas(tmp_path):
    width = 2 * pcd.BASE_W
    path = make_pcd(tmp_path / "d.pcd", level=1,
                    rows4=[(0, 0, [5] * width), (0, 7, [-3] * width)])
    y = _luma(pcd.render(path))
    assert y.size == (1536, 1024)
    flat = _luma(pcd.render(make_pcd(tmp_path / "flat.pcd", level=1)))
    px, ref = y.getpixel((40, 0)), flat.getpixel((40, 0))
    assert px > ref                                   # Zeile 0: +5
    assert y.getpixel((40, 7)) < ref                  # Zeile 7: −3
    assert y.getpixel((40, 3)) == ref                 # ohne Differenz


def test_16base_all_planes_and_rotation(tmp_path):
    width = 4 * pcd.BASE_W
    rows16 = [(0, 10, [5] * width), (2, 20, [5] * (width // 2)),
              (3, 20, [-3] * (width // 2))]
    path = make_pcd(tmp_path / "s.pcd", rows16=rows16)
    img = pcd.render(path)
    assert img.size == (3072, 2048)
    flat = pcd.render(make_pcd(tmp_path / "flat.pcd"))
    assert img.getpixel((100, 10)) != flat.getpixel((100, 10))
    assert img.getpixel((100, 20)) != flat.getpixel((100, 20))   # Chroma-Zeile 10
    assert img.getpixel((100, 100)) == flat.getpixel((100, 100))
    rotated = pcd.render(make_pcd(tmp_path / "rot.pcd", rotation=1))
    assert rotated.size == (2048, 3072)


def test_render_limits_level(tmp_path):
    path = make_pcd(tmp_path / "m.pcd")
    assert pcd.render(path, max_factor=1).size == (768, 512)
    assert pcd.render(path, max_factor=2).size == (1536, 1024)


# --- Anzeige + Thumbnails ---------------------------------------------------

def test_preview_16base_and_thumbnail(tmp_path):
    path = make_pcd(tmp_path / "v.pcd")
    data, reason = render_preview(path)
    assert reason == "" and Image.open(io.BytesIO(data)).size == (3072, 2048)
    thumb = tmp_path / "t.jpg"
    assert generate_thumbnail(path, thumb, media_kind="image", size=320)
    assert Image.open(thumb).size == (320, 213)


def test_preview_endpoint_stores_png_once(tmp_path):
    from feral.db.database import connect
    from feral.extract import container as ct
    from feral.db.store import store_extraction
    from feral.hashing import hash_file
    from feral.web.app import create_app

    path = make_pcd(tmp_path / "e.pcd")
    db = tmp_path / "t.sqlite"
    file_hash = hash_file(path)
    conn = connect(db)
    with conn:
        store_extraction(conn, file_hash=file_hash, file_size=path.stat().st_size,
                         path=path, extraction=ct.extract(path), now="2026-09-25T00:00:00")
    conn.close()
    app = create_app(db, thumb_cache=tmp_path / "thumbs", preview_cache=tmp_path / "prev")
    try:
        route = next(r for r in app.routes if getattr(r, "path", "") == "/api/preview/{file_hash}")
        first = route.endpoint(file_hash)
        cached = tmp_path / "prev" / file_hash[:2] / f"{file_hash}.png"
        assert Path(first.path) == cached and first.media_type == "image/png"
        assert Image.open(cached).size == (3072, 2048)
        stamp = cached.stat().st_mtime_ns
        assert Path(route.endpoint(file_hash).path) == cached
        assert cached.stat().st_mtime_ns == stamp      # nicht neu gerechnet
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


# --- Robustheit gegen präparierte Dateien (Release-QA 2026.09.3) -----------

def test_find_sync_matches_bitwise_reference():
    import random
    rnd = random.Random(7)

    def reference(data, bit):
        for s in range(bit, 8 * len(data) - 23):
            byte, off = divmod(s, 8)
            window = int.from_bytes(data[byte:byte + 5].ljust(5, b"\x00"), "big")
            if (window >> (16 - off)) & 0xFFFFFF == 0xFFFFFE:
                return s
        return -1

    for _ in range(300):
        bits = "".join(rnd.choice("01") for _ in range(rnd.randrange(0, 200)))
        bits += "1" * 23 + "0" + "".join(rnd.choice("01") for _ in range(rnd.randrange(0, 60)))
        bits += "0" * (-len(bits) % 8)
        data = _bits(bits) + b"\xff" * rnd.randrange(0, 4)
        start = rnd.randrange(0, 40)
        assert pcd._find_sync(data, start) == reference(data, start)


def test_hostile_files_end_quickly(tmp_path):
    import random
    import time
    # Lauter 0xFF hinter dem Kopf: keine Sync-Marke, darf nicht kriechen.
    ff = bytearray(b"\xff" * (8 * 1024 * 1024))
    ff[pcd.IPI_OFFSET:pcd.IPI_OFFSET + 7] = b"PCD_IPI"
    ff[0xE02] = 0x08
    (tmp_path / "ff.pcd").write_bytes(bytes(ff))
    t = time.monotonic()
    try:
        pcd.render(tmp_path / "ff.pcd")
    except ValueError:
        pass
    assert time.monotonic() - t < 10
    # Zufällig verbogene echte Struktur: endet, wirft höchstens ValueError.
    good = make_pcd(tmp_path / "g.pcd", rows4=[(0, 0, [5] * 1536)],
                    rows16=[(0, 1, [5] * 3072)]).read_bytes()
    rnd = random.Random(11)
    for i in range(25):
        bad = bytearray(good[:rnd.randrange(pcd.SECTOR * 97, len(good) + 1)])
        for _ in range(rnd.randrange(1, 64)):
            bad[rnd.randrange(pcd.SECTOR, len(bad))] = rnd.randrange(256)
        path = tmp_path / f"bad{i}.pcd"
        path.write_bytes(bytes(bad))
        try:
            pcd.render(path)
        except ValueError:
            pass
        assert pcd.extract(path).container == "pcd"
