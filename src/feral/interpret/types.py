"""Wertobjekte der Schicht-2-Interpretation (ADR 0004/0011).

Schicht 2 zieht aus den verlustfrei gespeicherten Roh-Blobs (Schicht 1)
**strukturierte, durchsuchbare Felder**. Sie darf unvollständig sein: Nicht
erkannt heißt "roh vorhanden, noch nicht strukturiert" — kein Fehler, kein
Datenverlust. Die Objekte hier sind rein (keine DB, keine Seiteneffekte).

Kanonisches Feldvokabular (Parser bilden Tool-Begriffe hierauf ab, damit die
Suche werkzeugübergreifend funktioniert):

    tool             Erzeuger-PLATTFORM (ADR 0066 + Nachtrag 2026-09-08):
                     'a1111', 'comfyui', 'midjourney', 'google', 'openai',
                     'azure-openai', 'adobe', 'flux', 'topaz'; 'c2pa' = Manifest
                     erkannt, nicht zugeordnet. Das Produkt darunter (Gemini,
                     GPT-4o, Topaz Gigapixel, Midjourney V7) steht in `model`.
    prompt           positiver Prompt
    negative_prompt  negativer Prompt
    model            Modell-/Checkpoint-Name
    model_hash       Modell-Hash (falls angegeben)
    seed             Seed
    sampler          Sampler-Name
    scheduler        Scheduler / Schedule type
    steps            Sampling-Schritte
    cfg_scale        CFG / Guidance
    denoise          Denoising-Stärke
    size             Zielgröße "BxH"
    lora             LoRA-Name (mehrfach möglich)
    vae              VAE-Name
    description      Bildbeschreibung (z. B. XMP dc:description)
    credit           Herkunftsangabe (z. B. "Made with Google AI")
    ai_source_type   IPTC-AI-Kennzeichnung (z. B. 'trainedAlgorithmicMedia')
    creator_tool     erzeugendes/bearbeitendes Programm (XMP CreatorTool)
    rating           in der Datei eingebettete Bewertung (z. B. aus Lightroom)
    job_id           Job-/Task-ID des Erzeugers (z. B. Midjourney)
    feature          genutztes Zusatzwerkzeug: 'adetailer', 'highres_fix',
                     'controlnet', 'refiner' (mehrfach möglich)
    input_image      Dateiname eines Eingangsbilds/-videos (img2img/i2v;
                     mehrfach möglich — Vorhandensein heißt: kein reines
                     text-to-image)
    topaz_version    Programmversion eines Topaz-Werkzeugs (ADR 0066;
                     `model` trägt dann „Topaz Photo AI" / „Topaz Gigapixel"
                     / „Topaz Video AI")
    topaz_model      Topaz-Modellname/-Kürzel ('High Compression', 'prob-3';
                     mehrfach möglich)
    upscale_factor   Vergrößerungsfaktor der Nachbearbeitung ('2x')
    source_size      Größe vor der Nachbearbeitung "BxH"
    topaz_settings   vollständige Einstellungszeile des Topaz-Werkzeugs, roh
    claim_generator  exakter Rohstring des C2PA-Claim-Erzeugers
                     ('DALL-E/3.0 c2pa-rs/0.28.4', 'Adobe Photoshop/25.7.0 …';
                     mehrfach möglich)
    software_agent   exakter Rohstring der C2PA-Aktion ('GPT-4o',
                     'Adobe Firefly 1.0'; mehrfach möglich)
    video_codec      Codec des ersten Video-Streams, wie ffprobe ihn nennt
                     ('prores', 'hevc', 'h264', 'vp9', 'av1'; Issue #71/ADR 0070)
    video_profile    Codec-Profil ('HQ', 'Main 10', 'High 10')
    pixel_format     Pixelformat des Video-Streams ('yuv420p', 'yuv422p10le')

Ein Feld darf mehrfach vorkommen (z. B. mehrere `prompt`-Kandidaten in einem
ComfyUI-Graphen); die Reihenfolge bleibt erhalten.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class InterpretedField:
    """Ein einzelnes strukturiertes Feld: kanonischer Name + Wert als Text."""

    field: str
    value: str


@dataclass(frozen=True)
class Interpretation:
    """Das Ergebnis EINES Parsers für EINE Datei.

    Felder:
        parser:         Registry-Name des Parsers (z. B. ``"a1111"``).
        parser_version: Version des Parsers. Wird mitgespeichert, damit
                        erkennbar bleibt, welcher Stand einen Eintrag erzeugt
                        hat — und ein verbesserter Parser rückwirkend neu
                        laufen kann (``python -m feral.interpret``).
        fields:         Die extrahierten Felder in Fundreihenfolge.
    """

    parser: str
    parser_version: int
    fields: list[InterpretedField] = field(default_factory=list)
