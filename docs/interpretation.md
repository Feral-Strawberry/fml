# Metadaten-Interpretation (Schicht 2)

> Was tut sie? Sie deutet die roh gespeicherten Metadaten ([Schicht 1](extraction.md))
> und macht daraus **strukturierte, durchsuchbare Felder**: Prompt, Negativ-Prompt,
> Modell, Seed, Sampler, Steps, CFG usw. Was kein Parser versteht, bleibt trotzdem
> vollständig erhalten — „nicht erkannt" heißt nur „noch nicht strukturiert".

**Stand:** Parser für **A1111/Forge/SD.Next** (der `parameters`-Infotext),
**ComfyUI** (der eingebettete Prompt-Graph, auch in WEBM/MP4-Videos) und **XMP**
(Standard-Metadaten: Midjourney-Prompts, „Made with Google AI"-Kennzeichnungen,
Lightroom-Bewertungen, Creator-Tool). Weitere (NovelAI, InvokeAI, …) folgen —
jeder neue Parser wirkt **rückwirkend auf den gesamten Bestand**, ohne dass
Dateien neu gescannt werden müssen.

## Läuft automatisch beim Scan mit

Beim Scannen ([Ordner scannen](scanning.md), [Web-GUI](gui.md)) wird jede Datei
direkt nach der Roh-Extraktion interpretiert. Im Scan-Report bzw. in der
Aktivitätsanzeige steht die Zahl unter **„interpretiert"**.

## Rückwirkend über den Bestand laufen lassen

Wenn ein neuer oder verbesserter Parser dazukommt:

```bash
python -m feral.interpret --db ./feral.sqlite
```

> **Windows:** `python` muss das Projekt-Python sein, sonst kommt
> „no module named feral" — in der Projektmappe stattdessen
> `.venv\Scripts\python.exe -m feral.interpret --db .\feral.sqlite`
> aufrufen (die venv legt `start.bat` beim ersten Start an).

Das liest die bereits gespeicherten Roh-Metadaten aus der Datenbank, lässt alle
Parser darüber laufen und ersetzt die strukturierten Felder. Kein Datei-Zugriff,
darum auch für 70.000 Items schnell. Der Lauf ist beliebig wiederholbar.

## Suchen über die Felder

In der [Web-GUI](gui.md) versteht die Suche zwei Formen:

- `flux` — freie Suche über alle Felder **und** die Roh-Metadaten.
- `model: flux`, `seed: 777`, `prompt: erdbeere` — gezielte Suche in einem Feld.

## Die Feldnamen

