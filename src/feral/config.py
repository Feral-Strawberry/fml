"""Konfiguration laden und schreiben (stdlib, keine Abhängigkeit).

Die `config.toml` enthält rechner-spezifische Pfade (DB-Ablage, feste Scan-Orte)
und ist in `.gitignore` ausgeschlossen. Vorlage: `config.example.toml`. Fehlt die
Datei, greifen sinnvolle Standardwerte — die App läuft also auch ohne Config.

Schreiben (Admin-Bereich, Stufe 2A): erzeugt die Datei neu aus den geladenen
Werten. **Kommentare gehen dabei verloren** (bewusst: kein TOML-Schreib-Paket,
ADR 0014); vorher wird ein Backup `config.toml.bak` angelegt. Unbekannte
Sektionen/Schlüssel bleiben erhalten — es wird der komplette geladene Zustand
zurückgeschrieben, nicht nur die verwalteten Felder.
"""

from __future__ import annotations

import json
import re
import shutil
import tomllib
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = "./feral.sqlite"


def load_config(path: str | Path = "config.toml") -> dict[str, Any]:
    """Lies die Config-Datei. Existiert sie nicht, gib ein leeres Dict zurück."""
    p = Path(path)
    if not p.is_file():
        return {}
    with open(p, "rb") as fh:
        return tomllib.load(fh)


def database_path(config: dict[str, Any]) -> str:
    """DB-Pfad aus der Config (oder Standard)."""
    return config.get("database", {}).get("path", DEFAULT_DB_PATH)


def thumbnail_cache_path(config: dict[str, Any], db_path: str | Path) -> str:
    """Thumbnail-Cache-Verzeichnis: ``[cache] thumbnails`` aus der Config, sonst
    ``cache/thumbnails`` neben der DB-Datei (der Cache gehört zu den Daten,
    nicht zum Arbeitsverzeichnis)."""
    configured = config.get("cache", {}).get("thumbnails")
    if configured:
        return str(configured)
    return str(Path(db_path).resolve().parent / "cache" / "thumbnails")


def thumbnail_size(config: dict[str, Any]) -> int:
    """Kantenlänge der Thumbnails in Pixeln (``[cache] thumbnail_size``, Standard 320)."""
    return int(config.get("cache", {}).get("thumbnail_size", 320))


def thumbnail_workers(config: dict[str, Any]) -> int | None:
    """Prozess-Zahl des Thumbnail-Pools (``[cache] thumbnail_workers``).

    ``None`` = Automatik (ein Viertel der Kerne, höchstens 8 — ADR 0020).
    Wer den Rückstand nach einem Groß-Import mit voller Kraft aufholen will,
    setzt hier z. B. die Kernzahl."""
    value = config.get("cache", {}).get("thumbnail_workers")
    return int(value) if value else None


def thumbnail_low_priority(config: dict[str, Any]) -> bool:
    """Thumbnail-Prozesse mit niedriger Priorität? (``[cache]
    thumbnail_low_priority``, Standard True = leiser Betrieb.)
    ``false`` = Vollgas-Modus für Groß-Importe."""
    return bool(config.get("cache", {}).get("thumbnail_low_priority", True))


def hotfolder_settings(config: dict[str, Any]) -> dict[str, Any] | None:
    """``[hotfolder]``-Einstellungen (ADR 0025) oder None ohne ``root``.

    ``verschieben`` ist nur mit dem wörtlichen Sentinel "JA_WIRKLICH" aktiv —
    Erfolgsfälle werden dann nach dem Commit gelöscht statt nach
    ``_importiert/`` bewegt (der Watchfolder bleibt leer)."""
    section = config.get("hotfolder", {})
    root = section.get("root")
    if not root:
        return None
    return {
        "root": str(root),
        "quiet_seconds": float(section.get("quiet_seconds", 5)),
        "poll_seconds": float(section.get("poll_seconds", 1)),
        "verschieben": section.get("verschieben") == "JA_WIRKLICH",
    }


