"""Audio-Walker (Schicht 1, ADR 0083): ID3v2/ID3v1/APEv2, FLAC, Ogg, RIFF,
AIFF, CAF — alle Fixtures programmatisch (tests/audiobuild.py). ffprobe ist
abgeschaltet bzw. durch eine Attrappe ersetzt."""

from __future__ import annotations

import hashlib
import json
import struct

import pytest

from feral.extract import audio, container, id3, video_ffprobe
from feral.extract.container import UnknownContainerError

from . import audiobuild as ab

FAKE_PROBE = {
    "format": {"format_name": "mp3", "duration": "187.431", "bit_rate": "320000",
               "tags": {"title": "ignored"}},
    "streams": [
        {"codec_type": "audio", "codec_name": "mp3", "sample_rate": "44100",
         "channels": 2, "channel_layout": "stereo", "sample_fmt": "fltp",
         "bits_per_sample": 0, "bit_rate": "320000"},
        {"codec_type": "video", "codec_name": "mjpeg", "width": 500, "height": 500,
         "disposition": {"attached_pic": 1}},
    ],
}


@pytest.fixture(autouse=True)
def no_ffprobe(monkeypatch):
    monkeypatch.setattr(video_ffprobe, "probe", lambda path: (None, "no ffprobe (test)"))


def write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def extract(path):
    return container.extract(path, audio_enabled=True)


def by_source(result, source):
    return [(i.keyword, i.text if i.text is not None else i.data)
            for i in result.items if i.source == source]


# -- Erkennung + Modul-Schalter ------------------------------------------------

@pytest.mark.parametrize("data,name", [
    (ab.mp3(ab.id3_tag(b"")), "mp3"),
    (ab.mp3(), "mp3"),
    (ab.flac([]), "flac"),
    (ab.flac([], prefix=ab.id3_tag(b"")), "flac"),
    (ab.opus([]), "ogg"),
    (ab.wav(b""), "wav"),
    (ab.wav(b"", form=b"RF64"), "wav"),
    (ab.aiff(b""), "aiff"),
    (ab.caf(b""), "caf"),
])
def test_detects_audio_containers(tmp_path, data, name):
    p = write(tmp_path, "x.bin", data)
    result = extract(p)
    assert result.container == name
    assert result.media_kind == "audio"


def test_module_off_means_unknown_format(tmp_path):
    p = write(tmp_path, "song.mp3", ab.mp3(ab.id3_tag(b"")))
    with pytest.raises(UnknownContainerError):
        container.extract(p)


def test_id3_without_audio_behind_is_unknown(tmp_path):
    p = write(tmp_path, "x.mp3", ab.id3_tag(b"") + b"no audio here" * 10)
    with pytest.raises(UnknownContainerError):
        extract(p)


