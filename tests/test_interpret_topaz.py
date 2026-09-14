"""Tests für den Topaz-Parser (Schicht 2, Issue #44 / ADR 0066).

Fixtures sind programmatisch gebaute Roh-Einträge (§8) nach den belegten
Community-Dumps: Photo AI (EXIF Software / XMP CreatorTool), Gigapixel
(Einstellungszeile in der Beschreibung, auch XML-escaped im XMP), Video AI
(ffprobe-Tag ``videoai`` inkl. Kette Slowmo + Enhance, MKV-Großschreibung).
"""

from __future__ import annotations

from feral.extract.types import RawMetadataItem
from feral.interpret import registry, topaz


def text_item(source: str, keyword: str, text: str) -> RawMetadataItem:
    return RawMetadataItem(source=source, keyword=keyword, text=text, data=None, encoding="utf-8")


def xmp_item(payload: str) -> RawMetadataItem:
    packet = (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        f"{payload}</rdf:RDF></x:xmpmeta>"
    )
    return text_item("jpeg:info", "xmp", packet)


def fields_of(result) -> dict[str, list[str]]:
    assert result is not None, "Parser hat sich nicht zuständig gefühlt"
    out: dict[str, list[str]] = {}
    for f in result.fields:
        out.setdefault(f.field, []).append(f.value)
    return out


GIGAPIXEL_LINE = (
    "Upscaled with Gigapixel v1.0.7. 1200x593 => 2400x1186 (2x) "
    "Model: High Compression, denoise: 0.2585995509541035, sharpen: 0.41282109356999397."
)


# -- Photo AI ----------------------------------------------------------------------

def test_photo_ai_exif_software():
    items = [text_item("jpeg:exif", "Software", "Topaz Photo AI 3.2.2 (Windows)")]
    result = topaz.parse(items)
    f = fields_of(result)
    assert result.parser == "topaz" and result.parser_version == topaz.VERSION
    assert [i.parser for i in registry.interpret_items(items)] == ["topaz"], "in der Registry"

    assert f["model"] == ["Topaz Photo AI"]
    assert f["tool"] == ["topaz"], "Topaz ist die Plattform (Facette Generator), die Produkte sind die Modelle"
    assert f["topaz_version"] == ["3.2.2"]
    assert "topaz_settings" not in f


def test_photo_ai_xmp_creator_tool_attribute_and_element():
    attr = xmp_item('<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/"'
                    ' xmp:CreatorTool="Topaz Photo AI 2.2.2 (Macintosh)"/>')
    elem = xmp_item('<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/">'
                    "<xmp:CreatorTool>Topaz Photo AI 3.0.1</xmp:CreatorTool></rdf:Description>")
    assert fields_of(topaz.parse([attr]))["topaz_version"] == ["2.2.2"]
    assert fields_of(topaz.parse([elem]))["topaz_version"] == ["3.0.1"]


def test_photo_ai_description_settings_taken_raw():
    items = [
        text_item("jpeg:exif", "Software", "Topaz Photo AI 3.2.2 (Windows)"),
        text_item("jpeg:exif", "ImageDescription", "Sharpen: 0.55, Denoise: 0.30"),
    ]
    f = fields_of(topaz.parse(items))
    assert f["topaz_settings"] == ["Sharpen: 0.55, Denoise: 0.30"]


def test_photo_ai_ignores_a1111_user_comment():
    """Ein von Photo AI bearbeitetes A1111-JPEG: die Parameter im UserComment
    sind KEINE Topaz-Einstellungen (dafür gibt es den A1111-Parser)."""
    items = [
        text_item("jpeg:exif", "Software", "Topaz Photo AI 3.2.2 (Windows)"),
        text_item("jpeg:exif", "UserComment", "a cat\nSteps: 20, Sampler: Euler, Seed: 1"),
    ]
    f = fields_of(topaz.parse(items))
    assert f["model"] == ["Topaz Photo AI"]
    assert "topaz_settings" not in f


# -- Gigapixel ---------------------------------------------------------------------

