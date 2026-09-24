"""Schicht 2 für Musik (Issue #160, ADR 0083): ComfyUI-Musikknoten, Suno,
allgemeine Audio-Felder, C2PA in Audio-Containern, Suno-Datum. Fixtures
programmatisch (tests/audiobuild.py), ffprobe abgeschaltet bzw. Attrappe."""

from __future__ import annotations

import json
import struct
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from feral import importer
from feral.db import connect, store_extraction
from feral.extract import audio as audio_extract
from feral.extract import video_ffprobe
from feral.extract.types import RawMetadataItem
from feral.interpret import audio, comfyui, interpret_items, provenance, reparse_database, suno

from . import audiobuild as ab

UUID = "5f0c2a1e-9b3d-4e6f-8a7b-1c2d3e4f5a6b"
PARENT = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
LYRICS = "[Verse]\nRegen auf dem Dach\nund die Stadt ist wach"


@pytest.fixture(autouse=True)
def no_ffprobe(monkeypatch):
    monkeypatch.setattr(video_ffprobe, "probe", lambda path: (None, "no ffprobe (test)"))


def fields(interp) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for f in interp.fields:
        out.setdefault(f.field, []).append(f.value)
    return out


def item(source, keyword, text=None, data=None):
    return RawMetadataItem(source=source, keyword=keyword, text=text, data=data,
                           encoding="binary" if text is None else "utf-8")


def cbor_text(s: str) -> bytes:
    raw = s.encode()
    return bytes([0x60 + len(raw)]) + raw if len(raw) < 24 else bytes([0x78, len(raw)]) + raw


def suno_c2pa(codename: str = "chirp-auk-turbo-t2") -> bytes:
    """Minimaler Manifest-Store mit JUMBF-Markern und Sunos Claim-Info
    (Aufbau wie der Dump in Recherche §12, stark gekürzt)."""
    return (b"\x00\x00\x00\x20jumb\x00\x00\x00\x18jumdc2pa"
            + cbor_text("claim_generator_info") + b"\x81\xa3"
            + cbor_text("name") + cbor_text("Suno")
            + cbor_text("version") + cbor_text(codename)
            + b"com.suno.provenance" + cbor_text("providerName") + cbor_text("Suno, Inc."))


def geob(mime: str, data: bytes) -> bytes:
    return b"\x00" + mime.encode() + b"\x00c2pa\x00c2pa manifest store\x00" + data


def write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return p


# -- ComfyUI-Musik -------------------------------------------------------------

def comfy(graph: dict, *, source="id3v2:TXXX") -> list[RawMetadataItem]:
    return [item(source, "prompt", json.dumps(graph))]


def test_yue2_style_lyrics_seed_model_behind_primitive_links():
    graph = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "yue2_3b.safetensors"}},
        "2": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "melancholic synthpop, female vocals"}},
        "3": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": LYRICS}},
        "4": {"class_type": "YuE2GenerateABC",
              "inputs": {"style": ["2", 0], "lyrics": ["3", 0], "seed": 4242, "mode": "full"}},
        "5": {"class_type": "YuE2GenerateMusic",
              "inputs": {"style": ["2", 0], "lyrics": ["3", 0], "abc": ["4", 0],
                         "seed": 4242, "cfg_scale": 1.5}},
        "6": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["5", 0], "negative": ["5", 1],
                         "latent_image": ["7", 0], "seed": 99, "steps": 50, "cfg": 1.0,
                         "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "7": {"class_type": "EmptyYuE2LatentAudio", "inputs": {"seconds": 120}},
    }
    f = fields(comfyui.parse(comfy(graph, source="flac:comment")))
    assert f["prompt"] == ["melancholic synthpop, female vocals"]
    assert f["lyrics"] == [LYRICS]
    assert "99" in f["seed"] and "4242" in f["seed"]
    assert f["model"] == ["yue2_3b.safetensors"]
    assert "negative_prompt" not in f


