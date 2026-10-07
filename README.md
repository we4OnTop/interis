# Interis

Lokales, offline laufendes Werkzeug zum Verwalten, Transkribieren und Vergleichen der
Interviews für die Masterarbeit (Deutsch, Interviewer + eine befragte Person).

- [PLAN.md](PLAN.md): Ziele, Features, Phasen
- [ARCHITECTURE.md](ARCHITECTURE.md): Architektur, Datenmodell, API, Sicherheitskonzept
- [DEPENDENCIES.md](DEPENDENCIES.md): Abhängigkeiten, bekannte CVEs, Schutz vor Datenabfluss

**Wichtig:** Interviewdaten (Audio, Datenbank, Exporte, Modelle) gehören **nie** in dieses
Repository. Sie liegen ausschließlich im verschlüsselten Datenverzeichnis. Die `.gitignore`
blockiert die üblichen Dateitypen zusätzlich.

## Stand

- Transkription (Whisper large-v3, Wort-Alignment, Sprechertrennung) → JSON/DOCX/TXT
- Fragenerkennung, Leitfaden-Zuordnung, „an anderer Stelle beantwortet“
- Website mit Splitscreen aller Interviews pro Leitfadenfrage

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
   - `-UseSystemCerts`: nötig, wenn ein Virenscanner HTTPS aufbricht (z. B. Kaspersky).
   - Sprechertrennungs-Modell (pyannote): bevorzugt bei Hugging Face die Bedingungen von
     [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
     akzeptieren, einen **Read**-Token erstellen und vor dem Skript `$env:HF_TOKEN = "hf_..."`
     setzen. Der Token wird nicht gespeichert; danach bei Hugging Face wieder löschen.
     Alternativ `-AllowVerifiedMirror`: identische Dateien aus einem freien Spiegel, geprüft
     gegen die Prüfsummen des offiziellen Repos.
4. **Internet für Interis sperren** (PowerShell **als Administrator**, im Projektordner):
   ```powershell
   .\scriptsirewall.ps1
   ```
5. **Selbsttest:** `uv run interis doctor`

Updates später: `git pull`, dann `uv sync --locked`.

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
| `--speakers 2` | Anzahl der Sprecher (Standard 2; `0` = automatisch) |
| `--no-diarize` / `--no-align` | Sprechertrennung / Wort-Alignment überspringen |

Ergebnis in `X:\interis-data\exports\I01\`:
- `I01.json`: verlustfrei, mit allen Wörtern, Zeitstempeln, Wahrscheinlichkeiten und Metadaten
- `I01.docx`: zum Lesen und Korrigieren; unsichere Wörter sind gelb markiert, gleichzeitiges
  Sprechen kursiv
- `I01.txt`: Klartext mit Zeitstempeln

## Interviewleitfaden

Als Markdown-Datei, z. B. `X:\interis-data\leitfaden.md`:

```markdown
# Leitfaden Masterarbeit
## Einstieg
- F1: Erzählen Sie mir, wie Ihr Arbeitsalltag aussieht.
  ~ Wie sieht ein typischer Arbeitstag bei Ihnen aus?     (andere Formulierung)
  > Seit wann sind Sie in dieser Position?                 (geplante Nachfrage)
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

## Website: alle Interviews nebeneinander

```powershell
uv run interis serve            # öffnet den Browser; nur von diesem PC erreichbar
```

Den Leitfaden als `leitfaden.md` in den Datenordner legen oder mit `--guide` angeben.
Nach Änderungen am Leitfaden einmal `uv run interis analyze --all` ausführen.

**Vergleich (Splitscreen):** eine Zeile pro Leitfadenfrage, eine Spalte pro Interview. Jede
Zelle zeigt:
- wie und wann du die Frage gestellt hast;
- die Antwort, einschließlich deiner Nachfragen;
- Stellen, die die Frage *an anderer Stelle* beantworten (vorweg, später oder ohne Frage).

Jede Stelle kannst du mit ▶ anhören.

| Was du tun willst | So geht's |
|---|---|
| Eine Antwort beantwortet auch eine andere Frage | im Vergleich ↗ neben der Antwort, **oder** im Transkript den Text markieren → „Antwort auf Frage …“. Optional „Frage deshalb weggelassen“ ankreuzen |
| Frage falsch zugeordnet (anders formuliert) | auf das blaue Fragen-Kürzel klicken → richtige Leitfadenfrage wählen |
| Eine Frage wurde nicht erkannt | im Transkript markieren → „Als Frage markieren“ |
| Etwas wurde fälschlich als Frage erkannt | Kürzel anklicken → „Ist keine Frage“ |
| Automatischer Vorschlag | ✓ übernehmen oder ✕ verwerfen |

Deine Entscheidungen werden in `interis.db` im Datenordner gespeichert. Die Transkripte
selbst bleiben unverändert. Fehlt die Audiodatei eines Interviews:
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

```powershell
uv run pytest                 # Tests
uv run ruff check src tests   # Linter
uv run pip-audit              # bekannte Sicherheitslücken
```
