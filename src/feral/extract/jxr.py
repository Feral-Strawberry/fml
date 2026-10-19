"""JPEG XR (``.jxr``, HDR-Screenshots) — Schicht 1, Decoder, SDR-Umrechnung
(ADR 0104).

Die NVIDIA-Aufnahme speichert HDR-Screenshots als JPEG XR in scRGB:
linear, Gleitkomma, 1.0 entspricht 80 Nits, Werte über 1 (Lichter) und
unter 0 (Farben außerhalb von sRGB) kommen vor. Weder Pillow noch ffmpeg
lesen das Format.

- ``extract`` liest das Verzeichnis der Datei (TIFF-artig) mit der Stdlib:
  Maße, Pixelformat, Textfelder, XMP und Farbprofil byte-treu. Läuft auf
  jedem System; rein und defensiv (Warnungen statt Ausnahmen).
- ``decode_scrgb`` holt die Gleitkomma-Pixel über den Decoder des Systems
  (Windows Imaging Component, per ``ctypes`` auf die COM-Schnittstelle).
  Nur unter Windows; überall sonst ``JxrUnsupported``.
- ``tone_map`` rechnet nach SDR um: Mitten bleiben, Lichter werden weich
  zusammengeschoben statt abgeschnitten. Nur Pillow-C-Routinen auf
  Gleitkomma-Kanälen, läuft auf jedem System.
- ``render`` verbindet beides zu einem Pillow-Bild (RGB, 8 Bit).
"""

from __future__ import annotations

import ctypes
import struct
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageMath

from .types import ContainerExtraction, RawMetadataItem

SCRGB_WHITE_NITS = 80.0           # scRGB: 1.0 entspricht 80 Nits
PAPER_WHITE_NITS = 200.0          # Vorgabe für ``[jxr] paper_white_nits``
KNEE = 0.35                       # Vorgabe für ``[jxr] knee``: bis hier unverändert
PEAK_SHARE = 0.001                # „hellste Stelle": nur 0,1 % der Pixel liegen darüber

# Deckel für präparierte Dateien: 8K (7680×4320) sind 33 Megapixel und roh
# 531 MB Gleitkomma — mehr wird nicht dekodiert.
MAX_PIXELS = 34_000_000

_BYTES_PER_PIXEL = 16             # 128bppRGBAFloat
_LOG_Q = 0.05                     # Potenz, die den Logarithmus der Kurve nachbildet


class JxrError(ValueError):
    """Die Datei ließ sich nicht dekodieren."""


class JxrUnsupported(JxrError):
    """Auf diesem System gibt es keinen Decoder (nur Windows, ADR 0104)."""


# ---------------------------------------------------------------- Schicht 1

SIGNATURE = b"II\xbc\x01"         # Byte-Reihenfolge, Kennung 0xBC, Version 1

PIXEL_FORMAT_RGBA_FLOAT = "6fddc324-4e03-4bfe-b185-3d77768dc919"
PIXEL_FORMATS = {
    PIXEL_FORMAT_RGBA_FLOAT: "128bppRGBAFloat",
    "6fddc324-4e03-4bfe-b185-3d77768dc91a": "128bppPRGBAFloat",
    "6fddc324-4e03-4bfe-b185-3d77768dc91b": "128bppRGBFloat",
    "e3fed78f-e8db-4acf-84c1-e97f6136b327": "96bppRGBFloat",
    "6fddc324-4e03-4bfe-b185-3d77768dc93a": "64bppRGBAHalf",
    "6fddc324-4e03-4bfe-b185-3d77768dc942": "64bppRGBHalf",
    "6fddc324-4e03-4bfe-b185-3d77768dc93b": "48bppRGBHalf",
    "6fddc324-4e03-4bfe-b185-3d77768dc916": "64bppRGBA",
    "6fddc324-4e03-4bfe-b185-3d77768dc915": "48bppRGB",
    "6fddc324-4e03-4bfe-b185-3d77768dc90f": "32bppBGRA",
    "6fddc324-4e03-4bfe-b185-3d77768dc90c": "24bppBGR",
}