def test_minimax_music3_caption_is_prompt_lyrics_separate():
    graph = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax_music3.safetensors"}},
        "2": {"class_type": "MiniMaxMusic3TextEncode",
              "inputs": {"caption": "upbeat funk, slap bass", "lyrics": LYRICS, "seed": 7}},
        "3": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["2", 0]}},
        "4": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
                         "seed": 7, "steps": 30, "cfg": 2.0, "sampler_name": "euler",
                         "scheduler": "simple", "denoise": 1.0}},
    }
    f = fields(comfyui.parse(comfy(graph)))
    assert f["prompt"] == ["upbeat funk, slap bass"]
    assert f["lyrics"] == [LYRICS]
    assert LYRICS not in f["prompt"]
    assert "negative_prompt" not in f


def test_ace_step_15_tags_bpm_key_and_negative_encoder_keeps_lyrics_out():
    graph = {
        "1": {"class_type": "TextEncodeAceStepAudio1.5",
              "inputs": {"tags": "lofi hip hop", "lyrics": LYRICS, "bpm": 84,
                         "keyscale": "A minor", "seed": 1}},
        "2": {"class_type": "TextEncodeAceStepAudio1.5",
              "inputs": {"tags": "distorted, noisy", "lyrics": "la la negativ", "bpm": 84,
                         "keyscale": "C major", "seed": 1}},
        "3": {"class_type": "KSampler",
              "inputs": {"positive": ["1", 0], "negative": ["2", 0], "seed": 5, "steps": 8,
                         "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple"}},
    }
    f = fields(comfyui.parse(comfy(graph, source="ogg:comment")))
    assert f["prompt"] == ["lofi hip hop"]
    assert f["negative_prompt"] == ["distorted, noisy"]
    assert f["lyrics"] == [LYRICS]
    assert f["bpm"] == ["84"] and f["key"] == ["A minor"]


def test_ace_step_10_encoder_without_sampler_link_still_yields_style():
    graph = {"1": {"class_type": "TextEncodeAceStepAudio",
                   "inputs": {"tags": "orchestral", "lyrics": "", "lyrics_strength": 1.0}}}
    f = fields(comfyui.parse(comfy(graph)))
    assert f["prompt"] == ["orchestral"] and "lyrics" not in f


def test_comfyui_mp3_txxx_end_to_end_through_walker(tmp_path):
    graph = {"1": {"class_type": "MiniMaxMusic3TextEncode",
                   "inputs": {"caption": "ambient", "lyrics": LYRICS, "seed": 3}}}
    tag = ab.id3_tag(ab.id3_frame("TXXX", ab.txxx("prompt", json.dumps(graph)))
                     + ab.id3_frame("TSSE", ab.text_frame("Lavf61.7.100")))
    extraction = audio_extract.extract(write(tmp_path, "a.mp3", ab.mp3(tag)), container="mp3")
    by = {i.parser: fields(i) for i in interpret_items(extraction.items)}
    assert by["comfyui"]["prompt"] == ["ambient"]
    assert by["comfyui"]["lyrics"] == [LYRICS]


# -- Suno ------------------------------------------------------------------------

SUNO_COMMENT = f"made with suno; created=2026-09-11T06:34:15.123Z; id={UUID}"


def suno_mp3(tmp_path, *, c2pa=True):
    frames = (ab.id3_frame("TIT2", ab.text_frame("Regenzeit"))
              + ab.id3_frame("TPE1", ab.text_frame("strawberry"))
              + ab.id3_frame("USLT", ab.comm("eng", "", LYRICS))
              + ab.id3_frame("COMM", ab.comm("eng", "", SUNO_COMMENT))
              + ab.id3_frame("TXXX", ab.txxx("comment", SUNO_COMMENT))
              + ab.id3_frame("WOAS", f"https://suno.com/song/{UUID}".encode()))
    if c2pa:
        frames += ab.id3_frame("GEOB", geob("application/c2pa", suno_c2pa()))
    return write(tmp_path, "Regenzeit.mp3", ab.mp3(ab.id3_tag(frames)))