| Feld | Bedeutung |
|------|-----------|
| `tool` | Erzeuger-**Plattform**: `comfyui`, `a1111`, `midjourney`, `google`, `openai`, `azure-openai`, `adobe`, `flux`, `topaz`, `suno`; `c2pa` = Manifest erkannt, nicht zugeordnet. Das Produkt darunter (Gemini, GPT-4o, Topaz Gigapixel, Midjourney V7) steht in `model` (siehe [Generator-Erkennung](#generator-erkennung-gemini-chatgpt-firefly--co-c2paxmp)) |
| `prompt` / `negative_prompt` | die Prompts |
| `model` / `model_hash` | Checkpoint-Name / -Hash |
| `seed`, `sampler`, `scheduler`, `steps`, `cfg_scale`, `denoise`, `size` | Sampling-Parameter |
| `lora`, `vae` | geladene LoRAs (normalisierter Name, ohne Pfad/Endung) / VAE |
| `description` | Bildbeschreibung aus XMP (wenn kein Prompt erkennbar) |
| `credit` | Herkunftsangabe, z. B. `Made with Google AI` (Gemini/Imagen) |
| `ai_source_type` | IPTC-AI-Kennzeichnung, z. B. `trainedAlgorithmicMedia` |
| `creator_tool` | erzeugendes/bearbeitendes Programm (z. B. Photoshop) |
| `rating` | in der Datei eingebettete Bewertung (z. B. aus Lightroom) |
| `job_id` | Job-ID des Erzeugers (z. B. Midjourney) |
| `feature` | genutztes Zusatzwerkzeug / Workflow-Eigenschaft (`adetailer`, `highres_fix`, `controlnet`, `refiner`, `prompt_builder`, `bbox`) |
| `input_image` | Dateiname des Eingangsbilds/-videos (vorhanden = img2img/i2v, nicht reines t2i) |
| `topaz_version`, `topaz_model`, `upscale_factor`, `source_size`, `topaz_settings` | Topaz-Nachbearbeitung (siehe unten); `model` trägt dann `Topaz Photo AI` / `Topaz Gigapixel` / `Topaz Video AI` |
| `claim_generator`, `software_agent` | exakte Rohstrings aus dem C2PA-Manifest (z. B. `DALL-E/3.0 c2pa-rs/0.28.4`, `GPT-4o`, `Adobe Firefly 1.0`) - damit lassen sich Engines unterscheiden, sobald die Metadaten es hergeben |
| `video_codec`, `video_profile`, `pixel_format` | Codec, Profil und Pixelformat des ersten Video-Streams, wie ffprobe sie nennt (`prores` / `HQ` / `yuv422p10le`; `hevc` / `Main 10`; `h264` / `High` / `yuv420p`); Kurzform im Suchfeld: `codec: prores` (siehe [unten](#video-codec-und-abspielbarkeit)) |
| `lyrics`, `title` | Songtext und Titel-Tag einer Musikdatei (der Songtext ist in der Volltextsuche) |
| `song_id`, `parent_id`, `relation` | Song-ID beim Dienst (Suno), Eltern-Song und Beziehung (`extend`, `cover`, `remaster`, `edit` …), soweit die Datei sie nennt |
| `bpm`, `key` | Tempo und Tonart |
| `audio_codec`, `sample_rate`, `channels`, `bit_depth` | Technik der ersten Tonspur, wie ffprobe sie nennt (`flac` / `48000` / `2` / `24`) |

Ein Feld kann mehrfach vorkommen (z. B. mehrere Prompt-Kandidaten in einem
ComfyUI-Graphen mit mehreren Text-Knoten).

## Verwendung aus Python

```python
from feral.interpret import interpret_items

results = interpret_items(extraction.items)   # Roh-Einträge aus Schicht 1
for interpretation in results:
    print(interpretation.parser, interpretation.parser_version)
    for f in interpretation.fields:
        print(" ", f.field, "=", f.value)
```

## ComfyUI: Generator-/API-Knoten und moderne Text-Encoder (Parser v4)

Neben klassischen Graphen (KSampler + CLIPTextEncode) versteht der Parser
auch **Generator-/API-Knoten**, die den Prompt direkt tragen (z. B. Krea 2
Turbo, Ideogram 4 — als String oder als Link auf einen Quell-/Builder-Knoten
wie den Ideogram-4-Prompt-Builder von KJNodes) sowie **eigene Text-Encoder**
moderner Templates (Klassenname enthält „TextEncode", z. B. Qwen-Encoder des
Krea-2-Turbo-Subgraphen). Bereits gescannte Bestände: einmal **Admin →
Wartung → „Neu interpretieren"** — läuft rückwirkend über die gespeicherten
Roh-Blobs, kein neuer Datei-Scan nötig.

**String-Ketten** (v9): Der Text hängt oft nicht direkt am Encoder, sondern
läuft über Ketten aus String-Halte-, Verkettungs- und Switch-Knoten
(`PrimitiveStringMultiline`, `StringConcatenate` mit `string_a`/`string_b`,
`TextBox1`, rgthree `Any Switch`). Der Parser folgt diesen Ketten und setzt
Verkettungen zusammen (Szene + Stil-Suffix, `delimiter` wird respektiert);
auch Encoder, die über keinen Sampler-Pfad erreichbar sind, werden so
aufgelöst. Graphen, die unter fremdem Keyword eingebettet sind (z. B. im
MP4-`comment`-Tag), werden an ihrer Struktur erkannt.

**Prompt-Enhancer-Templates** (v10, ADR 0050 — Ernie Image/Turbo, Krea 2):
Diese Templates schalten per Boolean-Switch zwischen Roh-Prompt und einem
eingebauten LLM-Enhancer (`TextGenerate`) um. Der Parser löst den Switch
auf und führt den **Roh-User-Prompt** — der „enhancte" Text entsteht erst
zur Laufzeit und steht nicht in der Datei; die Systemprompt-Schablone des
Enhancers erscheint nicht mehr als Prompt. War der Enhancer **aktiv**,
markiert `feature: prompt_enhancer` das Medium (im Panel unter FEATURES,
suchbar) — der angezeigte Prompt ist dann der Text VOR der Erweiterung.
Das leere Negativ dieser Workflows (`ConditioningZeroOut`) wird nicht mehr
fälschlich dem positiven Text zugeordnet. Bestand aktualisieren: einmal
Admin → Wartung → „Neu interpretieren".

**Prompt-Builder-Workflows** (ADR 0028, z. B. Ideogram 4 Prompt Builder KJ,
auch in Krea-2-Setups): Der finale Prompt entsteht dort erst zur Laufzeit
(JSON aus gezeichneten Regionen, oft mit KI-Anreicherung) und steckt nicht
lesbar in der Datei. Der Parser führt stattdessen die **allgemeine
Szenenbeschreibung** des Builders als `prompt` und markiert das Medium mit
`feature: prompt_builder` (bzw. zusätzlich `feature: bbox`, wenn
Regionen-Definitionen im Spiel sind) — im Panel unter FEATURES sichtbar,
suchbar per `feature: prompt_builder`.

**Sampling-Einstellungen aus Subgraphen und Split-Knoten** (v11, ADR 0068,
Issue #29): Steps, Sampler, CFG, Scheduler und Seed werden auch dort
gefunden, wo kein klassischer `KSampler` steht — in geflatteten Subgraphen
(Knoten-IDs wie `30:3`, Werte als Link vom Subgraph-Rand), in Split-
Bauformen moderner Templates (`BasicScheduler`/`LTXVScheduler` für Steps
und Scheduler, `KSamplerSelect` für den Sampler, `CFGGuider` für CFG) und
in LTX-2-Workflows mit `ManualSigmas` (neun Sigma-Werte = acht Schritte);
Sampler-Knoten ohne Namensfeld (`SamplerEulerAncestral`) liefern den Namen
aus der Klasse. Bei mehreren Durchgängen (Hires-Fix, Upscale-Pass) steht
der **Hauptpass zuerst** (voller Denoise vor Teil-Denoise; eine Sigma-
Liste, die unter 1,0 beginnt, ist ein Teilpass), die übrigen
Werte bleiben als weitere Zeilen erhalten; das Detail-Panel zeigt Steps als
ersten Chip. Fehlt der `prompt`-Blob, liest der Rückfall die Sampler-
Widgets aus dem UI-Graphen — Subgraphen und promotete Werte am Subgraph-
Knoten inklusive. Cloud-API-Knoten (MiniMax Hailuo, LTX 2.5 API) tragen
keine Steps; dort bleibt das Feld ehrlich leer. Bestand: einmal **Admin →
Wartung → „Neu interpretieren"**.

## LoRA-Erkennung und benutztes Modell (ADR 0026/0027)

**LoRAs** werden werkzeugübergreifend als **normalisierter Name** abgelegt
(Pfad und Endung weg: `subdir/detail.safetensors` → `detail`), damit ein
LoRA aus ComfyUI und aus A1111 auf denselben Wert fällt und gemeinsam gefunden
wird. Gewichte werden bewusst nicht gespeichert.

- **ComfyUI** erkennt LoRAs **generisch** (ADR 0027): klassische Loader und
  Stacker (`lora_name`, `lora_name_1` …, Ein/Aus-Schalter und `lora_count`
  werden respektiert), Dict-Slots (rgthree **Power Lora Loader**, pysssss)
  sowie unbekannte Knoten, bei denen Klassen- oder Input-Name „lora" enthält
  und der Wert eine Modelldatei benennt. Fehlt der prompt-Blob, liest der
  Parser den **workflow-Blob** (UI-Graph) — dort werden stummgeschaltete/
  umgangene Knoten (Bypass/Mute) übersprungen.
- **ComfyUI-Modell**: Es wird das **tatsächlich benutzte** Checkpoint geführt —
  der Parser verfolgt den Modell-Eingang des Samplers durch LoRA-/Model-Knoten
  bis zum Loader zurück. Ein reiner Upscale-/Nebenzweig-Checkpoint taucht damit
  nicht mehr fälschlich als Modell auf.
- **A1111** liest LoRAs aus den **Inline-Tags** im Prompt (`<lora:name:gewicht>`,
  `<lyco:…>`) und aus der `Lora hashes:`-Zeile. Der Prompttext selbst bleibt
  unverändert.

Für den Bestand: **Admin → Wartung → „Neu interpretieren"** (ADR 0011) — zieht
die neuen LoRA-/Modell-Werte rückwirkend über die Roh-Blobs.

## Eingangsbild (img2img/i2v) und A1111-Features (ADR 0027)

- **`input_image`** (ComfyUI): Für jeden Bild-/Video-Lade-Knoten (`LoadImage`,
  `VHS_LoadVideo`, …) wird der Dateiname abgelegt. Ist das Feld vorhanden, war
  es kein reines text-to-image. Suche: `has: input_image` bzw.
  `-has: input_image` (reine t2i-Bilder).
- **`feature`** (A1111): zeigt genutzte Zusatzwerkzeuge — `adetailer`,
  `highres_fix`, `controlnet`, `refiner` (aus den Schlüsseln der
  Einstellungszeile). Suche: `feature: controlnet`.
- **`feature`** (ComfyUI, ADR 0028): `prompt_builder` und `bbox` markieren
  Builder-Workflows, deren angezeigter Prompt nur die Szenenbeschreibung ist
  (siehe oben).

## Topaz: Nachbearbeitung zählt wie ein Modell (ADR 0066)

Mit **Topaz Photo AI, Gigapixel oder Video AI** bearbeitete Dateien
erkennt der Parser `topaz` an den Spuren, die die Programme hinterlassen:

- **Photo AI:** `Software` (EXIF) bzw. `CreatorTool` (XMP), z. B.
  `Topaz Photo AI 3.2.2 (Windows)`.
- **Gigapixel:** die Einstellungszeile in der Bildbeschreibung, z. B.
  `Upscaled with Gigapixel v1.0.7. 1200x593 => 2400x1186 (2x) Model: High
  Compression, denoise: 0.26, sharpen: 0.41.` (Gigapixel schreibt sie nur,
  wenn „Embed image settings" in den Einstellungen an ist - Standard an).
- **Video AI:** das Container-Tag `videoai`, z. B. `Enhanced using prob-3
  with recover details at 43 … Changed resolution to 1266x960`.

Sie erscheinen in der Sidebar **unter „Nach Modell"** als `Topaz Photo AI`,
`Topaz Gigapixel` bzw. `Topaz Video AI` und sind mit `model: Topaz Gigapixel`
filterbar - so, wie man sie vorher von Hand als manuelles Modell zugeordnet
hat. Ein manuell gesetztes Modell hat weiter Vorrang. Behält die Datei ihre
ursprünglichen Generator-Daten (A1111/ComfyUI), steht sie unter beiden
Modellen: erzeugt mit dem einen, hochskaliert mit Topaz.

Die Einzelheiten stehen daneben im Panel: `topaz_version`, `topaz_model`
(z. B. `High Compression`, `prob-3`; bei Video-Ketten mehrere),
`upscale_factor` (`2x`), `source_size` (Größe vor der Bearbeitung, `size` ist
die Zielgröße) und `topaz_settings` (die komplette Zeile, unverändert).
Suchbar wie jedes Feld: `topaz_model: prob-3`, `has: upscale_factor`.

Die Erkennung beruht auf Community-Belegen (Topaz dokumentiert seine
Metadaten nicht). Fehlt ein Fall, hilft eine Meldung mit der Ausgabe von
`exiftool -a -G1 datei` - der Parser läuft dann rückwirkend über den Bestand
(`python -m feral.interpret`), ein Neu-Scan ist nicht nötig.

## Video-Codec und Abspielbarkeit

Der Parser `video` liest aus den Stream-Eckwerten des ffprobe-Extraktors
([extraction.md](extraction.md#was-bei-video-gelesen-wird-über-ffprobe)) den
**ersten Video-Stream** (nicht zwingend Stream 0 — in manchen MOV-Dateien
liegt der Ton vorn) und legt `video_codec`, `video_profile` und
`pixel_format` ab. Damit:

- **Suche:** `codec: prores` (Alias für `video_codec: prores`), `codec: hevc`,
  `pixel_format: yuv420p10le` — alle Betroffenen auf einen Schlag, zum
  Beispiel als Smart Folder.
- **Ehrlicher Player:** Lupe, Einzelbildansicht, Panel und Ranking fragen den
  Browser VOR dem Laden (`canPlayType`), ob er den Codec dekodiert. Wenn
  nicht, erscheint der Poster-Frame mit dem Hinweis „Dieser Browser kann
  ProRes (HQ, 10-bit) nicht abspielen …" statt eines schwarzen Players, der
  nur Ton bringt — und es wird gar kein Stream angefordert. Scheitert ein
  Video trotz Zusage erst beim Abspielen, nennt der Hinweis Codec und
  Fehlercode.
- **Scan-Problem beim Aufnehmen:** Beim Katalogisieren, Import und im
  Watchordner bekommen Videos mit Codecs, die kein gängiger Browser spielt
  (ProRes, DNxHD, Motion JPEG, 10-bit- oder 4:2:2-H.264), ein Problem der
  Art `playback` unter Admin → Probleme; HEVC (H.265) wird als „nur in
  manchen Browsern" gemeldet (Chrome/Safari mit Hardware-Decoder, Firefox je
  nach System). Das Problem quittiert sich selbst, sobald ein Re-Scan die
  Datei in einem abspielbaren Codec vorfindet.

Kein Browser außer Safari dekodiert ProRes; die Tonspur (AAC/PCM) läuft
trotzdem — deshalb „nur Ton ohne Bild". Bestand vor dieser Erweiterung:
einmal Re-Scan (Admin → Wartung), dann `python -m feral.interpret`; Überblick
vorab liefert das [Diagnose-Kommando](scanning.md#diagnose-video-codecs-im-bestand).

## Generator-Erkennung: Gemini, ChatGPT, Firefly & Co. (C2PA/XMP)

Die Sidebar-Gruppe **„Generator"** zeigt die **Plattform**, auf der eine Datei
entstanden ist: ComfyUI, A1111 / Forge, Midjourney, Google, OpenAI, Adobe,
Topaz. Darunter, in **„Nach Modell"**, steht das jeweilige Produkt oder
Modell: `flux1-dev` genauso wie `Midjourney V7`, `GPT-4o` oder
`Topaz Gigapixel`. Beides sind Feld-Werte aus Schicht 2 (`tool` und `model`).
Ein Klick auf eine Plattform lässt die Modell-Liste im Kontext zählen, die
passenden Modelle stehen dann oben.

Bilder aus **Gemini, ChatGPT, Firefly, Photoshop (Generative Fill), Azure
OpenAI oder Sora** tragen keinen Prompt, aber meist **Content Credentials**
(C2PA-Manifest, seit dem Scan als roher Baustein gesichert - siehe
[Extraktion](extraction.md)). Der Parser `provenance` liest daraus Plattform
und, wo das Manifest es hergibt, das Modell:

| Plattform (`tool`) | Woran erkannt | Modell (`model`), wenn belegt |
|---|---|---|
| `google` | Googles Generator-Bibliothek im Manifest (`Google C2PA Core Generator Library`), Aussteller `Google LLC` zusammen mit dem KI-Kennzeichen, oder XMP-Credit `Made with Google AI` / `Made by Google AI` | keins - Google nennt das Modell nicht (Imagen, Nano Banana, … bleiben manuell); XMP-Credit `Edited with Google AI` → `Google Fotos` |
| `openai` | `ChatGPT`, `OpenAI API`, `DALL-E`, `Sora` im Manifest | `GPT-4o` (GPT Image 1), `DALL-E 3`, `Sora` |
| `azure-openai` | `Azure OpenAI DALL-E` / `Azure OpenAI ImageGen` | keins |
| `adobe` | `Adobe_Firefly`, `Adobe Photoshop/…`, `Adobe Firefly` im Manifest | `Adobe Firefly` (auch bei Generative Fill in Photoshop) |
| `flux` | `Black Forest Labs`, `Flux.1` im Manifest (z. B. LMArena-Downloads) | der Produkt-Rohstring, z. B. `Flux.1`, `FLUX.1 Kontext [pro]` |
| `suno` | Sunos eigene Angaben im Manifest (`Suno, Inc.`); Songs, siehe [Audio](audio.md#was-fml-aus-musik-liest) | `Suno v4.5`, `Suno v5` … (Parser `suno`, aus dem Modell-Codenamen) |
| `c2pa` | Manifest vorhanden, aber kein bekannter Erzeuger | keins - die Rohstrings stehen daneben |

Dazu aus anderen Parsern: `midjourney` (Parser `xmp`, Web-Downloads; das Modell
kommt aus den Prompt-Parametern `--v 7` → `Midjourney V7`, `--niji 6` →
`Niji 6`; fehlt der Parameter, bleibt das Modell manuell) und `topaz`
(Parser `topaz`; Modelle `Topaz Photo AI`, `Topaz Gigapixel`,
`Topaz Video AI`).

**Der Workflow hat Vorrang.** Nennt eine Datei ihren Erzeuger selbst (A1111-
Parameter, ComfyUI-Workflow), dann ist ein zusätzliches Content-Credentials-
Manifest eine Nachbearbeitung - Windows Fotos, Paint, Photoshop und andere
schreiben es beim Speichern. Solche Dateien bleiben unter ComfyUI bzw. A1111;
das Manifest liefert nur die Rohstrings. Ein in ComfyUI erzeugtes Flux-Bild
wird also nicht zur Microsoft- oder Adobe-Datei, nur weil es dort einmal
geöffnet war.

Per Suche geht `tool: google` oder gleichbedeutend `generator: google`,
für Modelle wie immer `model: "GPT-4o"`. Im Panel stehen zusätzlich die
Rohstrings `claim_generator` und `software_agent` (exakt, mit Version) sowie
`ai_source_type` (`trainedAlgorithmicMedia` = erzeugt,
`compositeWithTrainedAlgorithmicMedia` = KI-bearbeitet).

**Ehrlichkeit:** Content Credentials überleben Upload und Weitergabe oft
nicht - Messenger, viele Webseiten und Bildbearbeitungen entfernen sie. Ohne
Manifest kann fml die Herkunft nicht erkennen; das Bild landet dann unter
„(unbekanntes Modell)" ohne Generator. Für Stability,
Grok, Ideogram und Leonardo gibt es keine belegten Kennzeichen - fml rät
nicht. Die Regeln beruhen auf Recherche, nicht auf Samples aus dem eigenen
Bestand: falsche oder fehlende Zuordnungen bitte melden (mit der Ausgabe von
`exiftool -a -G1 datei` oder `c2patool datei`), sie werden rückwirkend
korrigiert (`python -m feral.interpret`).

**Bestand nachziehen:** Dateien, die vor dieser Version gescannt wurden,
haben ihr Manifest noch nicht als Roh-Baustein - einmal **Admin → Re-Scan
aller Fundorte**, danach läuft die Interpretation automatisch mit. Midjourney-
und Topaz-Modelle brauchen keinen Re-Scan, dort reicht
`python -m feral.interpret`.

## Abdeckung prüfen: LoRA- und Prompt-Report

Wenn LoRAs oder Prompts im Bestand fehlen, zeigen die Diagnosen, was der
Parser noch nicht versteht (beide lesen nur, schreiben nichts):

```bash
python -m feral.interpret --db ./feral.sqlite --lora-report
python -m feral.interpret --db ./feral.sqlite --prompt-report
```

Der **Prompt-Report** nimmt sich alle ComfyUI-verdächtigen Items ohne
erkannten Prompt vor und sortiert sie nach Ursache:

- `nur-workflow` — die Datei trägt nur den UI-Graphen, keinen prompt-Blob
  (der Saver hat den API-Graphen nicht mitgeschrieben)
- `json-kaputt` — der Blob ist kein parsebares JSON
- `text-unerkannt` — Graph lesbar, aber der Text hängt an Knoten/Inputs,
  die der Parser nicht kennt (werden mit Beispieltext gelistet)
- `fremdes-keyword` — Graph-JSON steckt unter einem unerwarteten Keyword
  (z. B. in einem EXIF-Feld statt im PNG-Chunk)

Die Ausgabe (Kategorien, Node-Typen, Beispiel-Hashes) bitte an die
Entwicklung geben — jeder gemeldete Typ wird ein Testfall für die nächste
Parser-Version.
