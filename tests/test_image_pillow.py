"""Tests für den Pillow-Bild-Extraktor (Schicht 1, ADR 0008).

Fixtures werden programmatisch mit Pillow erzeugt (Projektregel: Fixtures programmatisch): bekannte
Metadaten rein → unveränderte Roh-Einträge raus.
"""

from __future__ import annotations

import pytest
from PIL import Image

from feral.extract import container, image_pillow

EXIF_STUB = b"MM\x00\x2a\x00\x00\x00\x08"  # minimaler TIFF-Header als EXIF-Platzhalter
XMP_STUB = b'<?xpacket begin=""?><x:xmpmeta xmlns:x="adobe:ns:meta/"/>'


def _new_image() -> Image.Image:
    return Image.new("RGB", (4, 4), color=(255, 84, 112))


def test_webp_exif_and_xmp_roundtrip(tmp_path):
    path = tmp_path / "bild.webp"
    _new_image().save(path, "WEBP", exif=EXIF_STUB, xmp=XMP_STUB)

    # Der EXIF-Stub ist absichtlich unvollständig (nur TIFF-Header, kein IFD):
    # Pillow warnt beim Deuten, die Extraktion muss trotzdem sauber durchlaufen.
    with pytest.warns(UserWarning, match="Corrupt EXIF"):
        result = image_pillow.extract(path, container="webp")

    assert result.container == "webp"
    assert result.warnings == []
    by_keyword = {i.keyword: i for i in result.items}
    assert by_keyword["exif"].data is not None
    assert by_keyword["exif"].encoding == "binary"
    assert EXIF_STUB in by_keyword["exif"].data  # WEBP kapselt ggf. mit Exif-Präfix
    assert by_keyword["xmp"].data == XMP_STUB
    assert all(i.source == "webp:info" for i in result.items)


def test_gif_comment_extracted_as_metadata(tmp_path):
    path = tmp_path / "anim.gif"
    _new_image().save(path, "GIF", comment=b"made with comfyui")

    result = image_pillow.extract(path, container="gif")

    comments = [i for i in result.items if i.keyword == "comment"]
    assert len(comments) == 1
    value = comments[0].data if comments[0].data is not None else comments[0].text.encode()
    assert value == b"made with comfyui"


def test_jpeg_without_metadata_yields_no_text_items(tmp_path):
    path = tmp_path / "plain.jpg"
    _new_image().save(path, "JPEG")

    result = image_pillow.extract(path, container="jpeg")

    assert result.warnings == []
    # JPEG ohne eingebettete Metadaten: höchstens technische Info-Werte (jfif, dpi …).
    assert all(i.source == "jpeg:info" for i in result.items)


def test_corrupt_file_warns_instead_of_raising(tmp_path):
    path = tmp_path / "kaputt.webp"
    path.write_bytes(b"RIFF\x00\x00\x00\x00WEBP" + b"\xff" * 8)  # Magic ok, Rest Müll

    result = image_pillow.extract(path, container="webp")

    assert result.items == []
    assert result.warnings  # Warnung statt Ausnahme (defensiver Extraktor)


def test_dispatcher_routes_webp_to_pillow(tmp_path):
    path = tmp_path / "bild.webp"
    _new_image().save(path, "WEBP", exif=EXIF_STUB)

    with pytest.warns(UserWarning, match="Corrupt EXIF"):  # s. Roundtrip-Test
        result = container.extract(path)

    assert result.container == "webp"
    assert any(i.keyword == "exif" for i in result.items)


def _comfy_webp(tmp_path):
    """WEBP mit ComfyUI-typischem EXIF: Model="prompt:{…}", Make="workflow:{…}"."""
    from PIL import Image

    path = tmp_path / "comfy.webp"
    exif = Image.Exif()
    exif[0x0110] = 'prompt:{"5": {"class_type": "KSampler", "inputs": {"seed": 7}}}'
    exif[0x010F] = 'workflow:{"nodes": [], "links": []}'
    _new_image().save(path, "WEBP", exif=exif)
    return path


def test_webp_exif_text_tags_become_readable_items(tmp_path):
    """EXIF-String-Tags werden zusätzlich als Text-Einträge abgelegt (ADR 0016);
    ComfyUIs eingebettete Labels (prompt:/workflow:) werden zum Keyword."""
    result = image_pillow.extract(_comfy_webp(tmp_path), container="webp")

    by_kw = {i.keyword: i for i in result.items if i.text is not None}
    assert "prompt" in by_kw and "workflow" in by_kw
    assert by_kw["prompt"].text.startswith('{"5"')          # Präfix abgetrennt
    assert by_kw["workflow"].source == "webp:exif.Make"     # Quell-Label = EXIF-Tag
    # Der komplette EXIF-Block bleibt zusätzlich als Binär-Eintrag erhalten.
    assert any(i.keyword == "exif" and i.data is not None for i in result.items)