def test_suno_mp3_2026_full(tmp_path):
    extraction = audio_extract.extract(suno_mp3(tmp_path), container="mp3")
    by = {i.parser: fields(i) for i in interpret_items(extraction.items)}
    assert by["suno"]["tool"] == ["suno"]
    assert by["suno"]["model"] == ["Suno v4.5"]
    assert by["suno"]["song_id"] == [UUID]
    assert by["audio"]["title"] == ["Regenzeit"]
    assert by["audio"]["lyrics"] == [LYRICS]
    # C2PA im GEOB: Plattform suno statt „c2pa", Rohstring bleibt erhalten.
    assert by["provenance"]["tool"] == ["suno"]
    assert "Suno chirp-auk-turbo-t2" in by["provenance"]["claim_generator"]
    assert suno.created_at(extraction.items) == datetime(2026, 9, 11, 6, 34, 15, tzinfo=timezone.utc)


def test_suno_wav_icmt_studio_without_millis():
    items = [item("riff:INFO", "ICMT", f"made with suno studio; created=2026-08-17T06:38:06Z; id={UUID}"),
             item("riff:INFO", "ISFT", "Lavf60.16.100")]
    f = fields(suno.parse(items))
    assert f["tool"] == ["suno"] and f["song_id"] == [UUID]
    assert suno.created_at(items) == datetime(2026, 8, 17, 6, 38, 6, tzinfo=timezone.utc)


def test_suno_m4a_comment_and_lyrics_from_ffprobe_tags():
    items = [item("isobmff:format.tag", "comment", SUNO_COMMENT),
             item("isobmff:format.tag", "lyrics", LYRICS),
             item("isobmff:format.tag", "title", "Regenzeit"),
             item("isobmff:stream0", "codec_type", "audio"),
             item("isobmff:stream0", "codec_name", "aac"),
             item("isobmff:stream0", "sample_rate", "48000"),
             item("isobmff:stream0", "channels", "2"),
             item("isobmff:stream1", "codec_type", "video"),
             item("isobmff:stream1", "codec_name", "mjpeg")]
    by = {i.parser: fields(i) for i in interpret_items(items)}
    assert by["suno"]["song_id"] == [UUID]
    assert by["audio"]["lyrics"] == [LYRICS]
    assert by["audio"]["title"] == ["Regenzeit"]
    assert by["audio"]["audio_codec"] == ["aac"]
    assert by["audio"]["sample_rate"] == ["48000"] and by["audio"]["channels"] == ["2"]


def test_suno_rs_suno_vorbis_tags():
    items = [item("flac:comment", "SUNO_ID", UUID),
             item("flac:comment", "SUNO_STYLE", "dreamy shoegaze, reverb guitars"),
             item("flac:comment", "SUNO_STYLE_SUMMARY", "a sad song about rain"),
             item("flac:comment", "SUNO_MODEL", "chirp-crow (v5)"),
             item("flac:comment", "SUNO_PARENT", PARENT),
             item("flac:comment", "SUNO_LINEAGE", "Extended from 0a1b2c3d\nRoot 0a1b2c3d (Rain)"),
             item("flac:comment", "LYRICS", LYRICS)]
    f = fields(suno.parse(items))
    assert f["model"] == ["Suno v5"]
    assert f["prompt"] == ["dreamy shoegaze, reverb guitars"]
    assert f["description"] == ["a sad song about rain"]
    assert f["parent_id"] == [PARENT] and f["relation"] == ["extend"]
    assert fields(audio.parse(items))["lyrics"] == [LYRICS]


def test_suno_sunosync_uuid_only_and_ambiguous_prompt_ignored():
    items = [item("id3v2:TXXX", "SUNO_UUID", UUID), item("id3v2:TXXX", "prompt", "wer weiß")]
    f = fields(suno.parse(items))
    assert f == {"tool": ["suno"], "song_id": [UUID]}


def test_suno_not_applicable_and_lyrics_are_never_the_comment():
    assert suno.parse([item("id3v2:TIT2", None, "made by me")]) is None
    long_text = "made with suno; " + "x" * 5000
    assert suno.parse([item("id3v2:USLT", "eng:", long_text)]) is None


