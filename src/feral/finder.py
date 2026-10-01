"""macOS-Dateiattribute: Finder-Tags lesen, erweiterte Attribute mitkopieren (#221/#222, ADR 0097).

Finder-Tags liegen nicht im Dateiinhalt, sondern als erweitertes Attribut
``com.apple.metadata:_kMDItemUserTags`` am Dateieintrag: eine binäre plist
mit Einträgen ``"Name\\nFarbindex"`` (Farbe 0–7, ohne Zeilenumbruch = keine
Farbe). Der Hash sieht davon nichts.

Python hat unter macOS weder ``os.getxattr`` noch ``os.listxattr``;
``shutil.copy2`` überträgt dort darum KEINE erweiterten Attribute. Beides
läuft hier über ``ctypes`` gegen die libc (``getxattr`` bzw. ``copyfile(3)``
mit ``COPYFILE_XATTR`` — bewusst ohne ACL, sonst wanderte z. B. die
Time-Machine-Löschsperre mit in die Library). Auf allen anderen Systemen
sind die Funktionen wirkungslos: Linux kopiert ``user.*`` schon per
``copy2``, Windows kennt keine Finder-Tags.

Alle Funktionen sind defensiv: Fehler werfen nicht, sie liefern leer bzw.
einen Fehlertext.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import plistlib
import sys
from pathlib import Path

USER_TAGS = "com.apple.metadata:_kMDItemUserTags"
# Das Attribut kommt mit der Datei (auch aus Archiven) und ist fremde Eingabe.
MAX_XATTR = 1024 * 1024   # Bytes; echte Tag-Listen sind unter 1 KB
MAX_TAGS = 64             # Tags je Datei
MAX_TAG_NAME = 200        # Zeichen je Tag

# copyfile.h: COPYFILE_XATTR = 1<<2 (nur erweiterte Attribute, keine ACL/Stat/Daten).
_COPYFILE_XATTR = 1 << 2

_libc: ctypes.CDLL | None = None


def _lib() -> ctypes.CDLL | None:
    """libc des Macs (lazy); ``None`` auf anderen Systemen."""
    global _libc
    if sys.platform != "darwin":
        return None
    if _libc is None:
        lib = ctypes.CDLL(ctypes.util.find_library("c") or "libc.dylib", use_errno=True)
        lib.getxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                                 ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
        lib.getxattr.restype = ctypes.c_ssize_t
        lib.copyfile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                                 ctypes.c_uint32]
        lib.copyfile.restype = ctypes.c_int
        _libc = lib
    return _libc


def parse_user_tags(blob: bytes) -> list[tuple[str, int]]:
    """Inhalt von ``_kMDItemUserTags`` → ``[(Name, Farbindex)]``.

    Farbindex 0 = keine Farbe, 1 Grau, 2 Grün, 3 Lila, 4 Blau, 5 Gelb,
    6 Rot, 7 Orange. Leere Namen und Doppelte (case-insensitiv, wie das
    fml-Tag-Vokabular) fallen weg; Unlesbares ergibt eine leere Liste.
    """
    try:
        entries = plistlib.loads(blob)
    except Exception:
        return []
    if not isinstance(entries, list):
        return []
    tags: list[tuple[str, int]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, str):
            continue
        name, _, color = entry.partition("\n")
        name = name.strip()
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        color = color.strip()
        # isascii: "²" zählt für isdigit(), ist für int() aber keine Zahl
        index = int(color) if color.isascii() and color.isdigit() and len(color) <= 2 else 0
        tags.append((name[:MAX_TAG_NAME], index if 0 <= index <= 7 else 0))
        if len(tags) >= MAX_TAGS:
            break
    return tags


def read_finder_tags(path: str | Path) -> list[tuple[str, int]]:
    """Finder-Tags einer Datei (nur macOS, sonst immer ``[]``)."""
    lib = _lib()
    if lib is None:
        return []
    fs_path, name = os.fsencode(str(path)), USER_TAGS.encode()
    size = lib.getxattr(fs_path, name, None, 0, 0, 0)
    if size <= 0 or size > MAX_XATTR:
        return []                  # kein Attribut (ENOATTR), Lesefehler, absurd groß
    buf = ctypes.create_string_buffer(size)
    size = lib.getxattr(fs_path, name, buf, size, 0, 0)
    if size <= 0:
        return []
    return parse_user_tags(buf.raw[:size])


def copy_xattrs(source: str | Path, destination: str | Path) -> str | None:
    """Erweiterte Attribute von ``source`` auf die (schon kopierte)
    ``destination`` übertragen. Nur macOS; liefert ``None`` bei Erfolg bzw.
    auf anderen Systemen, sonst den Fehlertext."""
    lib = _lib()
    if lib is None:
        return None
    rc = lib.copyfile(os.fsencode(str(source)), os.fsencode(str(destination)),
                      None, _COPYFILE_XATTR)
    if rc != 0:
        err = ctypes.get_errno()
        return f"{os.strerror(err)} (errno {err})"
    return None