def test_webp_exif_plain_text_tag_keeps_tag_name(tmp_path):
    """Normale EXIF-Textfelder (ohne ComfyUI-Präfix) behalten den Tag-Namen."""
    from PIL import Image

    path = tmp_path / "plain-exif.webp"
    exif = Image.Exif()
    exif[0x0131] = "TestSoftware 1.0"  # Software
    _new_image().save(path, "WEBP", exif=exif)

    result = image_pillow.extract(path, container="webp")

    software = [i for i in result.items if i.keyword == "Software"]
    assert software and software[0].text == "TestSoftware 1.0"
    assert software[0].source == "webp:exif"


# -- C2PA-Manifeste (ADR 0066): JPEG-APP11 und WebP-RIFF-Chunk ------------------

JUMBF_HEAD = b"\x00\x00\x00\x00jumb"   # LBox (Platzhalter) + TBox


def _app11(instance: int, sequence: int, body: bytes) -> bytes:
    """Ein APP11-Segment nach JUMBF-in-JPEG: FF EB | Länge | 'JP' | En | Z | Body."""
    import struct
    payload = b"JP" + struct.pack(">HI", instance, sequence) + body
    return b"\xff\xeb" + struct.pack(">H", len(payload) + 2) + payload


def _jpeg_with_segments(path, *segments: bytes) -> None:
    import io
    buf = io.BytesIO()
    _new_image().save(buf, "JPEG")
    raw = buf.getvalue()
    assert raw[:2] == b"\xff\xd8"
    path.write_bytes(raw[:2] + b"".join(segments) + raw[2:])


def test_jpeg_app11_segments_assembled_in_sequence_order(tmp_path):
    path = tmp_path / "cc.jpg"
    first = JUMBF_HEAD + b"\x00\x00\x00\x10jumdc2pa-TEIL-EINS-"
    second = b"TEIL-ZWEI-claim_generator"
    # Fortsetzung wiederholt den 8-Byte-Superbox-Kopf; in der Datei steht sie
    # absichtlich VOR dem ersten Paket (die Spec erlaubt beliebige Reihenfolge).
    _jpeg_with_segments(
        path,
        _app11(1, 2, JUMBF_HEAD + second),
        _app11(1, 1, first),
        b"\xff\xeb\x00\x08XT1234",           # fremdes APP11 ohne 'JP' — bleibt außen vor
    )

    result = image_pillow.extract(path, container="jpeg")

    assert result.warnings == []
    c2pa = [i for i in result.items if i.source == "jpeg:APP11"]
    assert len(c2pa) == 1
    assert c2pa[0].data == first + second
    assert c2pa[0].encoding == "binary" and c2pa[0].keyword is None


def test_jpeg_app11_two_box_instances_stay_separate(tmp_path):
    path = tmp_path / "zwei.jpg"
    _jpeg_with_segments(path, _app11(1, 1, JUMBF_HEAD + b"A"), _app11(2, 1, JUMBF_HEAD + b"B"))

    result = image_pillow.extract(path, container="jpeg")

    assert [i.data for i in result.items if i.source == "jpeg:APP11"] == [
        JUMBF_HEAD + b"A", JUMBF_HEAD + b"B",
    ]


def test_jpeg_without_app11_has_no_c2pa_item(tmp_path):
    path = tmp_path / "plain.jpg"
    _new_image().save(path, "JPEG")
    result = image_pillow.extract(path, container="jpeg")
    assert not [i for i in result.items if i.source == "jpeg:APP11"]


def _webp_with_chunk(path, fourcc: bytes, data: bytes) -> None:
    import struct
    raw = bytearray()
    import io
    buf = io.BytesIO()
    _new_image().save(buf, "WEBP")
    raw += buf.getvalue()
    chunk = fourcc + struct.pack("<I", len(data)) + data + (b"\x00" if len(data) & 1 else b"")
    raw += chunk
    raw[4:8] = struct.pack("<I", len(raw) - 8)   # RIFF-Gesamtlänge nachziehen
    path.write_bytes(bytes(raw))


def test_webp_c2pa_riff_chunk_extracted_with_odd_length_padding(tmp_path):
    path = tmp_path / "cc.webp"
    manifest = JUMBF_HEAD + b"jumdc2pa-ungerade"   # ungerade Länge → Polsterbyte
    assert len(manifest) & 1
    _webp_with_chunk(path, b"C2PA", manifest)

    result = image_pillow.extract(path, container="webp")

    c2pa = [i for i in result.items if i.source == "webp:C2PA"]
    assert len(c2pa) == 1
    assert c2pa[0].data == manifest                # ohne Polsterbyte, byte-treu
    assert c2pa[0].encoding == "binary"
    # Die normalen Pillow-Einträge sind weiterhin da (Bild bleibt lesbar).
    assert result.width == 4 and result.warnings == []


def test_webp_foreign_riff_chunk_is_ignored(tmp_path):
    path = tmp_path / "fremd.webp"
    _webp_with_chunk(path, b"XYZW", b"irrelevant")
    result = image_pillow.extract(path, container="webp")
    assert not [i for i in result.items if i.source == "webp:C2PA"]