@pytest.mark.parametrize("code,label", [
    ("chirp-auk-turbo-t2", "Suno v4.5"), ("chirp-v3-5", "Suno v3.5"),
    ("chirp-v3-0", "Suno v3"), ("chirp-hawk", "Suno v6"), ("chirp-carp", "Suno v5 Remaster"),
    ("chirp-newbird", "Suno chirp-newbird"), ("gpt-4o", None),
])
def test_suno_model_label(code, label):
    assert suno.model_label(code) == label


# -- Allgemeine Audio-Felder -----------------------------------------------------

def test_audio_id3_bpm_key_and_flac_technics():
    items = [item("id3v2:TIT2", None, "Song"), item("id3v2:TBPM", None, "120"),
             item("id3v2:TKEY", None, "Am"),
             item("flac:stream0", "codec_type", "audio"), item("flac:stream0", "codec_name", "flac"),
             item("flac:stream0", "sample_rate", "44100"), item("flac:stream0", "channels", "2"),
             item("flac:stream0", "bits_per_raw_sample", "24")]
    f = fields(audio.parse(items))
    assert f == {"title": ["Song"], "bpm": ["120"], "key": ["Am"], "audio_codec": ["flac"],
                 "sample_rate": ["44100"], "channels": ["2"], "bit_depth": ["24"]}


def test_audio_logic_bounce_riff_lgwv_and_bext(tmp_path):
    bext = b"Mixdown".ljust(256, b"\x00") + b"Logic Pro X".ljust(32, b"\x00") + b"\x00" * 314
    data = ab.wav(ab.riff_chunk(b"bext", bext) + ab.riff_chunk(b"LGWV", b"\x00" * 8)
                  + ab.info_list([(b"INAM", b"Demo 3")])
                  + ab.riff_chunk(b"data", b"\x00" * 16))
    extraction = audio_extract.extract(write(tmp_path, "b.wav", data), container="wav")
    f = fields(audio.parse(extraction.items))
    assert f["creator_tool"] == ["Logic Pro X"]
    assert f["title"] == ["Demo 3"]


def test_audio_lgwv_alone_and_voice_memos():
    assert fields(audio.parse([item("riff:LGWV", None, data=b"\x00")]))["creator_tool"] == ["Logic Pro"]
    memo = [item("isobmff:format.tag", "encoder", "com.apple.VoiceMemos (iPhone Version 18.0)"),
            item("isobmff:format.tag", "title", "Neue Aufnahme 12")]
    assert fields(audio.parse(memo)) == {"title": ["Neue Aufnahme 12"], "creator_tool": ["Voice Memos"]}


def test_audio_parser_ignores_real_videos():
    items = [item("isobmff:format.tag", "title", "Clip"),
             item("isobmff:stream0", "codec_type", "video"), item("isobmff:stream0", "codec_name", "h264"),
             item("isobmff:stream1", "codec_type", "audio"), item("isobmff:stream1", "codec_name", "aac")]
    assert audio.parse(items) is None


# -- C2PA in Audio-Containern ----------------------------------------------------

def test_c2pa_in_riff_chunk_is_recognized(tmp_path):
    data = ab.wav(ab.riff_chunk(b"data", b"\x00" * 16) + ab.riff_chunk(b"C2PA", suno_c2pa()))
    extraction = audio_extract.extract(write(tmp_path, "c.wav", data), container="wav")
    assert fields(provenance.parse(extraction.items))["tool"] == ["suno"]


def test_c2pa_in_id3_before_flac(tmp_path):
    tag = ab.id3_tag(ab.id3_frame("GEOB", geob("application/c2pa", suno_c2pa("chirp-crow"))))
    data = ab.flac([(4, ab.vorbis_comment([]))], prefix=tag)
    extraction = audio_extract.extract(write(tmp_path, "d.flac", data), container="flac")
    by = {i.parser: fields(i) for i in interpret_items(extraction.items)}
    assert by["provenance"]["tool"] == ["suno"] and by["suno"]["model"] == ["Suno v5"]


def box(btype: bytes, body: bytes) -> bytes:
    return struct.pack(">I", 8 + len(body)) + btype + body


