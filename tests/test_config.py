"""Tests für das Laden der Konfiguration und die Scan-Orte."""

from __future__ import annotations

from feral.config import DEFAULT_DB_PATH, database_path, load_config, scan_locations
from feral.web import library

CONFIG_TOML = """
[database]
path = "/data/feral.sqlite"

[[scan.locations]]
name = "Hotfolder"
path = "/media/hotfolder"

[[scan.locations]]
path = "/media/ohne-name"

[[scan.locations]]
name = "kaputt"
"""


def _write(tmp_path, text):
    p = tmp_path / "config.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_missing_file_returns_empty(tmp_path):
    assert load_config(tmp_path / "fehlt.toml") == {}


def test_database_path_default_and_override(tmp_path):
    assert database_path({}) == DEFAULT_DB_PATH
    cfg = load_config(_write(tmp_path, CONFIG_TOML))
    assert database_path(cfg) == "/data/feral.sqlite"


def test_scan_locations_parsing(tmp_path):
    cfg = load_config(_write(tmp_path, CONFIG_TOML))
    locs = scan_locations(cfg)
    # Der Eintrag ohne 'path' wird übersprungen; fehlender Name aus Pfad abgeleitet.
    assert locs == [
        {"name": "Hotfolder", "path": "/media/hotfolder"},
        {"name": "ohne-name", "path": "/media/ohne-name"},
    ]


def test_scan_locations_empty_when_no_section():
    assert scan_locations({}) == []


def test_list_roots_always_offers_entry_points():
    """Einstiegspunkte in den Ordner-Browser: nie leer, Projektordner zuerst
    (Erststart-UX, ADR 0029 — describe_locations/„Feste Scan-Orte" entfallen)."""
    roots = library.list_roots()
    assert roots  # nie leer (Projekt/Home/Laufwerke)
    assert all("path" in r and "name" in r for r in roots)
    import os
    assert roots[0]["path"] == os.getcwd()


# --- Schreiben (Admin-Bereich, Stufe 2A) --------------------------------------

def test_dump_toml_roundtrips_through_tomllib(tmp_path):
    import tomllib
    from feral.config import dump_toml

    data = {
        "database": {"path": "/data/feral.sqlite"},
        "cache": {"thumbnails": "./cache/thumbnails", "thumbnail_size": 320},
        "scan": {"locations": [
            {"name": "Hotfolder", "path": "/media/hot"},
            {"name": 'mit "Anführung" und ümlaut', "path": "/media/x"},
        ]},
        "hotfolder": {"quiet_seconds": 5, "enabled": True},
    }
    parsed = tomllib.loads(dump_toml(data))
    assert parsed == data


def test_update_config_file_preserves_unknown_sections(tmp_path):
    from feral.config import load_config, update_config_file

    p = _write(tmp_path, CONFIG_TOML + '\n[library]\nroot = "/media/lib"\n')
    update_config_file(
        p,
        locations=[{"name": "Neu", "path": "/media/neu"}],
        thumbnail_size=256,
    )

    cfg = load_config(p)
    assert cfg["scan"]["locations"] == [{"name": "Neu", "path": "/media/neu"}]
    assert cfg["cache"]["thumbnail_size"] == 256
    assert cfg["library"]["root"] == "/media/lib"       # unbekannte Sektion überlebt
    assert cfg["database"]["path"] == "/data/feral.sqlite"
    assert (tmp_path / "config.toml.bak").is_file()     # Backup der alten Datei


def test_update_config_file_creates_missing_file(tmp_path):
    from feral.config import load_config, update_config_file

    p = tmp_path / "config.toml"
    update_config_file(p, locations=[{"name": "A", "path": "/a"}], thumbnail_size=320)
    assert p.is_file()
    assert load_config(p)["scan"]["locations"][0]["path"] == "/a"
    assert not (tmp_path / "config.toml.bak").exists()  # nichts zu sichern


