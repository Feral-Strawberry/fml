"""JPEG XR (ADR 0104): Erkennung, Schicht 1, SDR-Umrechnung, Anschluss an
Thumbnails, Vorschau-Cache und Export.

Die Umrechnung und der Anschluss laufen auf jedem System (der Decoder wird
durch synthetische Gleitkomma-Pixel ersetzt). Das Dekodieren selbst gibt es
nur unter Windows; dort schreibt der Test die Datei mit dem System-Encoder.
"""

from __future__ import annotations

import sys

import pytest
from PIL import Image

from feral import config, thumbs
from feral.db import connect, store_extraction
from feral.extract import container, jxr
from feral.hashing import hash_file
from feral.messages import load as msg_load
from feral.web import export

from .jxrbuild import PIXEL_FORMAT_RGBA_HALF, encode, half_pixels, interleave, make_jxr, \
    synthetic_pixels

windows_only = pytest.mark.skipif(sys.platform != "win32",
                                  reason="JPEG-XR-Decoder gibt es nur unter Windows")
XMP = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF/></x:xmpmeta>'


def _flat(value: float | tuple[float, float, float], size=(16, 16)):
    r, g, b = (value,) * 3 if isinstance(value, float) else value
    return tuple(Image.new("F", size, v) for v in (r, g, b))


def _gray(value: float, **kwargs) -> int:
    return jxr.tone_map(*_flat(value), jxr.Tone(**kwargs)).getpixel((0, 0))[0]


def _ramp(peak_nits: float) -> list[int]:
    """Grauverlauf von 0 bis ``peak_nits`` (256 Stufen) nach der Umrechnung."""
    ramp = Image.linear_gradient("L").resize((64, 256)).convert("F").point(
        lambda v: v * (peak_nits / jxr.SCRGB_WHITE_NITS / 255.0))
    out = jxr.tone_map(ramp, ramp, ramp)
    return [out.getpixel((0, y))[0] for y in range(256)]


# -- Erkennung und Schicht 1 ------------------------------------------------------

def test_sniff_by_signature_not_tiff():
    assert container.sniff_container(b"II\xbc\x01\x08\x00\x00\x00") == "jxr"
    assert container.sniff_container(b"II\x2a\x00\x08\x00\x00\x00") == "tiff"
    assert container.sniff_container(b"II\xbc\x00\x08\x00\x00\x00") is None


def test_extract_dimensions_format_texts_and_blobs(tmp_path):
    path = make_jxr(tmp_path / "shot.jxr", width=3840, height=2160,
                    texts={0x0131: "NVIDIA", 0x0132: "2026:10:01 20:15:00"},
                    exif={0x9003: "2026:10:01 20:14:59"}, xmp=XMP, icc=b"\x01\x02" * 40)
    result = container.extract(path)

    assert (result.container, result.media_kind) == ("jxr", "image")
    assert (result.width, result.height) == (3840, 2160)
    assert result.warnings == []
    found = {(i.source, i.keyword): i for i in result.items}
    assert found[("jxr:ifd", "PixelFormat")].text == "128bppRGBAFloat"
    assert found[("jxr:ifd", "Software")].text == "NVIDIA"
    assert found[("jxr:ifd", "DateTime")].text == "2026:10:01 20:15:00"
    assert found[("jxr:exif", "DateTimeOriginal")].text == "2026:10:01 20:14:59"
    assert found[("jxr:xmp", None)].data == XMP            # byte-treu
    assert found[("jxr:icc", None)].data == b"\x01\x02" * 40


def test_extract_unknown_pixel_format_keeps_the_guid(tmp_path):
    guid = "00000000-1111-2222-3333-444444444444"
    result = jxr.extract(make_jxr(tmp_path / "x.jxr", pixel_format=guid))
    assert [i.text for i in result.items] == [guid]


def test_extract_is_defensive(tmp_path):
    whole = make_jxr(tmp_path / "ok.jxr", xmp=XMP).read_bytes()
    for name, data in (("kopf.jxr", whole[:6]), ("tabelle.jxr", whole[:30]),
                       ("blob.jxr", whole[:-10]), ("weit.jxr", whole[:4] + b"\xff\xff\xff\x7f")):
        path = tmp_path / name
        path.write_bytes(data)
        result = jxr.extract(path)                         # wirft nicht
        assert result.container == "jxr" and result.warnings, name
    assert jxr.extract(tmp_path / "fehlt.jxr").warnings


