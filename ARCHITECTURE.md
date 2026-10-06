# Interis – Architecture

Status: v1, 2026-10-06 · Companion docs: [PLAN.md](PLAN.md), [DEPENDENCIES.md](DEPENDENCIES.md)

Target: Windows 11 laptop, Intel Core i7 11th gen, 32 GB RAM, CPU-only.
Language: German. Speakers: interviewer (you) + one interviewee.
Transcription goal for now: **raw and precise**. Transcription rules (e.g. Dresing & Pehl) are
added later as *export transformations*, never applied to the stored raw data.

---

## 1. Design decisions (and why)

| # | Decision | Reason |
|---|---|---|
| D1 | **No `whisperx` package. Build a WhisperX-style pipeline directly from its components** (faster-whisper, pyannote.audio, wav2vec2 CTC alignment). | `whisperx` pins `torch~=2.8`, which is affected by **CVE-2026-24747** (critical RCE in the `weights_only` unpickler, fixed in torch 2.10). It also downloads NLTK data and alignment models at runtime. Building it ourselves lets us use torch ≥ 2.10, removes NLTK and gives full control over every network access. The method stays the same, so we still cite Bain et al. 2023. |
| D2 | **One audio decoder: PyAV** (already bundled with faster-whisper). Audio is decoded once to 16 kHz mono float32 and passed in memory to every model. | pyannote 4 otherwise uses torchcodec, which needs separately installed FFmpeg DLLs on Windows (fragile, and one more binary to keep patched). A single decoder means less to maintain and a smaller attack surface. |
| D3 | **Single local process group: FastAPI (API + static frontend) + one ML worker process.** Bound to `127.0.0.1` only. | No CORS, one origin, nothing reachable from the network. A crash or out-of-memory error in the heavy ML work cannot kill the UI. |
| D4 | **SQLite + files in one data directory inside an encrypted VeraCrypt container.** | Zero-admin storage that is easy to back up, encrypt and delete. |
| D5 | **Machine output is immutable. Human edits are stored as new revisions.** | Precision and traceability: you can always show what the model produced and what you changed (good practice for the thesis methods). |
| D6 | **Defense in depth against data leaks:** env opt-outs → in-process network guard → OS firewall rule. | No single layer is trusted alone. See §6. |
| D7 | **Frontend is built once into static files and served by FastAPI.** Node is only needed at build time. | No Node runtime or npm code runs while you work with interview data. |

## 2. Component overview

```
┌──────────────────────────── Laptop (Windows 11) ────────────────────────────┐
│                                                                             │
│  Browser (dedicated profile, no extensions)                                 │
│     │  http://127.0.0.1:8765  (session cookie, same-origin only)            │
│     ▼                                                                       │
│  ┌──────────────── interis-server (Python, uvicorn) ───────────────┐        │
│  │ Security middleware: Host allowlist · Origin check · session    │        │
│  │ token · CSP · upload limits                                     │        │
│  │ FastAPI routers: interviews, audio, transcripts, guide,         │        │
│  │ questions, links, compare, search, jobs, export, settings       │        │
│  │ Static files: web/dist (React build)                            │        │
│  └───────────────┬─────────────────────────────────────────────────┘        │
│                  │ SQLite (jobs table = queue)                              │
│  ┌───────────────▼──────────── interis-worker (Python) ────────────┐        │
│  │ Network guard (audit hook) · offline env · telemetry off        │        │
│  │ Pipeline steps (each cached to data/cache/<interview>/):        │        │
│  │  1 decode (PyAV)  2 ASR (faster-whisper)  3 align (wav2vec2)    │        │
│  │  4 diarize (pyannote)  5 merge  6 speaker-ID  7 questions       │        │
│  │  8 answer suggestions (sentence-transformers)                   │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                             │
│  VeraCrypt volume  X:\interis-data\                                         │
│    db.sqlite · audio\<uuid>.<ext> · cache\ · exports\ · models\ · logs\     │
│                                                                             │
│  Windows Firewall: outbound BLOCK for <venv>\python.exe                     │
└─────────────────────────────────────────────────────────────────────────────┘
        ▲ Internet used ONLY by the explicit one-time `interis setup-models`
          command (separate step, verified hashes), then never again.
```

## 3. Processing pipeline (worker)

Each step is a pure function `input artifacts → output artifact (JSON/NPZ)` with a hash of
its inputs and parameters. If an input hash is unchanged, the step is skipped, so a run can
resume after a crash or sleep, and one step can be re-run alone.

