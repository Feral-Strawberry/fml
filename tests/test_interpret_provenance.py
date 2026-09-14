"""Tests für den Herkunfts-Parser (Schicht 2, Issue #43 / ADR 0066).

Fixtures sind programmatisch gebaute JUMBF-/CBOR-Bruchstücke (§8): nur die
Klartext-Marker aus der belegten Signaturtabelle
(Konzeptnotiz zu ADR 0066 im Arbeitsrepo, §2) plus die echten
CBOR-Textstring-Köpfe — kein vollständiges Manifest, kein CBOR-Parser.
"""

from __future__ import annotations

from feral.extract.types import RawMetadataItem
from feral.interpret import provenance, registry

UUID_SUFFIX = b"\x00\x11\x00\x10\x80\x00\x00\xaa\x00\x38\x9b\x71"
DST = b"http://cv.iptc.org/newscodes/digitalsourcetype/"


def cbor_text(s: str) -> bytes:
    raw = s.encode("utf-8")
    if len(raw) < 24:
        return bytes([0x60 + len(raw)]) + raw
    if len(raw) < 256:
        return b"\x78" + bytes([len(raw)]) + raw
    return b"\x79" + len(raw).to_bytes(2, "big") + raw


def cbor_map(**pairs: str) -> bytes:
    out = bytes([0xA0 + len(pairs)])
    for k, v in pairs.items():
        out += cbor_text(k) + cbor_text(v)
    return out


def manifest(*parts: bytes) -> bytes:
    """JUMBF-Kopf mit C2PA-UUID, dahinter beliebige Claim-Bruchstücke."""
    return (b"\x00\x00\x01\x00jumb\x00\x00\x00\x2fjumdc2pa" + UUID_SUFFIX
            + b"\x03c2pa\x00" + b"\x00" * 4 + b"".join(parts) + b"\x00" * 4)


def blob_item(data: bytes, source: str = "png:caBX") -> RawMetadataItem:
    return RawMetadataItem(source=source, keyword=None, text=None, data=data, encoding="binary")


def text_item(source: str, keyword: str, text: str) -> RawMetadataItem:
    return RawMetadataItem(source=source, keyword=keyword, text=text, data=None, encoding="utf-8")


def xmp_item(payload: str) -> RawMetadataItem:
    return text_item("png:iTXt", "XML:com.adobe.xmp",
                     '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
                     '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
                     f"{payload}</rdf:RDF></x:xmpmeta>")


def fields_of(result) -> dict[str, list[str]]:
    assert result is not None, "Parser hat sich nicht zuständig gefühlt"
    out: dict[str, list[str]] = {}
    for f in result.fields:
        out.setdefault(f.field, []).append(f.value)
    return out


# -- Google -------------------------------------------------------------------------

def test_gemini_claim_generator_info_and_source_type():
    blob = manifest(
        cbor_text("claim_generator_info") + b"\x81"
        + cbor_map(name="Google C2PA Core Generator Library", version="1.0.0"),
        b"O=Google LLC", cbor_text("digitalSourceType"),
        cbor_text((DST + b"trainedAlgorithmicMedia").decode()),
    )
    items = [blob_item(blob)]
    result = provenance.parse(items)
    f = fields_of(result)
    assert result.parser == "provenance" and result.parser_version == provenance.VERSION
    assert "provenance" in [i.parser for i in registry.interpret_items(items)]

    assert f["tool"] == ["google"]
    assert "model" not in f, "Gemini nennt kein Modell — bleibt manuell"
    assert f["claim_generator"] == ["Google C2PA Core Generator Library 1.0.0"]
    assert f["ai_source_type"] == ["trainedAlgorithmicMedia"]
    assert "software_agent" not in f


def test_xmp_credit_made_with_google_ai_without_c2pa():
    items = [xmp_item('<rdf:Description xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"'
                      ' photoshop:Credit="Made with Google AI"/>')]
    assert fields_of(provenance.parse(items))["tool"] == ["google"]