def watch_sources(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Überwachte Quellordner (ADR 0030) als Liste normalisierter Einträge.

    Erwartet ``[[watch]]``-Tabellen mit ``path`` (Pflicht) und optional ``name``,
    ``modus`` (``kopieren`` | ``verschieben`` | ``katalogisieren``, Standard
    ``kopieren``; ADR 0031), ``quiet_seconds``, ``poll_seconds`` und
    ``leere_ordner_entfernen`` (ADR 0033: nach Verschiebe-Importen leer
    gewordene Unterordner der Quelle löschen; Standard False).
    kopieren/verschieben speisen die Import-Pipeline (ADR 0019);
    katalogisieren nimmt am Ort auf (weder kopieren noch bewegen).

    **Migration** (ADR 0030): Fehlt ``[[watch]]`` ganz, aber ein Alt-``[hotfolder]``
    mit ``root`` ist vorhanden, wird dieser als **ein** Watch-Eintrag interpretiert
    (``verschieben = "JA_WIRKLICH"`` → ``modus = "verschieben"``). So gehen Configs
    aus der Zeit vor dem Quellen-Modell nicht verloren.
    """
    raw = config.get("watch")
    if not raw:
        legacy = hotfolder_settings(config)
        if legacy is None:
            return []
        return [{
            "name": Path(legacy["root"]).name or legacy["root"],
            "path": legacy["root"],
            "modus": "verschieben" if legacy["verschieben"] else "kopieren",
            "quiet_seconds": legacy["quiet_seconds"],
            "poll_seconds": legacy["poll_seconds"],
            "leere_ordner_entfernen": False,
        }]
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if not path:
            continue
        modus = str(item.get("modus", "kopieren")).lower()
        if modus not in ("kopieren", "verschieben", "katalogisieren"):
            modus = "kopieren"
        result.append({
            "name": str(item.get("name") or Path(str(path)).name or path),
            "path": str(path),
            "modus": modus,
            "quiet_seconds": float(item.get("quiet_seconds", 5)),
            "poll_seconds": float(item.get("poll_seconds", 1)),
            "leere_ordner_entfernen": bool(item.get("leere_ordner_entfernen", False)),
        })
    return result


def library_root(config: dict[str, Any]) -> str | None:
    """Wurzel des konsolidierten Bestands (``[library] root``, ADR 0019).

    ``None``, wenn nicht konfiguriert — der Import verlangt sie ausdrücklich.
    """
    root = config.get("library", {}).get("root")
    return str(root) if root else None


def library_verwaltung(config: dict[str, Any]) -> bool:
    """Library-Verwaltung eingeschaltet? (``[library] verwaltung``, ADR 0041/I4.)

    Standard ist der **Übersichtsmodus** (False): fml katalogisiert und
    kuratiert nur — Dateien werden nie kopiert, verschoben oder gelöscht.
    Migrations-Regel: Fehlt der Schlüssel, gelten bestehende Configs mit
    ``library.root`` oder einer schreibenden Watch-Quelle (kopieren/
    verschieben) als bewusst eingerichtet ⇒ True.
    """
    value = config.get("library", {}).get("verwaltung")
    if value is not None:
        return bool(value)
    if library_root(config):
        return True
    return any(
        src["modus"] in ("kopieren", "verschieben") for src in watch_sources(config)
    )


def import_min_date(config: dict[str, Any]) -> str:
    """Untergrenze des Plausibilitätsfensters fürs Erstelldatum
    (``[import] min_date``, ISO-Datum; Standard 2015-01-01, ADR 0019)."""
    return str(config.get("import", {}).get("min_date", "2015-01-01"))


def import_rules(config: dict[str, Any]) -> dict[str, Any]:
    """Import-Filterregeln (ADR 0046) aus ``[import]``:

    - ``min_kante`` / ``max_kante``: Pixel-Grenzen für die kleinste bzw.
      längste Bildseite (0 = aus; greifen nur bei Bildern mit bekannten
      Maßen — ohne Maße wird nie gefiltert, kein Raten).
    - ``formate_ausschliessen``: Container-Namen (z. B. ``["psd", "arw"]``),
      die beim Import/Scan gar nicht erst aufgenommen werden.

    Alles inaktiv = die Funktionen filtern nichts (Auslieferungszustand).
    """
    section = config.get("import", {})
    raw_formats = section.get("formate_ausschliessen") or []
    if isinstance(raw_formats, str):   # defensiv: einzelner String statt Liste
        raw_formats = [raw_formats]

    def _px(key: str) -> int:
        try:
            value = int(section.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0
        return max(0, value)

    formate: list[str] = []
    for f in raw_formats:
        s = str(f).strip().lower()
        s = _FORMAT_ALIASES.get(s, s)
        if s and s not in formate:
            formate.append(s)
    return {
        "min_kante": _px("min_kante"),
        "max_kante": _px("max_kante"),
        "formate": formate,
    }


# Gängige Schreibweisen → interne Container-Namen (sniff_container):
# Feral Strawberrys Befund 2026-07-17 — »tif« filterte nichts, weil der Container
# intern »tiff« heißt. Nutzer sollen Alltagsnamen tippen dürfen.
_FORMAT_ALIASES = {
    "tif": "tiff",
    "jpg": "jpeg",
    "jpe": "jpeg",
    "mkv": "matroska",
    "webm": "matroska",
    "mp4": "isobmff",
    "mov": "isobmff",
    "m4v": "isobmff",
}


def scan_locations(config: dict[str, Any]) -> list[dict[str, str]]:
    """Feste Scan-Orte aus der Config als Liste ``[{name, path}]``.

    Erwartet ``[[scan.locations]]``-Einträge mit ``path`` und optional ``name``.
    Fehlt der Name, wird der Ordnername aus dem Pfad verwendet. Ungültige Einträge
    (ohne ``path``) werden übersprungen.
    """
    locations = config.get("scan", {}).get("locations", [])
    result: list[dict[str, str]] = []
    for item in locations:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if not path:
            continue
        name = item.get("name") or Path(path).name or path
        result.append({"name": str(name), "path": str(path)})
    return result


# -- Instanz ([web], ADR 0041/I5) -------------------------------------------------
#
# Zwei Instanzen laufen heute schon per `--config X --db Y --port Z` parallel;
# [web] macht den Port zur Instanz-Eigenschaft (statt Startskript-Wissen) und
# gibt jeder Instanz Name + Akzentfarbe, damit zwei Tabs unterscheidbar sind.

_ACCENT_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def web_port(config: dict[str, Any]) -> int | None:
    """Port der Web-Oberfläche (``[web] port``). ``None`` = nicht konfiguriert
    (der Start nutzt dann ``--port``/``$PORT`` bzw. 8765). Ungültige Werte
    zählen defensiv als nicht konfiguriert."""
    value = config.get("web", {}).get("port")
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def instance_name(config: dict[str, Any]) -> str | None:
    """Instanzname (``[web] name``) — erscheint in Topbar-Badge und Tab-Titel.
    ``None`` = kein Name (Standard-Erscheinungsbild)."""
    value = str(config.get("web", {}).get("name", "")).strip()
    return value or None


def instance_accent(config: dict[str, Any]) -> str | None:
    """Akzentfarbe der Instanz (``[web] akzentfarbe``, ``#rrggbb``).
    ``None`` = Standard-Akzent aus dem Theme; ungültige Werte zählen als
    nicht gesetzt (die GUI darf nie mit kaputtem CSS starten)."""
    value = str(config.get("web", {}).get("akzentfarbe", "")).strip()
    return value if _ACCENT_HEX.match(value) else None


# -- Ranking-Modul ([rankings], ADR 0045) -----------------------------------------

def rankings_enabled(config: dict[str, Any]) -> bool:
    """Ranking-Modul eingeschaltet? (``[rankings] enabled``, Standard False.)

    Ab Werk aus (Feral Strawberrys Schlank-Prinzip): keine Sidebar-Gruppe, keine
    Queries, keine Kosten. Die Tabellen existieren trotzdem (Migrationen
    sind linear, ADR 0012) — leere Tabellen kosten nichts."""
    return bool(config.get("rankings", {}).get("enabled", False))


# -- Schreiben (Admin-Bereich) --------------------------------------------------

def ui_show_dupes(config: dict[str, Any]) -> bool:
    """Dubletten-Ansicht in der Sidebar zeigen? (``[ui] dubletten``, Standard
    True — ausblendbar, wenn der Import ohnehin hart auf Dateiebene filtert.)"""
    return bool(config.get("ui", {}).get("dubletten", True))


def model_sort(config):
    """Sortierung der Modell-Liste (``[ui] modell_sortierung``):
    'zuletzt' (Standard, neueste Nutzung zuerst) | 'alphabet' | 'anzahl'."""
    value = str(config.get("ui", {}).get("modell_sortierung", "zuletzt"))
    return value if value in ("zuletzt", "alphabet", "anzahl") else "zuletzt"


def update_config_file(
    path: str | Path,
    *,
    locations: list[dict[str, str]] | None = None,
    thumbnail_size: int | None = None,
    library_root: str | None = None,
    verwaltung: bool | None = None,
    import_min_date: str | None = None,
    import_min_kante: int | None = None,
    import_max_kante: int | None = None,
    import_formate_ausschliessen: list[str] | None = None,
    watch: list[dict[str, Any]] | None = None,
    thumbnail_low_priority: bool | None = None,
    thumbnail_workers: int | None = None,
    show_dupes: bool | None = None,
    model_sort_order: str | None = None,
    web_port: int | None = None,
    instance_name: str | None = None,
    instance_accent: str | None = None,
    rankings_enabled: bool | None = None,
) -> dict[str, Any]:
    """Aktualisiere verwaltete Felder der Config-Datei und schreibe sie zurück.

    Lädt den vorhandenen Zustand (alle Sektionen bleiben erhalten), ersetzt nur
    die übergebenen Felder und schreibt die Datei neu (Backup: ``.bak``).
    Gibt die neue Config zurück.
    """
    config = load_config(path)
    if locations is not None:
        config.setdefault("scan", {})["locations"] = [
            {"name": loc["name"], "path": loc["path"]} for loc in locations
        ]
    if thumbnail_size is not None:
        config.setdefault("cache", {})["thumbnail_size"] = int(thumbnail_size)
    if library_root is not None:
        # Leerer String = Eintrag entfernen (Import dann nicht möglich).
        if library_root.strip():
            config.setdefault("library", {})["root"] = library_root.strip()
        else:
            config.get("library", {}).pop("root", None)
    if verwaltung is not None:
        # ADR 0041/I4: der Schalter wird beim GUI-Speichern immer explizit —
        # die Migrations-Regel (root vorhanden ⇒ an) greift nur, solange der
        # Schlüssel fehlt.
        config.setdefault("library", {})["verwaltung"] = bool(verwaltung)
    if import_min_date is not None and import_min_date.strip():
        config.setdefault("import", {})["min_date"] = import_min_date.strip()
    if import_min_kante is not None:
        # 0 = Regel aus; der Schlüssel bleibt dann weg (Config bleibt schlank).
        section = config.setdefault("import", {})
        if int(import_min_kante) > 0:
            section["min_kante"] = int(import_min_kante)
        else:
            section.pop("min_kante", None)
    if import_max_kante is not None:
        section = config.setdefault("import", {})
        if int(import_max_kante) > 0:
            section["max_kante"] = int(import_max_kante)
        else:
            section.pop("max_kante", None)
    if import_formate_ausschliessen is not None:
        section = config.setdefault("import", {})
        formate = [s for s in (str(f).strip().lower()
                               for f in import_formate_ausschliessen) if s]
        if formate:
            section["formate_ausschliessen"] = formate
        else:
            section.pop("formate_ausschliessen", None)
    if watch is not None:
        # Watch-Quellen-Modell (ADR 0030): [[watch]]-Array ersetzt den einzelnen
        # [hotfolder]. Beim Schreiben die Alt-Sektion entfernen, damit nie zwei
        # konkurrierende Definitionen nebeneinander stehen (Bug 1 an der Wurzel).
        config.pop("hotfolder", None)
        entries: list[dict[str, Any]] = []
        for src in watch:
            src_path = str(src.get("path", "")).strip()
            if not src_path:
                continue
            modus = str(src.get("modus", "kopieren")).lower()
            if modus not in ("kopieren", "verschieben", "katalogisieren"):
                modus = "kopieren"
            entry: dict[str, Any] = {
                "name": str(src.get("name") or Path(src_path).name or src_path).strip(),
                "path": src_path,
                "modus": modus,
            }
            if src.get("quiet_seconds") is not None:
                entry["quiet_seconds"] = float(src["quiet_seconds"])
            if src.get("poll_seconds") is not None:
                entry["poll_seconds"] = float(src["poll_seconds"])
            if src.get("leere_ordner_entfernen"):
                # ADR 0033 — nur schreiben, wenn gesetzt (Config bleibt schlank).
                entry["leere_ordner_entfernen"] = True
            entries.append(entry)
        if entries:
            config["watch"] = entries
        else:
            config.pop("watch", None)
    if thumbnail_low_priority is not None:
        config.setdefault("cache", {})["thumbnail_low_priority"] = bool(thumbnail_low_priority)
    if thumbnail_workers is not None:
        if thumbnail_workers > 0:
            config.setdefault("cache", {})["thumbnail_workers"] = int(thumbnail_workers)
        else:
            config.get("cache", {}).pop("thumbnail_workers", None)   # 0 = Automatik
    if show_dupes is not None:
        config.setdefault("ui", {})["dubletten"] = bool(show_dupes)
    if model_sort_order is not None and model_sort_order in ("zuletzt", "alphabet", "anzahl"):
        config.setdefault("ui", {})["modell_sortierung"] = model_sort_order
    # [web]-Sektion (ADR 0041/I5): leerer String = Eintrag entfernen (Name/
    # Farbe haben keinen sinnvollen Default). Der Port wird dagegen IMMER
    # explizit geschrieben (0 = Standard 8765) — wer zuerst in der Datei
    # wühlt statt in der GUI, soll die Option sehen (Feral Strawberry, 2026-07-11).
    if web_port is not None:
        config.setdefault("web", {})["port"] = (
            int(web_port) if 1 <= web_port <= 65535 else 8765
        )
    if instance_name is not None:
        if instance_name.strip():
            config.setdefault("web", {})["name"] = instance_name.strip()
        else:
            config.get("web", {}).pop("name", None)
    if instance_accent is not None:
        if instance_accent.strip():
            config.setdefault("web", {})["akzentfarbe"] = instance_accent.strip()
        else:
            config.get("web", {}).pop("akzentfarbe", None)
    if "web" in config and not config["web"]:
        config.pop("web")
    if rankings_enabled is not None:
        # Modul-Schalter (ADR 0045): immer explizit schreiben — wer in der
        # Datei wühlt, soll die Option sehen (gleiche Logik wie beim Port).
        config.setdefault("rankings", {})["enabled"] = bool(rankings_enabled)
    save_config(path, config)
    return config


def save_config(path: str | Path, config: dict[str, Any]) -> None:
    """Schreibe die Config als TOML (Backup der alten Datei als ``.bak``)."""
    p = Path(path)
    if p.is_file():
        shutil.copy2(p, p.with_name(p.name + ".bak"))
    # Englisch wie config.example.toml (ADR-0055-Nachtrag O.2): die Datei
    # gehört dem Nutzer, nicht der UI-Sprache.
    header = (
        "# Written by the Feral Media Library (admin area).\n"
        "# Template and explanations: config.example.toml — comments do not\n"
        "# survive saving from the GUI (backup: config.toml.bak).\n\n"
    )
    p.write_text(header + dump_toml(config), encoding="utf-8")


def dump_toml(data: dict[str, Any]) -> str:
    """Minimaler TOML-Ausgeber für die Config-Strukturen (Tabellen, Tabellen-Arrays,
    Skalare, flache Listen). Bewusst kein Rundum-TOML — nur, was wir brauchen."""
    lines: list[str] = []

    def is_table_array(value: Any) -> bool:
        return (
            isinstance(value, list)
            and len(value) > 0
            and all(isinstance(v, dict) for v in value)
        )

    def scalar(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return repr(value)
        if isinstance(value, str):
            return json.dumps(value, ensure_ascii=False)  # gültiger TOML-Basic-String
        if isinstance(value, list):
            return "[" + ", ".join(scalar(v) for v in value) + "]"
        raise ValueError(f"Nicht unterstützter Config-Werttyp: {type(value).__name__}")

    def emit(table: dict[str, Any], prefix: str) -> None:
        for key, value in table.items():
            if not isinstance(value, dict) and not is_table_array(value):
                lines.append(f"{key} = {scalar(value)}")
        for key, value in table.items():
            full = f"{prefix}{key}"
            if isinstance(value, dict):
                lines.extend(["", f"[{full}]"])
                emit(value, full + ".")
            elif is_table_array(value):
                for entry in value:
                    lines.extend(["", f"[[{full}]]"])
                    emit(entry, full + ".")

    emit(data, "")
    return "\n".join(lines).lstrip("\n") + "\n"
