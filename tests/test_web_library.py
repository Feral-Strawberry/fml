"""Tests für die reinen Datenfunktionen der Web-Oberfläche."""

from __future__ import annotations

import io

import pytest

from feral.db import connect, store_extraction, store_interpretations
from feral.extract import ContainerExtraction, png
from feral.interpret import Interpretation, InterpretedField, interpret_items
from feral.web import library

from .pngbuild import build_png, itxt_chunk, text_chunk


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    yield conn
    conn.close()


def _store(db, file_hash, path, *chunks, file_size=1):
    extraction = png.extract(io.BytesIO(build_png(*chunks)))
    store_extraction(db, file_hash=file_hash, file_size=file_size, path=path, extraction=extraction)
    store_interpretations(
        db, file_hash=file_hash, interpretations=interpret_items(extraction.items)
    )


def test_browse_directory_lists_subdirs_and_counts_files(tmp_path):
    (tmp_path / "sub_a").mkdir()
    (tmp_path / "sub_b").mkdir()
    (tmp_path / "f1.png").write_bytes(b"x")
    (tmp_path / "f2.txt").write_bytes(b"y")

    d = library.browse_directory(tmp_path)
    assert {s["name"] for s in d["subdirs"]} == {"sub_a", "sub_b"}
    assert d["file_count"] == 2
    assert d["parent"] is not None


def test_browse_directory_on_file_raises(tmp_path):
    f = tmp_path / "x.png"
    f.write_bytes(b"x")
    with pytest.raises(NotADirectoryError):
        library.browse_directory(f)


def test_list_roots_contains_home():
    roots = library.list_roots()
    assert any("path" in r and r["path"] for r in roots)


def test_library_stats(db):
    _store(db, "h1", "/a.png", text_chunk("parameters", "hallo welt"))
    _store(db, "h2", "/b.png", itxt_chunk("workflow", "{}"))
    # zweiter Fundort für h1
    store_extraction(
        db, file_hash="h1", file_size=1, path="/copy/a.png",
        extraction=png.extract(io.BytesIO(build_png(text_chunk("parameters", "hallo welt")))),
    )
    s = library.library_stats(db)
    assert s["total_items"] == 2
    assert s["items_with_metadata"] == 2
    assert s["total_locations"] == 3
    assert {c["container"] for c in s["by_container"]} == {"png"}


def test_library_stats_total_bytes(db):
    # Leerer Bestand: SUM(NULL) muss per COALESCE zu 0 werden.
    assert library.library_stats(db)["total_bytes"] == 0

    ex = png.extract(io.BytesIO(build_png(text_chunk("parameters", "x"))))
    store_extraction(db, file_hash="h1", file_size=1000, path="/a.png", extraction=ex)
    store_extraction(db, file_hash="h2", file_size=234, path="/b.png", extraction=ex)
    # Zweiter Fundort desselben Items — Größe zählt pro Item, nicht pro Fundort.
    store_extraction(db, file_hash="h1", file_size=1000, path="/copy/a.png", extraction=ex)

    assert library.library_stats(db)["total_bytes"] == 1234


# -- Freitext = text:-Prädikate (Block S3: die Chip-Suche filtert das Grid; --------
# -- die Snippet-Trefferliste und /api/search sind ersatzlos entfallen)     --------


def _text_hits(db, expr):
    return {i["file_hash"] for i in library.list_items(db, filter_expr=expr)["items"]}


def test_freitext_excludes_raw_blobs(db):
    """ADR 0036 (bewusster Verhaltenswechsel): Roh-Blobs wie das Workflow-JSON
    sind aus der Standard-Suche raus — das Rohdaten-Opt-in folgt als Chip."""
    _store(db, "h1", "/a.png", text_chunk("parameters", "a strawberry\nSteps: 30, Seed: 777"))
    _store(db, "h2", "/b.png", itxt_chunk("workflow", '{"type":"KSampler"}'))

    assert _text_hits(db, "text: strawberry") == {"h1"}
    assert _text_hits(db, "text: KSampler") == set()


def test_stats_count_interpreted_items(db):
    _store(db, "h1", "/a.png", text_chunk("parameters", "prompt\nSteps: 20, Seed: 1"))
    _store(db, "h2", "/b.png", text_chunk("title", "kein AI-Werkzeug"))
    s = library.library_stats(db)
    assert s["items_interpreted"] == 1


