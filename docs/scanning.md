# Ordner scannen

> Was tut sie? Sie geht rekursiv durch einen Ordner und nimmt jede Mediendatei in
> die Bibliothek auf: erkennen → hashen → [Metadaten extrahieren](extraction.md) →
> [interpretieren](interpretation.md) → [speichern](persistence.md). Danach ist
> der Bestand durchsuchbar — auch gezielt nach Prompt, Modell oder Seed.

> **Wichtig:** Der Scanner **liest** nur und **kopiert/verschiebt nichts**. Er
> katalogisiert die Dateien dort, wo sie liegen. (Der spätere Import mit Kopieren
> in eine datumsbasierte Struktur ist ein eigener Schritt.)

## Aufruf

```bash
python -m feral.scan /pfad/zum/ordner --db ./feral.sqlite
```

- `root` (Pflicht): der Ordner, der rekursiv durchsucht wird.
- `--db` (optional): Pfad zur SQLite-Datei (Standard `./feral.sqlite`). Wird bei
  Bedarf angelegt.
- `--quiet` (optional): keine Zwischen-Fortschrittsausgabe.

## Beispielausgabe

```
Scan abgeschlossen für: /media/ai-bilder
  Dateien betrachtet : 12877
  davon Medien       : 12450
    neu aufgenommen  : 12450
    bereits bekannt  : 0
    mit Metadaten    : 9980
    interpretiert    : 8100
    Extraktor folgt  : 120
  übersprungen (kein Container): 427
  mit Warnungen      : 14
  fehlgeschlagen     : 0
```

## Was die Zahlen bedeuten

| Zeile | Bedeutung |
|-------|-----------|
| **Dateien betrachtet** | alle Dateien im Ordnerbaum |
| **davon Medien** | als bekannter Container erkannt (PNG, JPEG, WEBP, …) |
| **neu aufgenommen** / **bereits bekannt** | Hash war neu bzw. schon in der DB (Dublette oder Re-Scan) |
| **mit Metadaten** | es wurden eingebettete Metadaten gefunden |
| **interpretiert** | [Schicht 2](interpretation.md) hat strukturierte Felder erkannt (Prompt, Seed, Modell, …) |
| **Extraktor folgt** | erkannt, aber der Extraktor ist noch nicht gebaut (aktuell PSD und PDF). Die Datei ist trotzdem **katalogisiert** und bekommt ihre Metadaten automatisch, sobald der Extraktor da ist |
| **übersprungen** | kein bekannter Container (z. B. `.txt`, macOS `._`-Dateien) |
| **fehlgeschlagen** | Datei nicht lesbar o. ä. — wird unten im Lauf aufgelistet |

## Eigenschaften

- **Wiederholbar (idempotent):** Denselben Ordner nochmal scannen erzeugt keine
  Duplikate; bereits bekannte Dateien werden nur als „bekannt" gezählt.
- **Bricht nicht ab:** Eine kaputte Datei beendet den Scan nicht — sie landet unter
  „fehlgeschlagen".
- **Dubletten fallen automatisch an:** bit-identische Dateien an verschiedenen Orten
  werden als **ein** Item mit mehreren Fundorten geführt.