_TAG_PIXEL_FORMAT = 0xBC01
_TAG_WIDTH = 0xBC80
_TAG_HEIGHT = 0xBC81
_TAG_XMP = 0x02BC
_TAG_ICC = 0x8773
_TAG_EXIF = 0x8769
# Textfelder: Tag → Schlüssel (Namen wie bei EXIF, damit ``DateTime`` die
# Datums-Kaskade speist, ADR 0019).
_TEXT_TAGS = {
    0x010D: "DocumentName", 0x010E: "ImageDescription", 0x010F: "Make",
    0x0110: "Model", 0x0131: "Software", 0x0132: "DateTime",
    0x013B: "Artist", 0x013C: "HostComputer", 0x8298: "Copyright",
}
_EXIF_TEXT_TAGS = {0x9003: "DateTimeOriginal", 0x9004: "CreateDate"}

_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 7: 1}   # BYTE, ASCII, SHORT, LONG, UNDEFINED
_MAX_ENTRIES = 256                # Deckel für präparierte Dateien
_MAX_BLOB = 8 * 1024 * 1024       # XMP/Farbprofil: mehr wird nicht gelesen


def is_jxr(head: bytes) -> bool:
    return head.startswith(SIGNATURE)


def is_jxr_file(source: str | Path) -> bool:
    try:
        with open(source, "rb") as fh:
            return is_jxr(fh.read(len(SIGNATURE)))
    except OSError:
        return False


def pixel_format_name(guid_text: str) -> str:
    return PIXEL_FORMATS.get(guid_text, guid_text)


def _directory(fh: BinaryIO, offset: int, wanted: set[int],
               warnings: list[str]) -> dict[int, tuple[int, bytes]]:
    """Ein Verzeichnis lesen: Tag → (Typ, Wert als Bytes), nur ``wanted``."""
    fh.seek(offset)
    head = fh.read(2)
    if len(head) < 2:
        warnings.append("Directory truncated.")
        return {}
    table = fh.read(min(int.from_bytes(head, "little"), _MAX_ENTRIES) * 12)
    found: dict[int, tuple[int, bytes]] = {}
    for pos in range(0, len(table) - 11, 12):
        tag, kind, count, value = struct.unpack_from("<HHI4s", table, pos)
        if tag not in wanted or kind not in _TYPE_SIZE:
            continue
        length = _TYPE_SIZE[kind] * count
        if length > 4:
            if length > _MAX_BLOB:
                warnings.append(f"Entry 0x{tag:04X} too large ({length} bytes).")
                continue
            fh.seek(int.from_bytes(value, "little"))
            value = fh.read(length)
            if len(value) < length:
                warnings.append(f"Entry 0x{tag:04X} truncated.")
        found[tag] = (kind, value[:length])
    return found


def _number(entry: tuple[int, bytes] | None) -> int | None:
    if entry is None or entry[0] not in (3, 4) or len(entry[1]) < _TYPE_SIZE[entry[0]]:
        return None
    return int.from_bytes(entry[1][:_TYPE_SIZE[entry[0]]], "little")


def _texts(entries: dict[int, tuple[int, bytes]], names: dict[int, str],
           source: str) -> list[RawMetadataItem]:
    items = []
    for tag, keyword in names.items():
        kind, value = entries.get(tag, (0, b""))
        text = value.split(b"\x00", 1)[0].decode("latin-1").strip()
        if kind == 2 and text:
            items.append(RawMetadataItem(
                source=source, keyword=keyword, text=text, data=None, encoding="latin-1"))
    return items


