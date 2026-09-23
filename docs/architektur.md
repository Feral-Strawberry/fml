# Architektur

> Was ist das? Das technische Konzept hinter fml in vier Bildern: welche
> Prozesse miteinander reden, wie eine Datei in den Katalog kommt, wie
> eine Suche zu einer schnellen Galerie wird und wie fml selbst sicher auf
> den Rechner kommt. Für alle, die verstehen
> wollen, was unter der Oberfläche passiert, bevor sie den Code lesen.

fml ist eine Anwendung, die daheim als Server oder unterwegs auf dem
Laptop läuft, immer über `localhost` im Browser.

Technik: Python 3.12+ · FastAPI + uvicorn · SQLite (stdlib `sqlite3`,
WAL) · Pillow · ffprobe/ffmpeg · ES-Module im Browser ohne Build-Schritt.
Jedes installierte Paket ist mit fester Version und Prüfsumme benannt.

## Prozesse und Grenzen

![Browser spricht per HTTP mit dem Web-Prozess. Der Web-Prozess liest die Datenbank, schreibt nur kurze Griffe und reicht Langläufer über eine Warteschlange an den Worker-Prozess, der die langen Schreibvorgänge übernimmt und Dateien liest und kopiert.](img/architektur-prozesse.de.svg)

Zwei Prozesse, eine Datenbank. Der Web-Prozess beantwortet jede Anfrage
und bleibt dabei flüssig, weil alles Langlaufende in einem zweiten Prozess
passiert. **Rot sind die beiden Schreibwege:** kurze Griffe (Bewerten,
Tags, Notizen, Duelle) schreibt der Web-Prozess selbst unter einer Sperre,
alles Langlaufende (Scan, Import, Neu interpretieren, Thumbnails) schreibt
der Worker. Der Worker wird per `spawn` gestartet, bekommt eine Aufgabe
auf einmal und meldet Fortschritt über eine zweite Queue; stirbt er,
startet ihn der nächste Auftrag neu. Medien laufen über einen eigenen
Thread-Pool, damit große Videos keine Galerie-Anfrage blockieren. Der
Watcher prüft jeden Watchordner und reiht eine Datei erst ein, wenn sie
eine Ruhezeit lang unverändert war.

## Wie eine Datei in den Katalog kommt

![Aufnahme-Kette: Quelle, Erkennen, Import-Regeln, SHA-256, optional Kopie und Prüfung, Katalog, optional Quelle leeren. Katalogisieren schreibt Schicht 1 byte-treu in raw_metadata, Schicht 2 interpretiert daraus Felder, beides landet im Volltextindex. Neu interpretieren läuft ohne Dateizugriff über raw_metadata.](img/architektur-aufnahme.de.svg)

Jede Datei läuft einmal durch dieselbe Kette, egal ob sie per Import,
Watchordner oder Katalogisieren kommt. Der Modus entscheidet nur über die
gestrichelten Schritte: kopieren und verschieben legen eine geprüfte Kopie
in der Media Library ab, nur verschieben leert danach die Quelle (siehe
[Import](import.md)).

Identität ist der Inhalt: Der SHA-256 der Datei ist der Schlüssel, ein
Pfad ist nur ein Fundort. Schicht 1 versteht Container, nicht
Konventionen, und speichert jeden Metadaten-Eintrag unverändert. Schicht 2
macht daraus Felder und darf Lücken haben. **Weil der Roh-Blob bleibt,**
läuft ein neuer oder verbesserter Parser über den ganzen Bestand, ohne
eine einzige Datei zu öffnen. Bewertungen, Tags und Notizen liegen
getrennt davon und werden nie von einem Parser überschrieben. Details:
[Extraktion](extraction.md), [Interpretation](interpretation.md).

## Von der Suche zur Galerie

![Sidebar, Tippen und gespeicherte Suchen erzeugen nur Chips. Die Grammatik übersetzt Chips in Prädikate, daraus entsteht parametrisiertes SQL. Der Epochen-Cache fragt SQLite nach data_version und rechnet nur neu, wenn sich die Epoche geändert hat. Jeder Commit, auch von außen, ändert data_version.](img/architektur-suche.de.svg)