def test_freitext_terms_are_and_joined(db):
    """»ball wüste« (= text: ball text: wüste) findet Items, die BEIDE
    Begriffe tragen — egal in welchem Feld (Feral Strawberry, 2026-07-07). Seit ADR 0036
    zählen die kuratierten Spalten: hier Prompt + Notiz."""
    from feral.db import manual

    _store(db, "h1", "/a.png", text_chunk("parameters", "ein Ball rollt\nSteps: 20, Seed: 1"))
    _store(db, "h2", "/b.png", text_chunk("parameters", "ein Ball rollt\nSteps: 20, Seed: 2"))
    _store(db, "h3", "/c.png", text_chunk("parameters", "nur Wüste\nSteps: 20, Seed: 3"))
    manual.set_notes(db, "h1", "Szene: Wüste")

    assert _text_hits(db, "text: ball text: wüste") == {"h1"}
    # Feld-Suche: beide Begriffe müssen im FELD stehen (LIKE-Teilstring).
    assert _text_hits(db, 'prompt: "ein ball rollt"') == {"h1", "h2"}
    assert _text_hits(db, "prompt: ball prompt: wüste") == set()


def test_freitext_finds_filename_not_folders(db):
    """Der Dateiname ist durchsuchbar — bei metadatenarmen Quellen (Midjourney
    & Co.) oft das Einzige; Ordnernamen zählen NICHT (sonst träfe "bilder"
    alles)."""
    _store(db, "h1", "/bilder/feral_ball_in_wueste_4f2a.png", text_chunk("title", "x"))
    _store(db, "h2", "/bilder/anderes.png", text_chunk("title", "x"))

    assert _text_hits(db, "text: wueste text: ball") == {"h1"}
    assert _text_hits(db, "text: bilder") == set()


def test_freitext_is_token_prefix_and_fts_safe(db):
    """ADR 0024: Freitext = Token-Präfixe über den FTS5-Index — »wüs« findet
    »Wüste«; FTS-Syntaxzeichen in Begriffen werfen nicht."""
    _store(db, "h1", "/a.png", text_chunk("parameters", "eine Wüste bei Nacht\nSteps: 20, Seed: 1"))
    _store(db, "h2", "/b.png", text_chunk("parameters", "gruene Wiese\nSteps: 20, Seed: 2"))

    assert _text_hits(db, "text: wüs") == {"h1"}
    assert _text_hits(db, "text: wüs text: nacht") == {"h1"}
    assert _text_hits(db, 'text: "NOT("') == set()   # FTS-Syntax ist entschärft
    assert _text_hits(db, "text: OR*") == set()


def test_freitext_manual_layer_immediately(db):
    """ADR 0036 (Design-Testfall 4): Tag, Notiz und manuelles Modell sind
    SOFORT frei findbar — Index-Pflege in derselben Transaktion wie die
    Änderung, kein Admin-Abgleich nötig."""
    from feral.db import manual

    _store(db, "h1", "/a.png", text_chunk("parameters", "x\nSteps: 20, Seed: 1"))
    _store(db, "h2", "/b.png", text_chunk("parameters", "y\nSteps: 20, Seed: 2"))

    manual.add_tag(db, "h1", "Lieblingsbild")
    assert _text_hits(db, "text: lieblingsb") == {"h1"}
    manual.remove_tag(db, "h1", "lieblingsbild")
    assert _text_hits(db, "text: lieblingsb") == set()

    manual.set_notes(db, "h2", "Geschenk für Oma")
    assert _text_hits(db, "text: geschenk text: oma") == {"h2"}
    manual.set_notes(db, "h2", None)
    assert _text_hits(db, "text: geschenk") == set()

    manual.set_model(db, "h2", "Midjourney V5")
    assert _text_hits(db, "text: midjourney") == {"h2"}


# --- Galerie: list_items / item_detail / resolve_media ------------------------

def _store_at(db, file_hash, path, when, *chunks):
    extraction = png.extract(io.BytesIO(build_png(*chunks)))
    store_extraction(
        db, file_hash=file_hash, file_size=7, path=path, extraction=extraction, now=when
    )
    store_interpretations(
        db, file_hash=file_hash, interpretations=interpret_items(extraction.items)
    )


def test_list_items_pages_newest_first(db):
    for k in range(5):
        _store_at(db, f"h{k}", f"/m/bild_{k}.png", f"2026-01-0{k + 1}T00:00:00+00:00",
                  text_chunk("parameters", f"prompt {k}\nSteps: 1, Seed: {k}"))

    page = library.list_items(db, limit=2, offset=0)
    assert page["total"] == 5
    assert [i["file_hash"] for i in page["items"]] == ["h4", "h3"]  # neueste zuerst
    assert page["items"][0]["name"] == "bild_4.png"
    assert page["items"][0]["tool"] == "a1111"

    rest = library.list_items(db, limit=10, offset=4)
    assert [i["file_hash"] for i in rest["items"]] == ["h0"]


