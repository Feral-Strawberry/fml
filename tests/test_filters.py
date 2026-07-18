"""Tests für die Smart-Folder-Filtergrammatik (ADR 0018)."""

from __future__ import annotations

import io

import pytest

from feral.db import connect, folders, manual, store_extraction, store_interpretations
from feral.extract import png
from feral.interpret import interpret_items
from feral.web import filters, library

from .pngbuild import build_png, itxt_chunk, text_chunk

T0 = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    yield conn
    conn.close()


def _store(db, file_hash, path, *chunks):
    extraction = png.extract(io.BytesIO(build_png(*chunks)))
    store_extraction(db, file_hash=file_hash, file_size=1, path=path, extraction=extraction)
    store_interpretations(
        db, file_hash=file_hash, interpretations=interpret_items(extraction.items)
    )


def _seed(db):
    _store(db, "a1" * 32, "/a1.png",
           text_chunk("parameters", "portrait\nSteps: 20, Model: flux1-dev"))
    _store(db, "b2" * 32, "/b2.png",
           text_chunk("parameters", "landscape\nSteps: 20, Model: flux1-dev"))
    _store(db, "c3" * 32, "/c3.png",
           text_chunk("parameters", "abstract\nSteps: 20, Model: sdxl_base"),
           itxt_chunk("workflow", '{"nodes": []}'))
    manual.add_tag(db, "a1" * 32, "wip", now=T0)
    manual.set_rating(db, "b2" * 32, 4, now=T0)


def _hashes(db, expr):
    return {i["file_hash"] for i in library.list_items(db, filter_expr=expr)["items"]}


# -- Parser ------------------------------------------------------------------------


def test_parse_and_negation_and_quotes():
    preds = filters.parse('model: flux -tag: wip rating>=4 prompt: "red hair"')
    kinds = [(p.kind, p.negated, p.exact) for p in preds]
    assert kinds == [
        ("field", False, False), ("tag", True, False),
        ("rating", False, False), ("field", False, True),
    ]


def test_parse_rejects_bare_words_and_unknown_fields():
    with pytest.raises(ValueError, match="filterUnknownToken"):
        filters.parse("flux")
    with pytest.raises(ValueError, match="filterUnknownField"):
        filters.parse("farbe: rot")
    with pytest.raises(ValueError, match="filterRatingSyntax"):
        filters.parse("rating: 4")
    with pytest.raises(ValueError, match="filterEmpty"):
        filters.parse("   ")


# -- Ausführung (Feral Strawberrys Kernfall: „Flux ohne Tag wip") -------------------------------


def test_filter_model_without_tag(db):
    _seed(db)
    assert _hashes(db, "model: flux -tag: wip") == {"b2" * 32}


def test_filter_rating_and_unrated(db):
    _seed(db)
    assert _hashes(db, "rating>=4") == {"b2" * 32}
    assert _hashes(db, "model: flux rating=0") == {"a1" * 32}   # unbewertet
    assert _hashes(db, "-rating=0") == {"b2" * 32}              # hat Bewertung


def test_filter_has_workflow_and_container(db):
    _seed(db)
    assert _hashes(db, "has: workflow") == {"c3" * 32}
    assert _hashes(db, "container: png -has: workflow") == {"a1" * 32, "b2" * 32}


def test_filter_exact_vs_substring(db):
    _seed(db)
    assert _hashes(db, "model: flux") == {"a1" * 32, "b2" * 32}
    assert _hashes(db, 'model: "flux1-dev"') == {"a1" * 32, "b2" * 32}
    assert _hashes(db, 'model: "flux"') == set()   # exakt: kein Treffer


def test_list_items_dupes_filter(db):
    _seed(db)
    # zweiter Fundort für a1 ⇒ Dublette auf der Platte
    extraction = png.extract(io.BytesIO(build_png(text_chunk("parameters", "portrait"))))
    store_extraction(db, file_hash="a1" * 32, file_size=1, path="/kopie/a1.png", extraction=extraction)
    d = library.list_items(db, dupes=True)
    assert d["total"] == 1 and d["items"][0]["file_hash"] == "a1" * 32
    assert library.library_stats(db)["items_multi_location"] == 1


# -- Smart Folders (Persistenz) -------------------------------------------------------


def test_folder_crud(db):
    fid = folders.create(db, "Flux ohne WIP", "model: flux -tag: wip", now=T0)
    assert folders.list_folders(db)[0]["name"] == "Flux ohne WIP"
    with pytest.raises(ValueError, match="folderNameTaken"):
        folders.create(db, "flux ohne wip", "model: flux", now=T0)
    assert folders.delete(db, fid) is True
    assert folders.delete(db, fid) is False
    assert folders.list_folders(db) == []


