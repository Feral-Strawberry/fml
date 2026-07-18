# Rankings: Paarvergleich mit Arenen (Ranking-Modul)

> Was ist das? Ein **optionales Modul** (Standard: aus), das Rankings
> **zusätzlich zur Sternebewertung** aufbaut — per Paarvergleich wie bei
> LMArena: zwei Medien aus einer selbst definierten **Arena**, du klickst
> das bessere an, im Hintergrund entsteht eine Elo-Bestenliste.
> Nebeneffekt: Gamification und Wiederentdecken von altem Material —
> die Paar-Auswahl sorgt dafür, dass jedes Bild irgendwann drankommt.

## Einschalten

Das Modul ist ab Werk aus und kostet dann nichts (keine Sidebar-Gruppe,
keine Abfragen). Einschalten:

- **Admin → Konfiguration → Module → „Ranking-Modul (Arenen & Duelle)"**
  ankreuzen und speichern — wirkt sofort, ohne Neustart. Oder:
- in der `config.toml`: `[rankings]` → `enabled = true`.

Danach erscheint links in der Sidebar die Gruppe **„Rankings"**.

## Arenen

Eine **Arena** ist ein benanntes Ranking über eine Teilmenge der
Bibliothek: **Name + Filterausdruck** (dieselbe Grammatik wie das
Suchfeld, z. B. `tag: porträt` oder `model: "flux"` — leer = ganze
Bibliothek). Die Population wird **live** ausgewertet, wie bei
gespeicherten Suchen: Neu Importiertes wächst automatisch hinein,
Abgelehntes fällt heraus.

- **Anlegen:** Sidebar → Rankings → „+ Neue Arena" (Name + Ausdruck).
- **Umbenennen / Population ändern:** in der Arena-Ansicht das ✎ —
  die bisherigen Duelle bleiben erhalten.
- **Löschen:** **Admin → Wartung → Ranking-Arenen**, zweistufig —
  löscht die Arena **mit allen Duellen und Scores**. (Das ✕ in der
  Arena-Ansicht schließt nur die Ansicht, wie überall sonst.)

Der Zähler an der Arena-Zeile ist die aktuelle Population; die bisherige
Duell-Zahl steht im Tooltip.

## Bestenliste (Standardansicht)

Klick auf eine Arena öffnet die **Bestenliste** als große Ansicht:
links das Medium des aktuellen Rangs, darunter Platzierung, Elo und
Duell-Zahl; rechts die Rangliste (Rang, Thumbnail, Elo) als
**mitscrollende Spalte** — bei Platz 55 bleibt die Umgebung ~50–60
sichtbar. Bester Score zuerst; Items ohne Duell tauchen nicht auf
(kein Rang ohne Urteil).

- `←`/`→` (oder `↑`/`↓`) blättert in **Rang-Reihenfolge** — so klickt
  man sich durch die Perlen der Arena. `Pos1`/`Ende` springt zum
  ersten/letzten Platz.
- Klick in die Spalte springt zu diesem Rang; die Spalte lädt beim
  Scrollen nach.
- `Enter` (oder der Knopf unten) öffnet die **Einzelbildansicht** mit
  allen Metadaten — z. B. um den Prompt herauszuziehen; `Esc` dort
  führt zurück zur Arena.
- Ist die Liste noch leer, führt ein Knopf direkt ins erste Duell.

## Duell-Modus

Der Umschalter oben wechselt in den Duell-Modus: zwei Medien
nebeneinander (Videos laufen stumm in Schleife).

- **Klick aufs bessere** (oder `←`/`→`) wertet das Duell — kurz erscheint
  der neue Elo-Stand am Paar, dann kommt das nächste.
- **Beide verlieren** (Knopf oder `↓`): beide sind schlecht — beide
  bekommen ein Duell und verlieren Punkte (als hätten sie gegen ein
  durchschnittliches Bild verloren). Wichtig gegen Wiedergänger: das
  Paar gilt als verglichen und drängt sich nicht immer wieder auf.
  Das ist ein Ranking-Urteil, kein Aussortieren — dafür gibt es
  weiterhin das Ablehnen.
- **Überspringen** (Knopf oder Leertaste) ist das ehrliche „weiß nicht /
  Paar passt nicht": Es wird **nichts** gewertet und nichts gespeichert.
- `Esc` schließt die Ansicht.

Die Paar-Auswahl folgt „Abdeckung, dann Nähe": bevorzugt kommen Items mit
den wenigsten Duellen dran (jedes Bild wird wiederentdeckt), der Gegner
stammt bevorzugt aus der Elo-Nachbarschaft (knappe Duelle sagen am
meisten aus).

## Wie die Scores funktionieren (und warum nichts verloren geht)

Gespeichert wird jedes **Duell** (wer gegen wen gewann, wann) — das ist
die Rohwahrheit, sie wird nie verändert. Der **Elo-Score** (Start 1000,
K-Faktor 32) ist daraus nur abgeleitet und jederzeit reproduzierbar:
**Admin → Wartung → „Ranking-Scores neu berechnen"** spielt das gesamte
Duell-Log deterministisch neu ab (Rescan-Prinzip). Verschwindet ein Item
aus der Bibliothek (abgelehnt/rausverschoben), bleibt seine
Duell-Geschichte erhalten — es taucht nur nicht mehr in Paaren und
Bestenliste auf.

Hintergründe und Entscheidungen: ADR 0045.
