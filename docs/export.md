# Kopien exportieren

Mit dem Export legt die Feral Media Library (fml) **Kopien** von Medien
in einen Ordner, aus dem ein anderes Programm sie abholt: ein Stapel
Bilder für den Videoschnitt, die Songs für eine CD, eine Auswahl für
jemand anderen.

Der Export ist immer eine Kopie. Die Originale bleiben, wo sie sind, und
an der Library, den Bewertungen und Tags ändert sich nichts.

## Einmal einrichten: der Export-Ordner

**Admin → Konfiguration → Media Library → Export-Ordner**: einen Ordner
eintragen oder mit 📁 wählen, dann speichern. In der `config.toml` ist
das `[export] root`.

Der Ordner darf nicht in der Media Library, in einem Watchordner oder im
Cache liegen, und keiner davon darf in ihm liegen. Sonst würde fml die
eigenen Exporte wieder einlesen. Solche Ordner weist das Speichern mit
einer Meldung ab.

Ohne Export-Ordner ist der Knopf in der Sammel-Aktion gesperrt, und in
seinem Kasten steht, warum. Dasselbe gilt, wenn der Ordner gerade nicht erreichbar
ist, etwa weil die Platte nicht angeschlossen ist.

Der Export funktioniert auch im Übersichtsmodus, also ohne
Library-Verwaltung: Er liest die Originale nur und schreibt
ausschließlich in den Export-Ordner.

## Exportieren

1. Medien auswählen oder eine Suche eingrenzen (Bilder, Videos oder, in
   der Audioansicht, Songs).
2. **⚡ Sammel-Aktion** öffnen. Ist etwas ausgewählt, steht oben
   „Auswahl (N)" oder „alle Treffer (M)" zur Wahl.
3. Im unteren Abschnitt **Export** (er ändert nichts an der Library) im
   Kasten „Kopien" auf **Kopien exportieren …** klicken.