def test_folder_update(db):
    """Block S7: Überschreiben/Umbenennen aus dem Speicherdialog."""
    fid = folders.create(db, "Flux", "model: flux", now=T0)
    other = folders.create(db, "Krea", "model: krea", now=T0)

    folders.update(db, fid, "Flux gut", "model: flux rating>=4", now="2026-07-09T12:00:00")
    row = next(f for f in folders.list_folders(db) if f["id"] == fid)
    assert row["name"] == "Flux gut"
    assert row["expression"] == "model: flux rating>=4"
    assert row["updated_at"] == "2026-07-09T12:00:00"
    assert row["created_at"] == T0

    # Gleicher Name (nur Ausdruck neu) ist KEIN Konflikt mit sich selbst.
    folders.update(db, fid, "Flux gut", "model: flux")

    with pytest.raises(ValueError, match="folderNameTaken"):
        folders.update(db, fid, "krea", "model: flux")
    with pytest.raises(ValueError, match="folderGone"):
        folders.update(db, 99999, "Neu", "model: flux")
    with pytest.raises(ValueError, match="folderNeedsName"):
        folders.update(db, other, "  ", "model: krea")


def test_metric_predicates_width_height_fps(db):
    """Eckwert-Filter (Feral Strawberry, 2026-07-08): width/height/fps mit >=/<=/=."""
    import sqlite3

    _seed(db)
    db.execute("UPDATE items SET width=1920, height=1080, fps=24.0 WHERE file_hash=?", ("a1" * 32,))
    db.execute("UPDATE items SET width=832, height=1216 WHERE file_hash=?", ("b2" * 32,))
    db.commit()

    assert _hashes(db, "width>=1920") == {"a1" * 32}
    assert _hashes(db, "height>=1200") == {"b2" * 32}
    assert _hashes(db, "fps>=24") == {"a1" * 32}
    assert _hashes(db, "model: flux -width>=1920") == {"b2" * 32}
    with pytest.raises(ValueError):
        filters.parse("width: breit")


# -- Block 4S: format:-Eimer + has: für Schicht-2-Felder ------------------------------


def _set_dims(db, file_hash, width, height):
    db.execute("UPDATE items SET width=?, height=? WHERE file_hash=?",
               (width, height, file_hash))
    db.commit()


def test_format_buckets(db):
    """Grobe Seitenverhältnis-Eimer (Feral Strawberry: Fehlersuche nach dem Import)."""
    _seed(db)
    _set_dims(db, "a1" * 32, 832, 1216)     # Hochformat
    _set_dims(db, "b2" * 32, 1024, 1024)    # quadratisch
    _set_dims(db, "c3" * 32, 1920, 1080)    # 16:9 ⇒ Widescreen

    assert _hashes(db, "format: hochformat") == {"a1" * 32}
    assert _hashes(db, "format: quadratisch") == {"b2" * 32}
    assert _hashes(db, "format: widescreen") == {"c3" * 32}
    assert _hashes(db, "format: querformat") == set()
    _set_dims(db, "c3" * 32, 1216, 832)     # ~1.46 ⇒ Querformat
    assert _hashes(db, "format: querformat") == {"c3" * 32}
    with pytest.raises(ValueError, match="filterFormatUnknown"):
        filters.parse("format: schräg")

    # Zähler und Filter nutzen dieselben Grenzen (library.format_counts).
    counts = library.format_counts(db)
    assert counts == {"quadratisch": 1, "hochformat": 1, "querformat": 1, "widescreen": 0}


def test_megapixel_buckets(db):
    """mp:-Eimer (Feral Strawberrys 100-GB-Runde): <1 / 1-2 / 2-4 / >4 Megapixel."""
    _seed(db)
    _set_dims(db, "a1" * 32, 832, 1216)      # 1,01 MP ⇒ 1-2
    _set_dims(db, "b2" * 32, 512, 512)       # 0,26 MP ⇒ <1
    _set_dims(db, "c3" * 32, 2048, 2048)     # 4,19 MP ⇒ >4

    assert _hashes(db, "mp: <1") == {"b2" * 32}
    assert _hashes(db, "mp: 1-2") == {"a1" * 32}
    assert _hashes(db, "mp: 2-4") == set()
    assert _hashes(db, "mp: >4") == {"c3" * 32}
    assert _hashes(db, "-mp: <1") == {"a1" * 32, "c3" * 32}
    with pytest.raises(ValueError, match="filterMpUnknown"):
        filters.parse("mp: riesig")

    # Zähler und Filter nutzen dieselben Grenzen (library.megapixel_counts).
    _set_dims(db, "c3" * 32, 1920, 1080)     # 2,07 MP ⇒ 2-4
    counts = library.megapixel_counts(db)
    assert counts == {"<1": 1, "1-2": 1, "2-4": 1, ">4": 0}