def test_xmp_credit_edited_with_google_ai_is_google_photos_model():
    blob = manifest(b"Google LLC", DST + b"compositeWithTrainedAlgorithmicMedia")
    items = [blob_item(blob, "jpeg:APP11"),
             xmp_item('<rdf:Description xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/">'
                      "<photoshop:Credit>Edited with Google AI</photoshop:Credit></rdf:Description>")]
    f = fields_of(provenance.parse(items))
    assert f["tool"] == ["google"]
    assert f["model"] == ["Google Fotos"]
    assert f["ai_source_type"] == ["compositeWithTrainedAlgorithmicMedia"]


# -- OpenAI / Microsoft -------------------------------------------------------------

def test_chatgpt_is_openai_with_gpt4o_model():
    blob = manifest(
        cbor_text("claim_generator_info") + b"\x81" + cbor_map(name="ChatGPT"),
        cbor_text("softwareAgent") + cbor_text("GPT-4o"),
        b"CN=Truepic Lens CLI in Sora, O=OpenAI",
    )
    f = fields_of(provenance.parse([blob_item(blob)]))
    assert f["tool"] == ["openai"]
    assert f["model"] == ["GPT-4o"]
    assert f["claim_generator"] == ["ChatGPT"]
    assert f["software_agent"] == ["GPT-4o"]


def test_dall_e_claim_is_openai_with_dall_e_3_model():
    blob = manifest(cbor_text("claim_generator") + cbor_text("DALL-E/3.0 c2pa-rs/0.28.4"))
    f = fields_of(provenance.parse([blob_item(blob, "webp:C2PA")]))
    assert f["tool"] == ["openai"]
    assert f["model"] == ["DALL-E 3"]
    assert f["claim_generator"] == ["DALL-E/3.0 c2pa-rs/0.28.4"]


def test_openai_api_long_claim_generator_string():
    blob = manifest(
        cbor_text("claim_generator") + cbor_text("OpenAI-API c2pa-rs/0.28.4 DALL-E/3.0"),
        cbor_text("softwareAgent") + cbor_text("OpenAI API"),
        b"O=OpenAI OpCo, LLC",
    )
    f = fields_of(provenance.parse([blob_item(blob)]))
    assert f["tool"] == ["openai"]
    assert f["model"] == ["DALL-E 3"]
    assert f["claim_generator"] == ["OpenAI-API c2pa-rs/0.28.4 DALL-E/3.0"]
    assert f["software_agent"] == ["OpenAI API"]


def test_sora_is_openai_with_sora_model():
    blob = manifest(cbor_text("claim_generator_info") + b"\x81" + cbor_map(name="Sora"))
    f = fields_of(provenance.parse([blob_item(blob)]))
    assert f["tool"] == ["openai"] and f["model"] == ["Sora"]


def test_azure_openai_beats_openai_and_microsoft():
    blob = manifest(
        cbor_text("softwareAgent") + cbor_map(name="Azure OpenAI ImageGen"),
        b"OpenAI API", b"O=Microsoft Corporation",
    )
    f = fields_of(provenance.parse([blob_item(blob)]))
    assert f["tool"] == ["azure-openai"]
    assert "model" not in f
    assert f["software_agent"] == ["Azure OpenAI ImageGen"]


def test_issuer_alone_is_no_product_microsoft_signature_stays_c2pa():
    """Aussteller-Regeln sind gestrichen (Befund 2026-09-08: „Microsoft
    Corporation" im Zertifikat wurde „bing") — ohne Produktmarker bleiben nur
    die Rohstrings, die Plattform heißt ehrlich c2pa."""
    blob = manifest(cbor_text("claim_generator") + cbor_text("Microsoft Photos/2026.1 c2pa-rs/0.49.5"),
                    cbor_text("softwareAgent") + cbor_map(name="Microsoft Photos"),
                    b"O=Microsoft Corporation, L=Redmond")
    f = fields_of(provenance.parse([blob_item(blob)]))
    assert f["tool"] == ["c2pa"]
    assert f["claim_generator"] == ["Microsoft Photos/2026.1 c2pa-rs/0.49.5"]
    assert f["software_agent"] == ["Microsoft Photos"]


def test_google_issuer_counts_only_with_ai_source_type():
    pixel_photo = manifest(b"O=Google LLC", DST + b"digitalCapture")
    assert fields_of(provenance.parse([blob_item(pixel_photo)]))["tool"] == ["c2pa"]
    gemini = manifest(b"O=Google LLC", DST + b"trainedAlgorithmicMedia")
    assert fields_of(provenance.parse([blob_item(gemini)]))["tool"] == ["google"]