@pytest.fixture
def populated_db(db):
    """Fünf Items, deren Reihenfolge sich je Sortierschlüssel unterscheidet.

    Dateinamen mit gemischter Groß-/Kleinschreibung in verschiedenen
    Verzeichnissen (auch ein Windows-Pfad), damit sich die Basename-Sortierung
    (case-insensitiv) von einer Vollpfad-Sortierung unterscheidet.
    """
    daten = [
        # (hash, pfad, größe, zeitstempel, container)
        ("h1", "/z/Apfel.PNG", 40, "2026-01-03T00:00:00+00:00", "png"),
        ("h2", "/a/zebra.png", 20, "2026-01-01T00:00:00+00:00", "png"),
        ("h3", "/m/Mango.png", 10, "2026-01-04T00:00:00+00:00", "png"),
        ("h4", "C:\\pics\\birne.png", 30, "2026-01-02T00:00:00+00:00", "png"),
        ("h5", "/q/foto.jpg", 25, "2025-12-31T00:00:00+00:00", "jpeg"),
    ]
    for file_hash, path, size, when, container in daten:
        if container == "png":
            extraction = png.extract(
                io.BytesIO(build_png(text_chunk("parameters", "x\nSteps: 1, Seed: 1")))
            )
        else:
            extraction = ContainerExtraction(container=container)
        store_extraction(
            db, file_hash=file_hash, file_size=size, path=path,
            extraction=extraction, now=when,
        )
    return db


def test_list_items_sort_size(populated_db):
    out = library.list_items(populated_db, sort="size")
    sizes = [it["file_size"] for it in out["items"]]
    assert sizes == sorted(sizes, reverse=True)  # größte zuerst


def test_list_items_sort_name(populated_db):
    # Sortiert nach Dateiname (Basename), case-insensitiv — nicht nach
    # Vollpfad: Apfel < birne < foto < Mango < zebra, egal in welchem Ordner.
    out = library.list_items(populated_db, sort="name")
    assert [i["file_hash"] for i in out["items"]] == ["h1", "h4", "h5", "h3", "h2"]


def test_list_items_sort_container(populated_db):
    # Alphabetisch nach Container (jpeg vor png), innerhalb neueste zuerst.
    out = library.list_items(populated_db, sort="container")
    assert [i["container"] for i in out["items"]] == ["jpeg", "png", "png", "png", "png"]
    assert [i["file_hash"] for i in out["items"]] == ["h5", "h3", "h1", "h4", "h2"]


def test_list_items_sort_unknown_falls_back(populated_db):
    a = library.list_items(populated_db)
    b = library.list_items(populated_db, sort="kaputt")
    assert [i["file_hash"] for i in a["items"]] == [i["file_hash"] for i in b["items"]]


def test_item_detail_contains_all_layers(db):
    _store(db, "h1", "/a.png", text_chunk("parameters", "rot\nSteps: 20, Seed: 9"))

    d = library.item_detail(db, "h1")
    assert d["container"] == "png"
    assert d["locations"][0]["path"] == "/a.png"
    assert d["locations"][0]["exists"] is False  # Pfad existiert im Test nicht
    fields = {f["field"]: f["value"] for f in d["interpreted"]}
    assert fields["seed"] == "9"
    assert d["raw"][0]["keyword"] == "parameters"
    assert library.item_detail(db, "gibtsnicht") is None


def test_workflow_json_returns_raw_blob_case_insensitive(db):
    wf = '{"nodes": [{"id": 1, "type": "KSampler"}], "links": []}'
    _store(db, "h1", "/a.png", itxt_chunk("workflow", wf))       # PNG: klein
    _store(db, "h2", "/b.png", text_chunk("WORKFLOW", wf))       # Video-Stil: groß
    _store(db, "h3", "/c.png", text_chunk("parameters", "ohne workflow"))

    assert library.workflow_json(db, "h1") == wf
    assert library.workflow_json(db, "h2") == wf
    assert library.workflow_json(db, "h3") is None
    assert library.workflow_json(db, "unbekannt") is None


# --- Sidebar: model_counts -----------------------------------------------------

def _store_models(db, file_hash, path, models):
    """Item anlegen und dessen Schicht-2-'model'-Felder direkt setzen."""
    extraction = png.extract(io.BytesIO(build_png(text_chunk("title", "kein AI"))))
    store_extraction(db, file_hash=file_hash, file_size=1, path=path, extraction=extraction)
    store_interpretations(
        db,
        file_hash=file_hash,
        interpretations=[
            Interpretation(
                parser="test",
                parser_version=1,
                fields=[InterpretedField("model", m) for m in models],
            )
        ],
    )


def test_model_counts_groups_and_sorts(db):
    # sdxl: 2 Items, flux: 1 Item, anders: 1 Item → Zählung absteigend,
    # bei Gleichstand alphabetisch nach Modellname.
    _store_models(db, "h1", "/a.png", ["sdxl"])
    _store_models(db, "h2", "/b.png", ["sdxl"])
    _store_models(db, "h3", "/c.png", ["flux"])
    _store_models(db, "h4", "/d.png", ["anders"])

    out = library.model_counts(db, order="anzahl")
    assert out == [
        {"model": "sdxl", "count": 2},
        {"model": "anders", "count": 1},
        {"model": "flux", "count": 1},
    ]


