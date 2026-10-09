# Interis

Lokales, offline laufendes Werkzeug zum Verwalten, Transkribieren und Vergleichen der
Interviews für die Masterarbeit (Deutsch, Interviewer + eine befragte Person).

- [PLAN.md](PLAN.md): Ziele, Features, Phasen
- [ARCHITECTURE.md](ARCHITECTURE.md): Architektur, Datenmodell, API, Sicherheitskonzept
- [DEPENDENCIES.md](DEPENDENCIES.md): Abhängigkeiten, bekannte CVEs, Schutz vor Datenabfluss
- [docs/ABLAUF.md](docs/ABLAUF.md): Ablauf der Auswertung, Schritt für Schritt
- [docs/METHODEN.md](docs/METHODEN.md): methodische Grundlagen und offene Prüfpunkte

**Wichtig:** Interviewdaten (Audio, Datenbank, Exporte, Modelle) gehören **nie** in dieses
Repository. Sie liegen ausschließlich im verschlüsselten Datenverzeichnis. Die `.gitignore`
blockiert die üblichen Dateitypen zusätzlich.

## Stand

- Transkription (Whisper large-v3, Wort-Alignment, Sprechertrennung) → JSON/DOCX/TXT
- Fragenerkennung, Leitfaden-Zuordnung, „an anderer Stelle beantwortet“
- Website: Projekte, Splitscreen aller Gespräche pro Leitfadenfrage, Korrektur und Glättung
  am Transkript (ohne das Original zu ändern), Begründung fehlender Fragen, Extraktion
  mit Export als Word oder CSV

## Ablauf

Die Auswertung läuft in acht Schritten: Leitfaden festlegen, Transkribieren, Korrigieren,
Glätten (optional), Fragen zuordnen, Fehlende Fragen klären, Extrahieren, Exportieren.
Was du in Interis bei jedem Schritt tust und wann er erledigt ist, steht in
[docs/ABLAUF.md](docs/ABLAUF.md). Die Seite **Ablauf** in der Oberfläche zeigt den Stand jedes
Gesprächs. Die methodischen Grundlagen und die Punkte, die vor dem Zitieren zu prüfen sind,
stehen in [docs/METHODEN.md](docs/METHODEN.md). Beide Dokumente sind keine Methodenbeschreibung
für die Masterarbeit.

## Installation auf einem neuen PC (z. B. dem Laptop)

