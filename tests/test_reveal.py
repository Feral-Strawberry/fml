"""„Im Dateimanager anzeigen" (I6, ADR 0041): Kommando-Bauer + Endpunkt.

Der Prozessstart selbst wird nicht getestet (würde echte Fenster öffnen) —
`reveal_command` ist pur, der Endpunkt bekommt einen aufzeichnenden Ersatz.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
from fastapi import HTTPException

from feral import reveal


# --- Kommando-Bauer (pur, je Plattform) ------------------------------------------


def test_reveal_command_windows_selects_file() -> None:
    """explorer zerlegt seine Kommandozeile selbst: Anführungszeichen NUR um
    den Pfad (Issue #37 — ``"/select,C:\\a b\\x.png"`` als Ganzes in Quotes
    öffnet still „Dokumente"). Darum ein String, keine Argumentliste."""
    # Pure*-Pfade: der Test darf nicht vom Host-Betriebssystem abhängen
    # (Path("/medien/…") wurde unter Windows zu "\\medien\\…", Issue #50).
    cmd, selected = reveal.reveal_command(
        PureWindowsPath(r"C:\medien\bild.png"), platform="win32")
    assert cmd == r'explorer /select,"C:\medien\bild.png"'
    assert selected is True


def test_reveal_command_windows_quotes_only_the_path_with_spaces() -> None:
    cmd, _ = reveal.reveal_command(
        PureWindowsPath(r"C:\Users\Feral Strawberry\Stable Diffusion\a b.png"),
        platform="win32")
    assert cmd == r'explorer /select,"C:\Users\Feral Strawberry\Stable Diffusion\a b.png"'
    assert isinstance(cmd, str)   # kein list2cmdline-Quoting um /select,


def test_reveal_command_windows_strips_long_path_prefix() -> None:
    """``\\\\?\\``-Syntax versteht nur die Win32-API, nicht Explorer."""
    cmd, selected = reveal.reveal_command(
        PureWindowsPath(r"\\?\D:\medien\bild.png"), platform="win32")
    assert cmd == r'explorer /select,"D:\medien\bild.png"'
    assert selected is True
    assert reveal.windows_display_path(r"\\?\UNC\nas\share\x.png") == r"\\nas\share\x.png"


def test_reveal_command_windows_long_path_opens_folder_only() -> None:
    """Über MAX_PATH kann /select, nicht markieren: ehrlich nur den Ordner
    öffnen und das melden (selected=False) statt still „Dokumente"."""
    folder = PureWindowsPath("C:\\" + "\\".join(["ordner_mit_langem_namen"] * 12))
    path = folder / "bild.png"
    assert len(str(path)) > reveal.WINDOWS_MAX_PATH
    cmd, selected = reveal.reveal_command(path, platform="win32")
    assert cmd == f'explorer "{folder}"'
    assert selected is False


def test_reveal_command_macos_reveals_in_finder() -> None:
    cmd, selected = reveal.reveal_command(PurePosixPath("/medien/bild.png"), platform="darwin")
    assert cmd == ["open", "-R", "/medien/bild.png"]
    assert selected is True


def test_reveal_command_other_opens_parent_folder() -> None:
    """Ohne Markier-Fähigkeit (Linux u. a.): Fallback öffnet den Ordner."""
    cmd, selected = reveal.reveal_command(PurePosixPath("/medien/bild.png"), platform="linux")
    assert cmd == ["xdg-open", "/medien"]
    assert selected is False


# --- Endpunkt POST /api/item/{hash}/reveal ---------------------------------------


def _reveal_endpoint(app):
    return next(
        route for route in app.routes
        if getattr(route, "path", None) == "/api/item/{file_hash}/reveal"
    ).endpoint


def test_reveal_endpoint_opens_first_existing_location(tmp_path, monkeypatch) -> None:
    from feral.db import connect, store_extraction
    from feral.extract.types import ContainerExtraction
    from feral.hashing import hash_file
    from feral.web.app import create_app

    media = tmp_path / "bild.png"
    media.write_bytes(b"png")
    # Echter Hash: der Endpunkt verifiziert den Inhalt vor dem Öffnen (ADR 0062).
    file_hash = hash_file(media)
    # Unnormalisierter Fundort-Pfad ("sub/../"): explorer /select, scheitert an
    # solchen Pfaden kommentarlos — der Endpunkt muss normalisieren.
    (tmp_path / "sub").mkdir()
    stored = tmp_path / "sub" / ".." / "bild.png"

    app = create_app(tmp_path / "t.sqlite")
    try:
        conn = connect(tmp_path / "t.sqlite")
        store_extraction(conn, file_hash=file_hash, file_size=3, path=stored,
                         extraction=ContainerExtraction(container="png"))
        conn.close()

        opened: list[Path] = []
        monkeypatch.setattr(reveal, "show_in_file_manager",
                            lambda p: (opened.append(p), (True, "test"))[1])

        result = _reveal_endpoint(app)(file_hash)
        assert opened == [media]                     # ohne ".."-Segment
        assert result == {"revealed": str(media), "verified": True, "selected": True, "via": "test"}
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


def test_reveal_endpoint_404_on_foreign_content_same_size(tmp_path, monkeypatch) -> None:
    """Größengleicher Fremdinhalt am katalogisierten Pfad (das Restfenster
    aus ADR 0049): die Hash-Verifikation lässt den Dateimanager NICHT auf
    die falsche Datei zeigen."""
    from feral.db import connect, store_extraction
    from feral.extract.types import ContainerExtraction
    from feral.hashing import hash_file
    from feral.web.app import create_app

    media = tmp_path / "bild.png"
    media.write_bytes(b"png")
    file_hash = hash_file(media)

    app = create_app(tmp_path / "t.sqlite")
    try:
        conn = connect(tmp_path / "t.sqlite")
        store_extraction(conn, file_hash=file_hash, file_size=3, path=media,
                         extraction=ContainerExtraction(container="png"))
        conn.close()
        media.write_bytes(b"xxx")   # gleiche Größe, anderer Inhalt

        def boom(_path: Path) -> None:  # pragma: no cover - darf nie laufen
            raise AssertionError("Dateimanager darf bei Fremdinhalt nicht starten")

        monkeypatch.setattr(reveal, "show_in_file_manager", boom)
        with pytest.raises(HTTPException) as exc:
            _reveal_endpoint(app)(file_hash)
        assert exc.value.status_code == 404
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


def test_reveal_endpoint_404_without_existing_location(tmp_path, monkeypatch) -> None:
    """Fundort-Datei weg ⇒ ehrliche 404, es wird kein Prozess gestartet."""
    from feral.db import connect, store_extraction
    from feral.extract.types import ContainerExtraction
    from feral.web.app import create_app

    file_hash = "cd" * 32
    app = create_app(tmp_path / "t.sqlite")
    try:
        conn = connect(tmp_path / "t.sqlite")
        store_extraction(conn, file_hash=file_hash, file_size=3,
                         path=tmp_path / "verschwunden.png",
                         extraction=ContainerExtraction(container="png"))
        conn.close()

        def boom(_path: Path) -> None:  # pragma: no cover - darf nie laufen
            raise AssertionError("Dateimanager darf ohne Fundort nicht starten")

        monkeypatch.setattr(reveal, "show_in_file_manager", boom)
        with pytest.raises(HTTPException) as exc:
            _reveal_endpoint(app)(file_hash)
        assert exc.value.status_code == 404
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


def test_reveal_endpoint_skips_hashing_above_size_guard(tmp_path, monkeypatch) -> None:
    """Größen-Wächter fürs Verifizieren (Issue #37): Dateien über
    VERIFY_MAX_BYTES werden NICHT gehasht (ein 2-GB-Video ließ den Request
    minutenlang hängen) — der Endpunkt öffnet auf Basis der Größenprüfung
    und sagt ehrlich ``verified: False``."""
    from feral.db import connect, store_extraction
    from feral.extract.types import ContainerExtraction
    from feral.hashing import hash_file
    from feral.web import library
    from feral.web.app import create_app

    media = tmp_path / "video.webm"
    media.write_bytes(b"webm")
    file_hash = hash_file(media)
    monkeypatch.setattr(library, "VERIFY_MAX_BYTES", 3)   # 4 Bytes > Grenze

    def never(_path):  # pragma: no cover - darf nie laufen
        raise AssertionError("über der Größengrenze darf nicht gehasht werden")

    monkeypatch.setattr(library, "hash_file", never)
    app = create_app(tmp_path / "t.sqlite")
    try:
        conn = connect(tmp_path / "t.sqlite")
        store_extraction(conn, file_hash=file_hash, file_size=4, path=media,
                         extraction=ContainerExtraction(container="webm"))
        conn.close()
        opened: list[Path] = []
        monkeypatch.setattr(reveal, "show_in_file_manager",
                            lambda p: (opened.append(p), (True, "test"))[1])
        result = _reveal_endpoint(app)(file_hash)
        assert opened == [media]
        assert result == {"revealed": str(media), "verified": False, "selected": True, "via": "test"}
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


def test_reveal_endpoint_prefers_library_location(tmp_path, monkeypatch) -> None:
    """Fundort-Priorisierung (ADR-0062-Nachtrag): die Library-Kopie schlägt
    die zuerst katalogisierte Watch-Quelle, egal in welcher Reihenfolge die
    Fundorte in die DB kamen."""
    from feral.db import connect, store_extraction
    from feral.extract.types import ContainerExtraction
    from feral.hashing import hash_file
    from feral.web import filters, library
    from feral.web.app import create_app

    quelle = tmp_path / "quelle"; quelle.mkdir()
    lib = tmp_path / "bestand" / "2026" / "09" / "08"; lib.mkdir(parents=True)
    a = quelle / "bild.png"; a.write_bytes(b"png")
    b = lib / "bild.png"; b.write_bytes(b"png")
    file_hash = hash_file(a)

    app = create_app(tmp_path / "t.sqlite")
    try:
        # Provider wie im Config-Betrieb (create_app ohne Config setzt keine).
        monkeypatch.setattr(filters, "library_root_provider",
                            lambda: str(tmp_path / "bestand"))
        monkeypatch.setattr(library, "watch_roots_provider", lambda: [str(quelle)])
        conn = connect(tmp_path / "t.sqlite")
        ext = ContainerExtraction(container="png")
        store_extraction(conn, file_hash=file_hash, file_size=3, path=a, extraction=ext)
        store_extraction(conn, file_hash=file_hash, file_size=3, path=b, extraction=ext)
        conn.close()
        opened: list[Path] = []
        monkeypatch.setattr(reveal, "show_in_file_manager",
                            lambda p: (opened.append(p), (True, "test"))[1])
        _reveal_endpoint(app)(file_hash)
        assert opened == [b]
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


# --- Shell-API + Rückfall (Windows), Öffnen im Standardprogramm -----------------


def test_show_in_file_manager_windows_prefers_shell_api(monkeypatch) -> None:
    """Erster Weg auf Windows: SHOpenFolderAndSelectItems (markiert UND
    scrollt ins Bild), danach das Fenster des Elternordners nach vorn;
    explorer wird dann NICHT gestartet."""
    called: list[str] = []
    focused: list[str] = []
    monkeypatch.setattr(reveal, "windows_shell_select", called.append)
    monkeypatch.setattr(reveal, "explorer_handles_before", lambda: frozenset({7}))
    monkeypatch.setattr(reveal, "windows_focus_explorer",
                        lambda folder, before: (focused.append((folder, before)), True)[1])

    def no_popen(*_a, **_k):  # pragma: no cover - darf nie laufen
        raise AssertionError("bei erfolgreicher Shell-API kein explorer-Start")

    monkeypatch.setattr(reveal.subprocess, "Popen", no_popen)
    result = reveal.show_in_file_manager(PureWindowsPath(r"\\?\C:\medien\bild.png"), platform="win32")
    assert result == (True, "shell-api")
    assert called == [r"C:\medien\bild.png"]           # ohne \\?\-Präfix
    assert focused == [(r"C:\medien", frozenset({7}))]   # Momentaufnahme VOR dem Öffnen


def test_show_in_file_manager_windows_reports_missing_focus(monkeypatch) -> None:
    """Fokus ist Komfort: klappt er nicht (oder wirft), bleibt die Markierung
    gültig — die Antwort sagt es nur (``shell-api-nofocus``)."""
    monkeypatch.setattr(reveal, "windows_shell_select", lambda _p: None)
    monkeypatch.setattr(reveal, "windows_focus_explorer", lambda _f, before: False)
    assert reveal.show_in_file_manager(PureWindowsPath(r"C:\m\a.png"), platform="win32") == (
        True, "shell-api-nofocus")

    def boom(_f, before):
        raise RuntimeError("EnumWindows kaputt")

    monkeypatch.setattr(reveal, "windows_focus_explorer", boom)
    assert reveal.show_in_file_manager(PureWindowsPath(r"C:\m\a.png"), platform="win32") == (
        True, "shell-api-nofocus")


def test_explorer_title_matches_display_name_full_path_and_drive() -> None:
    m = reveal.explorer_title_matches
    assert m("08", r"D:\fml\bestand\2026\09\08")                 # Anzeigename
    assert m("08 - Datei-Explorer", r"D:\fml\bestand\2026\09\08")  # Win-11-Anhängsel
    assert not m("080", r"D:\fml\bestand\2026\09\08")
    assert m(r"d:\FML\bestand\2026\09\08", r"D:\fml\bestand\2026\09\08")  # voller Pfad
    assert m("Daten (D:)", "D:\\")                                # Laufwerkswurzel
    assert not m("09", r"D:\fml\bestand\2026\09\08")
    assert not m("Dokumente", r"D:\fml\bestand\2026\09\08")
    assert not m("", r"D:\x")


def test_show_in_file_manager_windows_falls_back_to_explorer(monkeypatch) -> None:
    def boom(_path: str) -> None:
        raise OSError("COM kaputt")

    monkeypatch.setattr(reveal, "windows_shell_select", boom)
    started: list = []
    monkeypatch.setattr(reveal.subprocess, "Popen", lambda cmd, **_k: started.append(cmd))
    result = reveal.show_in_file_manager(PureWindowsPath(r"C:\medien\a b.png"), platform="win32")
    assert result == (True, "explorer")
    assert started == [r'explorer /select,"C:\medien\a b.png"']


def test_show_in_file_manager_macos_reports_via(monkeypatch) -> None:
    started: list = []
    monkeypatch.setattr(reveal.subprocess, "Popen", lambda cmd, **_k: started.append(cmd))
    assert reveal.show_in_file_manager(PurePosixPath("/m/bild.png"), platform="darwin") == (True, "open")
    assert started == [["open", "-R", "/m/bild.png"]]


def test_open_command_per_platform() -> None:
    """Datei/Ordner im zugeordneten Programm: Windows über os.startfile
    (None), macOS `open`, sonst `xdg-open` — je ein Kommando für beides."""
    assert reveal.open_command(PureWindowsPath(r"C:\m\bild.png"), platform="win32") is None
    assert reveal.open_command(PurePosixPath("/m/bild.png"), platform="darwin") == ["open", "/m/bild.png"]
    assert reveal.open_command(PurePosixPath("/m"), platform="linux") == ["xdg-open", "/m"]


def test_open_in_default_app_windows_uses_startfile(monkeypatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(reveal.os, "startfile", called.append, raising=False)
    focused: list = []
    monkeypatch.setattr(reveal, "windows_focus_explorer",
                        lambda folder, before: (focused.append(folder), True)[1])
    reveal.open_in_default_app(PureWindowsPath(r"\\?\C:\m\bild.png"), platform="win32")
    assert called == [r"C:\m\bild.png"]
    assert focused == []                                # Datei: Programm holt sich den Fokus selbst


def test_open_in_default_app_windows_focuses_folder(tmp_path, monkeypatch) -> None:
    """Breadcrumb-Ordner: os.startfile öffnet über die Shell und landet
    hinter dem Browser — danach dieselbe Fokus-Routine wie beim 📂-Knopf."""
    called: list[str] = []
    monkeypatch.setattr(reveal.os, "startfile", called.append, raising=False)
    monkeypatch.setattr(reveal, "explorer_handles_before", lambda: frozenset({3}))
    focused: list = []
    monkeypatch.setattr(reveal, "windows_focus_explorer",
                        lambda folder, before: (focused.append((folder, before)), True)[1])
    reveal.open_in_default_app(tmp_path, platform="win32")
    assert called == [str(tmp_path)]
    assert focused == [(str(tmp_path), frozenset({3}))]


# --- Endpunkt POST /api/item/{hash}/open (Fundort-Breadcrumb) --------------------


def _open_endpoint(app):
    return next(
        route for route in app.routes
        if getattr(route, "path", None) == "/api/item/{file_hash}/open"
    ).endpoint


def _catalogue(tmp_path, *paths):
    """App + DB mit EINEM Item an mehreren Fundorten (alle gleicher Inhalt)."""
    from feral.db import connect, store_extraction
    from feral.extract.types import ContainerExtraction
    from feral.hashing import hash_file
    from feral.web.app import create_app

    file_hash = hash_file(paths[0])
    app = create_app(tmp_path / "t.sqlite")
    conn = connect(tmp_path / "t.sqlite")
    for p in paths:
        store_extraction(conn, file_hash=file_hash, file_size=p.stat().st_size, path=p,
                         extraction=ContainerExtraction(container="png"))
    conn.close()
    return app, file_hash


def test_open_endpoint_opens_folder_prefix_and_file(tmp_path, monkeypatch) -> None:
    from feral.web.app import OpenRequest

    sub = tmp_path / "quelle" / "out"; sub.mkdir(parents=True)
    media = sub / "bild.png"; media.write_bytes(b"png")
    app, file_hash = _catalogue(tmp_path, media)
    try:
        opened: list[Path] = []
        monkeypatch.setattr(reveal, "open_in_default_app", opened.append)
        ep = _open_endpoint(app)
        # Ordner: jedes Verzeichnis-Präfix des Fundorts, ohne Markierung.
        assert ep(file_hash, OpenRequest(path=str(tmp_path / "quelle"), what="folder")) == {
            "opened": str(tmp_path / "quelle"), "what": "folder"}
        assert ep(file_hash, OpenRequest(path=str(sub) + "/", what="folder"))["opened"] == str(sub)
        # Datei: exakt der Fundort, im zugeordneten Programm.
        assert ep(file_hash, OpenRequest(path=str(media), what="file")) == {
            "opened": str(media), "what": "file"}
        assert opened == [tmp_path / "quelle", sub, media]
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


def test_open_endpoint_rejects_foreign_paths(tmp_path, monkeypatch) -> None:
    """Kein freier Pfad von außen: nur Fundorte dieses Items und deren
    Verzeichnis-Präfixe — sonst 400, und es startet nichts."""
    from feral.web.app import OpenRequest

    (tmp_path / "quelle").mkdir()
    media = tmp_path / "quelle" / "bild.png"; media.write_bytes(b"png")
    (tmp_path / "fremd").mkdir()
    app, file_hash = _catalogue(tmp_path, media)
    try:
        def boom(_p):  # pragma: no cover
            raise AssertionError("fremder Pfad darf nichts öffnen")
        monkeypatch.setattr(reveal, "open_in_default_app", boom)
        ep = _open_endpoint(app)
        for path, what in [(str(tmp_path / "fremd"), "folder"),
                           (str(tmp_path / "quelle" / "anderes.png"), "file"),
                           (str(tmp_path / "quel"), "folder"),     # Namensteil ist kein Präfix
                           (str(media), "folder"),                 # Datei ist kein Ordner-Präfix
                           (str(media), "delete")]:
            with pytest.raises(HTTPException) as exc:
                ep(file_hash, OpenRequest(path=path, what=what))
            assert exc.value.status_code == 400, (path, what)
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


def test_open_endpoint_404_when_folder_or_file_gone(tmp_path, monkeypatch) -> None:
    from feral.web.app import OpenRequest

    (tmp_path / "quelle").mkdir()
    media = tmp_path / "quelle" / "bild.png"; media.write_bytes(b"png")
    app, file_hash = _catalogue(tmp_path, media)
    try:
        def boom(_p):  # pragma: no cover
            raise AssertionError("ohne Ziel darf nichts öffnen")
        monkeypatch.setattr(reveal, "open_in_default_app", boom)
        ep = _open_endpoint(app)
        media.write_bytes(b"xxxx")                    # andere Größe ⇒ unbrauchbar
        with pytest.raises(HTTPException) as exc:
            ep(file_hash, OpenRequest(path=str(media), what="file"))
        assert exc.value.status_code == 404
        media.unlink(); (tmp_path / "quelle").rmdir()
        with pytest.raises(HTTPException) as exc:
            ep(file_hash, OpenRequest(path=str(tmp_path / "quelle"), what="folder"))
        assert exc.value.status_code == 404
        assert exc.value.detail["key"] == "errFolderMissing"
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()