# -- Adobe --------------------------------------------------------------------------

def test_firefly_underscore_claim_generator():
    blob = manifest(
        cbor_text("claim_generator") + cbor_text("Adobe_Firefly"),
        cbor_text("softwareAgent") + cbor_map(name="Adobe Firefly", version="1.0"),
        b"O=Adobe Inc.", DST + b"trainedAlgorithmicMedia",
    )
    f = fields_of(provenance.parse([blob_item(blob, "jpeg:APP11")]))
    assert f["tool"] == ["adobe"]
    assert f["model"] == ["Adobe Firefly"]
    assert f["claim_generator"] == ["Adobe_Firefly"]
    assert f["software_agent"] == ["Adobe Firefly 1.0"]


def test_photoshop_with_firefly_action_is_adobe_firefly():
    blob = manifest(
        cbor_text("claim_generator")
        + cbor_text("Adobe Photoshop/25.7.0 adobe_c2pa/0.9.0 c2pa-rs/0.31.0"),
        cbor_text("softwareAgent") + cbor_text("Adobe Firefly"),
        DST + b"compositeWithTrainedAlgorithmicMedia",
    )
    f = fields_of(provenance.parse([blob_item(blob)]))
    assert f["tool"] == ["adobe"]
    assert f["model"] == ["Adobe Firefly"]
    assert f["claim_generator"] == ["Adobe Photoshop/25.7.0 adobe_c2pa/0.9.0 c2pa-rs/0.31.0"]
    assert f["software_agent"] == ["Adobe Firefly"]
    assert f["ai_source_type"] == ["compositeWithTrainedAlgorithmicMedia"]


# -- Black Forest Labs / Flux (Belegstufe A: LMArena-Downloads, 2026-09-08) -------

def test_flux_platform_with_raw_product_as_model():
    blob = manifest(cbor_text("claim_generator_info") + b"\x81" + cbor_map(name="Black Forest Labs API"),
                    cbor_text("softwareAgent") + cbor_text("Flux.1"),
                    b"O=Microsoft Corporation")     # so signiert, trotzdem Flux
    f = fields_of(provenance.parse([blob_item(blob)]))
    assert f["tool"] == ["flux"]
    assert f["model"] == ["Flux.1"]
    assert f["claim_generator"] == ["Black Forest Labs API"]


def test_flux_without_product_string_gets_fallback_model():
    blob = manifest(b"Black Forest Labs")
    f = fields_of(provenance.parse([blob_item(blob)]))
    assert f["tool"] == ["flux"] and f["model"] == [provenance._FLUX_FALLBACK_MODEL]
    kontext = manifest(cbor_text("softwareAgent") + cbor_text("FLUX.1 Kontext [pro]"))
    assert fields_of(provenance.parse([blob_item(kontext)]))["model"] == ["FLUX.1 Kontext [pro]"]


# -- Unbekannt / nicht zuständig -----------------------------------------------------

def test_unknown_manifest_yields_c2pa_with_raw_strings():
    blob = manifest(cbor_text("claim_generator") + cbor_text("Fancy Tool/1.0 c2pa-rs/0.40.0"),
                    b'"softwareAgent":"Fancy Engine"')
    f = fields_of(provenance.parse([blob_item(blob)]))
    assert f["tool"] == [provenance.TOOL_UNKNOWN_C2PA]
    assert f["claim_generator"] == ["Fancy Tool/1.0 c2pa-rs/0.40.0"]
    assert f["software_agent"] == ["Fancy Engine"]      # JSON-Form wird auch gelesen


def test_two_blobs_dedupe_and_first_marker_wins():
    a = manifest(cbor_text("claim_generator") + cbor_text("Adobe_Firefly"))
    b = manifest(cbor_text("claim_generator") + cbor_text("Adobe_Firefly"), b"Google LLC")
    f = fields_of(provenance.parse([blob_item(a), blob_item(b)]))
    assert f["tool"] == ["adobe"]
    assert f["claim_generator"] == ["Adobe_Firefly"]