def test_has_field_and_unknown_model(db):
    """»-has: model« = unbekanntes Modell (metadatenarme Quellen sichtbar machen)."""
    _seed(db)
    _store(db, "d4" * 32, "/d4.png", text_chunk("Comment", "nur ein Kommentar"))

    assert _hashes(db, "has: model") == {"a1" * 32, "b2" * 32, "c3" * 32}
    assert _hashes(db, "-has: model") == {"d4" * 32}
    assert library.model_unknown_count(db) == 1
    with pytest.raises(ValueError, match="filterHasUnknown"):
        filters.parse("has: quatsch")


def test_container_counts(db):
    _seed(db)
    assert library.container_counts(db) == [{"container": "png", "count": 3}]


def test_text_predicate_saved_search(db):
    """text:-Prädikat (gespeicherte Suche): Begriff irgendwo am Item —
    Schicht 2, Roh-Texte oder Dateiname; mehrere text: = UND."""
    _seed(db)
    _store(db, "d4" * 32, "/bilder/wueste_ball_x.png", text_chunk("title", "nix"))

    assert _hashes(db, "text: portrait") == {"a1" * 32}
    assert _hashes(db, "text: wueste text: ball") == {"d4" * 32}   # Dateiname
    assert _hashes(db, "text: ball -text: wueste") == set()
    assert _hashes(db, "text: flux container: png") == {"a1" * 32, "b2" * 32}


def test_manual_model_overrides_everywhere(db):
    """ADR 0022: manuell gesetztes Modell gewinnt — in Zählern, ?model=-Filter,
    model:-Grammatik und beim „(unbekanntes Modell)"-Bestand (-has: model)."""
    _seed(db)   # a1+b2: flux1-dev · c3: sdxl_base
    _store(db, "d4" * 32, "/d4.png", text_chunk("Comment", "ohne Modell"))
    manual.set_model(db, "d4" * 32, "Midjourney V5", now=T0)   # unbekannt → V5
    manual.set_model(db, "b2" * 32, "Midjourney V5", now=T0)   # flux → V5 (Override)

    counts = {m["model"]: m["count"] for m in library.model_counts(db)}
    assert counts["Midjourney V5"] == 2
    assert counts["flux1-dev"] == 1          # b2 zählt nicht mehr doppelt
    assert library.model_unknown_count(db) == 0

    assert {i["file_hash"] for i in library.list_items(db, model="Midjourney V5")["items"]} \
        == {"b2" * 32, "d4" * 32}
    assert {i["file_hash"] for i in library.list_items(db, model="flux1-dev")["items"]} \
        == {"a1" * 32}
    assert _hashes(db, 'model: "midjourney v5"') == {"b2" * 32, "d4" * 32}
    assert _hashes(db, "model: flux") == {"a1" * 32}   # b2 ist übersteuert
    assert _hashes(db, "-has: model") == set()


def test_year_month_filters_and_counts(db):
    """Nach Jahr/Monat filtern (ADR 0021) — Zähler und Filter konsistent."""
    _seed(db)
    db.execute("UPDATE items SET media_date='2022-07-15' WHERE file_hash=?", ("a1" * 32,))
    db.execute("UPDATE items SET media_date='2022-03-02' WHERE file_hash=?", ("b2" * 32,))
    db.commit()

    assert _hashes(db, "year: 2022") == {"a1" * 32, "b2" * 32}
    assert _hashes(db, "month: 2022-07") == {"a1" * 32}
    assert _hashes(db, "year: unbekannt") == {"c3" * 32}
    with pytest.raises(ValueError, match="filterYearInvalid"):
        filters.parse("year: damals")
    with pytest.raises(ValueError, match="filterMonthInvalid"):
        filters.parse("month: 2022-13")

    counts = library.year_counts(db)
    assert counts["undated"] == 1
    assert counts["years"] == [{
        "year": "2022", "count": 2,
        "months": [{"month": "2022-07", "count": 1}, {"month": "2022-03", "count": 1}],
    }]


