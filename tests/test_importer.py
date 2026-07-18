"""Tests für den Import-Kern (Stufe 4.1, ADR 0006/0019)."""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone

import pytest

from feral.db import connect
from feral import importer

from .pngbuild import build_png, text_chunk

MTIME_2024 = datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc).timestamp()


@pytest.fixture
def env(tmp_path):
    source = tmp_path / "quelle"
    target = tmp_path / "bestand"
    source.mkdir()
    target.mkdir()
    conn = connect(tmp_path / "feral.sqlite")
    yield conn, source, target
    conn.close()


def _png(path, text="ein prompt", mtime=MTIME_2024):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_png(text_chunk("parameters", text)))
    os.utime(path, (mtime, mtime))
    return path


def _run(conn, source, target):
    return importer.import_folder(conn, source, target_root=target)


def _log_actions(conn):
    return [r["action"] for r in conn.execute(
        "SELECT action FROM import_log ORDER BY id")]


# -- Neu: Datumsstruktur, Katalogisierung, Quelle nach _importiert -----------------


def test_new_file_lands_in_date_structure(env):
    conn, source, target = env
    _png(source / "bild.png")

    report = _run(conn, source, target)

    assert report.importiert == 1 and report.fehler == 0
    destination = target / "2024" / "05" / "01" / "bild.png"
    assert destination.is_file()
    assert (source / "_importiert" / "bild.png").is_file()
    # sofort katalogisiert, Fundort = Ziel (nicht die Quelle)
    row = conn.execute("SELECT path FROM file_locations").fetchone()
    assert row["path"] == str(destination)
    assert _log_actions(conn) == ["importiert"]


def test_subfolders_are_flattened(env):
    conn, source, target = env
    _png(source / "unter" / "ordner" / "tief.png")

    report = _run(conn, source, target)

    assert report.importiert == 1
    assert (source / "_importiert" / "tief.png").is_file()


# -- Dubletten ----------------------------------------------------------------------


def test_duplicate_goes_to_dubletten_without_copy(env):
    conn, source, target = env
    _png(source / "a.png")
    _run(conn, source, target)
    # identischer Inhalt, anderer Name, zweite Lieferung
    _png(source / "b_kopie.png")

    report = _run(conn, source, target)

    assert report.dublette == 1 and report.importiert == 0
    assert (source / "_dubletten" / "b_kopie.png").is_file()
    assert len(list((target / "2024" / "05" / "01").iterdir())) == 1
    assert _log_actions(conn) == ["importiert", "dublette"]


def test_identical_files_in_same_run_are_one_import_one_dupe(env):
    """In-Run-Dublettencheck (Block 4S): die Pipeline arbeitet mit Vorlauf —
    zwei identische neue Dateien im SELBEN Lauf müssen trotzdem 1× Import
    und 1× Dublette ergeben (der Writer prüft gegen die Hashes des Laufs)."""
    conn, source, target = env
    _png(source / "a.png")
    _png(source / "b_gleich.png")   # bit-identischer Inhalt

    report = _run(conn, source, target)

    assert report.importiert == 1 and report.dublette == 1
    assert len(list((target / "2024" / "05" / "01").iterdir())) == 1
    assert sorted(_log_actions(conn)) == ["dublette", "importiert"]


def test_batched_commit_moves_sources_only_after_persist(env):
    """Quell-Moves nach _importiert kommen erst NACH dem Commit ihres Schubs
    (ADR 0006 + Block 4S) — am Ende des Laufs ist beides konsistent."""
    conn, source, target = env
    for i in range(7):
        _png(source / f"bild{i}.png", text=f"prompt {i}")

    report = importer.import_folder(
        conn, source, target_root=target, commit_every=3,
    )

    assert report.importiert == 7
    assert len(list((source / "_importiert").iterdir())) == 7
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 7