def test_extract_skips_oversized_blobs(tmp_path, monkeypatch):
    monkeypatch.setattr(jxr, "_MAX_BLOB", 16)
    result = jxr.extract(make_jxr(tmp_path / "x.jxr", xmp=XMP, pixel_format=None))
    assert result.items == [] and "too large" in result.warnings[0]
    assert (result.width, result.height) == (3840, 2160)


# -- SDR-Umrechnung ---------------------------------------------------------------

def test_split_channels_drops_alpha():
    pixels = interleave(*_flat((0.25, 1.5, -0.5), size=(3, 2)))
    red, green, blue = jxr.split_channels(3, 2, pixels)
    assert (red.size, red.mode) == ((3, 2), "F")
    assert [c.getpixel((2, 1)) for c in (red, green, blue)] == [0.25, 1.5, -0.5]


def test_paper_white_becomes_white_and_midtones_stay():
    # 200 Nits sind in scRGB 2.5. Ohne Lichter darüber ist das reine Skalierung.
    assert _gray(2.5) == 255
    assert _gray(0.0) == 0
    assert _gray(2.5 * 0.2140) in (127, 128)                           # sRGB-Mittelgrau
    assert _gray(2.5, paper_white=400.0) < 200                         # dunkler bei mehr Nits


def test_highlights_keep_gradation_up_to_the_peak():
    column = _ramp(1000.0)                           # Lichter bis zum Fünffachen von Weiß
    at = lambda nits: column[round(nits / 1000 * 255)]

    assert column == sorted(column)                  # monoton: nichts kippt um
    assert column[-1] == 255                         # die hellste Stelle wird Weiß
    # Unter dem Knie (35 % von Weiß = 70 Nits) bleibt das Bild, wie es war.
    assert column[13] == _gray(13 / 255 * 1000 / jxr.SCRGB_WHITE_NITS)   # 51 Nits
    # Darüber bekommt jede Verdopplung ähnlich viele Stufen, statt dass sich
    # alles direkt unter Weiß drängt.
    assert 200 <= at(200) <= 215
    assert 225 <= at(400) <= 236
    assert at(800) < 252
    assert at(400) - at(200) >= 18 and at(800) - at(400) >= 14


def test_lower_knee_gives_the_highlights_more_room():
    ramp = Image.linear_gradient("L").resize((64, 256)).convert("F").point(
        lambda v: v * (12.5 / 255.0))
    low = jxr.tone_map(ramp, ramp, ramp, jxr.Tone(knee=0.2)).getpixel((0, 102))[0]
    high = jxr.tone_map(ramp, ramp, ramp, jxr.Tone(knee=0.7)).getpixel((0, 102))[0]
    assert low < high                                # 400 Nits: tieferes Knie = dunkler


def test_coloured_highlights_keep_hue_and_never_clip():
    # Kräftiges Orange, viermal so hell wie Weiß: Maßstab ist der hellste
    # Kanal, alle drei werden um dasselbe Verhältnis gedrückt.
    r, g, b = jxr.tone_map(*_flat((10.0, 5.0, 0.0))).getpixel((0, 0))
    linear = lambda v: ((v / 255 + 0.055) / 1.055) ** 2.4
    assert (r, b) == (255, 0)
    assert linear(g) / linear(r) == pytest.approx(0.5, rel=0.03)

    # Neben einem viel helleren Licht bleibt eine helle farbige Fläche farbig
    # und unter der Grenze.
    channels = _flat((6.0, 3.0, 1.5), size=(64, 64))
    for channel in channels:
        channel.paste(40.0, (0, 0, 16, 16))
    r, g, b = jxr.tone_map(*channels).getpixel((40, 40))
    assert r < 250
    assert linear(g) / linear(r) == pytest.approx(0.5, rel=0.03)
    assert linear(b) / linear(r) == pytest.approx(0.25, rel=0.04)
    # Negative Werte (außerhalb von sRGB) werden 0.
    assert jxr.tone_map(*_flat((-0.5, 1.0, 2.0))).getpixel((0, 0))[0] == 0