def extract(source: str | Path) -> ContainerExtraction:
    """Roh-Metadaten einer JXR: Maße und Pixelformat, die Textfelder des
    Verzeichnisses, XMP und Farbprofil byte-treu."""
    result = ContainerExtraction(container="jxr", media_kind="image")
    try:
        with open(source, "rb") as fh:
            head = fh.read(8)
            if not is_jxr(head) or len(head) < 8:
                result.warnings.append("No complete JPEG XR header.")
                return result
            wanted = {_TAG_PIXEL_FORMAT, _TAG_WIDTH, _TAG_HEIGHT, _TAG_XMP,
                      _TAG_ICC, _TAG_EXIF, *_TEXT_TAGS}
            entries = _directory(fh, int.from_bytes(head[4:], "little"), wanted,
                                 result.warnings)
            exif_at = _number(entries.get(_TAG_EXIF))
            exif = _directory(fh, exif_at, set(_EXIF_TEXT_TAGS), result.warnings) \
                if exif_at else {}
    except OSError as exc:
        result.warnings.append(f"Read error: {exc}")
        return result

    result.width = _number(entries.get(_TAG_WIDTH))
    result.height = _number(entries.get(_TAG_HEIGHT))
    if not result.width or not result.height:
        result.warnings.append("Dimensions missing in the directory.")
    _, raw_format = entries.get(_TAG_PIXEL_FORMAT, (0, b""))
    if len(raw_format) == 16:
        result.items.append(RawMetadataItem(
            source="jxr:ifd", keyword="PixelFormat",
            text=pixel_format_name(str(uuid.UUID(bytes_le=raw_format))),
            data=None, encoding="utf-8"))
    result.items += _texts(entries, _TEXT_TAGS, "jxr:ifd")
    result.items += _texts(exif, _EXIF_TEXT_TAGS, "jxr:exif")
    for tag, label in ((_TAG_XMP, "jxr:xmp"), (_TAG_ICC, "jxr:icc")):
        _, blob = entries.get(tag, (0, b""))
        if blob:
            result.items.append(RawMetadataItem(
                source=label, keyword=None, text=None, data=blob, encoding="binary"))
    return result


# ------------------------------------------------------------------ Decoder

_CLSID_FACTORY = "cacaf262-9370-4615-a13b-9f5539da4c0a"
_IID_FACTORY = "ec5ec8a9-c395-4314-9c77-54d7a935ff70"

_CLSCTX_INPROC_SERVER = 0x1
_GENERIC_READ = 0x80000000
_RPC_E_CHANGED_MODE = -2147417850  # 0x80010106: COM läuft schon, anderer Modus

_VTABLE = ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
_GUID = ctypes.c_ubyte * 16
_P = ctypes.c_void_p
_OUT = ctypes.POINTER(ctypes.c_void_p)
_UINT = ctypes.c_uint32

# Methoden nach ihrem Platz in der vtable (wincodec.h); 0–2 sind IUnknown.
_RELEASE = 2
_FACTORY_DECODER_FROM_FILENAME = 3
_FACTORY_FORMAT_CONVERTER = 10
_DECODER_GET_FRAME = 13
_SOURCE_GET_SIZE = 3
_SOURCE_GET_PIXEL_FORMAT = 4
_SOURCE_COPY_PIXELS = 7
_CONVERTER_INITIALIZE = 8


def guid(text: str):
    """GUID im Speicherformat von Windows."""
    return _GUID.from_buffer_copy(uuid.UUID(text).bytes_le)


