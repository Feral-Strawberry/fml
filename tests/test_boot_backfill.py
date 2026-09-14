"""Boot-Backfill nur bei Items, die der Lauf datieren könnte (#62, #113)."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from feral.db import connect, store_extraction
from feral.extract.types import ContainerExtraction
from feral.importer import backfill_pending


def _item(conn, h, path):
    store_extraction(conn, file_hash=h, file_size=1, path=path,
                     extraction=ContainerExtraction(container="png"), now="T0")


def test_backfill_pending_ignores_items_without_existing_file(tmp_path):
    conn = connect(tmp_path / "f.sqlite")
    _item(conn, "a" * 64, str(tmp_path / "weg.png"))          # Datei existiert nicht
    conn.commit()
    assert backfill_pending(conn) is False                     # kein vergeblicher Lauf je Start
    real = tmp_path / "da.png"
    real.write_bytes(b"x")
    _item(conn, "b" * 64, str(real))
    conn.commit()
    assert backfill_pending(conn) is True
    conn.execute("UPDATE items SET media_date = '2024-05-01 10:00:00'")
    conn.commit()
    assert backfill_pending(conn) is False                     # alles datiert
    conn.execute("UPDATE items SET media_date = '2024-05-01'")   # nur datumsgenau (ADR 0061)
    conn.commit()
    assert backfill_pending(conn) is False                     # kein Start-Lauf, nur per Admin-Knopf
    conn.close()


def test_backfill_pending_ignores_undatable_items(tmp_path):
    """#113: Datei existiert, aber Stempel (und Metadaten) liegen außerhalb
    des Fensters → kein Start-Lauf mehr (vorher: ~200 vergebliche Läufe bei
    Feral Strawberry). Mit gesenktem min_date lohnt der Lauf wieder."""
    conn = connect(tmp_path / "f.sqlite")
    old = tmp_path / "uralt.png"
    old.write_bytes(b"x")
    os.utime(old, (0, 0))                                      # 1.1.1970
    _item(conn, "a" * 64, str(old))
    conn.commit()
    assert backfill_pending(conn) is False
    assert backfill_pending(
        conn, min_date=datetime(1970, 1, 1, tzinfo=timezone.utc)) is True
    conn.close()
