"""Tests für den Container-Dispatcher (Magic-Byte-Erkennung + Delegation)."""

from __future__ import annotations

import pytest

from feral.extract import container
from feral.extract.container import (
    ExtractorNotImplementedError,
    UnknownContainerError,
    sniff_container,
)

from .pngbuild import build_png, text_chunk


def test_sniff_known_formats():
    assert sniff_container(b"\x89PNG\r\n\x1a\n....") == "png"
    assert sniff_container(b"\xff\xd8\xff\xe0somejpeg") == "jpeg"
    assert sniff_container(b"RIFF\x00\x00\x00\x00WEBPdata") == "webp"
    assert sniff_container(b"GIF89a....") == "gif"
    assert sniff_container(b"BM........") == "bmp"
    assert sniff_container(b"II\x2a\x00....") == "tiff"
    assert sniff_container(b"\x1a\x45\xdf\xa3....") == "matroska"
    assert sniff_container(b"\x00\x00\x00\x18ftypisom") == "isobmff"
    assert sniff_container(b"8BPS....") == "psd"
    assert sniff_container(b"%PDF-1.7") == "pdf"


def test_sniff_unknown_returns_none():
    assert sniff_container(b"completely unknown bytes") is None


def test_extract_dispatches_png(tmp_path):
    path = tmp_path / "image.png"
    path.write_bytes(build_png(text_chunk("parameters", "hallo")))
    result = container.extract(path)
    assert result.container == "png"
    assert result.items[0].keyword == "parameters"


def test_extract_recognized_but_unimplemented_raises(tmp_path):
    # Gültige PDF-Signatur, aber bewusst kein Extraktor (ADR 0051).
    path = tmp_path / "papier.pdf"
    path.write_bytes(b"%PDF-1.4\n" + b"\x00" * 20)
    with pytest.raises(ExtractorNotImplementedError) as exc:
        container.extract(path)
    assert exc.value.container == "pdf"


def test_extract_unknown_container_raises(tmp_path):
    path = tmp_path / "mystery.bin"
    path.write_bytes(b"no known magic bytes here")
    with pytest.raises(UnknownContainerError):
        container.extract(path)


def test_sniff_cr2_and_tiff_raw_refinement(tmp_path):
    from feral.extract.container import (
        ExtractorNotImplementedError, extract, sniff_container,
    )

    # Canon CR2 hat einen eigenen Marker im TIFF-Header (rein über Magic Bytes).
    assert sniff_container(b"II\x2a\x00\x10\x00\x00\x00CR\x02\x00....") == "cr2"
    # Sony ARW ist byte-identisch zu TIFF — hier verfeinert die Endung.
    arw = tmp_path / "foto.arw"
    arw.write_bytes(b"II\x2a\x00" + b"\x00" * 64)
    with pytest.raises(ExtractorNotImplementedError) as exc:
        extract(arw)
    assert exc.value.container == "arw"