def test_backfill_media_dates(db, tmp_path):
    """Alt-Bestand ohne media_date wird nachgetragen (ADR 0021): eingebettetes
    Datum aus den gespeicherten Roh-Texten, sonst Datei-mtime; ohne Fundort
    und Datum bleibt es ehrlich NULL."""
    import os

    from feral import importer

    # Item mit eingebettetem EXIF-Textdatum (kein Dateizugriff nötig).
    _store(db, "a1" * 32, str(tmp_path / "weg.png"),
           text_chunk("DateTimeOriginal", "2021:06:15 10:00:00"))
    # Item ohne Metadaten-Datum, aber mit existierender Datei (mtime 2022).
    real = tmp_path / "echt.png"
    real.write_bytes(build_png(text_chunk("parameters", "x")))
    os.utime(real, (1651406400, 1651406400))   # 2022-05-01 UTC
    _store(db, "b2" * 32, str(real), text_chunk("parameters", "x"))
    # Item ohne alles: Fundort existiert nicht, kein Datum.
    _store(db, "c3" * 32, str(tmp_path / "auch-weg.png"), text_chunk("title", "x"))

    result = importer.backfill_media_dates(db)

    assert result == {"total": 3, "dated": 2}
    dates = dict(db.execute("SELECT file_hash, media_date FROM items"))
    assert dates["a1" * 32] == "2021-06-15"
    assert dates["b2" * 32] == "2022-05-01"
    assert dates["c3" * 32] is None
    # Zweiter Lauf: nichts mehr zu tun.
    assert importer.backfill_media_dates(db) == {"total": 1, "dated": 0}


# -- Block S2 (ADR 0036): text:-Prädikat auf kuratierten FTS-Spalten ------------------


def test_text_predicate_uses_curated_columns(db):
    """text: trifft die manuelle Schicht (Design-Testfall 4), aber weder
    negative_prompt (Design-Testfall 3) noch Roh-Blobs."""
    _seed(db)
    _store(db, "e5" * 32, "/e5.png", text_chunk(
        "parameters", "eine katze\nNegative prompt: hund\nSteps: 20, Model: flux1-dev"))
    manual.add_tag(db, "c3" * 32, "favorit", now=T0)

    assert _hashes(db, "text: katze") == {"e5" * 32}
    assert _hashes(db, "text: hund") == set()            # Negativ-Prompt raus
    assert _hashes(db, "text: nodes") == set()           # Roh-Blob (c3-Workflow) raus
    assert _hashes(db, "text: favorit") == {"c3" * 32}   # Tag rein, sofort
    assert _hashes(db, "text: favorit | katze") == {"c3" * 32, "e5" * 32}
    assert _hashes(db, "negative_prompt: hund") == {"e5" * 32}   # gezielt bleibt


# -- Block S5 (ADR 0038): raw:-Prädikat — Rohdaten-Opt-in ------------------------------


def test_raw_predicate_searches_raw_blobs_too(db):
    """raw: ist die Text-Suche PLUS Roh-Texte: Node-Namen im Workflow-JSON
    werden findbar (der in S2 bewusst geschlossene Weg, jetzt als Opt-in)."""
    _seed(db)

    assert _hashes(db, "text: nodes") == set()             # Standard: raus (ADR 0036)
    assert _hashes(db, "raw: nodes") == {"c3" * 32}        # Opt-in: rein
    assert _hashes(db, "raw: portrait") == {"a1" * 32}     # Obermenge: interp weiter dabei
    assert _hashes(db, "raw: nodes | portrait") == {"a1" * 32, "c3" * 32}
    assert _hashes(db, "-raw: nodes container: png") == {"a1" * 32, "b2" * 32}
    assert _hashes(db, "raw: nixda") == set()


# -- Block S3 (ADR 0035): JSON-Brücke für die Chip-Leiste ------------------------------


def test_chip_json_bridge_round_trip():
    """Chips ↔ Grammatik über parse_for_api/predicate_from_dict: kanonischer
    Text bleibt stabil, Client-Dicts laufen durch den EINEN Parser."""
    expr = 'model: flux | "sd 1.5" -tag: wip rating>=4 sort: created'
    d = filters.parse_for_api(expr)
    assert d["expression"] == expr
    assert d["sort"] == "created"
    preds = [filters.predicate_from_dict(x) for x in d["predicates"]]
    assert filters.serialize(preds) == expr

    # Werte mit Leerraum sind nur exakt darstellbar → automatisch hochgestuft.
    p = filters.predicate_from_dict({"kind": "tag", "values": [{"value": "zwei worte"}]})
    assert p.values == (("zwei worte", True),)
    # Eingebettete Quote im Ein-Wort-Wert: als \S+-Token darstellbar,
    # bleibt Teilstring; Round-Trip hält (ADR-0035-Nachtrag).
    p = filters.predicate_from_dict({"kind": "tag", "values": [{"value": 'a"b'}]})
    assert p.values == (('a"b', False),)
    assert filters.parse(filters.serialize([p])) == [p]
    # Client-Müll fällt durch parse — EINE Validierung, keine zweite.
    junk = filters.predicate_from_dict({"kind": "quatsch", "values": [{"value": "x"}]})
    with pytest.raises(ValueError):
        filters.parse_for_api(filters.serialize([junk]))


