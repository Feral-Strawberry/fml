# Ausschnitt aus einem Song oder Video

Mit dem Modul **Ausschnitt** schneidet die Feral Media Library (fml) ein
Stück aus einem Song oder Video und legt es als neue Datei in den
Export-Ordner: zehn Sekunden aus einem Song als Vorlage für einen
Workflow, ein paar Sekunden aus einem Video als Quellmaterial.

Das Original wird dabei nur gelesen. An der Library, den Bewertungen und
Tags ändert sich nichts, und der Ausschnitt taucht nicht in der
Bibliothek auf. Wer ihn dort haben will, liest ihn ein wie jede andere
Datei.

## Einmal einrichten

1. **Admin → Konfiguration → Module → Modul Ausschnitt** einschalten und
   speichern. Ab Werk ist das Modul aus.
2. Einen **Export-Ordner** eintragen, falls noch keiner eingerichtet ist
   (siehe [Kopien exportieren](export.md)). Ausschnitte landen im selben
   Ordner wie die Kopien.

Das Modul braucht **ffmpeg**. Für Video-Ausschnitte muss dieses ffmpeg
H.264 kodieren können (libx264); die üblichen Pakete können das. Fehlt
etwas, steht es direkt am Schalter in der Konfiguration: ohne H.264 gehen
nur Ton-Ausschnitte, ohne ffmpeg gar keine.

## Ausschnitt öffnen

Ein Video oder einen Song auswählen. Im Panel rechts steht neben den
Bewertungspunkten der Knopf **✂ Ausschnitt**. Er ist überall da, wo das
Panel ist: in der Galerie, in der Audioansicht und in der Einzelansicht.

Der Knopf ist gesperrt, wenn der Browser die Datei nicht abspielen kann
(etwa ProRes) oder ihre Dauer unbekannt ist. Ohne Bild und Ton zur
Kontrolle lässt sich nicht sinnvoll schneiden.

## Den Bereich markieren

Die Ansicht zeigt das Video (bei Songs das Cover) und darunter eine
Zeitleiste über die ganze Länge, bei Songs mit der Wellenform. Der
markierte Bereich ist farbig hinterlegt und hat links und rechts einen
Griff.

- **Griff ziehen** ändert den Anfang oder das Ende.
- **In der Mitte ziehen** verschiebt den ganzen Bereich. Die Länge bleibt.
- **Klick ohne Ziehen** (außerhalb oder innerhalb des Bereichs) setzt nur
  die Abspielstelle. So sucht man eine Stelle, ohne den Bereich zu
  verändern. Ein Klick aufs Bild spielt oder hält an.
- **Anfang**, **Ende** und **Länge** lassen sich eintippen, in Sekunden
  (`72,5`) oder als Zeit (`1:12.5`). Gerechnet wird in Zehntelsekunden.
- **hier** neben Anfang und Ende setzt den Rand an die Abspielstelle.
  Liegt die Stelle hinter dem Ende (oder vor dem Anfang), wandert der
  ganze Bereich mit.

**Feste Länge:** die Länge eintippen, zum Beispiel `10`, und den Bereich
dann in der Mitte an die richtige Stelle ziehen.

Beim Öffnen beginnt der Bereich an der Stelle, an der der Song im Player
oder das Video in der Einzelansicht gerade steht, und ist zehn Sekunden
lang. Läuft im Player eine A–B-Schleife für diesen Song, wird sie
übernommen.

## Anhören

**▶** oder die Leertaste spielt ab. Erreicht die Abspielstelle das Ende
des Bereichs, springt sie an den Anfang zurück: Der Bereich läuft in
Schleife. Außerhalb des Bereichs läuft die Wiedergabe normal weiter.

Nach jeder Änderung springt die Abspielstelle dorthin, wo sie wirkt: an
den neuen Anfang, oder zwei Sekunden vor das neue Ende.

Solange die Ansicht offen ist, pausiert der Player, und andere Videos im
Fenster halten an.

## Tasten

| Taste | Wirkung |
| --- | --- |
| Leertaste | abspielen und anhalten |
| I | Anfang an die Abspielstelle |
| O | Ende an die Abspielstelle |
| ← → | den zuletzt angefassten Griff um 0,1 s schieben, mit Umschalt um 1 s |
| Esc | Ansicht schließen |

## Exportieren

Unter **Ausgabe** steht, was geschrieben wird:

- **Song:** immer **Ton (WAV)**.
- **Video:** per Häkchen **Video mit Ton**, **nur Video**, **Ton (WAV)**.
  Jedes Häkchen ergibt eine eigene Datei; die Wahl bleibt für das nächste
  Mal gemerkt. Ein Video ohne Tonspur gibt nur das Bild her.

**Exportieren** schreibt die Dateien. Das dauert in der Regel Sekunden und
hat Vorrang vor laufender Hintergrundarbeit; ist die Hintergrundarbeit
angehalten, wartet der Ausschnitt, bis sie weiterläuft. Darunter erscheint je Datei
ein Knopf **📂 Dateiname**, der sie im Dateimanager zeigt. Die Ansicht
bleibt offen, damit sich gleich das nächste Stück aus derselben Datei
schneiden lässt.

Ist der Export gesperrt, steht der Grund neben dem Knopf: kein
Export-Ordner eingerichtet, Ordner oder Quelldatei nicht erreichbar, oder
ffmpeg fehlt.

## Was geschrieben wird

```
<Export-Ordner>/2026-10-11/song 0m12s-0m22s.wav
<Export-Ordner>/2026-10-11/take 0m03s-0m07.5s.mp4
<Export-Ordner>/2026-10-11/take 0m03s-0m07.5s mute.mp4     nur Video
```

Der Ordner ist der Tag des Exports, derselbe wie bei Kopien ohne
Paketname. Der Dateiname ist der Name der Quelle plus der Zeitbereich;
„nur Video" bekommt den Zusatz `mute`. Derselbe Ausschnitt ein zweites
Mal erzeugt keine zweite Datei.

| Ausgabe | Format |
| --- | --- |
| Ton | WAV, 16 Bit, Abtastrate und Kanäle wie die Quelle |
| Video | MP4 mit H.264 in hoher Qualität, Auflösung und Bildrate wie die Quelle |
| Ton im Video | AAC |

Der Ausschnitt wird neu kodiert, damit der Schnitt genau an der
markierten Stelle sitzt. Eingebettete Metadaten der Quelle (Titel,
Workflows) stehen nicht im Ausschnitt.

## Grenzen

- Keine Blenden, keine weiteren Formate, keine Qualitätsregler.
- Die Zeitleiste hat keinen Zoom. Bei langen Dateien wird der Bereich
  über die Felder und die Pfeiltasten genau.
- Ein Ausschnitt gehört zu genau einer Datei; es gibt keine Sammel-Aktion.
- Bei Videos mit ungerader Breite oder Höhe fällt eine Pixelzeile weg.