| Step | Implementation | Output | Precision settings |
|---|---|---|---|
| 1 Decode | PyAV → 16 kHz mono float32. The sha256 of the original file is stored. | `audio.npy` | Original file kept unchanged. |
| 2 ASR | faster-whisper `WhisperModel` (CPU) | segments + words + per-word probability | `language="de"`, `beam_size=5`, temperature fallback (default), `condition_on_previous_text=False` (prevents repetition loops), `vad_filter=True` (Silero VAD, bundled ONNX), `word_timestamps=True`. Model: **large-v3** for the final transcript (max precision) or **large-v3-turbo** for fast drafts. Compute type `int8` by default, `float32` optional for max precision. Optional per-project **glossary** passed as `hotwords` (names, technical terms). |
| 3 Align | wav2vec2 CTC forced alignment (German model) with a CTC trellis/Viterbi port of WhisperX's alignment (BSD-2, attributed) | refined word start/end | Word timing precise to roughly tens of milliseconds. Needed to cut speaker turns exactly. |
| 4 Diarize | pyannote.audio 4 `speaker-diarization-community-1`, given the in-memory waveform, `num_speakers=2` | regular + **exclusive** speaker timeline, speaker embeddings | Exclusive timeline is used for word assignment. Overlap regions are kept for flags. |
| 5 Merge | own code | words → speaker → turns | Each word gets the speaker with maximum overlap. Words in overlap regions get `overlap=true`. |
| 6 Speaker-ID | cosine similarity of cluster embedding vs enrolled voice | role per speaker + similarity score | Below the threshold → UI asks. |
| 7 Questions | rules (German interrogatives, `?`, verb-first, narrative prompts) | question candidates with reason codes | Every mark records *why* it was set. |
| 8 Guide match + answer suggestions | sentence-transformers `multilingual-e5-base` | suggestions (status `suggested`) | Never auto-confirmed. |

Raw output is never modified. Whisper tends to drop fillers ("äh", "ähm") and false starts.
A true verbatim transcript therefore needs your review pass. Low-confidence words are
highlighted to speed this up. An optional *verbatim prompt* (an `initial_prompt` containing
fillers) can be tested in Phase 1 to see if it keeps more disfluencies, but it stays off
unless it is measurably better.

## 4. Data model (SQLite via SQLModel, migrations via Alembic)

```
Project(id, name, created_at)
GuideVersion(id, project_id, version, created_at, frozen)
  GuideSection(id, guide_version_id, order, title)
    GuideQuestion(id, section_id, order, code "F3.2", text, variants[json], probes[json])

Interview(id uuid, project_id, pseudonym "I03", date, duration_s, status, consent_note, notes)
AudioFile(id uuid, interview_id, stored_name uuid.ext, sha256, original_ext, size, deleted_at)
Speaker(id, interview_id, diar_label "SPEAKER_00", role interviewer|interviewee|unknown,
        display_name, similarity)
EnrolledVoice(id, label, embedding blob, model_rev, created_at)

Transcript(id, interview_id, kind machine|human, parent_id, created_at,
           pipeline_meta[json: model names, HF revisions, package versions, params])
Turn(id, transcript_id, idx, speaker_id, start, end)
Word(id, turn_id, idx, text, start, end, prob, overlap bool)
   (human revisions copy the turns/words they change, and keep references back to the machine words)

QuestionMark(id, transcript_id, start_word_id, end_word_id, kind main|followup|prompt,
             guide_question_id null, reason_codes[json], source auto|manual,
             status suggested|confirmed|rejected)
AnswerLink(id, transcript_id, start_word_id, end_word_id, guide_question_id,
           type direct|anticipated|later|partial, skipped_because_answered bool,
           source auto|manual, status suggested|confirmed|rejected, score, note)
Memo(id, interview_id null, guide_question_id null, text)        -- comparison-cell notes
Job(id, interview_id, step, state queued|running|done|failed, progress, error, timestamps)
Glossary(id, project_id, term)
PseudonymEntry(id, real, pseudonym)   -- stored in a SEPARATE database file
FTS5 virtual table over turn text for full-text search
```

## 5. API (FastAPI, JSON, all under `/api`, all require the session cookie)

```
GET/POST        /interviews                 list / create (metadata)
POST            /interviews/{id}/audio      upload (streamed to disk, size-limited, sniffed)
GET             /interviews/{id}/audio      range-request streaming for the player
POST            /interviews/{id}/process    enqueue pipeline (params: model, compute_type)
GET             /jobs?active=1              progress polling
GET             /interviews/{id}/transcript latest revision (turns + words)
PATCH           /transcripts/{id}           edits → new human revision
PUT             /speakers/{id}              role/name
GET/PUT         /guide                      guide versions, sections, questions
GET/PATCH       /questions?interview=       question marks (confirm/reject/relink)
GET/POST/PATCH  /links?interview=|question= answer links
GET             /compare?question={gq_id}   side-by-side payload (one column per interview)
GET             /compare/matrix             questions × interviews coverage + previews
GET             /search?q=                  FTS5 search
POST            /export/{kind}              docx | xlsx-matrix | json → file in data/exports
POST            /enroll                     voice enrollment (audio from browser mic)
DELETE          /interviews/{id}/audio      delete original audio (retention)
```

## 6. Security architecture (no data leaks)

### 6.1 Threats considered
1. A library phones home (telemetry, update checks, model downloads).
2. A malicious or compromised dependency (supply chain), at install time or at runtime.
3. A malicious model file (pickle deserialization → code execution).
4. A website in your normal browser attacking the local server (DNS rebinding, CSRF).
5. Files leaving the machine via OS features (OneDrive backup, search indexing, crash dumps),
   theft of the laptop, or browser extensions reading the page.

### 6.2 Controls