def test_not_responsible_without_c2pa_or_credit():
    items = [
        text_item("png:tEXt", "parameters", "a cat\nSteps: 20, Sampler: Euler"),
        RawMetadataItem(source="png:eXIf", keyword=None, text=None,
                        data=b"MM\x00\x2a" + b"jumb" + b"Google LLC", encoding="binary"),
        xmp_item('<rdf:Description xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"'
                 ' photoshop:Credit="Reuters"/>'),
    ]
    assert provenance.parse(items) is None
    assert provenance.parse([]) is None


def test_end_to_end_png_cabx_through_container_and_registry(tmp_path):
    from feral.extract import container
    from .pngbuild import build_png, chunk

    blob = manifest(cbor_text("claim_generator_info") + b"\x81" + cbor_map(name="ChatGPT"))
    path = tmp_path / "gpt.png"
    path.write_bytes(build_png(chunk(b"caBX", blob)))

    extraction = container.extract(path)
    results = registry.interpret_items(extraction.items)
    by_parser = {r.parser: r for r in results}
    assert fields_of(by_parser["provenance"])["tool"] == ["openai"]


# -- Härtung: präparierte Manifeste dürfen den Parser nicht festhalten -----------------

def test_hostile_blobs_parse_in_linear_time():
    """Vor den Deckeln lief der erste Fall > 5 Minuten (quadratische Dedupe-
    Liste). Jetzt: harte Obergrenzen für Vorkommen und Werte, gebundenes
    JSON-Backtracking — alles zusammen deutlich unter einer Sekunde."""
    import time

    hostile = [
        # 100k Schlüssel-Vorkommen mit je neuem Wert
        manifest(b"".join(cbor_text("claim_generator") + cbor_text(f"g{i}") for i in range(100_000))),
        # 100k verschiedene DST-Suffixe
        manifest(b"".join(b"digitalsourcetype/" + bytes(97 + int(c) for c in f"{i:06d}")
                          for i in range(100_000))),
        # 20k offene JSON-softwareAgent-Objekte ohne schließende Klammer
        manifest(b'"softwareAgent":{' * 20_000 + b"x" * 1_000_000),
        # 16 MB Rauschen mit einem Marker am Ende
        manifest(b"\x37" * 16_000_000 + b"ChatGPT"),
    ]
    t0 = time.perf_counter()
    results = [provenance.parse([blob_item(b)]) for b in hostile]
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, f"Parser brauchte {elapsed:.1f}s für präparierte Blobs"

    f = fields_of(results[0])
    assert f["tool"] == ["c2pa"] and len(f["claim_generator"]) == provenance._MAX_VALUES
    assert len(fields_of(results[1])["ai_source_type"]) == provenance._MAX_VALUES
    assert fields_of(results[3])["tool"] == ["openai"]


# -- Workflow hat Vorrang -------------------------------------------------------------

def test_native_workflow_beats_manifest_flux_in_comfyui_edited_in_windows():
    """Feral Strawberrys Flux.1-Bild: in ComfyUI erzeugt (Workflow in der Datei),
    danach mit C2PA signiert (Microsoft). Das Manifest ist Nachbearbeitung —
    keine Plattform, kein Modell aus dem Manifest, Rohfelder bleiben."""
    blob = manifest(cbor_text("claim_generator") + cbor_text("Microsoft Photos/2026.1"),
                    cbor_text("softwareAgent") + cbor_text("Microsoft Photos"),
                    DST + b"compositeWithTrainedAlgorithmicMedia")
    items = [
        text_item("png:tEXt", "workflow", '{"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux1-dev.safetensors"}}}'),
        blob_item(blob),
    ]
    f = fields_of(provenance.parse(items))
    assert "tool" not in f and "model" not in f
    assert f["claim_generator"] == ["Microsoft Photos/2026.1"]
    assert f["ai_source_type"] == ["compositeWithTrainedAlgorithmicMedia"]


def test_native_a1111_parameters_beats_google_credit():
    items = [
        text_item("png:tEXt", "parameters", "a cat\nSteps: 20, Sampler: Euler"),
        xmp_item('<rdf:Description xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"'
                 ' photoshop:Credit="Edited with Google AI"/>'),
    ]
    assert provenance.parse(items) is None      # nichts Rohes, keine Plattform → nicht zuständig