def test_c2pa_uuid_box_in_m4a(tmp_path):
    blob = suno_c2pa()
    data = (box(b"ftyp", b"M4A \x00\x00\x00\x00") + box(b"mdat", b"\x00" * 64)
            + box(b"uuid", video_ffprobe.C2PA_UUID + blob)
            + box(b"uuid", b"\x11" * 16 + b"other"))
    extraction = video_ffprobe.extract(write(tmp_path, "e.m4a", data), container="isobmff")
    uuids = [i for i in extraction.items if i.source == "isobmff:uuid"]
    assert len(uuids) == 1 and uuids[0].data == blob
    assert fields(provenance.parse(extraction.items))["tool"] == ["suno"]


def test_c2pa_uuid_walk_survives_broken_box(tmp_path):
    warnings: list[str] = []
    path = write(tmp_path, "f.m4a", box(b"ftyp", b"M4A ") + struct.pack(">I", 4) + b"uuid")
    assert video_ffprobe.c2pa_uuid_items(path, warnings) == []
    assert warnings


# -- Mediendatum und Suche -------------------------------------------------------

def test_suno_created_is_media_date_in_import_cascade(tmp_path):
    extraction = audio_extract.extract(suno_mp3(tmp_path, c2pa=False), container="mp3")
    stat = SimpleNamespace(st_mtime=datetime(2026, 9, 20, tzinfo=timezone.utc).timestamp())
    when, source = importer.determine_date(extraction, stat)
    assert (when, source) == (datetime(2026, 9, 11, 6, 34, 15, tzinfo=timezone.utc), "metadaten")