def test_update_config_file_library_root_and_min_date(tmp_path):
    """Import-Ziel + min_date aus der GUI (Block 4.1b): schreiben, ändern, leeren."""
    from feral.config import import_min_date, library_root, load_config, update_config_file

    path = tmp_path / "config.toml"
    path.write_text('[cache]\nthumbnail_size = 320\n')

    update_config_file(path, library_root="/daten/bestand", import_min_date="2018-06-01")
    config = load_config(path)
    assert library_root(config) == "/daten/bestand"
    assert import_min_date(config) == "2018-06-01"
    # unverwaltete Sektionen überleben
    assert config["cache"]["thumbnail_size"] == 320

    # leerer String entfernt das Import-Ziel wieder
    update_config_file(path, library_root="")
    assert library_root(load_config(path)) is None


# -- Watch-Quellen-Modell (ADR 0030) ------------------------------------------

def test_watch_sources_parsing_and_defaults(tmp_path):
    from feral.config import watch_sources

    p = _write(tmp_path, """
[[watch]]
name = "ComfyUI Output"
path = "/media/comfy/output"

[[watch]]
path = "/archiv/aufraeumen"
modus = "verschieben"
quiet_seconds = 20
""")
    sources = watch_sources(load_config(p))
    assert len(sources) == 2
    # Erster: Defaults (kopieren, Ruhezeiten aus Standard).
    assert sources[0] == {
        "name": "ComfyUI Output", "path": "/media/comfy/output",
        "modus": "kopieren", "quiet_seconds": 5.0, "poll_seconds": 1.0,
        "leere_ordner_entfernen": False,
    }
    # Zweiter: Name aus Pfad abgeleitet, Modus + Ruhezeit übernommen.
    assert sources[1]["name"] == "aufraeumen"
    assert sources[1]["modus"] == "verschieben"
    assert sources[1]["quiet_seconds"] == 20.0


def test_watch_sources_migrates_legacy_hotfolder(tmp_path):
    """Alt-[hotfolder] ohne [[watch]] wird als eine Watch-Quelle interpretiert."""
    from feral.config import watch_sources

    p = _write(tmp_path, """
[hotfolder]
root = "/media/hotfolder"
quiet_seconds = 8
verschieben = "JA_WIRKLICH"
""")
    sources = watch_sources(load_config(p))
    assert len(sources) == 1
    assert sources[0]["path"] == "/media/hotfolder"
    assert sources[0]["modus"] == "verschieben"     # Sentinel → verschieben
    assert sources[0]["quiet_seconds"] == 8.0


def test_watch_sources_prefers_new_over_legacy(tmp_path):
    """Sind BEIDE vorhanden, gewinnt das neue [[watch]] (kein Doppel-Import)."""
    from feral.config import watch_sources

    p = _write(tmp_path, """
[hotfolder]
root = "/alt/hotfolder"

[[watch]]
path = "/neu/quelle"
""")
    sources = watch_sources(load_config(p))
    assert [s["path"] for s in sources] == ["/neu/quelle"]


def test_update_config_writes_watch_and_drops_legacy_hotfolder(tmp_path):
    """Speichern schreibt [[watch]] und entfernt eine Alt-[hotfolder]-Sektion,
    damit nie zwei konkurrierende Definitionen persistiert bleiben (Bug 1)."""
    from feral.config import load_config, update_config_file, watch_sources

    path = _write(tmp_path, '[hotfolder]\nroot = "/alt"\nverschieben = "JA_WIRKLICH"\n')
    update_config_file(path, watch=[
        {"name": "A", "path": "/media/a", "modus": "kopieren"},
        {"name": "", "path": "/media/b", "modus": "verschieben", "quiet_seconds": 12},
    ])
    config = load_config(path)
    assert "hotfolder" not in config              # Alt-Sektion ist weg
    sources = watch_sources(config)
    assert [s["path"] for s in sources] == ["/media/a", "/media/b"]
    assert sources[1]["modus"] == "verschieben"
    assert sources[1]["quiet_seconds"] == 12.0

    # Leere Liste entfernt die Sektion wieder.
    update_config_file(path, watch=[])
    assert "watch" not in load_config(path)


def test_watch_sources_katalogisieren_modus(tmp_path):
    """Dritter Modus (ADR 0031): „katalogisieren" = am Ort aufnehmen."""
    from feral.config import watch_sources

    p = _write(tmp_path, '[[watch]]\npath = "/medien/archiv"\nmodus = "katalogisieren"\n')
    sources = watch_sources(load_config(p))
    assert sources[0]["modus"] == "katalogisieren"
    # Unbekannter Modus fällt weiter sicher auf kopieren zurück.
    p2 = _write(tmp_path, '[[watch]]\npath = "/x"\nmodus = "anheften"\n')
    assert watch_sources(load_config(p2))[0]["modus"] == "kopieren"


