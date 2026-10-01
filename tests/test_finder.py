"""Finder-Tags und erweiterte Attribute unter macOS (#221/#222, ADR 0097)."""

from __future__ import annotations

import ctypes
import os
import plistlib
import sys

import pytest

from feral import finder, importer
from feral.db import connect, manual, store_extraction
from feral.extract.types import ContainerExtraction
from feral.scan import scan_directory
from feral.web import library

from .test_importer import _png

T0 = "2026-01-01T00:00:00+00:00"
HASH = "ab" * 32

macos = pytest.mark.skipif(sys.platform != "darwin", reason="Finder-Tags gibt es nur unter macOS")


def _tag_blob(*entries: str) -> bytes:
    return plistlib.dumps(list(entries), fmt=plistlib.FMT_BINARY)


def _set_tags(path, *entries: str) -> None:
    """Finder-Tags so an eine Datei hängen, wie der Finder es tut."""
    lib = ctypes.CDLL(None, use_errno=True)
    blob = _tag_blob(*entries)
    rc = lib.setxattr(os.fsencode(str(path)), finder.USER_TAGS.encode(), blob,
                      ctypes.c_size_t(len(blob)), ctypes.c_uint32(0), ctypes.c_int(0))
    assert rc == 0, os.strerror(ctypes.get_errno())


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    store_extraction(conn, file_hash=HASH, file_size=1, path=tmp_path / "a.png",
                     extraction=ContainerExtraction(container="png"), now=T0)
    yield conn
    conn.close()


# -- Lesen (plattformunabhängig) ------------------------------------------------------


def test_parse_user_tags_names_and_colors():
    blob = _tag_blob("Rot\n6", "Projekt X", "rot\n6", "Blau\n4", "  \n2", "Kaputt\n99")
    assert finder.parse_user_tags(blob) == [
        ("Rot", 6), ("Projekt X", 0), ("Blau", 4), ("Kaputt", 0)]


def test_parse_user_tags_is_defensive():
    assert finder.parse_user_tags(b"kein plist") == []
    assert finder.parse_user_tags(plistlib.dumps({"a": 1})) == []


# -- Speichern als fml-Tags -------------------------------------------------------------


def test_finder_tags_become_colored_tags_with_origin(db):
    assert manual.add_finder_tags(db, HASH, [("Rot", 6), ("Projekt X", 0)], T0) == 2
    ann = manual.annotations_for(db, HASH)
    assert ann["tags"] == ["Projekt X", "Rot"]
    assert ann["tag_meta"] == {"Projekt X": {"color": None, "finder": True},
                               "Rot": {"color": 6, "finder": True}}
    # sofort findbar (FTS) und als tag:-Filter
    assert library.list_items(db, filter_expr="text:projekt")["total"] == 1
    assert library.list_items(db, filter_expr="tag:Rot")["items"][0]["colors"] == [6]


def test_manual_assignment_stays_manual_and_repeat_is_noop(db):
    manual.add_tag(db, HASH, "Rot", now=T0)
    assert manual.add_finder_tags(db, HASH, [("rot", 6)], T0) == 0
    assert manual.annotations_for(db, HASH)["tag_meta"] == {
        "Rot": {"color": 6, "finder": False}}   # Farbe ja, Herkunft bleibt manuell
    assert manual.add_finder_tags(db, HASH, [("Rot", 0)], T0) == 0
    assert db.execute("SELECT color FROM tags").fetchone()[0] == 6   # 0 löscht nicht


def test_unknown_hash_is_ignored(db):
    assert manual.add_finder_tags(db, "ef" * 32, [("Rot", 6)], T0) == 0
    assert db.execute("SELECT COUNT(*) FROM tags").fetchone()[0] == 0


def test_items_without_colors_have_no_colors_key(db):
    manual.add_tag(db, HASH, "ohne Farbe", now=T0)
    assert "colors" not in library.list_items(db)["items"][0]


# -- macOS: Attribute mitkopieren (#221) und Tags übernehmen (#222) ----------------------


@pytest.fixture
def env(tmp_path):
    source, target = tmp_path / "quelle", tmp_path / "bestand"
    source.mkdir()
    target.mkdir()
    conn = connect(tmp_path / "feral.sqlite")
    yield conn, source, target
    conn.close()


def _tags_of(conn):
    return {r[0]: r[1] for r in conn.execute(
        "SELECT t.name, it.source FROM item_tags it JOIN tags t ON t.id = it.tag_id")}


@macos
@pytest.mark.parametrize("mode", ["einsortieren", "loeschen"])
def test_import_keeps_finder_tags(env, mode):
    conn, source, target = env
    _set_tags(_png(source / "bild.png"), "Rot\n6", "Archiv")

    report = importer.import_folder(conn, source, target_root=target, source_mode=mode)

    assert report.importiert == 1
    copy = target / "2024" / "05" / "01" / "bild.png"
    assert finder.read_finder_tags(copy) == [("Rot", 6), ("Archiv", 0)]
    assert _tags_of(conn) == {"Rot": "finder", "Archiv": "finder"}
    assert (source / "bild.png").exists() is False


@macos
def test_duplicate_brings_its_finder_tags(env):
    conn, source, target = env
    _png(source / "a.png")
    importer.import_folder(conn, source, target_root=target)
    _set_tags(_png(source / "b.png"), "Blau\n4")

    report = importer.import_folder(conn, source, target_root=target, source_mode="loeschen")

    assert report.dublette == 1
    assert _tags_of(conn) == {"Blau": "finder"}


@macos
def test_rescan_picks_up_finder_tags(env):
    conn, source, _target = env
    path = _png(source / "bild.png")
    scan_directory(conn, source)
    assert _tags_of(conn) == {}
    _set_tags(path, "Gelb\n5")
    scan_directory(conn, source)
    assert _tags_of(conn) == {"Gelb": "finder"}


@macos
def test_copy_xattrs_reports_failure(tmp_path):
    target = tmp_path / "ziel"
    target.write_bytes(b"x")
    assert "errno" in finder.copy_xattrs(tmp_path / "fehlt", target)


def test_parse_user_tags_survives_odd_colors_and_caps_the_list():
    """Das Attribut kommt mit der Datei: "²" ist für isdigit() eine Ziffer, für
    int() nicht; Zahl und Länge der Tags sind gedeckelt."""
    assert finder.parse_user_tags(_tag_blob("Rot\n²", "Blau\n" + "9" * 5000, "Ok\n6")) == [
        ("Rot", 0), ("Blau", 0), ("Ok", 6)]
    many = finder.parse_user_tags(_tag_blob(*(f"t{i}" for i in range(500)), "x" * 5000))
    assert len(many) == finder.MAX_TAGS
    assert len(finder.parse_user_tags(_tag_blob("y" * 5000))[0][0]) == finder.MAX_TAG_NAME