def test_reject_blocks_reimport_until_unblocked(env, tmp_path):
    """ADR 0041: Ablehnen → Item raus + Sperrliste, die Datei bleibt liegen;
    Import/Scan überspringen gesperrte Hashes sichtbar; Entsperren erlaubt
    den Re-Import."""
    from feral import scan
    from feral.web import admin as admin_lib
    from feral.web.bulk import apply_bulk

    conn, source, target = env
    _png(source / "weg-damit.png")
    _run(conn, source, target)
    file_hash = conn.execute("SELECT file_hash FROM items").fetchone()[0]
    bestand_copy = target / "2024" / "05" / "01" / "weg-damit.png"
    assert bestand_copy.is_file()

    result = apply_bulk(conn, hashes=[file_hash], reject=True)
    assert result == {"matched": 1, "rejected": 1}
    assert bestand_copy.is_file()                     # Original heilig — bleibt
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0
    entry = admin_lib.blocked_list(conn)[0]
    assert entry["file_hash"] == file_hash
    assert str(bestand_copy) in entry["last_paths"]   # Pfad-Gedächtnis (I3)

    # Re-Import derselben (liegen gebliebenen) Datei → _gesperrt.
    shutil.copy2(bestand_copy, source / "nochmal.png")
    report = _run(conn, source, target)
    assert report.gesperrt == 1 and report.importiert == 0
    assert (source / "_gesperrt" / "nochmal.png").is_file()
    assert "gesperrt" in _log_actions(conn)

    # Scan überspringt gesperrte Dateien ebenfalls.
    blocked_file = _png(tmp_path / "scan" / "auch-weg.png")
    shutil.copy2(source / "_gesperrt" / "nochmal.png", blocked_file)
    scan_report = scan.scan_files(conn, [blocked_file])
    assert scan_report.blocked == 1
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0

    # Entsperren → Import klappt wieder.
    assert admin_lib.unblock(conn, file_hash) == 1
    shutil.copy2(blocked_file, source / "dritter-versuch.png")
    report3 = _run(conn, source, target)
    assert report3.importiert == 1


def test_broken_bestand_copy_is_repaired_not_discarded(env):
    conn, source, target = env
    _png(source / "a.png")
    _run(conn, source, target)
    bestand = target / "2024" / "05" / "01" / "a.png"
    bestand.write_bytes(b"kaputt")   # Bitfäule simulieren
    _png(source / "a_nochmal.png")

    report = _run(conn, source, target)

    assert report.repariert == 1 and report.dublette == 0
    # die "Dublette" war die einzige gute Kopie — sie ist jetzt im Bestand
    assert (target / "2024" / "05" / "01" / "a_nochmal.png").is_file()
    assert "repariert" in _log_actions(conn)


# -- Kollision ------------------------------------------------------------------------


def test_name_collision_gets_suffix(env):
    conn, source, target = env
    _png(source / "gleich.png", text="inhalt eins")
    _run(conn, source, target)
    _png(source / "gleich.png", text="inhalt zwei, andere datei")

    report = _run(conn, source, target)

    assert report.importiert == 1
    day = target / "2024" / "05" / "01"
    assert (day / "gleich.png").is_file()
    assert (day / "gleich__2.png").is_file()


# -- Verifikationsfehler (Kopie manipuliert) --------------------------------------------


def test_copy_verification_failure_goes_to_fehler(env, monkeypatch):
    conn, source, target = env
    _png(source / "bild.png")

    real_copy2 = importer.shutil.copy2

    def corrupting_copy(src, dst):
        real_copy2(src, dst)
        with open(dst, "ab") as fh:
            fh.write(b"MANIPULIERT")

    monkeypatch.setattr(importer.shutil, "copy2", corrupting_copy)
    report = _run(conn, source, target)

    assert report.fehler == 1 and report.importiert == 0
    assert (source / "_fehler" / "bild.png").is_file()
    # keine halbe Kopie, kein Katalogeintrag
    assert not list((target).rglob("*.png"))
    assert not list((target).rglob("*.part"))
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0


# -- Unbekanntes Format / halbe Datei ---------------------------------------------------


def test_unknown_format_goes_to_own_folder(env):
    conn, source, target = env
    (source / "notizen.txt").write_text("kein Medium")

    report = _run(conn, source, target)

    assert report.unbekanntes_format == 1
    assert (source / "_unbekanntes-format" / "notizen.txt").is_file()
    assert _log_actions(conn) == ["unbekanntes_format"]