**Network egress (threat 1, 2), layered:**
1. `interis/_bootstrap.py` is imported first in every entry point and sets, *before any ML
   import*: `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`,
   `PYANNOTE_METRICS_ENABLED=0` (pyannote 4 has **OpenTelemetry metrics on by default**,
   sent to otel.pyannote.ai), `OTEL_SDK_DISABLED=true`, `DO_NOT_TRACK=1`, `HF_HOME` → the
   models folder inside the encrypted volume. It also sets
   `torch.hub` dir to the same folder.
2. **In-process network guard:** a `sys.addaudithook` that raises on `socket.connect`,
   `socket.getaddrinfo` and `socket.sendto` to any non-loopback address, and logs the
   attempted host. A test asserts that a full pipeline run triggers zero attempts.
   (It only sees Python-level sockets, which is why layer 3 exists.)
3. **OS-level:** a Windows Defender Firewall *outbound block* rule for the virtualenv's
   `python.exe` (created by a setup script, verified by `interis doctor`). This also covers
   native code (CTranslate2, ONNX Runtime).
4. Model download happens only in an explicit `interis setup-models` command. It runs
   without the guard, uses pinned revisions, and verifies sha256 against a committed
   manifest. The HF token is read from an env var for that one run and is never stored.

**Supply chain (threat 2):**
- Python: `uv` with committed `uv.lock` (hashes), `uv sync --locked`,
  `[tool.uv] exclude-newer = "7 days"` (cooldown against freshly published malicious
  releases), and PyTorch only from the official CPU index, scoped to torch/torchaudio.
- Audits: `pip-audit` + `osv-scanner` on the lockfile, before every dependency update and
  in a pre-commit/CI task.
- Frontend: **pnpm 10** (lifecycle scripts off by default), `minimumReleaseAge: 10080`
  (7 days), committed lockfile, `pnpm audit`, few dependencies (see DEPENDENCIES.md).
- No `trust_remote_code`. No dynamic plugin loading. No `subprocess(shell=True)`.

**Model files (threat 3):**
- torch ≥ 2.10 (fixes CVE-2025-32434 and CVE-2026-24747), with `weights_only=True` loading.
- Models pinned by HF commit hash, file hashes in `models.lock.json`, checked at worker
  start.
- Pickle-only checkpoints (e.g. a `.bin` wav2vec2 model) are **converted once to
  safetensors** during setup and from then on loaded only from safetensors.
- CTranslate2 ≥ 4.8.1 (fixes CVE-2026-102566/-102567 in its model loader).

**Local web server (threat 4):**
- Bind `127.0.0.1` only, never `0.0.0.0`.
- `TrustedHostMiddleware(allowed_hosts=["127.0.0.1","localhost"])` against DNS
  rebinding. Starlette ≥ 1.3.1 (fixes BadHost CVE-2026-48710 and the form-limit DoS
  CVE-2026-54283).
- **Session token:** the launcher generates a random token at start and opens
  `http://127.0.0.1:8765/#login=<token>`. The page exchanges it for an
  `HttpOnly; SameSite=Strict` cookie. Every API call requires the cookie.
- Origin/Referer check on all state-changing requests. No CORS middleware at all.
- Security headers: `Content-Security-Policy: default-src 'self'; media-src 'self' blob:;
  object-src 'none'; frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`. The frontend loads **no** CDN scripts or web fonts.
- Uploads: streamed, size cap, magic-byte sniffing, stored under a UUID name (the user's
  filename is never used as a path).
- Interview text is rendered as text, never as HTML (no `dangerouslySetInnerHTML`).

**Host / at rest (threat 5):**
- Data directory **only inside a VeraCrypt container** (independently audited), mounted
  when you work. The default path is outside Desktop/Documents. Windows 11 may silently
  back up those folders to OneDrive. `interis doctor` warns if the data dir is
  under a OneDrive-synced path.
- Exclude the data dir from Windows Search indexing. Temp files go to `data/tmp`, not
  `%TEMP%`.
- Logs contain IDs, step names and timings, **never transcript text or names**.
- Pseudonym mapping lives in a separate DB file (ideally a separate container).
- Use a **dedicated browser profile without extensions** for the app, because extensions
  can read page content.
- Backups: copy the encrypted container itself, never the mounted plain files.

## 7. Repository layout

```
interis/
  pyproject.toml  uv.lock  models.lock.json
  src/interis/
    _bootstrap.py          env opt-outs + network guard (imported first)
    config.py              paths, settings (pydantic-settings)
    cli.py                 setup-models | doctor | transcribe | serve | worker
    pipeline/
      decode.py asr.py align.py diarize.py merge.py speaker_id.py
      questions.py answers.py embeddings.py cache.py
    db/      models.py session.py migrations/
    api/     app.py security.py routers/*.py
    worker/  runner.py
    export/  json_export.py docx_export.py xlsx_export.py   (qda/ later)
  web/       package.json pnpm-lock.yaml .npmrc src/ (React + TS)
  tests/     unit/ pipeline/ (short German sample) api/ security/ (guard, host, csrf)
  scripts/   firewall.ps1  create-container.md
```