4. Im kleinen Dialog stehen die Zahl der Dateien, ihre Größe, der
   Zielordner und der freie Platz. Einzustellen ist:
   - **Paketname** (optional): wird an den Ordnernamen angehängt.
     Zeichen, die ein Dateisystem nicht erlaubt, werden entfernt.
   - **Ablage**: **flach** (alle Dateien direkt im Ordner, die Vorgabe)
     oder **Jahr/Monat/Tag** (Unterordner wie in der Media Library, nach
     dem Datum des Mediums; Medien ohne Datum landen in `ohne-datum`).
   - **Umgerechnete Formate** (erscheint nur, wenn welche dabei sind):
     siehe unten.
   - **Angaben von Hand: in die Kopie schreiben** (erscheint nur, wenn
     Songs mit Angaben, Songtext oder Cover von Hand dabei sind, und ist
     angehakt): siehe [Angaben von Hand in der Kopie](#angaben-von-hand-in-der-kopie).
5. **Exportieren** reiht den Export als Aufgabe ein. Der Dialog nennt den
   Zielordner; den Fortschritt zeigt das Hintergrund-Widget links, das
   Ergebnis steht danach dort und unter Admin → Übersicht.

Reicht der freie Platz nicht für alle Dateien, startet der Export nicht
und sagt, wie viel fehlt.

## Wohin die Kopien kommen

```
<Export-Ordner>/2026-10-09/              ohne Paketname
<Export-Ordner>/2026-10-09 Musikvideo/   mit Paketname „Musikvideo"
```

Das Datum ist der Tag des Exports. Ein zweiter Export am selben Tag mit
demselben Namen ergänzt denselben Ordner.

Jede Datei behält ihren Namen. Liegt im Ordner schon eine Datei dieses
Namens, entscheidet der Inhalt:

- **derselbe Inhalt:** die Datei wird übersprungen („schon da"). Derselbe
  Export zweimal erzeugt also keine doppelten Dateien.
- **anderer Inhalt:** die neue Datei heißt `name (1).ext`, `name (2).ext`
  und so weiter, wie im Dateimanager.

## Was genau kopiert wird

Immer das Original, Bit für Bit, mit allem, was es an Metadaten trägt,
und mit seinem Änderungsdatum. Jede Kopie wird nach dem Schreiben gegen
das Original geprüft. fml legt nichts dazu und rechnet nichts um. Nur
einen Schreibschutz (etwa bei Dateien, die von einer CD stammen) nimmt
die Kopie nicht mit.

**Die erste Ausnahme** sind Formate, die fml selbst nur über ein
gerechnetes Bild anzeigen kann, zurzeit Kodak Photo CD (`.pcd`). Die
Rohdatei ist außerhalb von fml kaum zu gebrauchen, darum geht hier die
umgerechnete Fassung als **PNG** raus (`bild.pcd` wird `bild.png`). Wer
die Rohdatei will, wählt im Dialog bei „Umgerechnete Formate"
**Original**.

Hat fml das Bild schon einmal in voller Größe gezeigt, liegt die
umgerechnete Fassung im Vorschau-Cache. Der PNG-Export nimmt sie von
dort und funktioniert dann auch, wenn die Rohdatei gerade fehlt (Platte
nicht angeschlossen, Datei verschoben). Die Rohdatei selbst lässt sich
ohne Rohdatei natürlich nicht exportieren.

Songs gehen als Original raus, auch wenn fml zum Abspielen im Browser
eine eigene Fassung benutzt. Die zweite Ausnahme sind Songs mit Angaben
von Hand, wenn das Häkchen gesetzt ist (nächster Abschnitt).

## Angaben von Hand in der Kopie

Was in fml von Hand gepflegt ist, steht nur in fml. Wer eine Datei
weitergibt, gibt aber die Datei weiter, nicht die Datenbank. Mit dem
Häkchen **Angaben von Hand: in die Kopie schreiben** schreibt fml deshalb
in die **Kopie** eines Songs:

- die [Musik-Angaben von Hand](audio.md#musik-angaben-von-hand) (Titel, Interpret,
  Album-Interpret, Album, Titelnummer, CD, Jahr, Genre),
- den [Songtext von Hand](audio.md#songtext-von-hand), samt Zeiten je Zeile, wenn jede
  Zeile eine hat,
- das [Cover](audio.md#cover-fertige-songs-in-der-galerie), verkleinert auf höchstens 1200 Pixel an der
  längsten Kante (JPEG). Es trägt eine Kennung, an der ein anderes fml
  erkennt, dass es von Hand gewählt ist; dort erscheint es dann als
  Anzeigebild, auch bei Songs von Suno.

Wo es etwas von Hand gibt, ersetzt es die Angabe der Datei; alles andere
in der Datei bleibt, wie es ist. Das Original wird nie angefasst.

**Formate:** MP3 und M4A. Andere Songs mit Angaben von Hand gehen
unverändert raus; das Ergebnis zählt sie als „ohne Angaben (Format)".

- **MP3:** fml schreibt die Angaben in den ID3-Tag; alle anderen
  Einträge darin bleiben erhalten, auch Suno-Kennung und Herkunftsdaten.
  Der Songtext steht in `USLT`, mit Zeiten zusätzlich in `SYLT`.
- **M4A:** fml packt die Datei mit ffmpeg neu, ohne den Ton anzufassen.
  Der Songtext steht im Songtext-Tag, mit Zeiten zusätzlich als
  Untertitel-Spur wie bei Suno V6.
  Eigene Angaben anderer Programme (iTunes-Freiform-Tags) übernimmt
  ffmpeg dabei nicht; das Serverlog nennt sie (`export: tags dropped`).
  Für M4A braucht es ffmpeg.

So eine Kopie ist nicht mehr bitgleich. fml prüft stattdessen, dass der
**Ton** unverändert ist, und erst dann liegt die Datei im Ordner. Der
Abgleich „schon da" entfällt für sie: Ein zweiter Export legt
`name (1).ext` daneben. Ist das Coverbild gerade nicht erreichbar,
bekommt die Kopie die übrigen Angaben ohne Cover.

Hat der Song eine Herkunfts-Signatur (C2PA, etwa von Suno), bleibt sie
in der Datei, gilt für die geänderte Kopie aber nicht mehr.

## Das Ergebnis

Nach dem Lauf steht eine Zeile wie
`Export: 118 kopiert · 4 schon da · 2 nicht erreichbar → <Ordner>`:

- **kopiert:** neu im Ordner; **davon mit Angaben von Hand**: Songs, in
  deren Kopie fml die Angaben geschrieben hat.
- **ohne Angaben (Format):** Songs mit Angaben von Hand in einem Format,
  in das fml nicht schreibt; sie liegen unverändert im Ordner.
- **schon da:** lag mit demselben Inhalt schon dort.
- **nicht erreichbar:** fml fand die Datei an keinem ihrer Fundorte. Das
  Ergebnis nennt beim ersten Fall den Grund: die **Datei fehlt** (Platte
  nicht angeschlossen, Datei verschoben oder gelöscht), oder am Fundort
  liegt inzwischen eine **andere Datei** (andere Größe als im Katalog,
  etwa nach dem Bearbeiten in einem anderen Programm). Alle Fälle stehen
  im Serverlog (`export: unreachable`). Der Export läuft trotzdem weiter.
  Ein Re-Scan des Ordners bringt den Katalog wieder auf den Stand der
  Platte.
- **Fehler:** die Kopie ließ sich nicht schreiben oder stimmte nicht mit
  dem Original überein; die Datei fehlt dann im Ordner. Das Ergebnis
  nennt den ersten Fehler mit Datei und Grund, alle weiteren stehen im
  Serverlog (Admin → Serverlog, Zeilen mit `export:`).

Der Export lässt sich wie jede Aufgabe anhalten und fortsetzen
([Hintergrund: Leistung und Anhalten](admin.md#hintergrund-leistung-und-anhalten)).

## Grenzen

- Keine ZIP-Pakete, keine Vorlagen für Dateinamen, keine Liste früherer
  Exporte.
- Kein Umrechnen in andere Formate oder Größen (außer den Ausnahmen oben).
- fml räumt den Export-Ordner nie auf. Was dort liegt, gehört dem
  Dateimanager.
