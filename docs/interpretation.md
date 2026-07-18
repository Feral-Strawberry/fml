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
| `tool` | Erzeuger-Werkzeug (`a1111`, `comfyui`) |
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