Voraussetzungen: [Git](https://git-scm.com), [uv](https://docs.astral.sh/uv/)
(`winget install --id=astral-sh.uv -e`), [VeraCrypt](https://veracrypt.io).

1. **Verschlüsselten Datenordner anlegen:** einen VeraCrypt-Container erstellen und
   einbinden, z. B. als Laufwerk `X:`. Darin den Ordner `X:\interis-data` anlegen. Er darf
   nicht auf dem Desktop, unter Dokumente oder in OneDrive liegen.
2. **Code holen.** Das Repo ist privat; einmalig `gh auth login` oder ein Git-Login nötig:
   ```powershell
   git clone https://github.com/we4OnTop/interis.git
   cd interis
   ```
3. **Installieren** (normale PowerShell, im Projektordner):
   ```powershell
   .\scripts\install.ps1 -DataDir X:\interis-data
   ```
   Das Skript installiert die festgelegte Umgebung, merkt sich den Datenordner, lädt und
   prüft die Modelle (etwa 8 GB) und zeigt die nächsten Schritte. Hilfreiche Optionen:
   - `-ModelsFrom E:\interis-models`: Modelle von einem USB-Stick übernehmen, statt sie
     herunterzuladen. Kopiert wird der Ordner `models` eines anderen PCs; geprüft wird per
     Prüfsumme.
   - Bricht ein Virenscanner HTTPS auf (z. B. Kaspersky, Fehler `CERTIFICATE_VERIFY_FAILED`):
     dessen Stammzertifikat als PEM exportieren und vor dem Skript
     `$env:SSL_CERT_FILE = "C:\pfad\zertifikat.pem"` setzen, oder die Modelle mit
     `-ModelsFrom` von einem anderen PC übernehmen.
   - Sprechertrennungs-Modell (pyannote): bevorzugt bei Hugging Face die Bedingungen von
     [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
     akzeptieren, einen **Read**-Token erstellen und vor dem Skript `$env:HF_TOKEN = "hf_..."`
     setzen. Der Token wird nicht gespeichert; danach bei Hugging Face wieder löschen.
     Alternativ `-AllowVerifiedMirror`: identische Dateien aus einem freien Spiegel, geprüft
     gegen die Prüfsummen des offiziellen Repos.
4. **Internet für Interis sperren** (PowerShell **als Administrator**, im Projektordner):
   ```powershell
   .\scripts\firewall.ps1
   ```
5. **Selbsttest:** `uv run interis doctor`

Updates später: `git pull`, dann `uv sync --locked --no-dev`.

## Transkribieren

```powershell
uv run interis transcribe "X:\interis-data\audio\interview01.m4a" --id I01
```

| Option | Bedeutung |
|---|---|
| `--id I01` | Pseudonym des Interviews (sonst aus dem Hash abgeleitet; der Dateiname wird nie verwendet) |
| `--model whisper-large-v3-turbo` | schneller Entwurf; Standard ist `whisper-large-v3` (am genauesten) |
| `--compute-type float32` | maximale Genauigkeit, langsamer (Standard `int8`) |
| `--hotwords "Name1 Fachbegriff"` | Glossar für die richtige Schreibweise von Namen/Begriffen |
| `--room-mic` | ein Mikrofon im Raum: gleicht leise/laute Stimmen an, erkennt leise Sprache besser |
| `--beam-size 1…10` | Suchbreite; 1 = am schnellsten, 5 = Standard |
| `--vad-threshold 0.1…0.9` | Sprach-Empfindlichkeit; niedriger findet leisere Sprache |
| `--min-duration-off 0…2` | Sprechertrennung: kürzere Pausen eines Sprechers überbrücken (Sekunden) |
| `--start 300 --duration 180 --out probe.json` | nur einen Ausschnitt, Ergebnis nur in diese Datei |
| `--speakers 2` | Anzahl der Sprecher (Standard 2; `0` = automatisch) |
| `--no-diarize` / `--no-align` | Sprechertrennung / Wort-Alignment überspringen |

Ergebnis in `X:\interis-data\exports\I01\`:
- `I01.json`: verlustfrei, mit allen Wörtern, Zeitstempeln, Wahrscheinlichkeiten und Metadaten
- `I01.docx`: zum Lesen und Korrigieren; unsichere Wörter sind gelb markiert, gleichzeitiges
  Sprechen kursiv
- `I01.txt`: Klartext mit Zeitstempeln

### Aufnahmen mit Raummikrofon

Hall und Abstand kosten mehr Genauigkeit als jede Einstellung. In dieser Reihenfolge wirkt es:

1. **Aufnahme:** Mikrofon oder Handy höchstens 1 m von beiden entfernt, zwischen euch, auf
   einem weichen Untergrund (Tuch, Buch), nicht auf einem hallenden Tisch. Kleiner Raum mit
   Teppich oder Vorhängen statt Besprechungsraum mit Glas. Wenn möglich zweites Handy direkt
   bei der befragten Person als Reserve.
2. **Glossar** (Projekt-Einstellungen): Namen und Fachbegriffe, die im Gespräch fallen
   (z. B. `Miro Figma Wireframe Mockup Klickdummy Prototyp Anforderungserhebung`). Kurz
   halten, nur Begriffe, keine Sätze.
3. **„Ein Mikrofon im Raum“** im Reiter „Transkription“ (CLI: `--room-mic`).
4. **Probelauf:** Im Reiter „Transkription“ einen Ausschnitt (1–10 min) mit verschiedenen
   Einstellungen transkribieren und zwei Ergebnisse nebeneinander vergleichen (Text,
   Sprecher, unsichere Wörter, Rechenzeit). Unter „Schritte“ jede Verarbeitungsstufe anhören
   (Original, nach „Hall reduzieren“, angeglichen) und sehen, was jeder Schritt geliefert hat
   und wie lange er gedauert hat: Rohtext der Spracherkennung, wer wann spricht, Ausrichtung.
   Gute Einstellungen speichern und mit ★ für alle neuen Transkriptionen festlegen. Das
   Gespräch selbst bleibt dabei unverändert.
5. **Messen statt raten:** 3–5 Minuten selbst abtippen und die Varianten vergleichen, siehe
   `bench/wer.py`. „fehlend“ hoch = leise Sprache verloren, „falsch“ hoch = undeutlich oder
   unbekannte Begriffe.

Schneller: `whisper-large-v3-turbo` braucht nur einen Bruchteil der Zeit, ist aber etwas
ungenauer. Ob der Unterschied bei deinen Aufnahmen zählt, zeigt `bench/wer.py`.

## Interviewleitfaden

Als Markdown-Datei, z. B. `X:\interis-data\leitfaden.md`, oder als Typst-Datei mit
`#frage(...)[...]` und `#impuls[...]`: in der Website laden oder einfügen, sie wird umgewandelt.

```markdown
# Leitfaden Masterarbeit
## Einstieg
- F1: Erzählen Sie mir, wie Ihr Arbeitsalltag aussieht.
  ~ Wie sieht ein typischer Arbeitstag bei Ihnen aus?     (andere Formulierung)
  > Seit wann sind Sie in dieser Position?                 (geplante Nachfrage)
  ! nur, wenn der Alltag noch nicht erzählt wurde          (Hinweis für dich)
- F3: Wie lange sind Sie schon dabei? [optional]           ([optional]/[Nebenfrage]: darf entfallen)
## Künstliche Intelligenz
- F2: Welche Rolle spielt künstliche Intelligenz in Ihrer Arbeit?
- Wie gehen Sie mit vertraulichen Daten um?                (Code wird automatisch vergeben)
```

```powershell
uv run interis transcribe interview01.m4a --id I01 --guide X:\interis-data\leitfaden.md
# Leitfaden geändert? Analyse neu, ohne neu zu transkribieren:
uv run interis analyze X:\interis-data\exports\I01\I01.json --guide X:\interis-data\leitfaden.md
```

Ergebnis:
- Deine Fragen sind im Transkript markiert:
  - `[F1]` = Leitfadenfrage
  - `[F1 Nachfrage]` = geplante Nachfrage
  - `[Nachfrage]` = spontane Nachfrage
- Im Word-Dokument steht am Ende eine Tabelle „Leitfaden-Abdeckung“. Sie zeigt, welche
  Fragen wann gestellt wurden und wo sie möglicherweise schon vorher, später oder ohne
  Frage beantwortet wurden.
- Alle Markierungen sind **Vorschläge** und werden von dir geprüft.

## Website: Projekte, Gespräche, Auswertung

```powershell
uv run interis serve            # öffnet den Browser; nur von diesem PC erreichbar
```

Alles läuft über die Website, die Kommandozeile ist nicht nötig.

**Projekte:** Ein Projekt besteht aus einem Interviewleitfaden und den Gesprächen dazu.
Auf der Startseite mit „Neues Projekt“ anlegen. Im Projekt gibt es den Reiter
**Leitfaden & Gespräche** mit drei Reitern:

1. **Gespräche:** „Gespräch hinzufügen“: Kürzel vergeben (z. B. `I01`) und die Aufnahme
   auswählen. Gab es eine Pause, alle Aufnahmen des Gesprächs auswählen und in die richtige
   Reihenfolge bringen: Sie werden als ein Gespräch transkribiert (gleiche Sprecherzuordnung
   über die Pause hinweg), Zeiten erscheinen als „T2 · 03:15“ = Teil 2, Minute 3:15. Die
   Aufnahmen werden als `audio\I01-1.<endung>`, `audio\I01-2.<endung>` … in den Datenordner
   kopiert; Dateinamen werden nicht übernommen. „Transkription starten“ läuft im Hintergrund,
   eine nach der anderen, mit Fortschrittsanzeige. Abbrechen und erneut starten sind möglich;
   bereits fertige Schritte bleiben zwischengespeichert. Ein Gespräch lässt sich auch wieder
   entfernen: dann werden Transkript, Zwischenergebnisse, Markierungen und die hochgeladene
   Kopie gelöscht. Die Originaldatei bleibt unberührt.
2. **Leitfaden:** Fragen eingeben oder als Datei laden (`.docx`, `.md`, `.txt`). Rechts siehst
   du sofort, welche Fragen erkannt wurden. „Jede Zeile als Frage“ macht aus einer einfachen
   Liste Leitfadenfragen. Wird der Leitfaden später geändert, werden die Gespräche automatisch
   neu analysiert (ohne neu zu transkribieren).
3. **Einstellungen:** Glossar (Namen, Fachbegriffe) und Glättungs-Tags, eine Zeile pro Tag.
   Ohne eigene Tags gelten die Standardgründe.

Interviews, die über die Kommandozeile transkribiert wurden, landen im Projekt „Bestehende
Interviews“.

**Ansichten** (in der oberen Leiste des Projekts):

- **Ablauf:** die acht Schritte und der Stand jedes Gesprächs: Häkchen für erledigte Schritte,
  „offen: F3, F5“ für fehlende Leitfadenfragen und „Analyse veraltet“, wenn Änderungen nach
  der letzten Analyse gespeichert wurden.
- **Pro Frage** (zusammengefasst): links alle Leitfadenfragen mit farbigen Kästchen je
  Gespräch (gestellt / anderswo beantwortet / weggelassen / nicht gestellt – begründet /
  fehlt – begründen). Eine Frage wählen → alle Antworten aller Gespräche untereinander.
  ← / → blättert.
- **Nebeneinander** (getrennt): eine Zeile pro Leitfadenfrage, eine Spalte pro Gespräch.
  Hier ziehst du Fragen und Antworten per **Drag & Drop** auf die richtige Leitfadenfrage;
  auf die Zeile „Fragen ohne Leitfaden-Zuordnung“ gezogene Fragen werden spontane
  Nachfragen. Drag & Drop ist nur eine Abkürzung: jede Zuordnung geht auch über einen Dialog.
- **Transkript** eines Gesprächs. Ein Klick auf ein Wort spielt die Aufnahme ab. Die Modi
  oben im Transkript sind:
  - **Lesen:** zum Anhören und Markieren;
  - **Korrigieren:** falsch erkannte Wörter ersetzen;
  - **Glätten:** Füllwörter, Wiederholungen und Abbrüche entfernen oder ersetzen, jeweils mit
    Grund.
  Mit „Änderungen anzeigen“ werden die Änderungen sichtbar, mit „Korrektur abgeschlossen“
  hakst du die Korrektur ab.
- **Auswertung:** alle Kernaussagen (Extrakte) je Leitfadenfrage und Gespräch. Hier exportierst
  du die Tabelle mit „Als Word exportieren“ oder „Als CSV (Excel) exportieren“.

Unten erscheint beim Abspielen ein Player (Leertaste = Pause, Alt+←/→ = 5 s). Jede Zelle
bzw. Antwort zeigt:
- wie und wann du die Frage gestellt hast;
- die Antwort, einschließlich deiner Nachfragen;
- Stellen, die die Frage *an anderer Stelle* beantworten (vorweg, später oder ohne Frage).

Jede Stelle kannst du anhören.

| Was du tun willst | So geht's |
|---|---|
| Eine Antwort beantwortet auch eine andere Frage | Im Vergleich den Redebeitrag auf die Leitfadenfrage ziehen, **oder** im Transkript den Text markieren → „Antwort auf Frage …“. Die Checkbox „Diese Frage habe ich deshalb weggelassen“ setzen, wenn die Frage deshalb nicht gestellt wurde |
| Frage falsch zugeordnet | auf das Frage-Kürzel klicken → „Frage zuordnen“ → richtige Leitfadenfrage wählen |
| Eine Frage wurde nicht erkannt | im Transkript markieren → „Als Frage markieren“ |
| Etwas wurde fälschlich als Frage erkannt | Frage-Kürzel anklicken → „Ist keine Frage“ |
| Leitfadenfrage ohne Antwort | „Begründen“ → Nicht gestellt / Nicht relevant für diese Person / Sonstiges, mit Notiz |
| Automatischer Vorschlag | unter „Vorschläge – bitte prüfen“ übernehmen oder verwerfen |
| Kernaussage festhalten | im Transkript markieren → „Als Extrakt übernehmen …“ |
| Wort korrigieren | Modus „Korrigieren“, Wort anklicken oder Text markieren → „Ersetzen …“ |
| Füllwort entfernen | Modus „Glätten“, markieren → „Entfernen“, Grund wählen; danach „Analyse aktualisieren“ |

Deine Entscheidungen werden in `interis.db` im Datenordner gespeichert. Die Transkripte
selbst bleiben unverändert: Korrekturen, Glättungen und Begründungen liegen als eigene
Einträge daneben. Fehlt die Audiodatei eines Interviews:
`uv run interis set-audio I01 X:\interis-data\audio\interview01.m4a`.

## Stimmprofil (damit du sicher als „Interviewer“ erkannt wirst)

Etwa 60 Sekunden nur deine Stimme aufnehmen (z. B. einen Text vorlesen), dann:

```powershell
uv run interis enroll X:\interis-data\meine_stimme.wav
```

Ohne Stimmprofil wird der Interviewer daran erkannt, wer anteilig die meisten Fragen
stellt. Das Stimmprofil ist ein biometrisches Merkmal. Es bleibt im verschlüsselten
Datenordner (`voices\`) und landet nie in Transkripten oder Exporten.

## Zwischenspeicher

Zwischenergebnisse werden zwischengespeichert. Ein abgebrochener Lauf (z. B. weil der
Laptop in den Ruhezustand gegangen ist) macht beim nächsten Start dort weiter. Während
langer Läufe den Laptop ans Netzteil hängen und den Ruhezustand deaktivieren.

## Entwicklung

Oberfläche (`frontend/`, nur auf dem Entwicklungs-PC nötig, Node ≥ 22):

```powershell
cd frontend
npm ci            # installiert exakt die Versionen aus package-lock.json, ohne Skripte
npm run dev       # Entwicklungsserver auf :5173 (API von `interis serve` auf :8765)
npm run build     # schreibt nach src/interis/web/dist (wird mit eingecheckt)
```

Mit Live-Reload arbeiten (zwei Terminals):

```powershell
# Terminal 1: Backend (API auf :8765)
uv sync --locked
uv run interis serve --no-browser
# gibt einen Link aus: http://127.0.0.1:8765/#login=<TOKEN>

# Terminal 2: Oberfläche (Vite auf :5173, leitet /api an :8765 weiter)
cd frontend
npm run dev
```

Dann im Browser `http://localhost:5173/#login=<TOKEN>` öffnen, also den Link aus Terminal 1
mit Port **5173** statt 8765. Änderungen in `frontend/src` erscheinen sofort; nach Änderungen
am Python-Code `interis serve` neu starten (das gibt auch einen neuen Token). Ohne Live-Reload
reicht `npm run build` und der Link aus Terminal 1 direkt.

```powershell
uv run pytest                 # Tests
uv run ruff check src tests   # Linter
uv run pip-audit              # bekannte Sicherheitslücken
```
