"""Tests für den PSD-Extraktor (Schicht 1, ADR 0052)."""

from __future__ import annotations

import io

from feral.extract import container, psd

from .psdbuild import build_psd, resource, version_info

_XMP = (
    '<?xpacket begin=""?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
    "</x:xmpmeta><?xpacket end=\"w\"?>"
)


def test_extracts_header_and_known_resources():
    data = build_psd(
        resource(0x0424, _XMP.encode("utf-8")),          # XMP
        resource(0x0422, b"II*\x00exif"),                # EXIF (binär)
        resource(0x040F, b"\x00\x01icc"),                # ICC-Profil
        width=4, height=3,
    )
    result = psd.extract(io.BytesIO(data))

    assert result.container == "psd"
    assert result.warnings == []
    assert (result.width, result.height) == (4, 3)
    by_keyword = {i.keyword: i for i in result.items}
    assert by_keyword["color_mode"].text == "rgb"
    assert by_keyword["xmp"].text == _XMP
    assert by_keyword["xmp"].source == "psd:8bim"
    assert by_keyword["exif"].data == b"II*\x00exif"
    assert by_keyword["exif"].encoding == "binary"
    assert by_keyword["icc_profile"].data == b"\x00\x01icc"


def test_unknown_resources_are_skipped_padding_intact():
    # Ungerade Datenlänge vor einem bekannten Block: die Polsterung muss
    # stimmen, sonst verrutscht der Walker.
    data = build_psd(
        resource(0x0409, b"\x01\x02\x03"),               # Thumbnail: uninteressant
        resource(0x0424, _XMP.encode("utf-8"), name=b"abc"),
    )
    result = psd.extract(io.BytesIO(data))

    assert result.warnings == []
    keywords = [i.keyword for i in result.items if i.source == "psd:8bim"]
    assert keywords == ["xmp"]


def test_truncated_file_warns_instead_of_raising():
    data = build_psd(resource(0x0424, _XMP.encode("utf-8")))
    result = psd.extract(io.BytesIO(data[:40]))          # mitten in den Ressourcen

    assert result.warnings
    assert result.container == "psd"


def test_garbage_signature_warns():
    result = psd.extract(io.BytesIO(b"NOPE" + b"\x00" * 30))
    assert result.warnings
    assert result.items == []


def test_invalid_utf8_xmp_falls_back_to_binary():
    data = build_psd(resource(0x0424, b"\xff\xfe kein utf-8"))
    result = psd.extract(io.BytesIO(data))

    (item,) = [i for i in result.items if i.keyword == "xmp"]
    assert item.data == b"\xff\xfe kein utf-8"
    assert item.encoding == "binary"
    assert result.warnings


def test_has_real_composite_flag(tmp_path):
    # ADR 0052: „Maximale Kompatibilität" aus ⇒ hasRealMergedData=False.
    with_composite = tmp_path / "mit.psd"
    with_composite.write_bytes(build_psd(version_info(True)))
    without = tmp_path / "ohne.psd"
    without.write_bytes(build_psd(version_info(False)))

    assert psd.has_real_composite(with_composite) is True
    assert psd.has_real_composite(without) is False


def test_has_real_composite_defaults_true_without_version_info(tmp_path):
    # Alte/fremde PSDs ohne Version-Info-Ressource: im Zweifel anzeigen.
    plain = tmp_path / "alt.psd"
    plain.write_bytes(build_psd(resource(0x0424, _XMP.encode("utf-8"))))
    assert psd.has_real_composite(plain) is True


def test_has_real_composite_survives_garbage(tmp_path):
    junk = tmp_path / "kaputt.psd"
    junk.write_bytes(b"NOPE")
    assert psd.has_real_composite(junk) is True   # nicht verstecken bei Unklarheit


def test_container_dispatch_uses_psd_extractor(tmp_path):
    path = tmp_path / "bild.psd"
    path.write_bytes(build_psd(resource(0x0424, _XMP.encode("utf-8"))))

    result = container.extract(path)
    assert result.container == "psd"
    assert any(i.keyword == "xmp" for i in result.items)