class Com:
    """Griff um einen COM-Zeiger: Methoden über ihren Platz in der vtable."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.ptr = ctypes.c_void_p()

    def call(self, index: int, argtypes: tuple, *args) -> None:
        vtable = ctypes.cast(self.ptr, _VTABLE).contents
        method = ctypes.WINFUNCTYPE(ctypes.c_long, _P, *argtypes)(vtable[index])
        check(method(self.ptr, *args), f"{self.name}[{index}]")

    def release(self) -> None:
        if self.ptr:
            vtable = ctypes.cast(self.ptr, _VTABLE).contents
            ctypes.WINFUNCTYPE(ctypes.c_ulong, _P)(vtable[_RELEASE])(self.ptr)
            self.ptr = ctypes.c_void_p()


def check(hresult: int, what: str) -> None:
    if hresult < 0:
        raise JxrError(f"WIC {what}: 0x{hresult & 0xFFFFFFFF:08X}")


class ComSession:
    """COM für diesen Thread anmelden, die Bild-Fabrik holen, am Ende alle
    Objekte in umgekehrter Reihenfolge freigeben."""

    def __enter__(self) -> ComSession:
        if sys.platform != "win32":
            raise JxrUnsupported("JPEG XR: decoder only available on Windows")
        self._ole32 = ctypes.WinDLL("ole32")
        self._ole32.CoInitializeEx.argtypes = (_P, _UINT)
        self._ole32.CoInitializeEx.restype = ctypes.c_long
        self._ole32.CoCreateInstance.argtypes = (
            ctypes.POINTER(_GUID), _P, _UINT, ctypes.POINTER(_GUID), _OUT)
        self._ole32.CoCreateInstance.restype = ctypes.c_long
        started = self._ole32.CoInitializeEx(None, 0)
        self._uninit = started >= 0
        if started < 0 and started != _RPC_E_CHANGED_MODE:
            check(started, "CoInitializeEx")
        self._objects: list[Com] = []
        self.factory = self.new("factory")
        try:
            check(self._ole32.CoCreateInstance(
                ctypes.byref(guid(_CLSID_FACTORY)), None, _CLSCTX_INPROC_SERVER,
                ctypes.byref(guid(_IID_FACTORY)), ctypes.byref(self.factory.ptr),
            ), "CoCreateInstance")
        except JxrError:
            self.__exit__()
            raise
        return self

    def new(self, name: str) -> Com:
        obj = Com(name)
        self._objects.append(obj)
        return obj

    def __exit__(self, *exc) -> None:
        for obj in reversed(self._objects):
            obj.release()
        if self._uninit:
            self._ole32.CoUninitialize()


def decode_scrgb(source: str | Path) -> tuple[int, int, bytearray, str]:
    """Pixel einer JXR als RGBA-Gleitkomma (16 Bytes je Pixel, linear scRGB).

    Gibt ``(breite, höhe, pixel, format_der_datei)`` zurück. Speichert die
    Datei ein anderes Pixelformat (die Game Bar etwa 16-Bit-Gleitkomma),
    rechnet der Format-Wandler des Systems um.
    """
    with ComSession() as com:
        decoder, frame = com.new("decoder"), com.new("frame")
        com.factory.call(
            _FACTORY_DECODER_FROM_FILENAME, (ctypes.c_wchar_p, _P, _UINT, _UINT, _OUT),
            str(source), None, _GENERIC_READ, 0, ctypes.byref(decoder.ptr))
        decoder.call(_DECODER_GET_FRAME, (_UINT, _OUT), 0, ctypes.byref(frame.ptr))

        width, height = _UINT(), _UINT()
        frame.call(_SOURCE_GET_SIZE, (ctypes.POINTER(_UINT),) * 2,
                   ctypes.byref(width), ctypes.byref(height))
        w, h = width.value, height.value
        if not w or not h or w * h > MAX_PIXELS:
            raise JxrError(f"JPEG XR: size {w}x{h} out of range")

        native = _GUID()
        frame.call(_SOURCE_GET_PIXEL_FORMAT, (ctypes.POINTER(_GUID),),
                   ctypes.byref(native))
        native_format = str(uuid.UUID(bytes_le=bytes(native)))

        pixels_from = frame
        if native_format != PIXEL_FORMAT_RGBA_FLOAT:
            converter = com.new("converter")
            com.factory.call(_FACTORY_FORMAT_CONVERTER, (_OUT,),
                             ctypes.byref(converter.ptr))
            converter.call(
                _CONVERTER_INITIALIZE,
                (_P, ctypes.POINTER(_GUID), _UINT, _P, ctypes.c_double, _UINT),
                frame.ptr, ctypes.byref(guid(PIXEL_FORMAT_RGBA_FLOAT)), 0, None, 0.0, 0)
            pixels_from = converter

        stride = w * _BYTES_PER_PIXEL
        pixels = bytearray(stride * h)
        pixels_from.call(
            _SOURCE_COPY_PIXELS, (_P, _UINT, _UINT, _P),
            None, stride, len(pixels), (ctypes.c_ubyte * len(pixels)).from_buffer(pixels))
    return w, h, pixels, native_format


# ------------------------------------------------------------- Umrechnung

def split_channels(width: int, height: int, pixels: bytes | bytearray,
                   ) -> tuple[Image.Image, Image.Image, Image.Image]:
    """RGBA-Gleitkomma → drei Pillow-Bilder im Modus ``F`` (Alpha entfällt)."""
    floats = memoryview(pixels).cast("f")
    return tuple(  # type: ignore[return-value]
        Image.frombuffer("F", (width, height), floats[c::4].tobytes(), "raw", "F", 0, 1)
        for c in range(3)
    )


def _srgb_table() -> list[int]:
    """Linear (16 Bit) → sRGB (8 Bit)."""
    table = []
    for i in range(65536):
        v = i / 65535
        v = 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
        table.append(round(v * 255))
    return table


_SRGB: list[int] = []


@dataclass(frozen=True)
class Tone:
    """Einstellungen der SDR-Umrechnung (``[jxr]`` in der Config). Picklebar
    und als JSON transportierbar, damit sie durch Pool und Aufgaben reisen."""

    paper_white: float = PAPER_WHITE_NITS
    knee: float = KNEE

    @classmethod
    def of(cls, params: dict | None) -> Tone:
        return cls(**{k: float(v) for k, v in (params or {}).items()
                      if k in ("paper_white", "knee")})

    def params(self) -> dict[str, float]:
        return {"paper_white": self.paper_white, "knee": self.knee}

    def variant(self) -> str:
        """Teil des Cache-Schlüssels: Ändert sich die Umrechnung, entsteht ein
        neues Anzeigebild, das alte bleibt unbenutzt liegen (ADR 0104 Punkt 6)."""
        return f"w{self.paper_white:g}k{round(self.knee * 100)}"


def peak_level(values: Image.Image, share: float = PEAK_SHARE) -> float:
    """Die Helligkeit, über der nur noch der Anteil ``share`` der Pixel liegt:
    die „hellste Stelle" des Bilds, ohne dass eine winzige Sonne oder ein
    einzelner Ausreißer die ganze Kurve bestimmt. Histogramm in zwei
    Durchgängen (grob, dann fein), auf einem verkleinerten Bild."""
    small = values.reduce(max(1, min(values.size) // 512))
    total = small.width * small.height
    top = small.getextrema()[1]
    for _ in range(2):
        if top <= 0:
            return 0.0
        bins = ImageMath.lambda_eval(
            lambda a: a["convert"](
                a["min"](a["max"](a["v"], 0.0) / top, 1.0) ** 0.5 * 255.0, "L"),
            v=small).histogram()
        budget = share * total
        level = 255
        while level > 0 and budget >= bins[level]:
            budget -= bins[level]
            level -= 1
        top *= min(1.0, (level + 1) / 255) ** 2     # Oberkante der Stufe
    return top


def shoulder_gain(knee: float, peak: float) -> float:
    """Stärke ``a`` des Auslaufs oberhalb des Knies.

    Die Kurve ist ``knee + (1 - knee) * L(a * e) / L(a * E)`` mit ``e`` =
    Wert über dem Knie, ``E`` = hellste Stelle über dem Knie und ``L`` einem
    Logarithmus (hier als Potenz mit kleinem Exponenten gerechnet, Pillow
    hat keinen). Logarithmisch heißt: Jede Verdopplung der Helligkeit bekommt
    etwa gleich viele Stufen, die Lichter drängen sich nicht direkt unter
    Weiß. ``a`` ist so gewählt, dass die Kurve am Knie mit Steigung 1
    ansetzt (kein Knick); die hellste Stelle landet genau auf 1.0.
    """
    room, span = 1.0 - knee, peak - knee

    def excess(a: float) -> float:            # > 0, solange a zu klein ist
        return (1.0 + a * span) ** _LOG_Q - 1.0 - room * a * _LOG_Q

    low, high = 0.0, 1.0
    while excess(high) > 0:
        low, high = high, high * 2
    for _ in range(40):
        mid = (low + high) / 2
        low, high = (mid, high) if excess(mid) > 0 else (low, mid)
    return high


def tone_map(red: Image.Image, green: Image.Image, blue: Image.Image,
             tone: Tone = Tone()) -> Image.Image:
    """Lineare scRGB-Kanäle (Modus ``F``) → SDR-Bild (RGB, 8 Bit, sRGB).

    Das Papierweiß (Nits) wird auf Weiß gelegt. Maßstab je Pixel ist sein
    hellster Kanal: Bis zum Knie bleibt er unverändert, darüber läuft er
    logarithmisch aus bis zur hellsten Stelle des Bilds. Alle drei Kanäle
    werden um dasselbe Verhältnis gedrückt. So bleiben Farbton und Sättigung,
    und kein Kanal stößt an die Grenze: Ein farbiges Licht wird dunkler,
    aber nicht weiß. Nur Farben außerhalb von sRGB (negative Werte) und der
    kleine Rest über der hellsten Stelle werden begrenzt.
    """
    gain = SCRGB_WHITE_NITS / tone.paper_white
    knee = min(max(tone.knee, 0.05), 0.95)
    top = ImageMath.lambda_eval(
        lambda a: a["max"](a["max"](a["r"], a["g"]), a["b"]) * gain,
        r=red, g=green, b=blue)
    peak = peak_level(top)

    scale: Image.Image | float = gain
    if peak > 1.0:
        strength = shoulder_gain(knee, peak)
        full = (1.0 + strength * (peak - knee)) ** _LOG_Q - 1.0
        over = ImageMath.lambda_eval(lambda a: a["max"](a["t"] - knee, 0.0), t=top)
        scale = ImageMath.lambda_eval(
            lambda a: (((a["e"] * strength + 1.0) ** _LOG_Q - 1.0)
                       * ((1.0 - knee) / full) + knee) / (a["e"] + knee) * gain,
            e=over)

    if not _SRGB:
        _SRGB.extend(_srgb_table())
    channels = []
    for channel in (red, green, blue):
        linear = ImageMath.lambda_eval(
            lambda a: a["convert"](
                a["min"](a["max"](a["c"] * a["s"], 0.0), 1.0) * 65535.0 + 0.5, "I"),
            c=channel, s=scale)
        channels.append(linear.point(_SRGB, "L"))
    return Image.merge("RGB", channels)


def render(source: str | Path, tone: Tone = Tone()) -> Image.Image:
    """JXR dekodieren und nach SDR umrechnen (nur unter Windows)."""
    width, height, pixels, _ = decode_scrgb(source)
    channels = split_channels(width, height, pixels)
    del pixels
    return tone_map(*channels, tone)


def provenance(source: str | Path, file_hash: str | None, tone: Tone) -> dict[str, str]:
    """Textfelder für das gerechnete PNG: woraus es entstand und mit welchen
    Werten (ADR 0104 Punkt 7)."""
    fields = {
        "Software": "Feral Media Library",
        "Source": Path(source).name,
        "fml:jxr-paper-white-nits": f"{tone.paper_white:g}",
        "fml:jxr-knee": f"{tone.knee:g}",
    }
    if file_hash:
        fields["fml:source-sha256"] = file_hash
    return fields