def test_tiny_hot_spot_does_not_set_the_curve():
    # Eine winzige Sonne (unter 0,1 % der Fläche) bestimmt nicht, wie stark
    # der Rest gedrückt wird; sie selbst wird Weiß.
    channels = _flat(2.0, size=(128, 128))
    for channel in channels:
        channel.paste(4000.0, (10, 10, 13, 13))
    out = jxr.tone_map(*channels)
    assert out.getpixel((60, 60))[0] == _gray(2.0)
    assert out.getpixel((11, 11)) == (255, 255, 255)
    assert jxr.peak_level(channels[0]) == pytest.approx(2.0, rel=0.02)


def test_tone_settings_travel_as_json_and_name_the_cache_variant():
    tone = jxr.Tone(paper_white=180.5, knee=0.4)
    assert jxr.Tone.of(tone.params()) == tone
    assert jxr.Tone.of(None) == jxr.Tone() == jxr.Tone.of({"fremd": 1})
    assert (jxr.Tone().variant(), tone.variant()) == ("w200k35", "w180.5k40")


# -- Anschluss: Thumbnails, Vorschau-Cache, Export --------------------------------

@pytest.fixture
def fake_decoder(monkeypatch):
    """Ersetzt den System-Decoder: jedes JXR ist ein 32×16-Verlauf mit Lichtern."""
    def decode(source):
        ramp = Image.linear_gradient("L").resize((32, 16)).convert("F").point(
            lambda v: v * (8.0 / 255.0))
        return 32, 16, interleave(ramp, ramp, ramp), jxr.PIXEL_FORMAT_RGBA_FLOAT
    monkeypatch.setattr(jxr, "decode_scrgb", decode)


@pytest.mark.skipif(sys.platform == "win32", reason="unter Windows gibt es den Decoder")
def test_without_windows_the_reason_is_honest(tmp_path):
    path = make_jxr(tmp_path / "shot.jxr")
    dest = tmp_path / "cache" / "ab" / ("ab" * 32 + ".jpg")

    assert thumbs.generate_thumbnail(path, dest, media_kind="image") is False
    reason = thumbs.fail_reason(tmp_path / "cache", "ab" * 32)
    assert msg_load(reason)["key"] == "thumbJxrWindowsOnly"
    assert thumbs.render_preview(path) == (None, reason)
    assert thumbs.write_preview(path, tmp_path / "x.png") == reason
    assert not (tmp_path / "x.png").exists()


def test_thumbnail_and_preview_from_the_converted_image(tmp_path, fake_decoder):
    path = make_jxr(tmp_path / "shot.jxr")
    dest = tmp_path / "thumb.jpg"
    assert thumbs.generate_thumbnail(path, dest, media_kind="image", size=16) is True
    with Image.open(dest) as img:
        assert img.size == (16, 8)

    data, reason = thumbs.render_preview(path)
    assert reason == "" and data[:3] == b"\xff\xd8\xff"

    png = tmp_path / "preview.png"
    assert thumbs.write_preview(path, png, tone=jxr.Tone(paper_white=250.0),
                                file_hash="ab" * 32) == ""
    with Image.open(png) as img:
        assert (img.format, img.size, img.mode) == ("PNG", (32, 16), "RGB")
        # Herkunft im Bild (ADR 0104 Punkt 7)
        assert img.text["Source"] == "shot.jxr"
        assert img.text["fml:source-sha256"] == "ab" * 32
        assert img.text["fml:jxr-paper-white-nits"] == "250"
    # und das PNG-Einlesen sieht diese Felder als Roh-Metadaten
    keys = {i.keyword for i in container.extract(png).items}
    assert {"Source", "fml:source-sha256", "fml:jxr-paper-white-nits"} <= keys