def test_truncated_png_is_still_imported(env):
    conn, source, target = env
    data = build_png(text_chunk("parameters", "abc"))
    half = source / "halb.png"
    half.write_bytes(data[: len(data) // 2])   # Magic ok, Rest fehlt
    os.utime(half, (MTIME_2024, MTIME_2024))

    report = _run(conn, source, target)

    # defensiv (ADR 0008): Warnungen ja, aber importiert — nur harte Fehler
    # landen in _fehler
    assert report.importiert == 1 and report.fehler == 0


# -- Datums-Kaskade ------------------------------------------------------------------


def test_epoch_mtime_lands_in_unknown_date_bucket(env):
    conn, source, target = env
    _png(source / "uralt.png", mtime=0)   # 1.1.1970 — unplausibel für AI-Medien

    report = _run(conn, source, target)

    assert report.importiert == 1
    assert (target / importer.UNKNOWN_DATE_DIR / "uralt.png").is_file()
    row = conn.execute("SELECT date_source FROM import_log").fetchone()
    assert row["date_source"] == "unplausibel"


def test_embedded_exif_date_beats_filesystem(tmp_path, env):
    conn, source, target = env
    from PIL import Image

    exif = Image.Exif()
    exif[0x0132] = "2023:11:24 09:30:00"   # DateTime
    path = source / "webp_mit_datum.webp"
    Image.new("RGB", (8, 8), (200, 40, 60)).save(path, "WEBP", exif=exif)
    os.utime(path, (MTIME_2024, MTIME_2024))  # Dateisystem sagt 2024

    report = _run(conn, source, target)

    assert report.importiert == 1
    assert (target / "2023" / "11" / "24" / "webp_mit_datum.webp").is_file()
    row = conn.execute("SELECT date_source FROM import_log").fetchone()
    assert row["date_source"] == "metadaten"


def test_state_folders_are_not_reimported(env):
    conn, source, target = env
    _png(source / "bild.png")
    _run(conn, source, target)

    report = _run(conn, source, target)   # zweiter Lauf über denselben Ordner

    assert report.importiert == 0 and report.dublette == 0
    assert _log_actions(conn) == ["importiert"]


# -- source_mode="belassen" (ADR 0031): Quelle wird NIE angefasst -------------------


def test_import_folder_belassen_laesst_quelle_unangetastet(env):
    """kopieren-Watchordner (ADR 0031): Kopie wandert in den Bestand, aber die
    Quelle bleibt exakt wie sie war — kein _importiert/, keine Ausgangs-Ordner.
    Genau der Windows-Befund: „Hotfolder verschiebt statt zu kopieren"."""
    conn, source, target = env
    _png(source / "neu.png", "belassen-test")

    report = importer.import_folder(
        conn, source, target_root=target, source_mode="belassen"
    )
    assert report.importiert == 1
    # Kopie im Bestand …
    assert (target / "2024" / "05" / "01" / "neu.png").is_file()
    # … und die Quelle liegt UNVERÄNDERT am Ort — nichts einsortiert.
    assert (source / "neu.png").is_file()
    assert not (source / "_importiert").exists()

    # Zweiter Lauf: Dublette — auch die bleibt liegen (kein _dubletten/).
    report2 = importer.import_folder(
        conn, source, target_root=target, source_mode="belassen"
    )
    assert report2.dublette == 1
    assert (source / "neu.png").is_file()
    assert not (source / "_dubletten").exists()


def test_import_file_belassen_und_loeschen(env):
    """import_file: belassen lässt die Quelle liegen, loeschen entfernt sie."""
    conn, source, target = env
    bleibt = _png(source / "bleibt.png", "eins")
    weg = _png(source / "weg.png", "zwei")

    action, _ = importer.import_file(
        conn, bleibt, source_root=source, target_root=target, source_mode="belassen"
    )
    assert action == "importiert" and bleibt.is_file()

    action, _ = importer.import_file(
        conn, weg, source_root=source, target_root=target, source_mode="loeschen"
    )
    assert action == "importiert" and not weg.exists()


# -- Fundort-Invariante + Leerordner-Aufräumen (ADR 0033) ---------------------------


def _katalogisiere(conn, path):
    """Datei am Ort aufnehmen wie ein katalogisieren-Watchordner (ADR 0031)."""
    from feral.db.store import now_iso, store_extraction
    from feral.extract import container
    from feral.hashing import hash_file

    file_hash = hash_file(path)
    store_extraction(
        conn, file_hash=file_hash, file_size=path.stat().st_size,
        path=path, extraction=container.extract(path), now=now_iso(),
    )
    conn.commit()
    return file_hash


def test_verschieben_raeumt_fundort_zeile_der_quelle_ab(env):
    """Katalogisierte Quelle wird verschoben → keine verwaiste Fundort-Zeile.

    Genau Feral Strawberrys 35k-Befund: Ordner stand auf „katalogisieren“, dann kam der
    Verschiebe-Import — vorher blieben alle Quell-Fundorte als Waisen stehen.
    """
    conn, source, target = env
    path = _png(source / "alt" / "bild.png")
    _katalogisiere(conn, path)

    report = importer.import_folder(
        conn, source, target_root=target, source_mode="loeschen"
    )

    assert report.importiert == 1 and not path.exists()
    paths = [r["path"] for r in conn.execute("SELECT path FROM file_locations")]
    assert str(path) not in paths                      # keine Waise
    assert len(paths) == 1 and paths[0].startswith(str(target))


def test_dublette_raeumt_fundort_zeile_ab(env):
    """Auch der Dubletten-Ausgang entwertet den Quellpfad → Zeile weg."""
    conn, source, target = env
    _png(source / "a.png", "gleicher inhalt")
    importer.import_folder(conn, source, target_root=target, source_mode="loeschen")

    dupe = _png(source / "kopie" / "b.png", "gleicher inhalt")
    _katalogisiere(conn, dupe)
    report = importer.import_folder(
        conn, source, target_root=target, source_mode="loeschen"
    )

    assert report.dublette == 1
    paths = [r["path"] for r in conn.execute("SELECT path FROM file_locations")]
    assert str(dupe) not in paths
    assert len(paths) == 1 and paths[0].startswith(str(target))


def test_belassen_laesst_fundort_zeile_stehen(env):
    """kopieren-Modus fasst die Quelle nie an (ADR 0031) — auch nicht ihre Zeile."""
    conn, source, target = env
    path = _png(source / "bild.png")
    _katalogisiere(conn, path)

    importer.import_folder(conn, source, target_root=target, source_mode="belassen")

    paths = [r["path"] for r in conn.execute("SELECT path FROM file_locations")]
    assert str(path) in paths                          # Quelle bleibt katalogisiert


def test_remove_empty_dirs_entfernt_nur_leere_unterordner(tmp_path):
    root = tmp_path / "quelle"
    (root / "2024" / "05" / "01").mkdir(parents=True)
    (root / "2024" / "05" / "01" / ".DS_Store").write_bytes(b"junk")
    (root / "2024" / "06").mkdir(parents=True)
    (root / "voll").mkdir()
    (root / "voll" / "bild.png").write_bytes(b"echt")
    (root / "_importiert" / "rest").mkdir(parents=True)

    removed = importer.remove_empty_dirs(root)

    # 2024/05/01, 2024/05, 2024/06 und 2024 kollabieren in EINEM Durchlauf.
    assert removed == 4
    assert not (root / "2024").exists()
    assert (root / "voll" / "bild.png").is_file()      # echter Inhalt bleibt
    assert (root / "_importiert" / "rest").is_dir()    # Ausgangs-Ordner tabu
    assert root.is_dir()                               # Wurzel tabu


def test_import_folder_verschieben_raeumt_leere_ordner(env):
    conn, source, target = env
    _png(source / "a" / "b" / "bild.png")

    report = importer.import_folder(
        conn, source, target_root=target, source_mode="loeschen", remove_empty=True
    )

    assert report.importiert == 1
    assert report.leere_ordner == 2                    # a/b und a
    assert not (source / "a").exists()
    assert source.is_dir()
    assert "leere Ordner entfernt" in report.summary()


def test_remove_empty_wirkt_nicht_im_belassen_modus(env):
    """Schalter + kopieren-Watchordner: Quelle bleibt komplett unangetastet."""
    conn, source, target = env
    _png(source / "unter" / "bild.png")

    report = importer.import_folder(
        conn, source, target_root=target, source_mode="belassen", remove_empty=True
    )

    assert report.leere_ordner == 0
    assert (source / "unter" / "bild.png").is_file()


# -- Import-Regeln (ADR 0046): Maße + Formate ---------------------------------------

from feral.extract.types import ContainerExtraction


def test_filter_reason_rules():
    rules = {"min_kante": 240, "max_kante": 8000, "formate": ["psd", "arw"]}
    img = lambda w, h, c="png": ContainerExtraction(container=c, width=w, height=h)
    assert importer.filter_reason(img(100, 500), rules) is not None      # zu klein
    assert importer.filter_reason(img(500, 9000), rules) is not None     # zu groß
    assert importer.filter_reason(img(500, 500), rules) is None          # passt
    # Format ausgeschlossen — auch ohne Maße (PSD/ARW haben keinen Extraktor).
    assert importer.filter_reason(ContainerExtraction(container="arw"), rules) is not None
    # Ohne Maße wird nie über Größe geraten; Videos sind von Maß-Regeln frei.
    assert importer.filter_reason(ContainerExtraction(container="png"), rules) is None
    assert importer.filter_reason(
        ContainerExtraction(container="matroska", width=100, height=100), rules
    ) is None
    # Keine/leere Regeln = kein Filter.
    assert importer.filter_reason(img(1, 1), None) is None
    assert importer.filter_reason(img(1, 1), {"min_kante": 0, "max_kante": 0, "formate": []}) is None


def _mini_png(path, width, height, mtime=MTIME_2024):
    from .pngbuild import PNG_SIGNATURE  # noqa: F401 — nur zur Doku
    from .pngbuild import build_png as _bp, ihdr, text_chunk as _tc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_bp(ihdr(width, height), _tc("parameters", "p"),
                         include_ihdr=False))
    os.utime(path, (mtime, mtime))
    return path


def test_import_rules_small_image_ausgefiltert(env):
    conn, source, target = env
    _mini_png(source / "thumb.png", 100, 100)
    _png(source / "gross.png")   # 1×1, aber ohne Regeln unter min? — s. rules

    rules = {"min_kante": 50, "max_kante": 0, "formate": []}
    # gross.png ist 1×1 → unter min_kante 50 ⇒ auch ausgefiltert; thumb.png
    # 100×100 ≥ 50 ⇒ importiert. So prüft EIN Lauf beide Richtungen.
    report = importer.import_folder(conn, source, target_root=target, rules=rules)

    assert report.ausgefiltert == 1 and report.importiert == 1
    assert (source / "_ausgefiltert" / "gross.png").is_file()
    assert not (source / "gross.png").exists()
    log = {r["action"]: r["detail"] for r in conn.execute(
        "SELECT action, detail FROM import_log")}
    assert "ausgefiltert" in log and "zu klein" in log["ausgefiltert"]
    # Nicht katalogisiert: nur das importierte Item steht im Katalog.
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1


def test_import_rules_keep_source_bleibt_liegen(env):
    conn, source, target = env
    _mini_png(source / "thumb.png", 10, 10)
    report = importer.import_folder(
        conn, source, target_root=target, source_mode="belassen",
        rules={"min_kante": 240, "max_kante": 0, "formate": []},
    )
    assert report.ausgefiltert == 1
    # „belassen" (ADR 0031): Quelle wird NIE angefasst, auch nicht beim Filtern.
    assert (source / "thumb.png").is_file()
    assert not (source / "_ausgefiltert").exists()


def test_import_rules_arw_format_ausgeschlossen(env):
    conn, source, target = env
    arw = source / "foto.arw"
    arw.write_bytes(b"II\x2a\x00" + b"\x00" * 64)   # TIFF-Magic, Endung .arw

    report = importer.import_folder(
        conn, source, target_root=target,
        rules={"min_kante": 0, "max_kante": 0, "formate": ["arw"]},
    )
    assert report.ausgefiltert == 1
    assert (source / "_ausgefiltert" / "foto.arw").is_file()


def test_arw_ohne_regeln_importiert_als_arw(env):
    conn, source, target = env
    (source / "foto.arw").write_bytes(b"II\x2a\x00" + b"\x00" * 64)

    report = importer.import_folder(conn, source, target_root=target)
    assert report.importiert == 1
    row = conn.execute("SELECT container, media_kind FROM items").fetchone()
    assert row["container"] == "arw" and row["media_kind"] == "image"
