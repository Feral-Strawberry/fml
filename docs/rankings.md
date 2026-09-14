# Rankings: Paarvergleich mit Bestenliste (Ranking-Modul)

> Was ist das? Ein **optionales Modul** (Standard: aus), das Rankings
> **zusätzlich zur Sternebewertung** aufbaut — per Paarvergleich wie bei
> LMArena: zwei Medien aus einem selbst definierten **Ranking**, du klickst
> das bessere an, im Hintergrund entsteht eine Elo-Bestenliste.
> Nebeneffekt: Gamification und Wiederentdecken von altem Material —
> die Paar-Auswahl sorgt dafür, dass jedes Bild irgendwann drankommt.

## Einschalten

Das Modul ist ab Werk aus und kostet dann nichts (keine Sidebar-Gruppe,
keine Abfragen). Einschalten:

- **Admin → Konfiguration → Module → „Ranking-Modul"** (Schalter „Rankings &
  Duelle einschalten") ankreuzen und speichern — wirkt sofort, ohne Neustart. Oder:
- in der `config.toml`: `[rankings]` → `enabled = true`.

Danach erscheint links in der Sidebar die Gruppe **„Rankings"**.

## Rankings anlegen und pflegen

Ein Ranking ist die dritte Stufe von Suche → gespeicherte Suche →
Ranking (das Bedienmodell erklärt [gui.md](gui.md#suche-gespeicherte-suche-ranking-ein-gedanke)).
Ein **Ranking** ist eine benannte Teilmenge der Bibliothek, über die
Duelle laufen: **Name + Filterausdruck** (dieselbe Grammatik wie das
Suchfeld, z. B. `tag: porträt` oder `model: "flux"` — leer = ganze
Bibliothek). Die Population wird **live** ausgewertet, wie bei
gespeicherten Suchen: Neu Importiertes wächst automatisch hinein,
Abgelehntes fällt heraus.

- **Anlegen:** Population in der Galerie zusammenklicken (Sidebar,
  „+ Kriterium", Chips), dann **🏆 Ranking** neben dem ☆ in der Chip-Leiste.
  Der Dialog zeigt die Chips als Vorschau mit Trefferzahl und fragt nur
  noch den Namen; ohne Chips ist die Population die ganze Bibliothek. Ein
  `sort:`-Chip wird nicht übernommen, das Ranking hat seine eigene Ordnung.
  Wer lieber tippt: „Ausdruck selbst tippen" im Dialog aufklappen, Enter
  prüft den Ausdruck und zeigt ihn als Chips. Nach dem Anlegen öffnet das
  Ranking.
- **Umbenennen / Population ändern:** in der Ranking-Ansicht das ✎ (oder
  „Bearbeiten" je Zeile auf der Admin-Seite „Rankings"). Es schließt das
  Ranking und lädt seine Population als Chips in die Galerie;
  die Kopfzeile schaltet in den Bearbeiten-Modus (akzentfarben,
  **„Bearbeiten: 🏆 Name"**, Sidebar-Zeile hervorgehoben, Knöpfe rechts nur
  als Symbole) mit ✎ (umbenennen), **Ranking speichern** (nur aktiv, wenn
  die Chips abweichen, dann steht ein Punkt am Namen) und **✕ Beenden**.
  Chips ändern wie immer; Ranking speichern führt zurück ins Ranking,
  Beenden geht ohne Speichern zurück. Die bisherigen
  Duelle bleiben erhalten.
- **Löschen:** **Admin → Rankings**, mit Bestätigungsdialog — löscht das
  Ranking **mit allen Duellen und Scores**. Bewusst nur dort: eine
  versehentlich gelöschte gespeicherte Suche ist schnell neu geklickt, ein
  gelöschtes Ranking nimmt tausende Duelle mit. (Das ✕ in der
  Ranking-Ansicht schließt nur die Ansicht, wie überall sonst.)

Der Zähler an der Ranking-Zeile ist die aktuelle Population; die bisherige
Duell-Zahl steht im Tooltip.

## Bestenliste (Standardansicht)

Klick auf ein Ranking öffnet die **Bestenliste** als große Ansicht:
links das Medium des aktuellen Rangs, darunter Platzierung, Elo und
Duell-Zahl; rechts die Rangliste (Rang, Thumbnail, Elo) als
**mitscrollende Spalte** — bei Platz 55 bleibt die Umgebung ~50–60
sichtbar. Bester Score zuerst; Items ohne Duell tauchen nicht auf
(kein Rang ohne Urteil). **Ausgeschiedene** (siehe „Beide raus") stehen
gedimmt und geschlossen am **Ende** der Spalte, mit dem Marker „raus"
statt der Rangzahl; der Kopf der Ansicht zählt sie mit („… · 12 ausgeschieden").
Sichtbar bleibt also, was du aussortiert hast.

- `←`/`→` (oder `↑`/`↓`) blättert in **Rang-Reihenfolge** — so klickt
  man sich durch die Perlen des Rankings. `Pos1`/`Ende` springt zum
  ersten/letzten Platz.
- Klick in die Spalte springt zu diesem Rang; die Spalte lädt beim
  Scrollen nach.
- `Enter` (oder der Knopf unten) öffnet die **Einzelbildansicht** mit
  allen Metadaten — z. B. um den Prompt herauszuziehen; `Esc` dort
  führt zurück zum Ranking.
- Steht ein Ausgeschiedenes links, zeigt die Info-Zeile „Ausgeschieden"
  und den Knopf **Wieder rein**: Das Item kommt zurück in den Pool dieses
  Rankings, Elo und Duell-Zahl bleiben. Die Liste lädt neu und bleibt an
  derselben Stelle, dort steht dann das nächste Ausgeschiedene, so lässt
  sich der Schwanz der Liste zügig durchsehen.
- Ist die Liste noch leer, führt ein Knopf direkt ins erste Duell.

## Duell-Modus

Der Umschalter oben wechselt in den Duell-Modus: zwei Medien
nebeneinander (Videos laufen stumm in Schleife). Über jedem Medium steht
eine Kopfzeile wie in der Vergleichsansicht: primärer Fundort (voller Pfad,
Tooltip zeigt ihn ungekürzt), Maße und Container, die **Bewertungspunkte**
(Klick setzt Sterne, gleiche Zahl löscht) und **raus**. Die Kopfzeile ist
keine Wertungsfläche, der Pfad lässt sich markieren und kopieren.

- **raus** (Knopf in der Kopfzeile): beendet das Duell wie ein Klick auf
  das andere Bild (der Partner gewinnt, dieses verliert Punkte), und dieses
  Medium scheidet zusätzlich aus dem Ranking aus, es kommt hier nicht mehr
  dran. Rückweg wie gehabt über die Bestenliste.

- **Klick aufs bessere** (oder `←`/`→`) wertet das Duell — kurz erscheint
  der neue Elo-Stand am Paar, dann kommt das nächste.
- **Beide raus** (Knopf oder `↓`): beide sind schlecht. Beide bekommen
  ein Duell, verlieren Punkte (als hätten sie gegen ein durchschnittliches
  Bild verloren) **und scheiden aus diesem Ranking aus**: Sie kommen in
  keinem Duell dieses Rankings mehr vor, mit keinem Partner. In der
  Bestenliste stehen sie gedimmt am Ende; von dort geht es mit **Wieder
  rein** zurück in den Pool. Das gilt nur für dieses Ranking und ist kein
  Aussortieren aus dem Katalog, dafür gibt es weiterhin das Ablehnen.
- **Überspringen** (Knopf oder Leertaste) ist das ehrliche „weiß nicht /
  Paar passt nicht" (oder „beide super, ich kann mich nicht
  entscheiden"): Es wird **nichts** gewertet und nichts gespeichert.
- Sind weniger als zwei aktive Items übrig, zeigt der Duell-Modus statt
  eines Paars den Hinweis „Keine Paare mehr: n von m Items sind
  ausgeschieden" und einen Knopf zur Bestenliste.
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
Duell-Log deterministisch neu ab (Rescan-Prinzip); auch wer ausgeschieden
ist, ergibt sich aus dem Log („Beide raus" setzt es, „Wieder rein" hebt es
auf, die letzte Zeile zählt). Verschwindet ein Item
aus der Bibliothek (abgelehnt/rausverschoben), bleibt seine
Duell-Geschichte erhalten — es taucht nur nicht mehr in Paaren und
Bestenliste auf.

Hintergründe und Entscheidungen: ADR 0045 (dort und im Code heißt ein
Ranking „Arena", nach dem Vorbild LMArena; die Oberfläche sagt seit ADR
0081 durchgehend „Ranking").