def test_quote_escaping_in_exact_values(db):
    """Anführungszeichen in exakten Werten (ADR-0035-Nachtrag): Verdopplung
    in serialize(), Rück-Übersetzung in parse() — die Seed-Varianten-Suche
    (ADR 0047) verliert Prompts mit Zitaten damit nicht mehr."""
    preds = filters.parse('prompt: "a sign that says ""OPEN"" at night"')
    assert preds[0].values == (('a sign that says "OPEN" at night', True),)
    assert filters.parse(filters.serialize(preds)) == preds

    # Chip-Dict-Brücke (Seed-Varianten-Weg): Quote-Wert wird getragen statt
    # abgelehnt; Werte, die mit " beginnen, werden exakt hochgestuft.
    p = filters.predicate_from_dict(
        {"kind": "field", "field": "prompt",
         "values": [{"value": 'sag "hallo" bitte', "exact": True}]})
    assert filters.parse(filters.serialize([p])) == [p]
    p = filters.predicate_from_dict({"kind": "tag", "values": [{"value": '"zitat'}]})
    assert p.values == (('"zitat', True),)
    assert filters.parse(filters.serialize([p])) == [p]

    # Nur-Quote-Wert, ODER-Liste, offene Phrase.
    preds = filters.parse('tag: """" | x')
    assert preds[0].values == (('"', True), ("x", False))
    with pytest.raises(ValueError, match="filterUnclosedQuote"):
        filters.parse('prompt: "offen')

    # Ausführung: exakter Treffer über die ganze Zeichenkette inkl. Quotes.
    _store(db, "f6" * 32, "/f6.png",
           text_chunk("parameters",
                      'a sign that says "OPEN" at night\nSteps: 20, Model: flux1-dev'))
    assert _hashes(db, 'prompt: "a sign that says ""OPEN"" at night"') == {"f6" * 32}
    assert _hashes(db, 'prompt: "a sign that says ""ZU"" at night"') == set()


def test_field_like_escapes_wildcards(db):
    """LIKE-Sonderzeichen in Feldwerten wirken wörtlich, nicht als Wildcard."""
    _seed(db)
    _store(db, "e5" * 32, "/e5.png",
           text_chunk("parameters", "literal 100% sure\nSteps: 20, Model: flux1-dev"))

    assert _hashes(db, "prompt: 100%") == {"e5" * 32}
    assert _hashes(db, "prompt: 100_") == set()


# -- Block S1 (ADR 0035): Facetten-ODER + sort:-Direktive + Serialisierer -------------


def test_parse_or_values_structure():
    preds = filters.parse('model: flux | krea | "sd 1.5"')
    assert len(preds) == 1
    assert preds[0].values == (("flux", False), ("krea", False), ("sd 1.5", True))
    # Bequem-Properties zeigen weiter den ersten Wert (Bestandscode).
    assert preds[0].value == "flux" and preds[0].exact is False


def test_pipe_without_whitespace_stays_one_value():
    """Keine Umdeutung (ADR 0018/0035): »a|b« war und bleibt EIN Wert."""
    preds = filters.parse("model: a|b")
    assert preds[0].values == (("a|b", False),)


def test_or_execution_and_negation(db):
    _seed(db)
    all_three = {"a1" * 32, "b2" * 32, "c3" * 32}
    assert _hashes(db, "model: flux | sdxl") == all_three
    assert _hashes(db, 'model: sdxl | "flux1-dev"') == all_three   # gemischt exakt/Teilstring
    assert _hashes(db, "-model: flux | sdxl") == set()             # weder noch
    # Design-Testfall 1: Flux ODER Krea, jeweils ab 4 Sterne.
    assert _hashes(db, "model: flux | krea rating>=4") == {"b2" * 32}


def test_or_execution_tag_year_text(db):
    _seed(db)
    manual.add_tag(db, "c3" * 32, "favorit", now=T0)
    db.execute("UPDATE items SET media_date='2022-07-15' WHERE file_hash=?", ("a1" * 32,))
    db.commit()

    assert _hashes(db, "tag: wip | favorit") == {"a1" * 32, "c3" * 32}
    assert _hashes(db, "year: 2022 | unbekannt") == {"a1" * 32, "b2" * 32, "c3" * 32}
    assert _hashes(db, "text: portrait | landscape") == {"a1" * 32, "b2" * 32}
    assert _hashes(db, "has: workflow | model") == {"a1" * 32, "b2" * 32, "c3" * 32}
    assert _hashes(db, "container: png | webm") == {"a1" * 32, "b2" * 32, "c3" * 32}