def test_gigapixel_description_exif():
    f = fields_of(topaz.parse([text_item("jpeg:exif", "ImageDescription", GIGAPIXEL_LINE)]))
    assert f["model"] == ["Topaz Gigapixel"]
    assert f["topaz_version"] == ["1.0.7"]
    assert f["topaz_model"] == ["High Compression"]
    assert f["upscale_factor"] == ["2x"]
    assert f["source_size"] == ["1200x593"]
    assert f["size"] == ["2400x1186"]
    assert f["topaz_settings"] == [GIGAPIXEL_LINE]


def test_gigapixel_description_in_xmp_is_unescaped():
    payload = ('<rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/">'
               "<dc:description><rdf:Alt>"
               '<rdf:li xml:lang="x-default">'
               "Upscaled with Gigapixel v8.3.4. 800x600 =&gt; 3200x2400 (4x) Model: Standard."
               "</rdf:li></rdf:Alt></dc:description></rdf:Description>")
    f = fields_of(topaz.parse([xmp_item(payload)]))
    assert f["model"] == ["Topaz Gigapixel"]
    assert f["upscale_factor"] == ["4x"]
    assert f["topaz_model"] == ["Standard"]
    assert f["source_size"] == ["800x600"] and f["size"] == ["3200x2400"]
    assert "=>" in f["topaz_settings"][0]


def test_gigapixel_without_model_and_png_description_keyword():
    line = "Upscaled with Gigapixel v1.2.0. 512x512 => 1024x1024 (2x)"
    f = fields_of(topaz.parse([text_item("png:tEXt", "Description", line)]))
    assert f["model"] == ["Topaz Gigapixel"]
    assert "topaz_model" not in f
    assert f["upscale_factor"] == ["2x"]


def test_gigapixel_software_plus_description_reports_version_once():
    items = [
        text_item("jpeg:exif", "Software", "Topaz Gigapixel AI 1.0.7"),
        text_item("jpeg:exif", "ImageDescription", GIGAPIXEL_LINE),
    ]
    f = fields_of(topaz.parse(items))
    assert f["model"] == ["Topaz Gigapixel"]
    assert f["topaz_version"] == ["1.0.7"]


# -- Video AI ----------------------------------------------------------------------

def test_video_ai_single_enhance():
    tag = ("Enhanced using prob-3 with recover details at 43, dehalo at 15, reduce noise "
           "at 15, sharpen at 35, revert compression at 28, and anti-alias/deblur at 6. "
           "Changed resolution to 1266x960")
    f = fields_of(topaz.parse([text_item("mp4:format.tag", "videoai", tag)]))
    assert f["model"] == ["Topaz Video AI"]
    assert f["topaz_model"] == ["prob-3"]
    assert f["size"] == ["1266x960"]
    assert f["topaz_settings"] == [tag]


def test_video_ai_chain_and_mkv_uppercase_tag():
    tag = ("Slowmo 400% and framerate changed to 29.97 using chr-2 ignoring duplicate "
           "frames. Enhanced using prob-3 auto with recover details at 0; dehalo at 0. "
           "and recover original detail at 20")
    f = fields_of(topaz.parse([text_item("matroska:format.tag", "VIDEOAI", tag)]))
    assert f["model"] == ["Topaz Video AI"]
    assert f["topaz_model"] == ["chr-2", "prob-3"]
    assert "size" not in f


def test_video_ai_short_form():
    f = fields_of(topaz.parse([text_item("mov:format.tag", "videoai",
                                         "Enhanced using ahq-12. Changed resolution to 2848x2160")]))
    assert f["topaz_model"] == ["ahq-12"] and f["size"] == ["2848x2160"]


# -- Nicht zuständig ---------------------------------------------------------------

def test_not_responsible_for_prompt_mentions_and_other_software():
    items = [
        text_item("png:tEXt", "parameters", "photo restored with Topaz Photo AI 3.0.0 look\nSteps: 20"),
        text_item("jpeg:exif", "Software", "Adobe Photoshop 25.7 (Windows)"),
        text_item("jpeg:exif", "ImageDescription", "Upscaled with love"),
        text_item("mp4:format.tag", "encoder", "Lavf60.3.100"),
    ]
    assert topaz.parse(items) is None
    assert topaz.parse([]) is None