def test_model_counts_dedupes_per_item(db):
    # Zwei 'model'-Zeilen mit demselben Wert am selben Item zählen EINMAL.
    _store_models(db, "h1", "/a.png", ["sdxl", "sdxl"])
    assert library.model_counts(db) == [{"model": "sdxl", "count": 1}]


def test_model_counts_excludes_empty_values(db):
    _store_models(db, "h1", "/a.png", [""])
    _store_models(db, "h2", "/b.png", ["flux"])
    assert library.model_counts(db) == [{"model": "flux", "count": 1}]


def test_model_counts_orders(db):
    """Sortierung der Modell-Liste (Feral Strawberry, 2026-07-08): zuletzt/alphabet/anzahl.
    'zuletzt' = jüngstes ERSTELLDATUM (media_date), nicht Import-Zeitpunkt -
    Kreidezeit-Importe dürfen aktuelle Modelle nicht verdrängen."""
    _store_models(db, "h1", "/a.png", ["Beta"])
    _store_models(db, "h2", "/b.png", ["alpha"])   # später importiert, aber ÄLTER
    db.execute("UPDATE items SET media_date='2026-01-01' WHERE file_hash='h1'")
    db.execute("UPDATE items SET media_date='2022-01-01' WHERE file_hash='h2'")
    db.commit()
    assert [m["model"] for m in library.model_counts(db, order="alphabet")] == ["alpha", "Beta"]
    assert [m["model"] for m in library.model_counts(db)] == ["Beta", "alpha"]


# --- WAN-2.2-Zweistufen-Dedup (Block N, ADR 0043) --------------------------------

_WAN_HIGH = "wan2.2_t2v_high_noise_14B_fp8"
_WAN_LOW = "wan2.2_t2v_low_noise_14B_fp8"
_WAN_CANON = "wan2.2_t2v_14B_fp8"


def test_canonical_model_strips_noise_stage():
    assert library.canonical_model(_WAN_HIGH) == _WAN_CANON
    assert library.canonical_model(_WAN_LOW) == _WAN_CANON
    assert library.canonical_model("Wan2_2-T2V-A14B-HighNoise-Q5.gguf") == "Wan2_2-T2V-A14B-Q5.gguf"
    # Kein allgemeines Varianten-Mapping (4L): andere Namen bleiben unberührt.
    assert library.canonical_model("sdxl_fp16") == "sdxl_fp16"
    assert library.canonical_model("denoise_master") == "denoise_master"


def test_canonical_model_strips_unconditional_marker():
    # Ideogram-Zwei-Sichten (Feral Strawberry, 2026-07-16): „unconditional" ist derselbe
    # Fall wie WAN High/Low — zwei Sichten auf dieselbe Generierung.
    assert library.canonical_model("ideogram4 unconditional") == "ideogram4"
    assert library.canonical_model("ideogram-v4_unconditional") == "ideogram-v4"
    assert library.canonical_model("Ideogram4-Unconditional") == "Ideogram4"


def test_model_counts_folds_unconditional_only_on_collision(db):
    # Kollision → EIN Eintrag mit variants; ohne Kollision bleibt der
    # Rohname stehen (dieselbe Sicherung wie bei WAN).
    _store_models(db, "u1", "/u1.png", ["ideogram4", "ideogram4 unconditional"])
    out = library.model_counts(db, order="anzahl")
    assert out == [{"model": "ideogram4", "count": 1,
                    "variants": ["ideogram4", "ideogram4 unconditional"]}]


def test_model_counts_folds_two_stage_items_once(db):
    # Zweistufen-Item trägt BEIDE Checkpoints → EIN Facetten-Eintrag,
    # Item zählt EINMAL; Rohnamen wandern als variants mit.
    _store_models(db, "h1", "/a.png", [_WAN_HIGH, _WAN_LOW])
    _store_models(db, "h2", "/b.png", [_WAN_HIGH, _WAN_LOW])
    _store_models(db, "h3", "/c.png", ["sdxl"])

    out = library.model_counts(db, order="anzahl")
    assert out == [
        {"model": _WAN_CANON, "count": 2, "variants": [_WAN_HIGH, _WAN_LOW]},
        {"model": "sdxl", "count": 1},
    ]


def test_model_counts_single_stage_stays_raw(db):
    # Nur EINE Stufe im Bestand → keine Kollision, Rohname bleibt (die
    # Kanonisierung greift nur, wenn Namen tatsächlich zusammenfallen).
    _store_models(db, "h1", "/a.png", [_WAN_HIGH])
    assert library.model_counts(db) == [{"model": _WAN_HIGH, "count": 1}]