def test_or_execution_buckets(db):
    _seed(db)
    _set_dims(db, "a1" * 32, 832, 1216)      # Hochformat, 1,01 MP
    _set_dims(db, "b2" * 32, 512, 512)       # quadratisch, 0,26 MP
    _set_dims(db, "c3" * 32, 2048, 2048)     # quadratisch, 4,19 MP

    assert _hashes(db, "format: hochformat | widescreen") == {"a1" * 32}
    assert _hashes(db, "mp: <1 | >4") == {"b2" * 32, "c3" * 32}


def test_or_rejected_for_comparisons():
    with pytest.raises(ValueError, match="filterOrSyntax"):
        filters.parse("rating>=4 | rating<=2")
    with pytest.raises(ValueError, match="filterOrSyntax"):
        filters.parse("width>=1920 | height>=1080")


def test_lora_or_from_a1111_inline_tags(db):
    """Design-Testfall 5: lora: als Facette (Werte aus A1111-Inline-Tags)."""
    _seed(db)
    _store(db, "d4" * 32, "/d4.png", text_chunk(
        "parameters", "portrait <lora:detail-tweaker:0.8>\nSteps: 20, Model: flux1-dev"))

    assert _hashes(db, "lora: detail-tweaker") == {"d4" * 32}
    assert _hashes(db, "lora: detail-tweaker | nixda") == {"d4" * 32}


def test_sort_directive_parse_and_errors():
    preds = filters.parse("model: flux sort: created")
    assert filters.sort_directive(preds) == "created"
    assert filters.sort_directive(filters.parse("model: flux")) is None
    with pytest.raises(ValueError, match="filterSortUnknown"):
        filters.parse("sort: quatsch")
    with pytest.raises(ValueError, match="filterSortNegated"):
        filters.parse("-sort: created")
    with pytest.raises(ValueError, match="filterSortOnce"):
        filters.parse("sort: added sort: name")
    with pytest.raises(ValueError, match="filterSortSingle"):
        filters.parse("sort: added | name")


def test_sort_directive_wins_over_sort_param(db):
    """Design-Testfall 7 (Grammatik-Teil): sort: created sortiert nach
    Erstelldatum, Undatierte ans Ende — und gewinnt über ?sort=."""
    _seed(db)
    db.execute("UPDATE items SET media_date='2021-01-01' WHERE file_hash=?", ("a1" * 32,))
    db.execute("UPDATE items SET media_date='2023-06-15' WHERE file_hash=?", ("b2" * 32,))
    db.commit()

    result = library.list_items(db, sort="size", filter_expr="container: png sort: created")
    assert [i["file_hash"] for i in result["items"]] == ["b2" * 32, "a1" * 32, "c3" * 32]
    # Ausdruck NUR aus sort: filtert nichts, sortiert aber.
    result = library.list_items(db, filter_expr="sort: created")
    assert result["total"] == 3
    assert [i["file_hash"] for i in result["items"]][:2] == ["b2" * 32, "a1" * 32]


def test_sort_keys_match_library_whitelist():
    """filters.SORT_KEYS darf nicht von library._SORTS abdriften (kein Import
    in diese Richtung möglich — der Test ist die Kopplung). Seit ADR 0039
    trägt library je Schlüssel GENAU die Basis-Form plus die Variante mit
    der Nicht-Standard-Richtung (die Standardrichtung wird beim Parsen
    weggekürzt und darf deshalb nicht als Schlüssel existieren)."""
    expected = set()
    for base in filters.SORT_KEYS:
        expected.add(base)
        other = "auf" if filters.SORT_DEFAULT_DIRECTION[base] == "ab" else "ab"
        expected.add(f"{base}-{other}")
    assert expected == set(library._SORTS)


def test_sort_direction_suffix_parse():
    """ADR 0039: -auf/-ab; die Standardrichtung wird kanonisch weggekürzt."""
    assert filters.sort_directive(filters.parse("sort: created-auf")) == "created-auf"
    assert filters.sort_directive(filters.parse("sort: created-ab")) == "created"
    assert filters.sort_directive(filters.parse("sort: name-auf")) == "name"
    assert filters.sort_directive(filters.parse("sort: name-ab")) == "name-ab"
    assert filters.serialize(filters.parse("sort: size-auf")) == "sort: size-auf"
    with pytest.raises(ValueError, match="filterSortUnknown"):
        filters.parse("sort: created-quer")