def test_watch_sources_leere_ordner_flag_roundtrip(tmp_path):
    """ADR 0033: leere_ordner_entfernen wird gelesen, geschrieben und
    round-getrippt; False bleibt aus der Datei draußen (schlanke Config)."""
    from feral.config import load_config, update_config_file, watch_sources

    p = tmp_path / "config.toml"
    update_config_file(p, watch=[
        {"name": "a", "path": "/quelle/a", "modus": "verschieben",
         "leere_ordner_entfernen": True},
        {"name": "b", "path": "/quelle/b", "modus": "kopieren"},
    ])

    sources = watch_sources(load_config(p))
    assert sources[0]["leere_ordner_entfernen"] is True
    assert sources[1]["leere_ordner_entfernen"] is False
    assert "leere_ordner_entfernen" not in p.read_text().split("[[watch]]")[2]


# -- Übersichtsmodus vs. Library-Verwaltung (ADR 0041, I4) ----------------------

def test_library_verwaltung_explicit_wins(tmp_path):
    """Ein gesetzter Schalter gewinnt immer — auch gegen die Migrations-Regel."""
    from feral.config import library_verwaltung

    p = _write(tmp_path, '[library]\nroot = "/daten/lib"\nverwaltung = false\n')
    assert library_verwaltung(load_config(p)) is False
    p2 = _write(tmp_path, '[library]\nverwaltung = true\n')
    assert library_verwaltung(load_config(p2)) is True


def test_library_verwaltung_migration_rule(tmp_path):
    """Fehlt der Schlüssel: root oder schreibende Watch-Quelle = bewusst
    eingerichtet (an); frische/katalogisieren-only Configs = Übersichtsmodus."""
    from feral.config import library_verwaltung

    assert library_verwaltung({}) is False
    p = _write(tmp_path, '[library]\nroot = "/daten/lib"\n')
    assert library_verwaltung(load_config(p)) is True
    p2 = _write(tmp_path, '[[watch]]\npath = "/quelle"\nmodus = "verschieben"\n')
    assert library_verwaltung(load_config(p2)) is True
    p3 = _write(tmp_path, '[[watch]]\npath = "/quelle"\nmodus = "katalogisieren"\n')
    assert library_verwaltung(load_config(p3)) is False


def test_update_config_file_writes_verwaltung(tmp_path):
    """GUI-Speichern macht den Schalter explizit (Migrations-Regel greift
    danach nicht mehr); None lässt die Datei unangetastet."""
    from feral.config import library_verwaltung, update_config_file

    p = tmp_path / "config.toml"
    update_config_file(p, library_root="/daten/lib", verwaltung=False)
    assert library_verwaltung(load_config(p)) is False   # trotz gesetzter root

    update_config_file(p, thumbnail_size=256)            # verwaltung=None
    assert library_verwaltung(load_config(p)) is False


def test_rankings_enabled_default_off_and_roundtrip(tmp_path):
    """Modul-Schalter Rankings (ADR 0045): Standard aus; GUI-Speichern
    schreibt [rankings] enabled explizit, None lässt ihn unangetastet."""
    from feral.config import rankings_enabled, update_config_file

    assert rankings_enabled({}) is False
    assert rankings_enabled(load_config(_write(
        tmp_path, "[rankings]\nenabled = true\n"
    ))) is True

    p = tmp_path / "config.toml"
    update_config_file(p, thumbnail_size=320, rankings_enabled=True)
    assert rankings_enabled(load_config(p)) is True
    update_config_file(p, thumbnail_size=256)            # None = unangetastet
    assert rankings_enabled(load_config(p)) is True
    update_config_file(p, thumbnail_size=256, rankings_enabled=False)
    assert rankings_enabled(load_config(p)) is False


