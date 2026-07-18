"""Registry der Schicht-2-Parser (ADR 0011).

Ein Parser ist ein Modul mit ``NAME``, ``VERSION`` und
``parse(items) -> Interpretation | None``. Er bekommt **alle** Roh-Einträge
einer Datei und entscheidet selbst, ob er zuständig ist (``None`` = nein).
Ein neues Format = ein neues Parser-Modul + ein Eintrag in ``PARSERS``.

Mehrere Parser dürfen zur selben Datei etwas sagen (kommt praktisch kaum vor);
ihre Ergebnisse stehen dann nebeneinander in der DB, je mit Parser-Name und
-Version. Rückwirkendes Neu-Interpretieren: ``python -m feral.interpret``.
"""

from __future__ import annotations

from typing import Protocol, Sequence

from ..extract.types import RawMetadataItem
from . import a1111, comfyui, xmp
from .types import Interpretation


class Parser(Protocol):
    """Schnittstelle, die jedes Parser-Modul erfüllt."""

    NAME: str
    VERSION: int

    @staticmethod
    def parse(items: Sequence[RawMetadataItem]) -> Interpretation | None: ...


# Reihenfolge = Speicher-Reihenfolge; inhaltlich unabhängig voneinander.
PARSERS: list[Parser] = [a1111, comfyui, xmp]


def interpret_items(items: Sequence[RawMetadataItem]) -> list[Interpretation]:
    """Lasse alle registrierten Parser über die Roh-Einträge einer Datei laufen.

    Liefert nur echte Ergebnisse (Parser, die sich zuständig fühlten und
    mindestens ein Feld gefunden haben). Keine Roh-Einträge → leere Liste.
    """
    if not items:
        return []
    results: list[Interpretation] = []
    for parser in PARSERS:
        interpretation = parser.parse(items)
        if interpretation is not None and interpretation.fields:
            results.append(interpretation)
    return results