def test_english_aliases_parse_to_canonical():
    """ADR 0054 (M.3): file:/location:, portrait/square/landscape und
    -asc/-desc sind reine Parse-Aliasse — Prädikate und serialize()
    bleiben kanonisch, gespeicherte Smart Folders unangetastet."""
    assert filters.parse("file: mj_") == filters.parse("datei: mj_")
    assert filters.parse("-location: extern") == filters.parse("-fundort: extern")
    assert filters.parse("location: external") == filters.parse("fundort: extern")
    assert filters.parse("year: unknown | 2022") == \
        filters.parse("year: unbekannt | 2022")
    assert filters.parse("format: portrait | square | landscape") == \
        filters.parse("format: hochformat | quadratisch | querformat")
    assert filters.sort_directive(filters.parse("sort: created-asc")) == "created-auf"
    assert filters.sort_directive(filters.parse("sort: created-desc")) == "created"
    assert filters.sort_directive(filters.parse("sort: name-desc")) == "name-ab"
    assert (filters.serialize(
        filters.parse("file: x -location: external format: landscape "
                      "year: unknown sort: added-asc"))
        == 'datei: x -fundort: extern format: querformat '
           'year: unbekannt sort: added-auf')
    # Unbekannte Werte bleiben Fehler — die Meldung zeigt die getippte Form.
    with pytest.raises(ValueError, match="filterFormatUnknown"):
        filters.parse("format: panorama")
    with pytest.raises(ValueError, match="filterSortUnknown"):
        filters.parse("sort: created-ascending")


def test_sort_directions_order_items(db):
    """Richtungen wirken; Undatierte bleiben in BEIDEN Richtungen am Ende."""
    _seed(db)
    db.execute("UPDATE items SET media_date='2021-01-01' WHERE file_hash=?", ("a1" * 32,))
    db.execute("UPDATE items SET media_date='2023-06-15' WHERE file_hash=?", ("b2" * 32,))
    db.commit()

    result = library.list_items(db, filter_expr="sort: created-auf")
    assert [i["file_hash"] for i in result["items"]] == ["a1" * 32, "b2" * 32, "c3" * 32]
    result = library.list_items(db, filter_expr="sort: size-auf")
    sizes = [i["file_size"] for i in result["items"]]
    assert sizes == sorted(sizes)


@pytest.mark.parametrize("expr", [
    "model: flux",
    'model: flux | krea | "sd 1.5"',
    "-tag: wip | alt",
    "rating>=4",
    "-rating=0",
    "width>=1920",
    "fps>=23.976",
    "container: png | webm",
    "has: workflow | lora",
    "format: hochformat | quadratisch",
    "mp: <1 | >4",
    "year: 2022 | unbekannt",
    "month: 2022-07",
    'prompt: "red hair"',
    "sort: created",
    "model: flux -tag: wip rating>=4",       # Design-Testfall 8 (Alt-Ausdruck)
    "text: wüste year: 2025",                # Design-Testfall 2
    "raw: nodes | ipadapter",                # Rohdaten-Opt-in (Block S5)
    "lora: detail-tweaker",                  # Design-Testfall 5
    "has: input_image",                      # Design-Testfall 6
    "model: flux | krea rating>=4 sort: created",
    "-fundort: extern",                      # Library vs. Extern (ADR 0041, I2)
])
def test_serialize_round_trip(expr):
    """Chips ↔ Text verlustfrei (ADR 0035): kanonischer Text bleibt identisch,
    parse(serialize(…)) liefert dieselben Prädikate."""
    preds = filters.parse(expr)
    assert filters.serialize(preds) == expr
    assert filters.parse(filters.serialize(preds)) == preds


def test_import_and_scan_set_media_date(db, tmp_path):
    """Import UND Scan befüllen items.media_date über die ADR-0019-Kaskade."""
    import os

    from feral import importer, scan

    source, target = tmp_path / "quelle", tmp_path / "bestand"
    source.mkdir(), target.mkdir()
    f = source / "bild.png"
    f.write_bytes(build_png(text_chunk("parameters", "x")))
    os.utime(f, (1651406400, 1651406400))   # 2022-05-01 UTC
    importer.import_folder(db, source, target_root=target)
    assert db.execute("SELECT media_date FROM items").fetchone()[0] == "2022-05-01"

    g = tmp_path / "alt" / "alt.png"
    g.parent.mkdir()
    g.write_bytes(build_png(text_chunk("parameters", "anders")))
    os.utime(g, (1420156800, 1420156800))   # 2015-01-02 UTC
    scan.scan_files(db, [g])
    row = db.execute(
        "SELECT media_date FROM items WHERE file_hash != ?",
        (db.execute("SELECT file_hash FROM items WHERE media_date='2022-05-01'").fetchone()[0],),
    ).fetchone()
    assert row[0] == "2015-01-02"


# -- fundort: Library vs. Extern (ADR 0041, I2) --------------------------------------


def test_fundort_parse_and_errors():
    preds = filters.parse("fundort: library -fundort: extern")
    assert [(p.kind, p.value, p.negated) for p in preds] == [
        ("fundort", "library", False), ("fundort", "extern", True),
    ]
    with pytest.raises(ValueError, match="filterFundortUnknown"):
        filters.parse("fundort: woanders")


