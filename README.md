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

Phase 0 + 1: Kommandozeilen-Transkription (Whisper → Wort-Alignment → Sprechertrennung →
JSON/DOCX/TXT). Die Website folgt in späteren Phasen.

## Einrichtung (einmalig)

Voraussetzungen: [uv](https://docs.astral.sh/uv/), [VeraCrypt](https://veracrypt.io).

1. **Verschlüsselten Datenordner anlegen:** einen VeraCrypt-Container erstellen und
   einbinden, z. B. als Laufwerk `X:`. Darin den Ordner `X:\interis-data` anlegen. Er darf
   nicht auf dem Desktop, unter Dokumente oder in OneDrive liegen.
2. **Umgebung installieren** (im Projektordner):
   ```powershell
   uv sync
   $env:INTERIS_DATA_DIR = "X:\interis-data"
   ```
3. **Zugang zum Sprechertrennungs-Modell:** Bei Hugging Face anmelden, die Bedingungen von
   [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
   akzeptieren und unter *Settings → Access Tokens* einen **Read**-Token erstellen.
4. **Modelle laden.** Das ist der einzige Schritt mit Internetzugriff. Der Token wird nur
   für diesen Download verwendet und nicht gespeichert:
   ```powershell
   $env:HF_TOKEN = "hf_..."
   uv run interis setup-models          # ggf. mit --use-system-certs (Virenscanner mit HTTPS-Scan)
   Remove-Item Env:HF_TOKEN
   ```
   Danach den Token bei Hugging Face wieder löschen.
5. **Internet für die Interis-Python sperren** (PowerShell **als Administrator**):
   ```powershell
   .\scripts\firewall.ps1
   ```
6. **Selbsttest:**
   ```powershell
   uv run interis doctor
   ```

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

Zwischenergebnisse werden zwischengespeichert. Ein abgebrochener Lauf (z. B. weil der
Laptop in den Ruhezustand gegangen ist) macht beim nächsten Start dort weiter. Während
langer Läufe den Laptop ans Netzteil hängen und den Ruhezustand deaktivieren.

## Entwicklung

```powershell
uv run pytest                 # Tests
uv run ruff check src tests   # Linter
uv run pip-audit              # bekannte Sicherheitslücken
```
