"""Wertobjekte der Schicht-1-Extraktion.

Diese Objekte sind **rein** (keine DB, keine Seiteneffekte) und beschreiben das
Ergebnis einer verlustfreien Roh-Extraktion. Die Persistenz in die DB ist eine
eigene Schicht und wird separat gebaut.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RawMetadataItem:
    """Ein einzelner, verlustfrei extrahierter Roh-Metadaten-Eintrag.

    Repräsentiert genau **einen** Metadaten-Fund im Container, unverändert und mit
    Angabe seiner Herkunft. Wir interpretieren hier nichts — wir beschriften nur.

    Felder:
        source:    Quell-Chunk/-Tag, präfixiert mit dem Container, z. B.
                   ``"png:tEXt"``, ``"png:iTXt"``, ``"png:eXIf"``. So bleibt
                   nachvollziehbar, **woher** ein Datum stammt (ADR 0004/0005).
        keyword:   Schlüssel/Keyword innerhalb des Chunks, falls vorhanden
                   (z. B. ``"parameters"`` bei A1111, ``"workflow"`` /
                   ``"prompt"`` bei ComfyUI). ``None``, wenn der Chunk keinen
                   Schlüssel trägt.
        text:      Der dekodierte Textwert, **unverändert**, falls der Eintrag
                   textuell ist. ``None`` bei rein binären Einträgen.
        data:      Die rohen Bytes, falls der Eintrag binär ist (z. B. eingebettetes
                   EXIF). ``None`` bei rein textuellen Einträgen.
        encoding:  Wie ``text`` dekodiert wurde bzw. ``"binary"`` für ``data``.
                   Beispiele: ``"latin-1"`` (tEXt), ``"utf-8"`` (iTXt),
                   ``"binary"`` (eXIf).
        compressed: ``True``, wenn der Wert im Container komprimiert vorlag
                   (zTXt, oder iTXt mit Kompressionsflag) und hier entpackt wurde.
                   Der Wert selbst bleibt inhaltlich unverändert.

    Invariante: Genau eines von ``text`` / ``data`` ist gesetzt.
    """

    source: str
    keyword: str | None
    text: str | None
    data: bytes | None
    encoding: str
    compressed: bool = False

    def __post_init__(self) -> None:
        has_text = self.text is not None
        has_data = self.data is not None
        if has_text == has_data:
            raise ValueError(
                "RawMetadataItem: genau eines von 'text' oder 'data' muss gesetzt sein "
                f"(text={has_text}, data={has_data}, source={self.source!r})"
            )


@dataclass
class ContainerExtraction:
    # Bewusst NICHT frozen: Extraktoren befüllen das Ergebnis inkrementell
    # (items/warnings anhängen, Eckwerte setzen). Die einzelnen
    # RawMetadataItem-Einträge bleiben frozen.
    """Das Gesamtergebnis einer Schicht-1-Extraktion für eine Datei.

    Felder:
        container: Erkannter Container-Typ, z. B. ``"png"``. Über **Magic Bytes**
                   bestimmt, nicht über die Dateiendung.
        items:     Alle gefundenen Roh-Metadaten-Einträge, in Fundreihenfolge.
        warnings:  Nicht-fatale Auffälligkeiten (z. B. CRC-Fehler, abgeschnittene
                   Datei, unerwartetes Chunk-Layout). Extraktoren werfen nicht bei
                   beschädigten Dateien, sondern sammeln Warnungen — der Aufrufer
                   entscheidet über `_failed` (ADR 0006).
    """

    container: str
    items: list[RawMetadataItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Medien-Eckwerte (Stufe-4-Erweiterung): Pixelmaße und — bei Video/
    # Animation — Bilder pro Sekunde. None = unbekannt/nicht anwendbar.
    width: int | None = None
    height: int | None = None
    fps: float | None = None