def test_models_facet_folds_in_context(db):
    from feral.db import manual

    _store_models(db, "e1" * 32, "/e1.png", [_WAN_HIGH, _WAN_LOW])
    _store_models(db, "e2" * 32, "/e2.png", [_WAN_HIGH, _WAN_LOW])
    _store_models(db, "e3" * 32, "/e3.png", ["sdxl"])
    manual.set_rating(db, "e1" * 32, 5)

    out = library.models_facet(db, order="anzahl", filter_expr="rating>=4")
    assert out["models"] == [
        {"model": _WAN_CANON, "count": 1, "variants": [_WAN_HIGH, _WAN_LOW]},
        {"model": "sdxl", "count": 0},
    ]


def test_model_counts_respects_limit(db):
    for k in range(5):
        _store_models(db, f"h{k}", f"/m{k}.png", [f"modell_{k}"])
    out = library.model_counts(db, limit=2, order="anzahl")
    assert len(out) == 2
    # Alle zählen 1 → alphabetische Reihenfolge entscheidet.
    assert [m["model"] for m in out] == ["modell_0", "modell_1"]


def test_resolve_media_only_existing_catalogued_paths(db, tmp_path):
    real = tmp_path / "echt.png"
    real.write_bytes(build_png(text_chunk("parameters", "x")))
    _store(db, "h1", str(real), text_chunk("parameters", "x"),
           file_size=real.stat().st_size)
    _store(db, "h2", "/weg/geloescht.png", text_chunk("parameters", "y"))

    path, mime = library.resolve_media(db, "h1")
    assert path == str(real) and mime == "image/png"
    assert library.resolve_media(db, "h2") is None      # Fundort existiert nicht
    assert library.resolve_media(db, "fremd") is None   # nie katalogisiert


def test_resolve_media_skips_foreign_bytes_at_stale_location(db, tmp_path):
    """Größen-Wächter (ADR 0049): liegt am katalogisierten Pfad inzwischen
    eine andere Datei (Größe ≠ items.file_size), wird der Fundort
    übersprungen — nie fremde Bytes unter diesem Hash ausliefern."""
    p = tmp_path / "Krea2_00013_.png"
    original = build_png(text_chunk("parameters", "original"))
    p.write_bytes(original)
    _store(db, "h1", str(p), text_chunk("parameters", "original"),
           file_size=len(original))

    # Umsortiert: am selben Pfad liegt jetzt ein ANDERES Bild gleichen Namens.
    p.write_bytes(build_png(text_chunk("parameters", "ein ganz anderes bild")))
    assert library.resolve_media(db, "h1") is None

    # Ein Zweitfundort mit den richtigen Bytes wird weiterhin gefunden.
    kopie = tmp_path / "kopie.png"
    kopie.write_bytes(original)
    store_extraction(db, file_hash="h1", file_size=len(original),
                     path=str(kopie),
                     extraction=png.extract(io.BytesIO(original)))
    path, _mime = library.resolve_media(db, "h1")
    assert path == str(kopie)


# -- Manuelle Schicht in Bestand & Suche (Stufe 3.2, ADR 0017) ---------------------


def test_list_items_carries_rating(db):
    from feral.db import manual

    _store(db, "r1" * 32, "/r1.png", text_chunk("parameters", "x"))
    _store(db, "r2" * 32, "/r2.png", text_chunk("parameters", "y"))
    manual.set_rating(db, "r1" * 32, 4)

    by_hash = {i["file_hash"]: i for i in library.list_items(db)["items"]}
    assert by_hash["r1" * 32]["rating"] == 4
    assert by_hash["r2" * 32]["rating"] is None


def test_item_detail_contains_manual_layer(db):
    from feral.db import manual

    _store(db, "m1" * 32, "/m1.png", text_chunk("parameters", "x"))
    manual.set_rating(db, "m1" * 32, 5)
    manual.add_tag(db, "m1" * 32, "Portfolio")

    d = library.item_detail(db, "m1" * 32)
    assert d["manual"]["rating"] == 5
    assert d["manual"]["tags"] == ["Portfolio"]


# Hinweis Block S3: Die Kurzformen »rating>=4«/»tag: xyz« der alten
# Trefferlisten-Suche laufen jetzt über die EINE Grammatik (test_filters.py);
# »rating: 4« (eingebettete XMP-Bewertung) hat dort bewusst eine erklärende
# Fehlermeldung statt einer stillen Zweitbedeutung (ADR 0018/0035).