def test_thumbnail_job_stores_the_display_image_and_decodes_once(tmp_path, monkeypatch):
    calls = []

    def decode(source):
        calls.append(source)
        ramp = Image.linear_gradient("L").resize((32, 16)).convert("F")
        return 32, 16, interleave(ramp, ramp, ramp), jxr.PIXEL_FORMAT_RGBA_FLOAT
    monkeypatch.setattr(jxr, "decode_scrgb", decode)
    path = make_jxr(tmp_path / "shot.jxr")
    h, tone = "cd" * 32, jxr.Tone()
    preview = thumbs.jxr_preview_file(tmp_path / "preview", h, tone)
    assert preview.name == f"{h}.w200k35.png"
    assert thumbs.jxr_preview_file(None, h, tone) is None

    assert thumbs.generate_thumbnail(path, tmp_path / "t.jpg", media_kind="image",
                                     size=16, tone=tone, preview=preview) is True
    with Image.open(preview) as img:                    # das große Bild liegt bereit
        assert img.size == (32, 16) and img.text["fml:source-sha256"] == h
    # Einzelansicht, Export und ein neues Vorschaubild rechnen nicht noch einmal.
    assert thumbs.generate_thumbnail(path, tmp_path / "t2.jpg", media_kind="image",
                                     size=8, tone=tone, preview=preview) is True
    assert len(calls) == 1
    # Andere Einstellung = anderes Bild: dafür wird neu gerechnet.
    other = jxr.Tone(paper_white=300.0)
    assert thumbs.generate_thumbnail(
        path, tmp_path / "t3.jpg", media_kind="image", size=8, tone=other,
        preview=thumbs.jxr_preview_file(tmp_path / "preview", h, other)) is True
    assert len(calls) == 2


def test_paper_white_is_part_of_the_cache_key(tmp_path):
    h = "ab" * 32
    tone = jxr.Tone()
    assert thumbs.preview_variant("jxr", tone) == thumbs.preview_variant(thumbs.JXR_MIME, tone) \
        == "w200k35"
    assert thumbs.preview_variant("pcd", tone) == ""
    assert thumbs.preview_cache_file(tmp_path, h).name == f"{h}.png"
    assert thumbs.preview_cache_file(tmp_path, h, "w180.5k40").name == f"{h}.w180.5k40.png"
    from feral.web.admin import _CACHE_FILE
    assert _CACHE_FILE.fullmatch(f"{h}.w180.5k40.png")     # „Cache löschen" findet es


def test_export_as_png_uses_setting_and_cache(tmp_path, fake_decoder):
    conn = connect(tmp_path / "feral.sqlite")
    (tmp_path / "quelle").mkdir()
    path = make_jxr(tmp_path / "quelle" / "shot.jxr")
    file_hash = hash_file(path)
    store_extraction(conn, file_hash=file_hash, file_size=path.stat().st_size, path=path,
                     extraction=jxr.extract(path))
    conn.commit()
    try:
        report = export.export_items(conn, [file_hash], target=tmp_path / "a",
                                     tone=jxr.Tone(paper_white=250.0))
        assert report.kopiert == 1
        with Image.open(tmp_path / "a" / "shot.png") as img:
            assert img.text["fml:jxr-paper-white-nits"] == "250"
            assert img.text["fml:source-sha256"] == file_hash

        # Liegt das Anzeigebild für DIESES Papierweiß im Cache, geht genau das raus;
        # eines für ein anderes Papierweiß zählt nicht.
        cache = tmp_path / "preview"
        cached = thumbs.preview_cache_file(cache, file_hash, jxr.Tone().variant())
        cached.parent.mkdir(parents=True)
        Image.new("RGB", (4, 4), (1, 2, 3)).save(cached, "PNG")
        export.export_items(conn, [file_hash], target=tmp_path / "b", preview_cache=cache,
                            tone=jxr.Tone())
        assert (tmp_path / "b" / "shot.png").read_bytes() == cached.read_bytes()
        export.export_items(conn, [file_hash], target=tmp_path / "c", preview_cache=cache,
                            tone=jxr.Tone(paper_white=300.0))
        assert (tmp_path / "c" / "shot.png").read_bytes() != cached.read_bytes()

        raw = tmp_path / "roh"
        export.export_items(conn, [file_hash], target=raw, converted="original")
        assert hash_file(raw / "shot.jxr") == file_hash
    finally:
        conn.close()


def test_settings_fall_back_on_nonsense():
    assert config.jxr_tone({}) == {"paper_white": 200.0, "knee": 0.35}
    assert config.jxr_tone({"jxr": {"paper_white_nits": 320, "knee": 0.5}}) \
        == {"paper_white": 320.0, "knee": 0.5}
    for bad in (0, -5, 99999, "hell", None):
        assert config.jxr_tone({"jxr": {"paper_white_nits": bad, "knee": bad}}) \
            == {"paper_white": 200.0, "knee": 0.35}


