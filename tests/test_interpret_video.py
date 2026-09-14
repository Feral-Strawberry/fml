"""Tests für den Video-Parser (Schicht 2, Issue #71 / ADR 0070).

Fixtures sind programmatisch gebaute Roh-Einträge (§8), wie sie der
ffprobe-Extraktor unter ``isobmff:streamN`` ablegt. Dazu die Einschätzung
``browser_support`` und das daraus abgeleitete Scan-Problem.
"""

from __future__ import annotations

from feral.extract.types import RawMetadataItem
from feral.interpret import registry, video
from feral.interpret.types import InterpretedField, Interpretation


def fact(stream: int, keyword: str, text: str, container: str = "isobmff") -> RawMetadataItem:
    return RawMetadataItem(source=f"{container}:stream{stream}", keyword=keyword,
                           text=text, data=None, encoding="utf-8")


def tag(stream: int, keyword: str, text: str) -> RawMetadataItem:
    return RawMetadataItem(source=f"isobmff:stream{stream}.tag", keyword=keyword,
                           text=text, data=None, encoding="utf-8")


PRORES_MOV = [
    fact(0, "codec_type", "audio"), fact(0, "codec_name", "aac"),
    fact(1, "codec_type", "video"), fact(1, "codec_name", "prores"),
    fact(1, "codec_tag_string", "apch"), fact(1, "profile", "HQ"),
    fact(1, "pix_fmt", "yuv422p10le"), fact(1, "width", "3840"),
    tag(1, "encoder", "Apple ProRes 422 HQ"),
]


def fields_of(result) -> dict[str, list[str]]:
    assert result is not None, "Parser hat sich nicht zuständig gefühlt"
    out: dict[str, list[str]] = {}
    for f in result.fields:
        out.setdefault(f.field, []).append(f.value)
    return out


def test_parse_takes_first_video_stream_not_stream_zero():
    result = video.parse(PRORES_MOV)
    f = fields_of(result)
    assert result.parser == "video" and result.parser_version == video.VERSION
    assert f == {"video_codec": ["prores"], "video_profile": ["HQ"], "pixel_format": ["yuv422p10le"]}
    assert "video" in [i.parser for i in registry.interpret_items(PRORES_MOV)], "in der Registry"


def test_parse_ignores_tags_and_foreign_sources():
    items = [
        tag(0, "codec_name", "prores"),                                  # ein Tag, kein Eckwert
        RawMetadataItem(source="png:tEXt", keyword="codec_type", text="video",
                        data=None, encoding="latin-1"),
    ]
    assert video.parse(items) is None
    assert video.parse([fact(0, "codec_type", "audio"), fact(0, "codec_name", "aac")]) is None


def test_parse_matroska_and_lowercases_codec():
    items = [fact(0, "codec_type", "video", "matroska"), fact(0, "codec_name", "VP9", "matroska"),
             fact(0, "pix_fmt", "yuv420p", "matroska")]
    assert fields_of(video.parse(items)) == {"video_codec": ["vp9"], "pixel_format": ["yuv420p"]}


def test_browser_support_rules():
    assert video.browser_support("h264", "High", "yuv420p") == "ok"
    assert video.browser_support("h264", None, None) == "ok"            # unbekannt → probieren
    assert video.browser_support("h264", "High 10", "yuv420p10le") == "none"
    assert video.browser_support("h264", "High 4:2:2", "yuv422p") == "none"
    assert video.browser_support("hevc", "Main 10", "yuv420p10le") == "limited"
    assert video.browser_support("prores", "HQ", "yuv422p10le") == "none"
    assert video.browser_support("dnxhd", None, None) == "none"
    assert video.browser_support("vp9", "Profile 0", "yuv420p") == "ok"
    assert video.browser_support("av1", None, None) == "ok"
    assert video.browser_support("wurstcodec", None, None) == "ok"     # nichts erfinden
    assert video.browser_support("", None, None) == "ok"


def _interp(**fields: str) -> Interpretation:
    return Interpretation(parser="video", parser_version=1,
                          fields=[InterpretedField(k, v) for k, v in fields.items()])


def test_playback_issue_keys_and_params():
    assert video.playback_issue([_interp(video_codec="prores", video_profile="HQ",
                                         pixel_format="yuv422p10le")]) == (
        "issueUnplayable", {"codec": "prores", "detail": "HQ, yuv422p10le"})
    assert video.playback_issue([_interp(video_codec="hevc")]) == (
        "issueLimitedPlayback", {"codec": "hevc", "detail": "-"})
    assert video.playback_issue([_interp(video_codec="h264", pixel_format="yuv420p")]) is None
    assert video.playback_issue([]) is None
    other = Interpretation(parser="a1111", parser_version=1,
                           fields=[InterpretedField("video_codec", "prores")])
    assert video.playback_issue([other]) is None, "nur die Felder des Video-Parsers zählen"