def test_jpeg_and_webp_are_not_audio():
    assert container.sniff_container(b"\xff\xd8\xff\xe0" + b"\x00" * 12) == "jpeg"
    assert container.sniff_container(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
    assert container.sniff_container(b"RIFF\x00\x00\x00\x00AVI LIST") is None


# -- ID3v2 ---------------------------------------------------------------------

def test_id3v24_txxx_comfyui_prompt_and_order(tmp_path):
    frames = (ab.id3_frame("TXXX", ab.txxx("prompt", '{"1": {}}'))
              + ab.id3_frame("TXXX", ab.txxx("workflow", '{"nodes": []}'))
              + ab.id3_frame("TSSE", ab.text_frame("Lavf61.7.100"))
              + ab.id3_frame("TXXX", ab.txxx("prompt", "second")))
    r = extract(write(tmp_path, "a.mp3", ab.mp3(ab.id3_tag(frames))))
    assert by_source(r, "id3v2:TXXX") == [
        ("prompt", '{"1": {}}'), ("workflow", '{"nodes": []}'), ("prompt", "second")]
    assert by_source(r, "id3v2:TSSE") == [(None, "Lavf61.7.100")]
    assert r.warnings == ["no ffprobe (test)"]


def test_id3v24_multiple_values_become_items(tmp_path):
    frames = ab.id3_frame("TPE1", b"\x03Alice\x00Bob\x00")
    r = extract(write(tmp_path, "a.mp3", ab.mp3(ab.id3_tag(frames))))
    assert by_source(r, "id3v2:TPE1") == [(None, "Alice"), (None, "Bob")]


@pytest.mark.parametrize("enc", [0, 1, 2, 3])
def test_id3_encodings_round_trip_bytes(tmp_path, enc):
    frames = ab.id3_frame("TIT2", ab.text_frame("Grüße ♪" if enc else "Grüße", enc))
    r = extract(write(tmp_path, "a.mp3", ab.mp3(ab.id3_tag(frames))))
    (item,) = [i for i in r.items if i.source == "id3v2:TIT2"]
    assert item.text == ("Grüße ♪" if enc else "Grüße")
    # Roh-Blob-Garantie: text.encode(encoding) = die Bytes des Werts (ohne BOM).
    raw = ab.text_frame(item.text, enc)[1:]
    if enc == 1:
        raw = raw[2:]
    assert item.text.encode(item.encoding) == raw


def test_id3v23_with_unsync_and_extended_header(tmp_path):
    payload = b"\x00" + b"caf\xff\xe0"   # enthält FF E0 → Unsync fügt 00 ein
    frame = ab.id3_frame("PRIV", b"owner\x00" + payload[1:], major=3)
    ext = struct.pack(">I", 6) + b"\x00" * 6
    body = ext + frame
    unsynced = body.replace(b"\xff", b"\xff\x00")
    tag = b"ID3\x03\x00" + bytes([0x80 | 0x40]) + ab.syncsafe(len(unsynced)) + unsynced
    r = extract(write(tmp_path, "a.mp3", ab.mp3(tag)))
    assert by_source(r, "id3v2:PRIV") == [("owner", b"caf\xff\xe0")]


def test_id3v24_zlib_frame(tmp_path):
    payload, flags = ab.zlib_frame_v4(ab.txxx("prompt", "x" * 500))
    frames = ab.id3_frame("TXXX", payload, flags=flags)
    r = extract(write(tmp_path, "a.mp3", ab.mp3(ab.id3_tag(frames))))
    assert by_source(r, "id3v2:TXXX") == [("prompt", "x" * 500)]


def test_itunes_non_syncsafe_sizes(tmp_path):
    long_text = ab.text_frame("L" * 200)   # 201 > 127: syncsafe ≠ big endian
    frames = (ab.id3_frame("TIT2", long_text, itunes=True)
              + ab.id3_frame("TALB", ab.text_frame("Album"), itunes=True))
    r = extract(write(tmp_path, "a.mp3", ab.mp3(ab.id3_tag(frames))))
    assert by_source(r, "id3v2:TIT2") == [(None, "L" * 200)]
    assert by_source(r, "id3v2:TALB") == [(None, "Album")]


def test_id3v22_three_char_frames(tmp_path):
    frames = (ab.id3_frame("TT2", ab.text_frame("Old", 0), major=2)
              + ab.id3_frame("PIC", b"\x00JPG\x03cover\x00" + b"\xff\xd8data", major=2))
    r = extract(write(tmp_path, "a.mp3", ab.mp3(ab.id3_tag(frames, major=2))))
    assert by_source(r, "id3v2:TT2") == [(None, "Old")]
    (pic,) = by_source(r, "id3v2:PIC")
    desc = json.loads(pic[1])
    assert desc["mime"] == "JPG" and desc["type"] == 3 and desc["size"] == 6


def test_suno_style_frames(tmp_path):
    cover = b"\xff\xd8" + b"\x11" * 100
    note = "made with suno; created=2026-09-11T06:34:15Z; id=abc"
    frames = (ab.id3_frame("COMM", ab.comm("eng", "", note))
              + ab.id3_frame("TXXX", ab.txxx("comment", note))
              + ab.id3_frame("USLT", ab.comm("eng", "", "[Chorus]\nla la"))
              + ab.id3_frame("WOAS", b"https://suno.com/song/abc")
              + ab.id3_frame("APIC", ab.apic("image/jpeg", 3, "", cover))
              + ab.id3_frame("GEOB", b"\x00application/c2pa\x00c2pa\x00c2pa manifest store\x00JUMBF"))
    r = extract(write(tmp_path, "a.mp3", ab.mp3(ab.id3_tag(frames))))
    assert by_source(r, "id3v2:COMM") == [("eng:", note)]
    assert by_source(r, "id3v2:USLT") == [("eng:", "[Chorus]\nla la")]
    assert by_source(r, "id3v2:WOAS") == [(None, "https://suno.com/song/abc")]
    (apic,) = by_source(r, "id3v2:APIC")
    assert json.loads(apic[1]) == {"mime": "image/jpeg", "type": 3, "description": "",
                                   "size": len(cover),
                                   "sha256": hashlib.sha256(cover).hexdigest()}
    (geob,) = by_source(r, "id3v2:GEOB")
    assert geob[0] == "application/c2pa" and geob[1].endswith(b"JUMBF")


def test_stacked_id3_tags(tmp_path):
    t1 = ab.id3_tag(ab.id3_frame("TIT2", ab.text_frame("one")), padding=0)
    t2 = ab.id3_tag(ab.id3_frame("TIT2", ab.text_frame("two")), major=3, padding=0)
    r = extract(write(tmp_path, "a.mp3", ab.mp3(t1 + t2)))
    assert by_source(r, "id3v2:TIT2") == [(None, "one"), (None, "two")]


def test_broken_frame_id_warns_not_raises(tmp_path):
    frames = ab.id3_frame("TIT2", ab.text_frame("ok")) + b"t!t2\x00\x00\x00\x05\x00\x00hello"
    r = extract(write(tmp_path, "a.mp3", ab.mp3(ab.id3_tag(frames, padding=0))))
    assert by_source(r, "id3v2:TIT2") == [(None, "ok")]
    assert any("invalid frame ID" in w for w in r.warnings)


def test_truncated_tag_warns(tmp_path):
    tag = ab.id3_tag(ab.id3_frame("TIT2", ab.text_frame("x" * 50)))
    p = write(tmp_path, "a.bin", tag[:30])
    items, _ = id3.read_id3v2_tags(open(p, "rb"), 0, warnings := [])
    assert warnings and "truncated" in " ".join(warnings)


# -- ID3v1 / APEv2 -------------------------------------------------------------

def test_id3v1_and_apev2_at_end(tmp_path):
    tail = ab.apev2([("Title", b"Ape Title", 0), ("Cover Art (Front)", b"c.jpg\x00\xff\xd8xx", 2)])
    tail += ab.id3v1(title="V1 Title", comment="note", track=7, genre=12)
    r = extract(write(tmp_path, "a.mp3", ab.mp3(tail=tail)))
    assert by_source(r, "apev2")[0] == ("Title", "Ape Title")
    cover = json.loads(by_source(r, "apev2")[1][1])
    assert cover["size"] == 4 and cover["description"] == "c.jpg"
    assert by_source(r, "id3v1") == [("title", "V1 Title"), ("comment", "note"),
                                     ("track", "7"), ("genre", "12")]


# -- FLAC ----------------------------------------------------------------------

def test_flac_vorbis_duplicates_case_and_picture(tmp_path):
    vc = ab.vorbis_comment([b"prompt={\"3\": 1}", b"Prompt=second", b"ARTIST=A", b"ARTIST=B",
                            b"noequals"])
    pic = ab.flac_picture("image/png", 3, "front", b"\x89PNG....")
    data = ab.flac([(4, vc), (6, pic), (2, b"riffEXTRA"), (1, b"\x00" * 10)],
                   prefix=ab.id3_tag(ab.id3_frame("GEOB", b"\x00application/c2pa\x00\x00\x00M")))
    r = extract(write(tmp_path, "a.flac", data))
    assert r.container == "flac"
    assert by_source(r, "flac:vendor") == [(None, "Lavf61.7.100")]
    assert by_source(r, "flac:comment") == [
        ("prompt", '{"3": 1}'), ("Prompt", "second"), ("ARTIST", "A"), ("ARTIST", "B"),
        (None, "noequals")]
    assert json.loads(by_source(r, "flac:PICTURE")[0][1])["mime"] == "image/png"
    assert by_source(r, "flac:APPLICATION") == [("riff", b"EXTRA")]
    assert by_source(r, "id3v2:GEOB")[0][0] == "application/c2pa"


def test_flac_truncated_metadata_warns(tmp_path):
    data = ab.flac([(4, ab.vorbis_comment([b"a=b"]))])
    r = extract(write(tmp_path, "a.flac", data[:50]))
    assert any("truncated" in w or "ends inside" in w for w in r.warnings)


# -- Ogg -----------------------------------------------------------------------

def test_opus_comment_across_pages(tmp_path):
    big = b"workflow=" + b"{" + b"x" * 200_000 + b"}"
    data = ab.opus([b"prompt={}", big, ab.metadata_block_picture("image/jpeg", b"\xff\xd8zz")])
    assert data.count(b"OggS") > 3   # Kommentar überspannt mehrere Seiten
    r = extract(write(tmp_path, "a.opus", data))
    items = by_source(r, "ogg:comment")
    assert items[0] == ("prompt", "{}")
    assert items[1][0] == "workflow" and len(items[1][1]) == 200_002
    assert json.loads(items[2][1])["size"] == 4
    assert r.warnings == ["no ffprobe (test)"]


def test_ogg_vorbis_comment(tmp_path):
    r = extract(write(tmp_path, "a.ogg", ab.ogg_vorbis([b"TITLE=Song"])))
    assert by_source(r, "ogg:comment") == [("TITLE", "Song")]


# -- RIFF ----------------------------------------------------------------------

def test_wav_info_after_data_with_pad_and_extras(tmp_path):
    note = b"made with suno studio; created=2026-08-17T06:38:06Z; id=u"
    chunks = (ab.riff_chunk(b"data", b"\x00" * 7)            # ungerade → Pad-Byte
              + ab.info_list([(b"ICMT", note), (b"ISFT", b"Lavf60.16.100")])
              + ab.riff_chunk(b"iXML", b"<BWFXML/>")
              + ab.riff_chunk(b"LGWV", b"\x01\x02")
              + ab.riff_chunk(b"id3 ", ab.id3_tag(ab.id3_frame("TIT2", ab.text_frame("T"))))
              + ab.riff_chunk(b"C2PA", b"manifest")
              + ab.riff_chunk(b"JUNK", b"\x00" * 8))
    r = extract(write(tmp_path, "a.wav", ab.wav(chunks)))
    assert by_source(r, "riff:INFO") == [("ICMT", note.decode()), ("ISFT", "Lavf60.16.100")]
    assert by_source(r, "riff:iXML") == [(None, "<BWFXML/>")]
    assert by_source(r, "riff:LGWV") == [(None, b"\x01\x02")]
    assert by_source(r, "id3v2:TIT2") == [(None, "T")]
    assert by_source(r, "riff:C2PA") == [(None, b"manifest")]
    assert not any(i.source == "riff:JUNK" for i in r.items)


def test_wav_missing_pad_byte_is_tolerated(tmp_path):
    chunks = ab.riff_chunk(b"data", b"\x00" * 7, pad=False) + ab.info_list([(b"INAM", b"X")])
    r = extract(write(tmp_path, "a.wav", ab.wav(chunks)))
    assert by_source(r, "riff:INFO") == [("INAM", "X")]


def test_wav_cp1252_info_falls_back(tmp_path):
    r = extract(write(tmp_path, "a.wav", ab.wav(ab.info_list([(b"IART", "Café".encode("cp1252"))]))))
    (item,) = [i for i in r.items if i.source == "riff:INFO"]
    assert item.text == "Café" and item.encoding == "cp1252"


def test_rf64_data_size_from_ds64(tmp_path):
    ds64 = ab.riff_chunk(b"ds64", struct.pack("<QQQI", 0, 8, 2, 0))
    data = b"data" + struct.pack("<I", 0xFFFFFFFF) + b"\x00" * 8
    chunks = ds64 + data + ab.info_list([(b"INAM", b"Big")])
    r = extract(write(tmp_path, "a.wav", ab.wav(chunks, form=b"RF64")))
    assert by_source(r, "riff:INFO") == [("INAM", "Big")]


def test_streaming_wav_data_to_eof_stops(tmp_path):
    chunks = ab.info_list([(b"INAM", b"A")]) + b"data" + struct.pack("<I", 0) + b"\x00" * 64
    r = extract(write(tmp_path, "a.wav", ab.wav(chunks)))
    assert by_source(r, "riff:INFO") == [("INAM", "A")]
    assert not [w for w in r.warnings if "RIFF" in w]


# -- AIFF / CAF ----------------------------------------------------------------

def test_aiff_text_appl_and_id3(tmp_path):
    chunks = (ab.aiff_chunk(b"NAME", "Café".encode("mac_roman"))
              + ab.aiff_chunk(b"APPL", b"LGBMdata")
              + ab.aiff_chunk(b"COMT", b"\x00\x01rest")
              + ab.aiff_chunk(b"ID3 ", ab.id3_tag(ab.id3_frame("TIT2", ab.text_frame("I")))))
    r = extract(write(tmp_path, "a.aif", ab.aiff(chunks)))
    assert by_source(r, "aiff:NAME") == [(None, "Café")]
    assert by_source(r, "aiff:APPL") == [("LGBM", b"data")]
    assert by_source(r, "aiff:COMT") == [(None, b"\x00\x01rest")]
    assert by_source(r, "id3v2:TIT2") == [(None, "I")]


def test_caf_info_and_data_to_eof(tmp_path):
    chunks = (ab.caf_info([("title", "Bounce"), ("encoding application", "Logic Pro")])
              + ab.caf_chunk(b"uuid", bytes(range(16)) + b"payload")
              + ab.caf_chunk(b"data", b"\x00" * 16, size=-1))
    r = extract(write(tmp_path, "a.caf", ab.caf(chunks)))
    assert by_source(r, "caf:info") == [("title", "Bounce"),
                                        ("encoding application", "Logic Pro")]
    assert by_source(r, "caf:uuid") == [(bytes(range(16)).hex(), b"payload")]
    assert not r.warnings[1:]


# -- ffprobe: technische Fakten, Dauer, Medienart ------------------------------

def test_technical_facts_from_ffprobe(tmp_path, monkeypatch):
    monkeypatch.setattr(video_ffprobe, "probe", lambda path: (FAKE_PROBE, None))
    r = extract(write(tmp_path, "a.mp3", ab.mp3(ab.id3_tag(b""))))
    assert r.duration == 187.431
    facts = {(i.source, i.keyword): i.text for i in r.items}
    assert facts[("mp3:format", "duration")] == "187.431"
    assert facts[("mp3:stream0", "sample_rate")] == "44100"
    assert facts[("mp3:stream0", "channels")] == "2"
    # Keine ffprobe-Tags (der Walker liest vollständiger), kein Cover-„Video",
    # keine Null-Bittiefe verlustbehafteter Codecs.
    assert not any(i.source.endswith(".tag") for i in r.items)
    assert not any(i.source == "mp3:stream1" for i in r.items)
    assert ("mp3:stream0", "bits_per_sample") not in facts


def _iso(streams):
    return {"format": {"duration": "12.5"}, "streams": streams}


@pytest.mark.parametrize("streams,kind", [
    ([{"codec_type": "audio"}], "audio"),
    ([{"codec_type": "audio"}, {"codec_type": "video", "disposition": {"attached_pic": 1}}], "audio"),
    ([{"codec_type": "video"}, {"codec_type": "audio"}], "video"),
    ([], None),
])
def test_media_kind_from_tracks(streams, kind):
    assert video_ffprobe.media_kind_from_ffprobe(_iso(streams)) == kind


def test_m4a_without_video_is_audio_or_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(video_ffprobe, "probe",
                        lambda path: (_iso([{"codec_type": "audio", "codec_name": "aac"}]), None))
    p = write(tmp_path, "a.m4a", b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 32)
    r = container.extract(p, audio_enabled=True)
    assert (r.container, r.media_kind, r.duration) == ("isobmff", "audio", 12.5)
    with pytest.raises(UnknownContainerError):
        container.extract(p)


def test_video_gets_duration_and_stays_video(tmp_path, monkeypatch):
    monkeypatch.setattr(video_ffprobe, "probe", lambda path: (_iso(
        [{"codec_type": "video", "codec_name": "h264", "width": 64, "height": 48,
          "avg_frame_rate": "25/1"}]), None))
    p = write(tmp_path, "a.mp4", b"\x00\x00\x00\x20ftypisom" + b"\x00" * 32)
    r = container.extract(p)
    assert (r.media_kind, r.duration, r.width) == ("video", 12.5, 64)


def test_refine_after_id3_prefers_flac(tmp_path):
    p = write(tmp_path, "x", ab.id3_tag(b"") + b"fLaC")
    assert audio.refine(p, "mp3") == "flac"


# -- Falsch-Positive der MPEG-Erkennung (#159) --------------------------------

def _utf16_lang() -> bytes:
    # Windows-Sprachdatei: UTF-16-LE mit BOM FF FE. BOM + erstes Zeichen
    # ist ein formal gültiger MPEG-1-Layer-I-Framekopf.
    return "\ufeff[Language]\r\nName=Deutsch\r\nOK=OK\r\n".encode("utf-16-le") * 40


def test_utf16_text_is_not_mp3(tmp_path):
    data = _utf16_lang()
    assert audio.sniff(data[:16]) == "mp3"          # vorläufig, wie bisher
    p = write(tmp_path, "de.lang", data)
    assert audio.refine(p, "mp3") is None             # keine Frame-Kette
    with pytest.raises(container.UnknownContainerError):
        container.extract(p, audio_enabled=True)


def test_mp3_needs_a_frame_chain_with_or_without_id3(tmp_path):
    assert audio.refine(write(tmp_path, "a.mp3", ab.mp3()), "mp3") == "mp3"
    assert audio.refine(write(tmp_path, "b.mp3", ab.mp3(ab.id3_tag(b""))), "mp3") == "mp3"
    # Ein Kopf mit Müll dahinter ist keine Kette.
    lone = ab.MPEG_FRAME[:4] + b"\x11" * 2000
    assert audio.refine(write(tmp_path, "c.mp3", lone), "mp3") is None


# -- Robustheit gegen verstümmelte Dateien (#190) -------------------------------------

def _robust_seeds() -> dict[str, bytes]:
    tag = ab.id3_tag(ab.id3_frame("TXXX", ab.txxx("prompt", "a cat")) +
                     ab.id3_frame("APIC", ab.apic("image/png", 3, "", b"\x89PNG" + b"x" * 40)))
    vc = ab.vorbis_comment([b"TITLE=t", b"LYRICS=la"])
    return {
        "mp3": ab.mp3(tag, tail=ab.apev2([("Title", b"x", 0)]) + ab.id3v1("t")),
        "flac": ab.flac([(4, vc), (6, ab.flac_picture("image/jpeg", 3, "", b"j" * 40))], prefix=tag),
        "opus": ab.opus([b"TITLE=x"]),
        "wav": ab.wav(ab.riff_chunk(b"fmt ", b"\x01\x00" * 8) + ab.riff_chunk(b"data", b"\x00" * 32)
                      + ab.info_list([(b"ICMT", b"c")]) + ab.riff_chunk(b"id3 ", tag)),
        "aiff": ab.aiff(ab.aiff_chunk(b"COMM", b"\x00" * 18) + ab.aiff_chunk(b"NAME", b"n")),
        "caf": ab.caf(ab.caf_chunk(b"desc", b"\x00" * 32) + ab.caf_chunk(b"info", ab.caf_info([("title", "t")]))),
    }


@pytest.mark.parametrize("fmt", sorted(_robust_seeds()))
def test_walkers_survive_truncation_and_huge_lengths(tmp_path, monkeypatch, fmt):
    # Fremde Datei = untrusted (SECURITY.md): an JEDER Stelle abgeschnitten und
    # mit einem Riesen-Längenfeld an JEDER Stelle darf der Walker nie werfen
    # (nur „unbekannt" ist erlaubt) und nie mehr als eine Handvoll MB anlegen.
    import tracemalloc
    monkeypatch.setattr(video_ffprobe, "add_technical_facts", lambda path, result: None)
    seed = _robust_seeds()[fmt]
    variants = [seed[:cut] for cut in range(len(seed))]
    variants += [seed[:i] + b"\xff\xff\xff\xff" + seed[i + 4:] for i in range(len(seed) - 3)]
    path = tmp_path / "x.bin"
    tracemalloc.start()
    try:
        for blob in variants:
            path.write_bytes(blob)
            try:
                container.extract(path, audio_enabled=True)
            except UnknownContainerError:
                pass
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 80 * 1024 * 1024   # Deckel 64 MiB je Block (id3.MAX_TAG) + Luft
