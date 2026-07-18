"""Tests für den XMP-Parser (Schicht 2): Midjourney, Google AI, Lightroom-Rating."""

from __future__ import annotations

from feral.extract.types import RawMetadataItem
from feral.interpret import xmp


def xmp_item(payload: str, *, as_bytes: bool = False) -> RawMetadataItem:
    packet = (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        f'<x:xmpmeta xmlns:x="adobe:ns:meta/">{payload}</x:xmpmeta>'
        '<?xpacket end="w"?>'
    )
    if as_bytes:
        return RawMetadataItem(
            source="webp:info", keyword="xmp", text=None,
            data=packet.encode("utf-8"), encoding="binary",
        )
    return RawMetadataItem(
        source="png:iTXt", keyword="XML:com.adobe.xmp", text=packet,
        data=None, encoding="utf-8",
    )


RDF = '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">{}</rdf:RDF>'


def _fields(result):
    out: dict[str, list[str]] = {}
    for f in result.fields:
        out.setdefault(f.field, []).append(f.value)
    return out


def test_midjourney_description_as_element():
    payload = RDF.format(
        '<rdf:Description rdf:about=""'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:description><rdf:Alt>"
        '<rdf:li xml:lang="x-default">a decayed planet logo, hyperdetailed'
        " Job ID: 1934f302-2790-4564-bdb0-26b9e6040fcb</rdf:li>"
        "</rdf:Alt></dc:description></rdf:Description>"
    )
    result = xmp.parse([xmp_item(payload)])

    fields = _fields(result)
    assert fields["tool"] == ["midjourney"]
    assert fields["prompt"] == ["a decayed planet logo, hyperdetailed"]
    assert fields["job_id"] == ["1934f302-2790-4564-bdb0-26b9e6040fcb"]
    assert "description" not in fields  # als Prompt erkannt, nicht doppelt


def test_google_ai_credit_and_iptc_marker_as_attributes():
    payload = RDF.format(
        '<rdf:Description rdf:about=""'
        ' xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/"'
        ' xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"'
        ' Iptc4xmpExt:DigitalSourceType='
        '"http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"'
        ' photoshop:Credit="Made with Google AI"/>'
    )
    result = xmp.parse([xmp_item(payload)])

    fields = _fields(result)
    assert fields["credit"] == ["Made with Google AI"]
    assert fields["ai_source_type"] == ["trainedAlgorithmicMedia"]  # URI gekürzt
    assert "tool" not in fields  # keine Midjourney-Signatur → nichts erfinden


def test_lightroom_rating_and_creator_tool():
    payload = RDF.format(
        '<rdf:Description rdf:about=""'
        ' xmlns:xmp="http://ns.adobe.com/xap/1.0/"'
        ' xmp:CreatorTool="Adobe Photoshop 25.0 (Macintosh)" xmp:Rating="4"/>'
    )
    fields = _fields(xmp.parse([xmp_item(payload)]))
    assert fields["rating"] == ["4"]
    assert fields["creator_tool"] == ["Adobe Photoshop 25.0 (Macintosh)"]


def test_plain_description_stays_description():
    payload = RDF.format(
        '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:description><rdf:Alt>"
        '<rdf:li xml:lang="x-default">nur eine Bildunterschrift</rdf:li>'
        "</rdf:Alt></dc:description></rdf:Description>"
    )
    fields = _fields(xmp.parse([xmp_item(payload)]))
    assert fields["description"] == ["nur eine Bildunterschrift"]
    assert "prompt" not in fields and "tool" not in fields


def test_binary_xmp_from_webp_is_read():
    payload = RDF.format(
        '<rdf:Description rdf:about=""'
        ' xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"'
        ' photoshop:Credit="Edited with Google AI"/>'
    )
    fields = _fields(xmp.parse([xmp_item(payload, as_bytes=True)]))
    assert fields["credit"] == ["Edited with Google AI"]


def test_not_applicable_without_xmp():
    item = RawMetadataItem(
        source="png:tEXt", keyword="parameters", text="Steps: 20",
        data=None, encoding="latin-1",
    )
    assert xmp.parse([item]) is None


def test_broken_xml_is_not_a_crash():
    broken = xmp_item("<rdf:RDF><kaputt")
    assert xmp.parse([broken]) is None


def test_empty_packet_yields_none():
    assert xmp.parse([xmp_item(RDF.format('<rdf:Description rdf:about=""/>'))]) is None


def test_billion_laughs_dtd_is_refused_not_expanded():
    """XMP mit interner Entity-Expansion („billion laughs") wird übergangen,
    nicht expandiert (Härtung ADR 0032) — das XML stammt aus fremden Dateien."""
    bomb = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE x:xmpmeta ['
        '<!ENTITY a "aaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
        '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
        ']>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<rdf:Description rdf:about="" dc:description="&c;"/>'
        '</rdf:RDF></x:xmpmeta>'
    )
    item = RawMetadataItem(
        source="png:iTXt", keyword="XML:com.adobe.xmp", text=bomb,
        data=None, encoding="utf-8",
    )
    assert xmp.parse([item]) is None  # kein Absturz, keine Expansion


def test_normal_packet_still_parses_after_hardening():
    """Gegenprobe: ein DTD-freies (legitimes) Paket funktioniert unverändert."""
    payload = RDF.format(
        '<rdf:Description rdf:about=""'
        ' xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"'
        ' photoshop:Credit="Made with Google AI"/>'
    )
    assert _fields(xmp.parse([xmp_item(payload)]))["credit"] == ["Made with Google AI"]