# -- Dekodieren (nur Windows) -----------------------------------------------------

@windows_only
def test_decode_round_trip_keeps_hdr_values(tmp_path):
    width, height = 256, 144
    pixels = synthetic_pixels(width, height)
    written = memoryview(pixels).cast("f").tolist()
    path = tmp_path / "synth.jxr"
    assert encode(path, width, height, pixels) == "128bppRGBAFloat"

    assert container.extract(path).width == width
    w, h, decoded, native = jxr.decode_scrgb(path)
    assert (w, h, len(decoded)) == (width, height, width * height * 16)
    assert jxr.pixel_format_name(native) == "128bppRGBAFloat"
    read = memoryview(decoded).cast("f").tolist()
    brightest = max(range(0, len(written), 4), key=written.__getitem__)
    assert written[brightest] > 8.0                              # deutlich über 1.0
    assert read[brightest] == pytest.approx(written[brightest], rel=0.05)
    assert min(read[0::4]) < 0                                   # Negatives bleibt

    image = jxr.render(path)
    assert (image.size, image.mode) == ((width, height), "RGB")
    dest = tmp_path / "thumb.jpg"
    assert thumbs.generate_thumbnail(path, dest, media_kind="image", size=64) is True


@windows_only
def test_decode_converts_half_float_files(tmp_path):
    # Die Windows Game Bar schreibt 16-Bit-Gleitkomma: der Wandler des Systems
    # liefert trotzdem 32-Bit-Gleitkomma.
    width, height = 64, 32
    pixels = synthetic_pixels(width, height)
    path = tmp_path / "half.jxr"
    assert encode(path, width, height, half_pixels(pixels), PIXEL_FORMAT_RGBA_HALF) \
        == "64bppRGBAHalf"
    w, h, decoded, native = jxr.decode_scrgb(path)
    assert jxr.pixel_format_name(native) == "64bppRGBAHalf"
    assert (w, h, len(decoded)) == (width, height, width * height * 16)
    assert max(memoryview(decoded).cast("f")[0::4]) > 4.0


@windows_only
def test_decode_broken_file_raises_a_jxr_error(tmp_path):
    with pytest.raises(jxr.JxrError):
        jxr.decode_scrgb(make_jxr(tmp_path / "leer.jxr"))
    dest = tmp_path / "ab" / ("ab" * 32 + ".jpg")
    assert thumbs.generate_thumbnail(make_jxr(tmp_path / "x.jxr"), dest, media_kind="image") is False
    assert thumbs.fail_reason(tmp_path, "ab" * 32).startswith("JPEG XR:")


# -- Vorschau-Adresse -------------------------------------------------------------

def test_preview_address_redirects_to_the_current_settings(tmp_path):
    from fastapi import HTTPException

    from feral.web.app import create_app

    cfg = tmp_path / "config.toml"
    cfg.write_text("[jxr]\npaper_white_nits = 250\nknee = 0.4\n", encoding="utf-8")
    db = tmp_path / "t.sqlite"
    conn = connect(db)
    path = make_jxr(tmp_path / "shot.jxr")
    file_hash = hash_file(path)
    store_extraction(conn, file_hash=file_hash, file_size=path.stat().st_size, path=path,
                     extraction=jxr.extract(path))
    conn.commit()
    conn.close()
    app = create_app(db, config_path=cfg)
    try:
        preview = next(r.endpoint for r in app.routes
                       if getattr(r, "path", "") == "/api/preview/{file_hash}")
        # Ohne (oder mit veralteter) Variante: kleine Umleitung, die der Browser
        # jedes Mal neu fragt. Das große Bild dahinter darf er dann festhalten.
        for stale in (None, "w200k35"):
            response = preview(file_hash, None, stale)
            assert response.status_code == 307
            assert response.headers["location"] == f"/api/preview/{file_hash}?v=w250k40"
            assert response.headers["cache-control"] == "no-cache"
        # Die Datei hat keine Bilddaten (und außerhalb von Windows keinen
        # Decoder): ehrliche 404 mit Grund statt Umleitung im Kreis.
        with pytest.raises(HTTPException) as exc:
            preview(file_hash, None, "w250k40")
        assert exc.value.status_code == 404 and exc.value.detail["key"] == "errPreviewFailed"
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()
