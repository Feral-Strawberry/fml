"""Filtergrammatik für Smart Folders (ADR 0018, erweitert um ADR 0035).

Parst Ausdrücke wie ``model: flux | krea -tag: wip rating>=4 sort: created``
in Prädikate und baut daraus WHERE-Fragmente (unkorrelierte IN-Subqueries,
Werte immer als Parameter). Bewusst klein: UND zwischen Prädikaten + Negation,
keine Klammern. Neu mit ADR 0035 (nur ergänzt, nichts umgedeutet):

- **Facetten-ODER** ``feld: wert1 | wert2`` — Pipe MIT Leerraum beidseits
  trennt Werte eines Werte-Prädikats (ODER); ``-feld: a | b`` = weder noch.
  Vergleiche (``rating>=``, ``width>=`` …) kennen kein ODER — Bereiche gehen
  über ``>=``/``<=``-Paare.
- **Sortier-Direktive** ``sort: <schlüssel>`` (Whitelist ``SORT_KEYS``,
  maximal einmal) — kein Filter, sondern Anweisung; gewinnt in
  ``library.list_items`` über den ``?sort=``-Parameter.
- **Serialisierer** ``serialize()`` — Prädikate → kanonischer Ausdruckstext,
  damit Chips ↔ Text verlustfrei in beide Richtungen gehen.

Fehler sind ``UserError`` (ein ``ValueError``) mit übersetzbarer Meldung
(Schlüssel + Parameter, Block M.2/ADR 0054) — die Anzeige-Sätze stehen in
``strings.<lang>.js`` unter ``server``.

Englische Grammatik-Aliasse (Block M.3/ADR 0054): ``parse()`` nimmt
``file:``/``location:``, die Formatwerte ``portrait``/``square``/
``landscape``, die Sortier-Suffixe ``-asc``/``-desc`` sowie die Werte
``unknown`` (year:) und ``external`` (fundort:) zusätzlich an;
``serialize()`` bleibt kanonisch (heutige Schreibweise) — gespeicherte
Smart Folders und die ADR-0035-Invariante bleiben unangetastet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..messages import UserError

# Kanonisches Schicht-2-Vokabular (interpret/types.py) — ohne 'rating',
# das im Ausdruck immer die manuelle Bewertung meint (ADR 0018).
FIELDS = frozenset({
    "tool", "prompt", "negative_prompt", "model", "model_hash", "seed",
    "sampler", "scheduler", "steps", "cfg_scale", "denoise", "size",
    "lora", "vae", "description", "credit", "ai_source_type",
    "creator_tool", "job_id", "feature", "input_image",
})

# Whitelist der sort:-Direktive (ADR 0035). Muss die Schlüssel von
# library._SORTS spiegeln (Test sichert das ab) — filters darf library
# nicht importieren, library importiert filters.
SORT_KEYS = frozenset({"added", "size", "name", "container", "rating", "created"})

# Standardrichtung je Schlüssel (ADR 0039): "ab" = absteigend (Neuestes/
# Größtes/Bestes zuerst), "auf" = aufsteigend (A–Z). Ein Richtungs-Suffix
# (`sort: created-auf`) übersteuert; das Suffix der Standardrichtung wird
# beim Parsen weggekürzt — gespeicherte Ausdrücke bleiben kanonisch kurz.
SORT_DEFAULT_DIRECTION = {
    "added": "ab", "size": "ab", "created": "ab", "rating": "ab",
    "name": "auf", "container": "auf",
}


def split_sort_key(key: str) -> tuple[str, str]:
    """Sortierschlüssel → (Basis, effektive Richtung ``"auf"``/``"ab"``)."""
    base, _, richtung = key.partition("-")
    return base, richtung or SORT_DEFAULT_DIRECTION.get(base, "ab")

# Grobe Seitenverhältnis-Klassen (Block 4S, Feral Strawberrys Wunsch zur Fehlersuche nach
# dem Import): bewusst nur vier Eimer statt exakter Verhältnisse. Grenzen als
# Multiplikation (nie durch height teilen — 0/NULL-sicher); die vier Klassen
# zerlegen alle Items MIT Maßen lückenlos. Dieselben Grenzen nutzt
# library.format_counts() für die Sidebar-Zähler.
FORMATS = {
    "quadratisch": "(i.width >= i.height * 0.95 AND i.width <= i.height * 1.05)",
    "hochformat": "(i.width < i.height * 0.95)",
    "querformat": "(i.width > i.height * 1.05 AND i.width < i.height * 1.7)",
    "widescreen": "(i.width >= i.height * 1.7)",
}
_FORMAT_GUARD = "(i.width IS NOT NULL AND i.height IS NOT NULL AND i.height > 0)"

# Megapixel-Eimer (Feral Strawberrys Wunsch aus der 100-GB-Runde, 2026-07-08): vier
# Bereiche über width*height, 1 MP = 1.000.000 Pixel (dezimal, wie bei
# Kameras üblich). Untergrenze inklusiv, Obergrenze exklusiv — zerlegt alle
# Items MIT Maßen lückenlos. Dieselben Grenzen nutzt
# library.megapixel_counts() für die Sidebar-Zähler.
MEGAPIXELS = {
    "<1": "(i.width * i.height < 1000000)",
    "1-2": "(i.width * i.height >= 1000000 AND i.width * i.height < 2000000)",
    "2-4": "(i.width * i.height >= 2000000 AND i.width * i.height < 4000000)",
    ">4": "(i.width * i.height >= 4000000)",
}

# Dateiname (Basename) einer path-Spalte, rein in SQL: '\'→'/' normalisieren
# (Windows-Pfade im Bestand), dann per rtrim-Idiom das Verzeichnis-Präfix
# tilgen. Auch von library.py genutzt (Sortierung nach Name, Suche).
NORM_PATH = "replace(path, '\\', '/')"

# Laufzeit-Kontext fürs fundort:-Prädikat (ADR 0041, I2): build_where braucht
# die Library-Wurzel, darf aber weder config noch library importieren (die
# Import-Richtung ist library → filters). create_app injiziert darum einen
# Provider, der die Config je Aufruf frisch liest — GUI-Änderungen an der
# Root wirken sofort. Standard: keine Library konfiguriert.
library_root_provider: Callable[[], str | None] = lambda: None

# Die zwei Werte des fundort:-Prädikats: „library" = mindestens ein Fundort
# unter library.root, „extern" = keiner (nur indiziert, ADR 0041).
FUNDORTE = ("library", "extern")

# Englische Aliasse der deutschen Grammatik-Reste (ADR 0054, Block M.3) —
# nur beim Parsen; kanonisch (Prädikate, serialize()) bleibt die heutige
# Schreibweise, damit gespeicherte Ausdrücke nie migriert werden müssen.
_KEY_ALIASES = {"file": "datei", "location": "fundort"}
_FORMAT_ALIASES = {"portrait": "hochformat", "square": "quadratisch",
                   "landscape": "querformat"}
_SORT_DIRECTION_ALIASES = {"asc": "auf", "desc": "ab"}
# Werte-Aliasse (Nachtrag Feral Strawberry, 2026-07-18): damit ist die Grammatik
# komplett englisch tippbar.
_YEAR_ALIASES = {"unknown": "unbekannt"}
_FUNDORT_ALIASES = {"external": "extern"}


def library_like_prefix() -> str | None:
    """LIKE-Präfix (``…/%``) der Library-Wurzel, separator-normalisiert und
    LIKE-escaped — oder ``None``, wenn keine Root konfiguriert ist.

    Bewusst ohne ``resolve()``: Importer und Scan speichern Pfade auf Basis
    der Config-Wurzel, wie sie dasteht (``_bestand_locations`` vergleicht
    genauso unaufgelöst). ``ESCAPE`` ist Pflicht — ``_``/``%`` sind in
    Windows-Pfaden legal und wären sonst Wildcards.
    """
    root = library_root_provider()
    if not root or not str(root).strip():
        return None
    norm = str(Path(str(root)).expanduser()).replace("\\", "/").rstrip("/")
    return f"{_escape_like(norm)}/%" if norm else None
BASENAME = f"replace({NORM_PATH}, rtrim({NORM_PATH}, replace({NORM_PATH}, '/', '')), '')"

_RATING = re.compile(r"^rating(>=|<=|=)([0-5])$")
# Eckwert-Vergleiche auf items-Spalten (Whitelist! Wert = Zahl).
_METRIC = re.compile(r"^(width|height|fps)(>=|<=|=)(\d+(?:\.\d+)?)$")
_METRIC_COLUMNS = {"width": "i.width", "height": "i.height", "fps": "i.fps"}
# Ein Wert: "…" (darf Leerraum enthalten) oder ein Token ohne Leerraum.
# Anführungszeichen IM Wert werden verdoppelt (SQL-Muster, ADR-0035-Nachtrag):
# "sag ""hi""" = ein exakter Wert `sag "hi"` — vorher konnte die Grammatik
# solche Werte gar nicht tragen (Seed-Varianten-Suche verlor den Prompt).
_VALUE = r'"(?:[^"]|"")*"|\S+'
_VALUE_RE = re.compile(_VALUE)
# feld: wert1 | wert2 | "wert drei" — Doppelpunkt mit optionalem Leerraum,
# Pipe MIT Leerraum beidseits als ODER-Trenner (ADR 0035; ohne Leerraum bleibt
# »a|b« EIN Wert — keine Umdeutung alter Ausdrücke). Das Minus fürs Negieren
# wird vorher abgetrennt; Vergleiche (rating/Eckwerte) sind eigene Alternative.
_TOKEN = re.compile(
    rf'(-?)([a-z_]+)\s*:\s*((?:{_VALUE})(?:\s+\|\s+(?:{_VALUE}))*)'
    rf'|(-?)((?:rating|width|height|fps)\s*(?:>=|<=|=)\s*[\d.]+)'
    rf'|(\S+)',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Predicate:
    kind: str            # 'field' | 'tag' | 'container' | 'has' | 'rating' | 'metric' | 'format' | 'mp' | 'year' | 'month' | 'fundort' | 'datei' | 'text' | 'raw' | 'sort'
    negated: bool
    field: str = ""      # bei kind='field'/'metric'
    # ODER-Liste (wert, exakt) — ADR 0035. Ein Eintrag = das klassische
    # Ein-Wert-Prädikat; exakt = mit "…" getippt.
    values: tuple[tuple[str, bool], ...] = ()
    op: str = "="        # bei kind='rating'/'metric'

    # Bequemer Zugriff für Ein-Wert-Prädikate (Vergleiche, sort:) und
    # Bestandscode/Tests aus der Zeit vor den ODER-Listen.
    @property
    def value(self) -> str:
        return self.values[0][0] if self.values else ""

    @property
    def exact(self) -> bool:
        return self.values[0][1] if self.values else False


def _split_values(key: str, blob: str) -> list[tuple[str, bool]]:
    """ODER-Werteliste eines Prädikats: [(wert, exakt), …] (ADR 0035)."""
    values: list[tuple[str, bool]] = []
    for m in _VALUE_RE.finditer(blob):
        raw = m.group(0)
        if raw == "|":  # der Trenner selbst (matcht als \S+)
            continue
        if raw.startswith('"'):
            # Unbalancierte Quotes landen in der \S+-Alternative (die
            # Quoted-Alternative verlangt den schließenden Abschluss).
            if len(raw) < 2 or not raw.endswith('"'):
                raise UserError("filterUnclosedQuote", value=raw)
            values.append((raw[1:-1].replace('""', '"'), True))
        else:
            values.append((raw, False))
    if not values or any(not v for v, _ in values):
        raise UserError("filterNeedsValue", field=key)
    return values


def parse(expression: str) -> list[Predicate]:
    """Ausdruck → Prädikate. Wirft ``UserError`` mit übersetzbarer Meldung."""
    preds: list[Predicate] = []
    rest = expression.strip()
    for m in _TOKEN.finditer(rest):
        if m.group(6):  # nacktes Token ohne feld: — bewusst kein stilles Raten
            token = m.group(6)
            rm = _RATING.match(token.replace(" ", "").lower())
            if rm is None:
                if token.startswith("|") or token.endswith("|"):
                    raise UserError("filterOrSyntax")
                raise UserError("filterUnknownToken", value=token)
            preds.append(Predicate(kind="rating", negated=False, op=rm.group(1),
                                   values=((rm.group(2), False),)))
            continue
        if m.group(5):  # Vergleichs-Prädikat: rating oder Eckwert (width/height/fps)
            token = m.group(5).replace(" ", "").lower()
            negated5 = m.group(4) == "-"
            rm = _RATING.match(token)
            if rm:
                preds.append(Predicate(kind="rating", negated=negated5, op=rm.group(1),
                                       values=((rm.group(2), False),)))
                continue
            mm = _METRIC.match(token)
            if mm:
                preds.append(Predicate(kind="metric", negated=negated5, field=mm.group(1),
                                       op=mm.group(2), values=((mm.group(3), False),)))
                continue
            raise UserError("filterBadComparison", value=m.group(5))
        negated, key = m.group(1) == "-", m.group(2).lower()
        key = _KEY_ALIASES.get(key, key)
        values = _split_values(key, m.group(3))
        if key == "sort":
            # Direktive, kein Filter (ADR 0035): Whitelist, maximal einmal,
            # nicht negierbar, kein ODER.
            if negated:
                raise UserError("filterSortNegated")
            if len(values) > 1:
                raise UserError("filterSortSingle")
            # Richtungs-Suffix -auf/-ab (ADR 0039), englisch -asc/-desc
            # (ADR 0054); die Standardrichtung wird weggekürzt: `created-ab`
            # und `created` sind derselbe kanonische Schlüssel.
            base, _, richtung = values[0][0].lower().partition("-")
            richtung = _SORT_DIRECTION_ALIASES.get(richtung, richtung)
            if base not in SORT_KEYS or richtung not in ("", "auf", "ab"):
                raise UserError("filterSortUnknown", value=values[0][0],
                                known=", ".join(sorted(SORT_KEYS)))
            sort_key = (base if richtung in ("", SORT_DEFAULT_DIRECTION[base])
                        else f"{base}-{richtung}")
            if any(p.kind == "sort" for p in preds):
                raise UserError("filterSortOnce")
            preds.append(Predicate(kind="sort", negated=False,
                                   values=((sort_key, False),)))
        elif key == "tag":
            preds.append(Predicate(kind="tag", negated=negated, values=tuple(values)))
        elif key == "text":
            # Freitext-Begriff (gespeicherte Suche): irgendwo am Item —
            # Schicht 2, Roh-Texte oder Dateiname.
            preds.append(Predicate(kind="text", negated=negated, values=tuple(values)))
        elif key == "raw":
            # Rohdaten-Opt-in (ADR 0036/0038): wie text:, aber ZUSÄTZLICH in
            # den Roh-Texten (Workflow-JSONs, Node-Namen — und allem, was
            # sonst im Blob steht, bei A1111 auch der Negativ-Prompt-Text).
            preds.append(Predicate(kind="raw", negated=negated, values=tuple(values)))
        elif key == "container":
            preds.append(Predicate(kind="container", negated=negated,
                                   values=tuple((v.lower(), e) for v, e in values)))
        elif key == "has":
            # 'workflow' prüft Schicht 1 (Roh-Blob); Schicht-2-Feldnamen prüfen
            # bloße Existenz des Felds — »-has: model« = unbekanntes Modell.
            for v, _ in values:
                if v.lower() != "workflow" and v.lower() not in FIELDS:
                    raise UserError("filterHasUnknown",
                                    known=", ".join(sorted(FIELDS)))
            preds.append(Predicate(kind="has", negated=negated,
                                   values=tuple((v.lower(), e) for v, e in values)))
        elif key == "format":
            # Werte über die englischen Aliasse auf kanonisch mappen (M.3).
            mapped = tuple((_FORMAT_ALIASES.get(v.lower(), v.lower()), e)
                           for v, e in values)
            for (v, _), (orig, _) in zip(mapped, values):
                if v not in FORMATS:
                    raise UserError("filterFormatUnknown", value=orig,
                                    known=", ".join(sorted(FORMATS)))
            preds.append(Predicate(kind="format", negated=negated, values=mapped))
        elif key == "mp":
            for v, _ in values:
                if v.lower() not in MEGAPIXELS:
                    raise UserError("filterMpUnknown", value=v,
                                    known=", ".join(MEGAPIXELS))
            preds.append(Predicate(kind="mp", negated=negated,
                                   values=tuple((v.lower(), e) for v, e in values)))
        elif key == "year":
            # Erstelldatum (ADR 0021): year: 2022 | year: unbekannt (= NULL);
            # englisch year: unknown (M.3).
            mapped = tuple((_YEAR_ALIASES.get(v.lower(), v.lower()), e)
                           for v, e in values)
            for v, _ in mapped:
                if v != "unbekannt" and not re.fullmatch(r"\d{4}", v):
                    raise UserError("filterYearInvalid")
            preds.append(Predicate(kind="year", negated=negated, values=mapped))
        elif key == "month":
            for v, _ in values:
                if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", v):
                    raise UserError("filterMonthInvalid")
            preds.append(Predicate(kind="month", negated=negated, values=tuple(values)))
        elif key == "datei":
            # Dateiname (Feral Strawberry, 2026-07-16 — v. a. für metadatenlose
            # Midjourney-Bestände, auch in Arena-Ausdrücken): Teilstring
            # bzw. exakt ("…") auf den Dateinamen der Fundorte.
            preds.append(Predicate(kind="datei", negated=negated, values=tuple(values)))
        elif key == "fundort":
            # Library vs. Extern (ADR 0041, I2): liegt mindestens ein Fundort
            # des Items unter library.root? Englisch: location: external (M.3).
            mapped = tuple((_FUNDORT_ALIASES.get(v.lower(), v.lower()), e)
                           for v, e in values)
            for (v, _), (orig, _) in zip(mapped, values):
                if v not in FUNDORTE:
                    raise UserError("filterFundortUnknown", value=orig,
                                    known=" und ".join(FUNDORTE))
            preds.append(Predicate(kind="fundort", negated=negated, values=mapped))
        elif key == "rating":
            raise UserError("filterRatingSyntax")
        elif key in FIELDS:
            preds.append(Predicate(kind="field", negated=negated, field=key,
                                   values=tuple(values)))
        else:
            raise UserError("filterUnknownField", field=key,
                            known=", ".join(sorted(FIELDS)))
    if not preds:
        raise UserError("filterEmpty")
    return preds


def serialize(predicates: list[Predicate]) -> str:
    """Prädikate → kanonischer Ausdruckstext (ADR 0035).

    Die Gegenrichtung zu ``parse()``, damit Chips ↔ Text verlustfrei in beide
    Richtungen gehen; ``parse(serialize(preds)) == preds`` ist garantiert
    (Round-Trip-Tests). Exakte Werte werden mit ``"…"`` ausgegeben — das
    Anführungszeichen trägt die Bedeutung; enthaltene ``"`` werden
    verdoppelt (Gegenstück zu ``_split_values``).
    """
    parts: list[str] = []
    for p in predicates:
        neg = "-" if p.negated else ""
        if p.kind == "rating":
            parts.append(f"{neg}rating{p.op}{p.value}")
        elif p.kind == "metric":
            parts.append(f"{neg}{p.field}{p.op}{p.value}")
        else:
            key = p.field if p.kind == "field" else p.kind
            rendered = " | ".join(
                '"{}"'.format(v.replace('"', '""')) if exact else v
                for v, exact in p.values
            )
            parts.append(f"{neg}{key}: {rendered}")
    return " ".join(parts)


def sort_directive(predicates: list[Predicate]) -> str | None:
    """Sortierschlüssel der ``sort:``-Direktive, falls vorhanden (ADR 0035)."""
    for p in predicates:
        if p.kind == "sort":
            return p.value
    return None


# -- JSON-Brücke für die Chip-Leiste (Block S3) ---------------------------------
#
# Das Frontend hält den Suchzustand als Prädikat-Dicts, aber Wahrheit und
# Validierung bleiben HIER: Chips → serialize() → parse() — es gibt genau
# einen Parser und einen Serialisierer (ADR 0035), keine zweite
# Grammatik-Implementierung in JavaScript.

def predicate_to_dict(p: Predicate) -> dict[str, Any]:
    """Prädikat → JSON-fähiges Dict (Chip)."""
    return {
        "kind": p.kind,
        "negated": p.negated,
        "field": p.field,
        "op": p.op,
        "values": [{"value": v, "exact": e} for v, e in p.values],
    }


def predicate_from_dict(d: dict[str, Any]) -> Predicate:
    """Chip-Dict → Prädikat (lose — die Validierung macht parse()).

    Werte mit Leerraum sind in der Grammatik nur exakt/als Phrase
    darstellbar und werden entsprechend hochgestuft; dito Werte, die mit
    ``"`` beginnen (unquotiert läse parse() das als offene Phrase).
    Eingebettete Anführungszeichen trägt die Grammatik seit dem
    Escaping-Nachtrag zu ADR 0035 per Verdopplung — das frühere
    Rundweg-Ablehnen ließ die Seed-Varianten-Suche Prompts mit Zitaten
    still verlieren.
    """
    values: list[tuple[str, bool]] = []
    for v in d.get("values", []):
        text = str(v.get("value", "")).strip()
        values.append((text, bool(v.get("exact"))
                       or bool(re.search(r"\s", text)) or text.startswith('"')))
    return Predicate(
        kind=str(d.get("kind", "")),
        negated=bool(d.get("negated")),
        field=str(d.get("field", "")),
        op=str(d.get("op", "=")),
        values=tuple(values),
    )


def parse_for_api(expression: str) -> dict[str, Any]:
    """Ausdruck → {expression (kanonisch), predicates, sort} für die
    Chip-Leiste. Wirft ``ValueError`` mit zeigbarer Meldung."""
    preds = parse(expression)
    return {
        "expression": serialize(preds),
        "predicates": [predicate_to_dict(p) for p in preds],
        "sort": sort_directive(preds),
    }


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def fts_match_query(terms: list[str]) -> str:
    """Begriffe → FTS5-MATCH-Ausdruck (ADR 0024): je Begriff ein
    Token-Präfix in Anführungszeichen (immun gegen FTS-Syntaxzeichen),
    Leerzeichen dazwischen = UND."""
    return " ".join(f'"{t.replace(chr(34), chr(34) * 2)}"*' for t in terms if t)


# Spalten der Standard-Suche im kuratierten FTS-Index (ADR 0036): manuelle
# Schicht rein; negative_prompt und Roh-Blobs nur gezielt erreichbar.
FTS_DEFAULT_COLUMNS = "{interp names manuell}"
# Rohdaten-Opt-in (raw:-Prädikat, ADR 0038): Standard-Spalten PLUS Roh-Texte —
# »auch in Rohdaten«, nicht »nur in Rohdaten«. Die negativ-Spalte bleibt
# draußen (Roh-Blobs können den Negativ-Prompt trotzdem wörtlich enthalten).
FTS_RAW_COLUMNS = "{interp names manuell raw}"


def fts_default_match(terms: list[str]) -> str:
    """MATCH-Ausdruck der Standard-Suche (ADR 0036): Token-Präfixe (UND),
    beschränkt auf die kuratierten Spalten — »hund« trifft keine
    Anti-Hund-Bilder (negative_prompt) und keine Roh-Blobs mehr."""
    return f"{FTS_DEFAULT_COLUMNS}: ({fts_match_query(terms)})"


def _value_match(column: str, values: tuple[tuple[str, bool], ...],
                 params: list[Any]) -> str:
    """ODER-verknüpfte Wertvergleiche einer Werteliste (ADR 0035):
    exakt (``= ? COLLATE NOCASE``) oder Teilstring (``LIKE``), Werte immer
    als Parameter."""
    frags = []
    for value, exact in values:
        if exact:
            frags.append(f"{column} = ? COLLATE NOCASE")
            params.append(value)
        else:
            frags.append(f"{column} LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(value)}%")
    return f"({' OR '.join(frags)})"


def build_where(predicates: list[Predicate]) -> tuple[str, list[Any]]:
    """Prädikate → (SQL-Fragment über Alias ``i``, Parameter). UND-verknüpft.

    Die ``sort:``-Direktive ist kein Filter und wird übersprungen — ein
    Ausdruck nur aus ``sort:`` ergibt ein leeres Fragment.
    """
    parts: list[str] = []
    params: list[Any] = []
    # WICHTIG (Feral Strawberrys Windows-Runde 5): Mengen-Prädikate als UNKORRELIERTE
    # ``IN (SELECT …)``-Subqueries — SQLite materialisiert die Treffermenge
    # EINMAL je Abfrage (ephemärer Index), danach nur noch Lookups. Die alte
    # EXISTS-Form probte JEDES Item einzeln; beim Blättern tief in gefilterte
    # Ansichten (OFFSET-Lauf) wurde daraus ein Prüf-Scan pro Seite —
    # „Alle Medien" blieb flott, Filteransichten rödelten.
    # ODER-Listen (ADR 0035) leben INNERHALB der einen Subquery je Prädikat —
    # weiterhin eine Materialisierung pro Prädikat, nicht pro Wert.
    for p in predicates:
        if p.kind == "sort":
            continue
        if p.kind == "field" and p.field == "model":
            # Effektives Modell (ADR 0022): manuell gesetztes gewinnt — Items
            # mit manuellem Modell matchen NICHT mehr über ihr interpretiertes.
            ann = _value_match("model", p.values, params)
            interp = _value_match("value_text", p.values, params)
            sub = (f"(i.file_hash IN (SELECT file_hash FROM annotations "
                   f"WHERE {ann}) "
                   f"OR (i.file_hash IN (SELECT file_hash FROM interpreted_metadata "
                   f"WHERE field = 'model' AND {interp}) "
                   f"AND i.file_hash NOT IN (SELECT file_hash FROM annotations "
                   f"WHERE model IS NOT NULL)))")
        elif p.kind == "field":
            params.append(p.field)
            match = _value_match("value_text", p.values, params)
            sub = (f"i.file_hash IN (SELECT file_hash FROM interpreted_metadata "
                   f"WHERE field = ? AND {match})")
        elif p.kind in ("text", "raw"):
            # Freitext (gespeicherte Suche): ein Begriff irgendwo am Item —
            # über den FTS5-Index (ADR 0024), dieselbe Semantik wie die
            # Live-Suche (Token-Präfix, kuratierte Spalten — ADR 0036).
            # Mehrere text: = UND, ODER-Werte innerhalb eines text: = FTS-OR.
            # raw: sucht ZUSÄTZLICH in den Roh-Blobs (Opt-in, ADR 0038).
            sub = ("i.file_hash IN (SELECT file_hash FROM search_index "
                   "WHERE search_index MATCH ?)")
            columns = FTS_RAW_COLUMNS if p.kind == "raw" else FTS_DEFAULT_COLUMNS
            joined = " OR ".join(fts_match_query([v]) for v, _ in p.values)
            params.append(f"{columns}: ({joined})")
        elif p.kind == "tag":
            match = _value_match("t.name", p.values, params)
            sub = (f"i.file_hash IN (SELECT it.file_hash FROM item_tags it "
                   f"JOIN tags t ON t.id = it.tag_id WHERE {match})")
        elif p.kind == "container":
            marks = ", ".join("?" for _ in p.values)
            sub = f"i.container IN ({marks})"
            params.extend(v for v, _ in p.values)
        elif p.kind == "has":
            subs = []
            for v, _ in p.values:
                if v == "workflow":
                    subs.append("i.file_hash IN (SELECT file_hash FROM raw_metadata "
                                "WHERE LOWER(keyword) = 'workflow' AND value_text IS NOT NULL)")
                elif v == "model":
                    # Effektiv (ADR 0022): auch ein manuell gesetztes Modell zählt —
                    # »-has: model« bleibt damit die ehrliche Aufräumliste.
                    subs.append("(i.file_hash IN (SELECT file_hash FROM interpreted_metadata "
                                "WHERE field = 'model' AND value_text != '') "
                                "OR i.file_hash IN (SELECT file_hash FROM annotations "
                                "WHERE model IS NOT NULL))")
                else:
                    # Feld-Existenz in Schicht 2 (leere Werte zählen nicht) — läuft
                    # über den Covering-Index aus Migration 0009.
                    subs.append("i.file_hash IN (SELECT file_hash FROM interpreted_metadata "
                                "WHERE field = ? AND value_text != '')")
                    params.append(v)
            sub = subs[0] if len(subs) == 1 else f"({' OR '.join(subs)})"
        elif p.kind == "format":
            buckets = " OR ".join(FORMATS[v] for v, _ in p.values)
            sub = f"({_FORMAT_GUARD} AND ({buckets}))"
        elif p.kind == "mp":
            buckets = " OR ".join(MEGAPIXELS[v] for v, _ in p.values)
            sub = f"({_FORMAT_GUARD} AND ({buckets}))"
        elif p.kind == "year":
            ors = []
            for v, _ in p.values:
                if v == "unbekannt":
                    ors.append("i.media_date IS NULL")
                else:
                    ors.append("substr(i.media_date, 1, 4) = ?")
                    params.append(v)
            sub = ors[0] if len(ors) == 1 else f"({' OR '.join(ors)})"
        elif p.kind == "month":
            marks = ", ".join("?" for _ in p.values)
            sub = f"substr(i.media_date, 1, 7) IN ({marks})"
            params.extend(v for v, _ in p.values)
        elif p.kind == "datei":
            # Dateiname der Fundorte: Teilstring (LIKE) oder exakt ("…").
            # Exakt läuft über den Ausdrucks-Index idx_loc_basename
            # (Migration 0016, exakt dieselbe BASENAME-Formel); Teilstring
            # bleibt ein Scan über file_locations — dieselbe Größenordnung
            # wie fundort: (~90 ms bei 275k Fundorten, gemessen §0.6).
            match = _value_match(BASENAME, p.values, params)
            sub = (f"i.file_hash IN (SELECT file_hash FROM file_locations "
                   f"WHERE {match})")
        elif p.kind == "fundort":
            # Library vs. Extern (ADR 0041, I2): ein Item ist „library", wenn
            # MINDESTENS EIN Fundort unter library.root liegt (Dublette
            # drinnen+draußen zählt als Library), „extern" sonst. Der LIKE-
            # Scan über file_locations kostet bei 250k/275k Fundorten ~90 ms
            # (gemessen, §0.6) — ein Index hilft nicht (replace() + ESCAPE
            # schalten SQLites LIKE-Optimierung ab). Ohne konfigurierte Root
            # ist nichts „library" — ehrliche Konstanten statt Fehler.
            prefix = library_like_prefix()
            in_lib = (f"i.file_hash IN (SELECT file_hash FROM file_locations "
                      f"WHERE {NORM_PATH} LIKE ? ESCAPE '\\')")
            subs = []
            for v, _ in p.values:
                if prefix is None:
                    subs.append("1=0" if v == "library" else "1=1")
                else:
                    subs.append(in_lib if v == "library" else f"NOT ({in_lib})")
                    params.append(prefix)
            sub = subs[0] if len(subs) == 1 else f"({' OR '.join(subs)})"
        elif p.kind == "rating":
            if p.value == "0":
                # rating=0 = unbewertet (keine gesetzte Bewertung)
                sub = ("i.file_hash NOT IN (SELECT file_hash FROM annotations "
                       "WHERE rating IS NOT NULL)")
            else:
                sub = (f"i.file_hash IN (SELECT file_hash FROM annotations "
                       f"WHERE rating {p.op} ?)")
                params.append(int(p.value))
        elif p.kind == "metric":
            column = _METRIC_COLUMNS[p.field]
            sub = f"{column} {p.op} ?"
            params.append(float(p.value) if p.field == "fps" else int(float(p.value)))
        else:  # pragma: no cover — Parser erzeugt nur bekannte Arten
            raise ValueError(f"Unbekanntes Prädikat: {p.kind}")
        parts.append(f"NOT ({sub})" if p.negated else sub)
    return " AND ".join(parts), params