def _seed_fundort(db):
    _store(db, "a1" * 32, "/bestand/2026/01/a1.png",
           text_chunk("parameters", "eins"))
    _store(db, "b2" * 32, "/extern/platte/b2.png",
           text_chunk("parameters", "zwei"))
    # Dublette drinnen UND draußen → zählt als Library (ADR 0041).
    _store(db, "c3" * 32, "/extern/platte/c3.png",
           text_chunk("parameters", "drei"))
    _store(db, "c3" * 32, "/bestand/2026/02/c3.png",
           text_chunk("parameters", "drei"))


def test_fundort_filters_items(db, monkeypatch):
    monkeypatch.setattr(filters, "library_root_provider", lambda: "/bestand")
    _seed_fundort(db)
    assert _hashes(db, "fundort: library") == {"a1" * 32, "c3" * 32}
    assert _hashes(db, "fundort: extern") == {"b2" * 32}
    assert _hashes(db, "-fundort: library") == {"b2" * 32}


def test_fundort_without_root_everything_is_extern(db):
    # Provider-Standard: keine Library konfiguriert (Fehlervermeidungsmodus).
    _seed_fundort(db)
    assert _hashes(db, "fundort: library") == set()
    assert _hashes(db, "fundort: extern") == {"a1" * 32, "b2" * 32, "c3" * 32}


def test_fundort_normalizes_windows_paths(db, monkeypatch):
    # Bestand mit Backslash-Pfaden, Root aus der Config ebenso — die
    # Separator-Normalisierung muss beide Seiten treffen.
    monkeypatch.setattr(filters, "library_root_provider", lambda: r"D:\medien\bestand")
    _store(db, "a1" * 32, r"D:\medien\bestand\2026\a.png",
           text_chunk("parameters", "eins"))
    _store(db, "b2" * 32, r"E:\extern\b.png", text_chunk("parameters", "zwei"))
    assert _hashes(db, "fundort: library") == {"a1" * 32}
    assert _hashes(db, "fundort: extern") == {"b2" * 32}


def test_fundort_escapes_like_wildcards(db, monkeypatch):
    # `_` ist in Pfaden legal und darf kein LIKE-Wildcard sein: /be_stand
    # darf /beXstand nicht matchen (dieselbe Falle wie _bestand_locations).
    monkeypatch.setattr(filters, "library_root_provider", lambda: "/be_stand")
    _store(db, "a1" * 32, "/beXstand/a.png", text_chunk("parameters", "eins"))
    _store(db, "b2" * 32, "/be_stand/b.png", text_chunk("parameters", "zwei"))
    assert _hashes(db, "fundort: library") == {"b2" * 32}


# -- datei: — Dateiname der Fundorte (Feral Strawberry, 2026-07-16) ----------------------------


def test_datei_parse_serialize_round_trip():
    preds = filters.parse('datei: mj_haus -datei: "genau.png"')
    assert [(p.kind, p.value, p.exact, p.negated) for p in preds] == [
        ("datei", "mj_haus", False, False), ("datei", "genau.png", True, True),
    ]
    assert filters.serialize(preds) == 'datei: mj_haus -datei: "genau.png"'


def test_datei_matches_basename_only(db):
    # Teilstring trifft NUR den Dateinamen, nicht das Verzeichnis — sonst
    # fände »haus« jede Datei unter /haus/. Windows-Pfade normalisiert.
    _store(db, "a1" * 32, "/haus/feral_haus_am_see_1234.png",
           text_chunk("parameters", "eins"))
    _store(db, "b2" * 32, r"C:\haus\anderes.png", text_chunk("parameters", "zwei"))
    assert _hashes(db, "datei: haus") == {"a1" * 32}
    assert _hashes(db, "-datei: haus") == {"b2" * 32}
    assert _hashes(db, "datei: HAUS") == {"a1" * 32}  # case-insensitiv


def test_datei_exact_and_or(db):
    _store(db, "a1" * 32, "/x/eins.png", text_chunk("parameters", "eins"))
    _store(db, "b2" * 32, "/x/zwei.png", text_chunk("parameters", "zwei"))
    _store(db, "c3" * 32, "/x/eins.png.bak.png", text_chunk("parameters", "drei"))
    assert _hashes(db, 'datei: "eins.png"') == {"a1" * 32}
    assert _hashes(db, "datei: eins | zwei") == {"a1" * 32, "b2" * 32, "c3" * 32}


def test_datei_escapes_like_wildcards(db):
    _store(db, "a1" * 32, "/x/a_b.png", text_chunk("parameters", "eins"))
    _store(db, "b2" * 32, "/x/aXb.png", text_chunk("parameters", "zwei"))
    assert _hashes(db, "datei: a_b") == {"a1" * 32}