def test_web_instance_accessors_defaults_and_values(tmp_path):
    """[web]-Sektion (ADR 0041/I5): Port, Instanzname, Akzentfarbe — fehlende
    oder ungültige Werte zählen defensiv als nicht konfiguriert."""
    from feral.config import instance_accent, instance_name, web_port

    assert web_port({}) is None
    assert instance_name({}) is None
    assert instance_accent({}) is None

    p = _write(
        tmp_path,
        '[web]\nport = 9001\nname = " Archiv "\nakzentfarbe = "#3B82F6"\n',
    )
    cfg = load_config(p)
    assert web_port(cfg) == 9001
    assert instance_name(cfg) == "Archiv"          # getrimmt
    assert instance_accent(cfg) == "#3B82F6"

    bad = load_config(_write(
        tmp_path, '[web]\nport = 70000\nname = ""\nakzentfarbe = "rot"\n'
    ))
    assert web_port(bad) is None                    # außerhalb 1–65535
    assert instance_name(bad) is None               # leer = kein Name
    assert instance_accent(bad) is None             # kein #rrggbb


def test_update_config_file_writes_and_removes_web_section(tmp_path):
    """GUI-Speichern: gesetzte Werte landen in [web]; leer entfernt Name/
    Farbe wieder — der Port bleibt als expliziter Standard 8765 sichtbar
    (wer zuerst in der Datei wühlt, soll die Option sehen)."""
    from feral.config import instance_accent, instance_name, update_config_file, web_port

    p = tmp_path / "config.toml"
    update_config_file(
        p, thumbnail_size=320,
        web_port=9001, instance_name="Archiv", instance_accent="#3b82f6",
    )
    cfg = load_config(p)
    assert web_port(cfg) == 9001
    assert instance_name(cfg) == "Archiv"
    assert instance_accent(cfg) == "#3b82f6"

    # None lässt alles unangetastet.
    update_config_file(p, thumbnail_size=256)
    cfg = load_config(p)
    assert web_port(cfg) == 9001 and instance_name(cfg) == "Archiv"

    # 0/leer = zurück zum Standard: Name/Farbe fliegen raus, der Port wird
    # explizit als 8765 geschrieben.
    update_config_file(
        p, thumbnail_size=256, web_port=0, instance_name="", instance_accent="",
    )
    cfg = load_config(p)
    assert cfg["web"] == {"port": 8765}
    assert instance_name(cfg) is None and instance_accent(cfg) is None


def test_import_rules_defaults_and_parsing(tmp_path):
    from feral.config import import_rules, load_config

    # Ohne Sektion: alles aus.
    assert import_rules({}) == {"min_kante": 0, "max_kante": 0, "formate": []}
    p = tmp_path / "config.toml"
    p.write_text(
        '[import]\nmin_kante = 240\nmax_kante = 8000\n'
        'formate_ausschliessen = ["PSD", " arw ", ""]\n',
        encoding="utf-8",
    )
    rules = import_rules(load_config(p))
    assert rules == {"min_kante": 240, "max_kante": 8000, "formate": ["psd", "arw"]}
    # Defensiv: Unsinn zählt als aus.
    assert import_rules({"import": {"min_kante": "abc"}})["min_kante"] == 0
    assert import_rules({"import": {"min_kante": -5}})["min_kante"] == 0


def test_update_config_file_import_rules_roundtrip(tmp_path):
    from feral.config import import_rules, load_config, update_config_file

    p = tmp_path / "config.toml"
    update_config_file(p, thumbnail_size=320, import_min_kante=240,
                       import_max_kante=8000,
                       import_formate_ausschliessen=["psd", "arw"])
    rules = import_rules(load_config(p))
    assert rules == {"min_kante": 240, "max_kante": 8000, "formate": ["psd", "arw"]}
    # 0/leer räumt die Schlüssel wieder ab (Config bleibt schlank).
    update_config_file(p, thumbnail_size=320, import_min_kante=0,
                       import_max_kante=0, import_formate_ausschliessen=[])
    cfg = load_config(p)
    assert "min_kante" not in cfg.get("import", {})
    assert "formate_ausschliessen" not in cfg.get("import", {})


def test_import_rules_format_aliases():
    from feral.config import import_rules

    rules = import_rules({"import": {"formate_ausschliessen":
                                     ["TIF", "jpg", "mp4", "arw", "tiff"]}})
    # Alltagsnamen → interne Container-Namen, Duplikate zusammengelegt.
    assert rules["formate"] == ["tiff", "jpeg", "isobmff", "arw"]