def test_list_items_filters_model_and_rating(db):
    from feral.db import manual

    _store(db, "f1" * 32, "/f1.png", text_chunk("parameters", "a\nSteps: 20, Model: alpha"))
    _store(db, "f2" * 32, "/f2.png", text_chunk("parameters", "b\nSteps: 20, Model: beta"))
    manual.set_rating(db, "f1" * 32, 5)

    only_alpha = library.list_items(db, model="alpha")
    assert only_alpha["total"] == 1
    assert only_alpha["items"][0]["file_hash"] == "f1" * 32

    rated = library.list_items(db, rating=5)
    assert rated["total"] == 1 and rated["items"][0]["rating"] == 5
    assert library.list_items(db, rating=4)["total"] == 0   # exakt, nicht >=
    assert library.list_items(db, rating=5, model="beta")["total"] == 0


def test_list_items_sort_by_rating_puts_unrated_last(db):
    from feral.db import manual

    _store(db, "g1" * 32, "/g1.png", text_chunk("parameters", "x"))
    _store(db, "g2" * 32, "/g2.png", text_chunk("parameters", "y"))
    _store(db, "g3" * 32, "/g3.png", text_chunk("parameters", "z"))
    manual.set_rating(db, "g2" * 32, 3)
    manual.set_rating(db, "g3" * 32, 5)

    order = [i["file_hash"] for i in library.list_items(db, sort="rating")["items"]]
    assert order == ["g3" * 32, "g2" * 32, "g1" * 32]


def test_rating_counts_distribution(db):
    from feral.db import manual

    for k, r in (("d1", 5), ("d2", 5), ("d3", 2)):
        _store(db, k * 32, f"/{k}.png", text_chunk("parameters", "egal"))
        manual.set_rating(db, k * 32, r)

    assert library.rating_counts(db) == [
        {"rating": 5, "count": 2},
        {"rating": 2, "count": 1},
    ]


# -- Mitfilternde Facetten (Block S4, ADR 0037) -------------------------------


def _store_fields(db, file_hash, path, fields):
    """Item anlegen und beliebige Schicht-2-Felder direkt setzen."""
    extraction = png.extract(io.BytesIO(build_png(text_chunk("title", "kein AI"))))
    store_extraction(db, file_hash=file_hash, file_size=1, path=path, extraction=extraction)
    store_interpretations(
        db,
        file_hash=file_hash,
        interpretations=[
            Interpretation(
                parser="test",
                parser_version=1,
                fields=[InterpretedField(f, v) for f, v in fields],
            )
        ],
    )


def test_models_facet_counts_in_context(db):
    from feral.db import manual

    _store_models(db, "a1" * 32, "/a1.png", ["sdxl"])
    _store_models(db, "a2" * 32, "/a2.png", ["flux"])
    manual.set_rating(db, "a1" * 32, 5)

    out = library.models_facet(db, order="anzahl", filter_expr="rating>=4")
    # Beide Zeilen bleiben sichtbar (0 wird im Frontend gedimmt), Zähler im
    # Kontext des Bewertungs-Chips.
    assert out["models"] == [
        {"model": "flux", "count": 0},
        {"model": "sdxl", "count": 1},
    ]


def test_models_facet_excludes_own_chips(db):
    # Gruppen-Ausschluss: ein aktiver Modell-Chip darf die Modell-Zähler NICHT
    # einschränken — sonst stünden alle anderen Modelle auf 0 und ODER-
    # Erweitern wäre unmöglich.
    _store_models(db, "b1" * 32, "/b1.png", ["sdxl"])
    _store_models(db, "b2" * 32, "/b2.png", ["flux"])

    out = library.models_facet(db, order="anzahl", filter_expr='model: "sdxl"')
    assert {m["model"]: m["count"] for m in out["models"]} == {"sdxl": 1, "flux": 1}


def test_models_facet_unknown_in_context(db):
    from feral.db import manual

    _store_models(db, "c1" * 32, "/c1.png", ["sdxl"])
    _store_fields(db, "c2" * 32, "/c2.png", [("prompt", "ohne modell")])
    _store_fields(db, "c3" * 32, "/c3.png", [("prompt", "auch ohne")])
    manual.set_rating(db, "c2" * 32, 4)

    out = library.models_facet(db, filter_expr="rating>=4")
    assert out["unknown"] == 1          # nur das bewertete modell-lose Item
    assert library.models_facet(db)["unknown"] == 2


def test_a1111_fields_only_a1111_parser(db):
    # Substrat für den erzeugten ComfyUI-Graphen (Block N): nur a1111-Zeilen,
    # Mehrfachfelder (lora) als Liste in ordinal-Reihenfolge.
    extraction = png.extract(io.BytesIO(build_png(text_chunk("title", "x"))))
    store_extraction(db, file_hash="f1" * 32, file_size=1, path="/f1.png",
                     extraction=extraction)
    store_interpretations(db, file_hash="f1" * 32, interpretations=[
        Interpretation(parser="a1111", parser_version=3, fields=[
            InterpretedField("tool", "a1111"),
            InterpretedField("lora", "stil_a"),
            InterpretedField("lora", "stil_b"),
        ]),
        Interpretation(parser="xmp", parser_version=1, fields=[
            InterpretedField("rating", "5"),
        ]),
    ])
    fields = library.a1111_fields(db, "f1" * 32)
    assert fields["tool"] == ["a1111"]
    assert fields["lora"] == ["stil_a", "stil_b"]
    assert "rating" not in fields
    assert library.a1111_fields(db, "leer" * 16) == {}


