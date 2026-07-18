"""PNG-Container-Extraktor (Schicht 1, reine Standardbibliothek).

PNG ist der wichtigste Container für AI-Metadaten: ComfyUI legt seinen Workflow-
und Prompt-Graphen in ``tEXt``/``iTXt``-Chunks ab, A1111 seine Parameter unter dem
Keyword ``parameters``. Dieser Extraktor läuft durch die **Container-Struktur** und
zieht **alle** Text-Chunks (``tEXt``, ``zTXt``, ``iTXt``) sowie eingebettetes EXIF
(``eXIf``) **unverändert** heraus. Er interpretiert nichts — das ist Schicht 2
(ADR 0004).

PNG-Aufbau (PNG-Spezifikation):

- 8-Byte-Signatur ``89 50 4E 47 0D 0A 1A 0A``.
- Danach eine Folge von Chunks, je: ``Länge(4, big-endian) | Typ(4) | Daten | CRC(4)``.
- Textchunks:
  - ``tEXt``: ``keyword \0 text``               (Latin-1)
  - ``zTXt``: ``keyword \0 methode(1) zlib-text`` (Latin-1, zlib-komprimiert)
  - ``iTXt``: ``keyword \0 flag(1) methode(1) sprache \0 übersetzt \0 text``
              (Text UTF-8, optional zlib-komprimiert)
- ``eXIf``: roher EXIF-/TIFF-Block (binär).

Der Extraktor ist **defensiv** (CLAUDE.md §8): beschädigte oder abgeschnittene
Dateien werfen nicht, sondern sammeln `warnings`. Große, uninteressante Chunks
(z. B. ``IDAT`` mit den Pixeldaten) werden übersprungen, ohne sie in den Speicher
zu laden.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import BinaryIO

from .types import ContainerExtraction, RawMetadataItem

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Chunk-Typen, aus denen wir Metadaten ziehen.
_TEXT_CHUNKS = frozenset({b"tEXt", b"zTXt", b"iTXt"})
_EXIF_CHUNK = b"eXIf"
_END_CHUNK = b"IEND"

# Schutz gegen absurde Längenangaben in defekten Dateien (PNG-Chunks sind << das).
_MAX_REASONABLE_CHUNK = 256 * 1024 * 1024  # 256 MiB

# Deckel für die DEKOMPRIMIERTE Größe von zTXt/iTXt (der Chunk-Deckel oben zählt
# nur die komprimierten Bytes). Ein winziger Chunk kann zu Gigabytes aufblähen
# („zlib-Bombe") und beim Scan/Import den Prozess per OOM abschießen — bei einem
# Groß-Import fremder Dateien reicht EINE präparierte Datei. Echte Text-Chunks
# sind winzig, 64 MiB ist absurd großzügig. (ADR 0032)
_MAX_DECOMPRESSED = 64 * 1024 * 1024  # 64 MiB


class _DecompressionBomb(Exception):
    """zlib-Daten sprengen den Dekompressionsdeckel (mögliche Bombe)."""


def _decompress_bounded(data: bytes) -> bytes:
    """Dekomprimiere zlib-Daten mit hartem Deckel (`_MAX_DECOMPRESSED`).

    Wirft `zlib.error` bei kaputten Daten und `_DecompressionBomb`, wenn die
    Ausgabe den Deckel überschreitet — ohne je mehr als den Deckel + einen
    Block in den Speicher zu ziehen (bricht die Dekompression ab).
    """
    dec = zlib.decompressobj()
    out = dec.decompress(data, _MAX_DECOMPRESSED)
    if dec.unconsumed_tail:  # es käme noch mehr ⇒ Deckel gerissen
        raise _DecompressionBomb()
    return out


def extract(source: str | Path | BinaryIO) -> ContainerExtraction:
    """Extrahiere alle Roh-Metadaten aus einer PNG-Quelle.

    `source` ist ein Dateipfad oder ein bereits geöffneter Binärstrom (mit
    ``read``/``seek``). Gibt eine `ContainerExtraction` mit allen gefundenen
    Text-/EXIF-Einträgen und etwaigen Warnungen zurück. Wirft nicht bei
    beschädigten Dateien — Probleme landen in `warnings`.
    """
    if hasattr(source, "read"):
        return _extract_from_stream(source)  # type: ignore[arg-type]
    with open(source, "rb") as fh:
        return _extract_from_stream(fh)


def _extract_from_stream(stream: BinaryIO) -> ContainerExtraction:
    result = ContainerExtraction(container="png")

    signature = stream.read(8)
    if signature != PNG_SIGNATURE:
        result.warnings.append("Keine gültige PNG-Signatur — Datei ist kein PNG?")
        return result

    while True:
        header = stream.read(8)
        if len(header) == 0:
            result.warnings.append("Datei endet ohne IEND-Chunk.")
            break
        if len(header) < 8:
            result.warnings.append("Abgeschnittener Chunk-Header — Datei unvollständig.")
            break

        length, ctype = struct.unpack(">I4s", header)

        if length > _MAX_REASONABLE_CHUNK:
            result.warnings.append(
                f"Chunk {_label(ctype)} meldet unplausible Länge {length} — Abbruch."
            )
            break

        if ctype == b"IHDR":
            data = stream.read(length)
            stream.read(4)  # CRC — für die Maße unerheblich
            if len(data) >= 8:
                result.width, result.height = struct.unpack(">II", data[:8])
        elif ctype in _TEXT_CHUNKS or ctype == _EXIF_CHUNK:
            data = stream.read(length)
            if len(data) < length:
                result.warnings.append(
                    f"Chunk {_label(ctype)} abgeschnitten ({len(data)}/{length} Bytes)."
                )
                break
            crc_bytes = stream.read(4)
            _verify_crc(ctype, data, crc_bytes, result)
            _decode_chunk(ctype, data, result)
        else:
            # Uninteressanter Chunk (IHDR, IDAT, …): Daten + CRC überspringen,
            # ohne sie zu laden.
            try:
                stream.seek(length + 4, 1)
            except OSError:
                result.warnings.append(f"Konnte Chunk {_label(ctype)} nicht überspringen.")
                break

        if ctype == _END_CHUNK:
            break

    return result


def _verify_crc(
    ctype: bytes, data: bytes, crc_bytes: bytes, result: ContainerExtraction
) -> None:
    """Prüfe die Chunk-CRC; bei Abweichung nur warnen (Daten trotzdem nutzen)."""
    if len(crc_bytes) < 4:
        result.warnings.append(f"Chunk {_label(ctype)} ohne vollständige CRC.")
        return
    expected = struct.unpack(">I", crc_bytes)[0]
    actual = zlib.crc32(ctype + data) & 0xFFFFFFFF
    if actual != expected:
        result.warnings.append(
            f"CRC-Fehler in Chunk {_label(ctype)} (erwartet {expected:#010x}, "
            f"berechnet {actual:#010x}) — Inhalt dennoch übernommen."
        )


def _decode_chunk(ctype: bytes, data: bytes, result: ContainerExtraction) -> None:
    if ctype == b"tEXt":
        result.items.append(_decode_text(data))
    elif ctype == b"zTXt":
        result.items.append(_decode_ztxt(data, result))
    elif ctype == b"iTXt":
        result.items.append(_decode_itxt(data, result))
    elif ctype == _EXIF_CHUNK:
        result.items.append(
            RawMetadataItem(
                source="png:eXIf",
                keyword=None,
                text=None,
                data=data,
                encoding="binary",
            )
        )


def _split_keyword(data: bytes) -> tuple[str | None, bytes]:
    """Trenne ``keyword \\0 rest``. Ohne Nullbyte: kein Keyword, alles ist Rest."""
    sep = data.find(b"\x00")
    if sep == -1:
        return None, data
    keyword = data[:sep].decode("latin-1")  # Latin-1 dekodiert jedes Byte verlustfrei
    return keyword, data[sep + 1 :]


def _decode_text(data: bytes) -> RawMetadataItem:
    """``tEXt``: Keyword + Latin-1-Text, unkomprimiert."""
    keyword, rest = _split_keyword(data)
    return RawMetadataItem(
        source="png:tEXt",
        keyword=keyword,
        text=rest.decode("latin-1"),
        data=None,
        encoding="latin-1",
    )


def _decode_ztxt(data: bytes, result: ContainerExtraction) -> RawMetadataItem:
    """``zTXt``: Keyword + Methode(1) + zlib-komprimierter Latin-1-Text."""
    keyword, rest = _split_keyword(data)
    if not rest:
        result.warnings.append("zTXt-Chunk ohne Kompressionsmethode/Daten.")
        return _raw_fallback("png:zTXt", keyword, rest)
    method, compressed = rest[0], rest[1:]
    if method != 0:
        result.warnings.append(f"zTXt: unbekannte Kompressionsmethode {method}.")
        return _raw_fallback("png:zTXt", keyword, compressed)
    try:
        text = _decompress_bounded(compressed).decode("latin-1")
    except _DecompressionBomb:
        result.warnings.append(
            f"zTXt: dekomprimiert über {_MAX_DECOMPRESSED >> 20} MiB — "
            f"mögliche Dekompressionsbombe, Chunk verworfen."
        )
        return _raw_fallback("png:zTXt", keyword, compressed)
    except (zlib.error, UnicodeDecodeError) as exc:
        result.warnings.append(f"zTXt: Dekompression/Dekodierung fehlgeschlagen ({exc}).")
        return _raw_fallback("png:zTXt", keyword, compressed)
    return RawMetadataItem(
        source="png:zTXt",
        keyword=keyword,
        text=text,
        data=None,
        encoding="latin-1",
        compressed=True,
    )


def _decode_itxt(data: bytes, result: ContainerExtraction) -> RawMetadataItem:
    """``iTXt``: Keyword + Flag(1) + Methode(1) + Sprache \\0 Übersetzt \\0 UTF-8-Text."""
    keyword, rest = _split_keyword(data)
    if len(rest) < 2:
        result.warnings.append("iTXt-Chunk zu kurz (Flag/Methode fehlen).")
        return _raw_fallback("png:iTXt", keyword, rest)

    compression_flag, compression_method = rest[0], rest[1]
    rest = rest[2:]

    # Sprach-Tag und übersetztes Keyword überspringen (für AI-Metadaten irrelevant,
    # aber strukturell vorhanden): zwei nullterminierte Felder.
    lang_sep = rest.find(b"\x00")
    if lang_sep == -1:
        result.warnings.append("iTXt-Chunk ohne Sprach-Trenner.")
        return _raw_fallback("png:iTXt", keyword, rest)
    rest = rest[lang_sep + 1 :]
    trans_sep = rest.find(b"\x00")
    if trans_sep == -1:
        result.warnings.append("iTXt-Chunk ohne Trenner für übersetztes Keyword.")
        return _raw_fallback("png:iTXt", keyword, rest)
    text_bytes = rest[trans_sep + 1 :]

    compressed = compression_flag == 1
    if compressed:
        if compression_method != 0:
            result.warnings.append(
                f"iTXt: unbekannte Kompressionsmethode {compression_method}."
            )
            return _raw_fallback("png:iTXt", keyword, text_bytes)
        try:
            text_bytes = _decompress_bounded(text_bytes)
        except _DecompressionBomb:
            result.warnings.append(
                f"iTXt: dekomprimiert über {_MAX_DECOMPRESSED >> 20} MiB — "
                f"mögliche Dekompressionsbombe, Chunk verworfen."
            )
            return _raw_fallback("png:iTXt", keyword, text_bytes)
        except zlib.error as exc:
            result.warnings.append(f"iTXt: Dekompression fehlgeschlagen ({exc}).")
            return _raw_fallback("png:iTXt", keyword, text_bytes)

    try:
        text = text_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        # UTF-8 laut Spezifikation erwartet, real-world aber gelegentlich kaputt:
        # dann verlustfrei als Roh-Bytes behalten statt zu raten.
        result.warnings.append(f"iTXt: kein gültiges UTF-8 ({exc}) — als Roh-Bytes behalten.")
        return _raw_fallback("png:iTXt", keyword, text_bytes, compressed=compressed)

    return RawMetadataItem(
        source="png:iTXt",
        keyword=keyword,
        text=text,
        data=None,
        encoding="utf-8",
        compressed=compressed,
    )


def _raw_fallback(
    source: str, keyword: str | None, raw: bytes, *, compressed: bool = False
) -> RawMetadataItem:
    """Verlustfreier Rückfall: rohe Bytes behalten, wenn Dekodierung scheitert."""
    return RawMetadataItem(
        source=source,
        keyword=keyword,
        text=None,
        data=raw,
        encoding="binary",
        compressed=compressed,
    )


def _label(ctype: bytes) -> str:
    """Chunk-Typ als lesbares Label (defensiv gegen Nicht-ASCII-Bytes)."""
    return ctype.decode("latin-1")