def test_reparse_sets_suno_date_and_lyrics_are_searchable(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    extraction = audio_extract.extract(suno_mp3(tmp_path), container="mp3")
    store_extraction(conn, file_hash="h1", file_size=1, path=str(tmp_path / "Regenzeit.mp3"),
                     extraction=extraction, now="2026-09-23T00:00:00+00:00")
    conn.execute("UPDATE items SET media_date = '2026-09-20 10:00:00' WHERE file_hash = 'h1'")
    conn.commit()

    reparse_database(conn)

    assert conn.execute("SELECT media_date FROM items").fetchone()[0] == "2026-09-11 06:34:15"
    hit = conn.execute(
        "SELECT file_hash FROM search_index WHERE search_index MATCH ?",
        ['{interp names manuell}: "Regen auf dem Dach"'],
    ).fetchall()
    assert [r[0] for r in hit] == ["h1"]
    # Backfill-Kaskade liest dieselbe Zeit aus den gespeicherten Roh-Texten.
    when, source = importer._date_candidate(
        conn, "h1", min_date=importer.DEFAULT_MIN_DATE,
        upper=datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert source == "metadaten" and when.day == 11
    conn.close()


def test_workflow_only_yue2_template_subgraph_model_style_lyrics():
    """Bauform der offiziellen Vorlage audio_yue2_text2music: alles im
    Subgraphen, Stil/Songtext über PrimitiveStringMultiline, deren Wert am
    Subgraph-Knoten promotet ist; Checkpoint ebenfalls promotet. Ohne
    prompt-Blob muss der Rückfall Modell, Stil und Songtext liefern —
    die am Knoten eingegebenen Werte, nicht die Vorgaben im Inneren."""
    sub_id = "59dddde1-2d83-4b6e-9c71-1e5cb2d823d6"
    workflow = {
        "nodes": [{"id": 33, "type": sub_id, "mode": 0,
                   "inputs": [{"name": "value", "link": None}, {"name": "value_1", "link": None},
                              {"name": "ckpt_name", "link": None}],
                   "widgets_values": ["upbeat indie pop", LYRICS, "yue2_3b_int8.safetensors"]}],
        "links": [],
        "definitions": {"subgraphs": [{
            "id": sub_id,
            "inputs": [{"name": "value", "type": "STRING"}, {"name": "value_1", "type": "STRING"},
                       {"name": "ckpt_name", "type": "COMBO"}],
            "nodes": [
                {"id": 15, "type": "CheckpointLoaderSimple", "mode": 0,
                 "inputs": [{"name": "ckpt_name", "widget": {"name": "ckpt_name"}, "link": 3}],
                 "widgets_values": ["default.safetensors"]},
                {"id": 36, "type": "PrimitiveStringMultiline", "mode": 0,
                 "inputs": [{"name": "value", "widget": {"name": "value"}, "link": 1}],
                 "widgets_values": ["pirate shanties"]},
                {"id": 37, "type": "PrimitiveStringMultiline", "mode": 0,
                 "inputs": [{"name": "value", "widget": {"name": "value"}, "link": 2}],
                 "widgets_values": ["[Verse] default"]},
                {"id": 25, "type": "YuE2GenerateMusic", "mode": 0,
                 "inputs": [{"name": "style", "widget": {"name": "style"}, "link": 4},
                            {"name": "lyrics", "widget": {"name": "lyrics"}, "link": 5}],
                 "widgets_values": ["", "", "", 1, "randomize", "full"]},
            ],
            "links": [
                {"id": 1, "origin_id": -10, "origin_slot": 0, "target_id": 36, "target_slot": 0},
                {"id": 2, "origin_id": -10, "origin_slot": 1, "target_id": 37, "target_slot": 0},
                {"id": 3, "origin_id": -10, "origin_slot": 2, "target_id": 15, "target_slot": 0},
                {"id": 4, "origin_id": 36, "origin_slot": 0, "target_id": 25, "target_slot": 1},
                {"id": 5, "origin_id": 37, "origin_slot": 0, "target_id": 25, "target_slot": 2},
            ],
        }]},
    }
    f = fields(comfyui.parse([item("flac:comment", "workflow", json.dumps(workflow))]))
    assert f["model"] == ["yue2_3b_int8.safetensors"]
    assert f["prompt"] == ["upbeat indie pop"]
    assert f["lyrics"] == [LYRICS]


def test_olm_yue2_custom_loader_model_without_ksampler():
    """ComfyUI-Olm-YuE2 (example_workflows/03_yue2_staged.api.json): Modell
    als Ordnername im Text-Eingang ``model`` des Loaders, kein KSampler."""
    graph = {
        "1": {"class_type": "OlmYuE2ModelLoader", "inputs": {"model": "yue2", "vae": "yue2_vae"}},
        "2": {"class_type": "OlmYuE2Request",
              "inputs": {"style": "gentle acoustic piano", "lyrics": LYRICS, "cot": "full",
                         "seed": 831001, "abc": ""}},
        "4": {"class_type": "OlmYuE2Plan", "inputs": {"model": ["1", 0], "request": ["2", 0]}},
        "6": {"class_type": "OlmYuE2Synthesize", "inputs": {"model": ["1", 0], "semantic": ["4", 0]}},
        "7": {"class_type": "OlmYuE2Decode", "inputs": {"model": ["1", 0], "latents": ["6", 0]}},
        "8": {"class_type": "SaveAudioAdvanced", "inputs": {"audio": ["7", 0], "format": "flac"}},
    }
    f = fields(comfyui.parse(comfy(graph, source="flac:comment")))
    assert f["model"] == ["yue2"]
    assert f["prompt"] == ["gentle acoustic piano"] and f["lyrics"] == [LYRICS]
    assert f["seed"] == ["831001"]


def test_string_model_on_non_loader_is_not_a_model():
    graph = {"1": {"class_type": "OpenAIChatNode", "inputs": {"model": "gpt-4o", "prompt": "hi"}}}
    assert "model" not in fields(comfyui.parse(comfy(graph)))


def test_suno_model_falls_back_to_system_version():
    blob = (b"\x00\x00\x00\x20jumb\x00\x00\x00\x18jumdc2pa"
            + cbor_text("claim_generator_info") + b"\x81\xa2"
            + cbor_text("name") + cbor_text("Suno") + cbor_text("version") + cbor_text("1.0")
            + b"com.suno.provenance\xa2" + cbor_text("systemName") + cbor_text("Suno")
            + cbor_text("systemVersion") + cbor_text("v5.5"))
    items = [item("isobmff:uuid", video_ffprobe.C2PA_UUID.hex(), data=blob),
             item("isobmff:format.tag", "comment", SUNO_COMMENT)]
    assert fields(suno.parse(items))["model"] == ["Suno v5.5"]