def test_models_facet_unknown_chip_belongs_to_group(db):
    # »-has: model« = „(unbekanntes Modell)"-Zeile — gehört zur Modell-Gruppe
    # und darf die eigenen Zähler nicht auf 0 ziehen.
    _store_models(db, "d1" * 32, "/d1.png", ["sdxl"])
    _store_fields(db, "d2" * 32, "/d2.png", [("prompt", "ohne modell")])

    out = library.models_facet(db, filter_expr="-has: model")
    assert out["models"] == [{"model": "sdxl", "count": 1}]
    assert out["unknown"] == 1


def test_facets_payload_containers_in_context_and_excluded(db):
    from feral.db import manual

    _store(db, "e1" * 32, "/e1.png", text_chunk("parameters", "x"))
    _store(db, "e2" * 32, "/e2.png", text_chunk("parameters", "y"))
    db.execute("UPDATE items SET container='webp' WHERE file_hash=?", ("e2" * 32,))
    db.commit()
    manual.set_rating(db, "e1" * 32, 5)

    out = library.facets_payload(db, filter_expr="rating>=4")
    assert {c["container"]: c["count"] for c in out["containers"]} == {"png": 1, "webp": 0}

    # Eigener Container-Chip klammert sich aus: beide Zeilen zählen weiter.
    out = library.facets_payload(db, filter_expr="container: webp")
    assert {c["container"]: c["count"] for c in out["containers"]} == {"png": 1, "webp": 1}


def test_facets_payload_years_overlay(db):
    from feral.db import manual

    for k, date in (("f1", "2025-03-01"), ("f2", "2025-07-01"), ("f3", None)):
        _store(db, k * 32, f"/{k}.png", text_chunk("parameters", "x"))
        db.execute("UPDATE items SET media_date=? WHERE file_hash=?", (date, k * 32))
    db.commit()
    manual.set_rating(db, "f1" * 32, 5)

    out = library.facets_payload(db, filter_expr="rating>=4")
    (year,) = out["years"]
    assert year["year"] == "2025" and year["count"] == 1
    assert {m["month"]: m["count"] for m in year["months"]} == {"2025-03": 1, "2025-07": 0}
    assert out["undated"] == 0

    # year-Chips gehören zur eigenen Gruppe → Zähler bleiben global.
    out = library.facets_payload(db, filter_expr="year: 2025")
    assert out["years"][0]["count"] == 2
    assert out["undated"] == 1


def test_facets_payload_loras(db):
    from feral.db import manual

    _store_fields(db, "g1" * 32, "/g1.png", [("lora", "detail-tweaker"), ("lora", "film-grain")])
    _store_fields(db, "g2" * 32, "/g2.png", [("lora", "detail-tweaker")])
    manual.set_rating(db, "g2" * 32, 5)

    out = library.facets_payload(db)
    assert out["loras"] == [
        {"lora": "detail-tweaker", "count": 2},
        {"lora": "film-grain", "count": 1},
    ]

    out = library.facets_payload(db, filter_expr="rating>=4")
    assert out["loras"] == [
        {"lora": "detail-tweaker", "count": 1},
        {"lora": "film-grain", "count": 0},
    ]

    # Eigener LoRA-Chip klammert sich aus.
    out = library.facets_payload(db, filter_expr='lora: "film-grain"')
    assert out["loras"][0] == {"lora": "detail-tweaker", "count": 2}


def test_facets_payload_input_image(db):
    from feral.db import manual

    _store_fields(db, "i1" * 32, "/i1.png", [("input_image", "quelle.png")])
    _store_fields(db, "i2" * 32, "/i2.png", [("prompt", "reines t2i")])
    manual.set_rating(db, "i2" * 32, 5)

    assert library.facets_payload(db)["input_image"] == {"mit": 1, "ohne": 1}
    out = library.facets_payload(db, filter_expr="rating>=4")
    assert out["input_image"] == {"mit": 0, "ohne": 1}
    # has: input_image ist der eigene Chip der Gruppe → global zählen.
    out = library.facets_payload(db, filter_expr="has: input_image")
    assert out["input_image"] == {"mit": 1, "ohne": 1}


