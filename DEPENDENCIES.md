# DEPENDENCIES.md

> Jede externe Abhängigkeit wird hier dokumentiert: **was** (Paket/Version),
> **wo** (welche Module nutzen es), **warum** (weshalb Eigenbau unverhältnismäßig
> wäre). Projektregel: Standardbibliothek bevorzugen. Tooling ist **pip**,
> Versionen werden **gepinnt**.

## Laufzeit-Abhängigkeiten

### Kern
Der Kern (Scanner, PNG-Container-Extraktor, Schicht-2-Parser, Hashing, DB) läuft
in **reiner Standardbibliothek** (`hashlib`, `zlib`, `struct`, `json`, `sqlite3`,
`os`, `threading`) — mit einer Ausnahme für Bild-Container:

| Paket | Version | Wo | Warum kein Eigenbau |
|-------|---------|----|--------------------|
| **Pillow** | `==12.3.0` | `src/feral/extract/image_pillow.py` — Bild-Container außer PNG (JPEG, WEBP, TIFF, GIF, BMP); `src/feral/thumbs.py` — Bild-Thumbnails | *Die* Python-Bildbibliothek seit 20+ Jahren, in jedem AI-Stack vorhanden, millionenfach geprüft (Fundament-Lib, kein Nischenpaket). Dutzende Container-Formate selbst zu parsen wäre unverhältnismäßig und fehleranfällig. Extraktion nutzt Pillow nur als **Container-Öffner**; Thumbnailing war im Steckbrief §0.1 ausdrücklich als Pillow-Fall vorgesehen. (ADR 0008/0013) |

| System-Programm | Wo | Warum |
|-----------------|----|-------|
| **ffprobe/ffmpeg** | `src/feral/extract/video_ffprobe.py` — Video-Container-Tags (WEBM/MKV, MP4/MOV); `src/feral/thumbs.py` — Video-Poster-Frames | Der 20+ Jahre alte De-facto-Standard für Mediencontainer; `ffprobe` gibt Container-Tags als JSON aus, `ffmpeg` zieht den Poster-Frame. Kein pip-Paket, via `subprocess`. **Optional:** ohne ffmpeg werden Videos katalogisiert (ohne Metadaten/Thumbnail), ein späterer Scan bzw. Ansehen holt beides nach. Installation: macOS `brew install ffmpeg`, Debian/Ubuntu `apt install ffmpeg`, Windows `winget install ffmpeg`. (ADR 0008/0013) |

### Web-Oberfläche (ADR 0001)

| Paket | Version | Wo | Warum kein Eigenbau |
|-------|---------|----|--------------------|
| **fastapi** | `==0.136.3` | `src/feral/web/` — Backend/Routen der lokalen GUI | Im Workshop als Stack festgelegt (ADR 0001). Ein eigenes HTTP-/ASGI-Framework mit Validierung wäre absurd viel Eigencode. Etabliert, breit geprüft. |
| **uvicorn** | `==0.49.0` | `src/feral/web/` — ASGI-Server, der die App ausführt | Standard-ASGI-Server für FastAPI. Plain installiert (ohne `[standard]`-Extras), um die transitive Abhängigkeitsfläche klein zu halten. |

> Transitive Abhängigkeiten von FastAPI/uvicorn (starlette, pydantic, anyio,
> sniffio, click, h11, typing-extensions, idna) sind die Standard-Begleiter dieses
> Stacks — etabliert und breit geprüft. Das Frontend selbst ist **abhängigkeitsfrei**
> (eine HTML-Seite mit Vanilla-JS, kein npm).

## Entwicklungs-Abhängigkeiten

| Paket | Version | Wo | Warum |
|-------|---------|----|-------|
| **pytest** | `~=8.0` (exakt pinnen) | `tests/` | De-facto-Standard für Python-Tests. Eigenbau eines Testrunners wäre absurd. Reine Dev-Dependency, nicht im Laufzeit-Pfad. |

## Bewusst NICHT genutzt

- **SQLAlchemy / ORM** — stdlib `sqlite3` reicht für eine Einzeldatei-DB mit einem
  Schreibprozess; ein ORM bringt hier keinen Vorteil. (ADR 0007/0009)
- **sd-prompt-reader / sd-parsers als Laufzeit-Dep** — gute Referenz-Projekte und
  Inspiration für die Schicht-2-Parser, aber Nischenpakete. Wir bauen die
  Parser selbst (aus Tool-Doku, ADR 0004) und behalten Kontrolle über das
  Roh-Format.
- **watchdog (Hotfolder)** — wird bei Stufe 4 neu bewertet; stdlib-Polling könnte
  reichen. Entscheidung dann per ADR.
