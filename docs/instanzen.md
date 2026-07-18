# Mehrere Instanzen: getrennte Galerien aus einem Programm

> Was ist das? Die Feral Media Library (fml) kann beliebig oft
> **parallel** laufen — aus demselben Programmordner. Eine **Instanz** ist: eine Config-Datei + eine eigene
> Datenbank + ein eigener Port. Jede Instanz ist eine vollständig
> eigenständige Galerie mit eigenem Katalog, eigenen Bewertungen, Tags,
> gespeicherten Suchen und eigener Sperrliste.

## Wozu? Der Subgalerie-Anwendungsfall

Das Hauptszenario: Du hast eine **konsolidierte Gesamt-Library** (alle
Medien, von einer Instanz mit Library-Verwaltung gepflegt) und möchtest
davon **themenspezifische Teilansichten** anbieten — etwa eine kuratierte
Auswahl zum Vorzeigen oder eine Galerie je Projekt. Genau dafür sind
Instanzen gebaut:

- Die **Hauptinstanz** verwaltet die Dateien (Import, Dubletten,
  Datumsstruktur).
- Jede **Subinstanz** läuft im Übersichtsmodus und **katalogisiert
  dieselben Dateien nur**: Sie liest sie, fasst sie aber garantiert nie an
  (kein Kopieren, kein Verschieben, kein Löschen — serverseitig gesperrt).
- Ihre Auswahl trifft die Subinstanz per **Ablehnen**: Was nicht zum Thema
  gehört, fliegt aus *ihrem* Katalog — die Datei und die Hauptinstanz
  bleiben unberührt.

Ergebnis: dieselben Dateien auf der Platte, mehrere unabhängige Sichten im
Browser — unterscheidbar per Instanzname, Akzentfarbe und Port.

## Das Modell: Was eine Instanz ausmacht — und was geteilt wird

| | je Instanz | geteilt |
| --- | --- | --- |
| Config-Datei (`--config`) | ✔ | |
| Datenbank (Katalog, Bewertungen, Tags, Notizen, gespeicherte Suchen, Sperrliste, Import-Log) | ✔ | |
| Port, Name, Akzentfarbe (`[web]`) | ✔ | |
| Watchordner-Liste, Library-Verwaltung an/aus | ✔ | |
| Programmordner (Code, `.venv`) | | ✔ |
| Mediendateien auf der Platte | | ✔ (werden nur gelesen, außer beim Import der verwaltenden Instanz) |
| Thumbnail-Cache | | ✔ wenn die DBs im selben Ordner liegen (siehe unten) |

Der Thumbnail-Cache liegt im Ordner `cache/` **neben der jeweiligen
DB-Datei**. Liegen mehrere Instanz-DBs im selben Ordner (der einfachste
Aufbau), teilen sie sich den Cache — das ist unbedenklich und sogar
sparsam, weil Thumbnails über den Datei-Hash adressiert sind: dieselbe
Datei bekommt in jeder Instanz dasselbe Vorschaubild und wird nur einmal
gerechnet. Zu wissen: „Cache leeren" (Admin → Wartung) trifft dann alle
Instanzen; die Vorschaubilder bauen sich beim Ansehen von selbst neu.

## Eine zweite Instanz anlegen (Schritt für Schritt)

**1. Config-Datei anlegen** — im Programmordner (neben `start.bat`), z. B.
`archiv.toml`. Drei Einträge genügen:

```toml
[database]
path = "./archiv.sqlite"        # eigene DB — NIE die einer anderen Instanz

[web]
port = 8801                     # eigener Port — je Instanz ein anderer
name = "Archiv"                 # erscheint in Topbar, Tab-Titel und Favicon
```

Optional dazu: `akzentfarbe = "#3b82f6"` unter `[web]` färbt die
Oberfläche dieser Instanz. Alle weiteren Einstellungen (Watchordner,
Library-Verwaltung, Thumbnail-Größe …) brauchst du hier nicht
einzutragen — die pflegst du nach dem Start in der GUI dieser Instanz.

**2. Starten** — mit `--config`:

| System | Befehl |
| --- | --- |
| Windows | `start.bat --config archiv.toml` |
| macOS / Linux | `./start.sh --config archiv.toml` |

Der Browser öffnet sich auf dem Port dieser Instanz, sobald der Server
bereit ist. Die erste Instanz startest du weiter ganz normal ohne
Argumente (`start.bat` nutzt `config.toml`) — beide laufen gleichzeitig,
jede in ihrem eigenen Browser-Tab.

**3. Konfigurieren** — in der GUI der neuen Instanz (Admin →
Konfiguration). Wichtig zu verstehen: **Die GUI bearbeitet genau die
Config-Datei, mit der die Instanz gestartet wurde.** Änderungen in der
Archiv-Instanz landen in `archiv.toml` und berühren `config.toml` nie.

**4. Stoppen** — das Terminal-/Konsolenfenster der Instanz schließen
(oder `Strg+C`). Jede Instanz hat ihr eigenes Fenster.

## Walkthrough: Subgalerie „Natur" aus der Gesamt-Library

Ausgangslage: Die Hauptinstanz (`config.toml`, Port 8765) verwaltet die
Library unter `D:\Media\Library`.

1. `natur.toml` anlegen: DB `./natur.sqlite`, Port `8802`, Name `Natur`.
2. `start.bat --config natur.toml` — die Natur-Instanz öffnet sich leer
   und im **Übersichtsmodus** (Standard; Badge „👁" in der Topbar).
   Die Library-Verwaltung bleibt hier bewusst AUS.
3. In der Natur-Instanz: Admin → Quellen & Import → Pfad
   `D:\Media\Library`, Modus **„katalogisieren"**, „dauerhaft beobachten"
   → Aufnehmen. Die Instanz indiziert den kompletten Bestand am Ort —
   keine Datei wird kopiert oder bewegt, es entsteht nur ihr eigener
   Katalog. (Ein Unterordner statt der ganzen Library geht genauso.)
4. Kuratieren: Alles, was nicht zum Thema gehört, **ablehnen** — einzeln
   (Entf), per Multiselect oder mit „⚡ Sammel-Aktion → ablehnen" auf ein
   ganzes Suchergebnis (z. B. erst `-tag: natur` filtern). Abgelehntes
   verschwindet aus dem Natur-Katalog und bleibt auf der Sperrliste
   dieser Instanz — der Watchordner nimmt es nicht wieder auf. Datei und
   Hauptinstanz: unverändert.
5. Ab jetzt: Port 8765 zeigt alles, Port 8802 nur Natur. Was die
   Hauptinstanz neu importiert, taucht in der Natur-Instanz automatisch
   zur Einsortierung auf — behalten oder ablehnen, einmal pro Datei.

## Grenzen (bewusst so)

- **Eine DB, ein Server:** Zwei Instanzen dürfen **nie** dieselbe
  DB-Datei verwenden (`[database] path` muss je Instanz eindeutig sein) —
  pro Datenbank gibt es genau einen schreibenden Prozess (ADR 0007).
  Ebenso muss der Port je Instanz eindeutig sein; ein belegter Port
  bricht den Start mit Fehlermeldung ab.
- **Genau eine Instanz verwaltet Dateien:** Die Library-Verwaltung
  (Import/Rausverschieben in dieselbe Library-Wurzel) gehört in EINE
  Instanz. Alle weiteren Instanzen katalogisieren nur — sie brauchen die
  Verwaltung nicht, und zwei unabhängig importierende Instanzen auf
  derselben Wurzel würden sich gegenseitig Dubletten einschleppen.
- **Kein Abgleich zwischen Instanzen:** Bewertungen, Tags, Notizen und
  gespeicherte Suchen sind je Instanz eigenständig und werden nicht
  synchronisiert. Eine Subgalerie ist eine eigene Kuratier-Ebene, kein
  gespiegelter Ausschnitt.
- **Backup je Instanz:** Jede Instanz hat ihre eigene `*.sqlite`-Datei —
  alle sichern, die dir wichtig sind.