def test_facets_payload_tags(db):
    # Tags im Facetten-Payload (Block S5): fürs „+ Kriterium"-Popover und die
    # Tipphilfe — globale Liste, Zähler im Kontext, eigene Gruppe ausgeklammert.
    from feral.db import manual

    _store(db, "k1" * 32, "/k1.png", text_chunk("parameters", "x"))
    _store(db, "k2" * 32, "/k2.png", text_chunk("parameters", "y"))
    manual.add_tag(db, "k1" * 32, "favorit")
    manual.add_tag(db, "k2" * 32, "favorit")
    manual.add_tag(db, "k2" * 32, "wip")
    manual.set_rating(db, "k1" * 32, 5)

    assert library.facets_payload(db)["tags"] == [
        {"tag": "favorit", "count": 2},
        {"tag": "wip", "count": 1},
    ]
    out = library.facets_payload(db, filter_expr="rating>=4")
    assert out["tags"] == [
        {"tag": "favorit", "count": 1},
        {"tag": "wip", "count": 0},
    ]
    # Eigener tag-Chip klammert sich aus (ODER-Erweitern bleibt möglich).
    out = library.facets_payload(db, filter_expr='tag: "wip"')
    assert {t["tag"]: t["count"] for t in out["tags"]} == {"favorit": 2, "wip": 1}


def test_ratings_facet_in_context_and_excluded(db):
    from feral.db import manual

    _store_models(db, "j1" * 32, "/j1.png", ["sdxl"])
    _store_models(db, "j2" * 32, "/j2.png", ["flux"])
    manual.set_rating(db, "j1" * 32, 5)
    manual.set_rating(db, "j2" * 32, 3)

    out = library.ratings_facet(db, filter_expr='model: "sdxl"')
    assert out == [{"rating": 5, "count": 1}, {"rating": 3, "count": 0}]

    # rating-Chips sind die eigene Gruppe → Verteilung bleibt global.
    assert library.ratings_facet(db, filter_expr="rating>=4") == [
        {"rating": 5, "count": 1},
        {"rating": 3, "count": 1},
    ]


def test_facets_invalid_filter_raises(db):
    with pytest.raises(ValueError):
        library.facets_payload(db, filter_expr="kaputt und falsch")
    with pytest.raises(ValueError):
        library.models_facet(db, filter_expr="unbekanntesfeld: x")


def test_facet_hits_tables_are_shared_and_cleaned(db):
    # Gruppen mit identischem effektivem Filter teilen sich die Temp-Tabelle;
    # nach dem Aufruf ist aufgeräumt (Leser aus Pools leben länger).
    from feral.db import manual

    _store_models(db, "k1" * 32, "/k1.png", ["sdxl"])
    manual.set_rating(db, "k1" * 32, 5)
    library.facets_payload(db, filter_expr="rating>=4")
    leftover = db.execute(
        "SELECT name FROM sqlite_temp_master WHERE type='table' AND name LIKE 'facet_hits%'"
    ).fetchall()
    assert leftover == []


# -- Library vs. Extern (ADR 0041, I2) -----------------------------------------------


def _seed_fundort(db, monkeypatch):
    from feral.web import filters

    monkeypatch.setattr(filters, "library_root_provider", lambda: "/bestand")
    ex = png.extract(io.BytesIO(build_png(text_chunk("parameters", "x"))))
    store_extraction(db, file_hash="h1", file_size=1000, path="/bestand/2026/a.png", extraction=ex)
    store_extraction(db, file_hash="h2", file_size=200, path="/extern/b.png", extraction=ex)
    # Dublette drinnen und draußen: zählt als Library, Größe einmal.
    store_extraction(db, file_hash="h3", file_size=30, path="/extern/c.png", extraction=ex)
    store_extraction(db, file_hash="h3", file_size=30, path="/bestand/2026/c.png", extraction=ex)


def test_library_stats_split_library_vs_extern(db, monkeypatch):
    _seed_fundort(db, monkeypatch)
    s = library.library_stats(db)
    assert s["library_configured"] is True
    assert s["library_items"] == 2 and s["library_bytes"] == 1030
    assert s["total_items"] == 3 and s["total_bytes"] == 1230


def test_library_stats_without_root_reports_unconfigured(db):
    s = library.library_stats(db)
    assert s["library_configured"] is False
    assert s["library_items"] == 0 and s["library_bytes"] == 0


def test_fundort_facet_counts_and_context(db, monkeypatch):
    _seed_fundort(db, monkeypatch)
    assert library.fundort_counts(db) == {"library": 2, "extern": 1}
    payload = library.facets_payload(db)
    assert payload["fundort"] == {"library": 2, "extern": 1}
    # Mitfilternder Zähler: die eigene Gruppe wird ausgeklammert (Block S4) —
    # ein aktiver fundort:-Chip lässt die Gruppenzähler unverändert.
    payload = library.facets_payload(db, filter_expr="fundort: extern")
    assert payload["fundort"] == {"library": 2, "extern": 1}


def test_fundort_facet_hidden_without_root(db):
    assert library.fundort_counts(db) is None
    assert library.facets_payload(db)["fundort"] is None