Es gibt genau einen Suchzustand. Sidebar, Baukasten, Tipphilfe und
gespeicherte Suchen kennen keinen eigenen Zustand, sie legen nur Chips an;
die Grammatik übersetzt in beide Richtungen, getippt und geklickt ist
garantiert dasselbe. Der Epochen-Cache im Web-Prozess hält Trefferlisten
und Zähler, bis **irgendein Commit** die `data_version` von SQLite
ändert, auch einer von außen wie `python -m feral.interpret`. Tiefes
Scrollen und der zweite Klick auf dieselbe Suche kosten dadurch praktisch
nichts. Wie man sucht: [Die Oberfläche](gui.md).

## Installation und Lieferkette

![Die direkten Pakete sind die Quelle; tools/lock_deps.py erzeugt daraus requirements.txt mit fester Version und SHA-256 je Datei, die Hashes kommen von PyPI. Das Startskript lässt pip im Hash-Modus installieren: pip lädt nur fertige Wheels von PyPI, vergleicht jede Datei mit dem Lock und bricht bei einem nicht gelisteten Paket oder falschem Hash ab. Wächter-Tests, Advisory-Check, Export-Sperre und Dependabot prüfen und pflegen den Lock.](img/architektur-lieferkette.de.svg)

Auf den Rechner kommt nur, was benannt ist. `requirements.txt` ist ein
vollständiger Lock: jedes Paket, direkt oder indirekt und pip selbst, mit
fester Version und den SHA-256-Prüfsummen aller seiner Dateien. Erzeugt
wird er aus den direkten Paketen (`# direct: wo benutzt`) von
`tools/lock_deps.py`. Die Startskripte lassen pip **im Hash-Modus und nur
mit fertigen Wheels** installieren: **ein nicht gelistetes Paket oder eine
veränderte Datei bricht die Installation ab**, und nichts wird aus
Quellcode gebaut. fml selbst wird über eine `.pth`-Datei eingebunden, ohne
Build-Schritt.

Vier Wächter halten den Lock ehrlich: Tests schlagen an, wenn Code ein
Paket importiert, das nicht direkt benannt ist, wenn ein Eintrag keine
Prüfsumme oder keine Dokumentation hat oder wenn die installierte Umgebung
vom Lock abweicht. Der Advisory-Check fragt die OSV-Datenbank nach jedem
gelockten Paket, und bei einer offenen Meldung sperrt er den Public-Export.
Dependabot schlägt Sicherheits-Updates direkt auf dem Lock vor. Details:
[Sicherheit](security.md), [`DEPENDENCIES.md`](../DEPENDENCIES.md).

## Leitplanken

- **Original heilig:** fml fasst Dateien nur beim Import und beim
  Rausverschieben an. Ab Werk läuft der Übersichtsmodus: nie kopieren,
  verschieben oder löschen.
- **Alles Abgeleitete ist reproduzierbar:** Schicht 2, Thumbnails,
  Erstelldatum und Volltextindex lassen sich aus Hash und Roh-Blobs neu
  rechnen, ohne Neuimport.
- **Ein Schreiber je Aufgabenart:** Langläufer schreibt der Worker, kurze
  Griffe der Web-Prozess. SQLite im WAL-Modus, nie auf einem Netzlaufwerk.
- **Herkunft getrennt:** aus der Datei extrahiert, daraus interpretiert
  und vom Menschen gesetzt sind drei getrennte Ablagen.
- **Erst messen, dann bauen:** Jede Skalierungsentscheidung ist gegen
  250.000 synthetische Medien gemessen. SQLite bleibt, weil die Zahlen es
  tragen.
- **Wenige, benannte Abhängigkeiten:** sechs direkte zur Laufzeit
  (Pillow, fastapi, uvicorn, starlette, anyio, pydantic), jede weitere
  steht mit Version und Prüfsumme im Lock; dazu ffprobe/ffmpeg als
  System-Programm. Das Frontend hat keine Bibliothek und keinen
  Build-Schritt.

Das Datenmodell mit allen Tabellen steht in der
[Schema-Referenz](schema.md).
