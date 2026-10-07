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
- Frontend: **npm** with a committed `frontend/package-lock.json`, `ignore-scripts=true`
  (no install scripts run), `save-exact=true`, `npm audit`, few dependencies (see
  DEPENDENCIES.md). Open point: npm 10 has no release-age setting, so the 7-day cooldown
  that applies to Python is **not** enforced for the frontend. Moving to pnpm (which has one)
  is a decision still to be made.
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
- State-changing requests must send `X-Interis: 1`; an `Origin` header, when present, must be the local origin. There is no Referer check and no CORS middleware.
- Security headers: `Content-Security-Policy` as built in `web/base.py`: scripts only from
  the app's own files (`script-src 'self'`); styles from the app, a fresh per-response nonce
  (`'nonce-…'`, also written into the page's `csp-nonce` meta tag, which the UI library reads),
  and one hash for the scrollbar style of the Radix select; no `unsafe-inline`; images from the
  app or `data:` URIs (the favicon); `object-src 'none'`, `frame-ancestors 'none'`,
  `form-action 'none'`. Also `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`
  and `X-Frame-Options: DENY`. The frontend loads **no** CDN scripts or web fonts.
  `tests/test_csp.py` pins the nonce behaviour.
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

## 6a. Implementation notes (Phase 0/1, as built)

- **Data dir is mandatory:** `INTERIS_DATA_DIR` or `--data-dir`. There is no default, so data
  never lands somewhere unintended. `HF_HOME`, `TORCH_HOME` and `TMP`/`TEMP` are redirected
  into it.
- **Model lock** lives at `<data>/models/models.lock.json`, not in the repo, because local
  conversions are machine-specific. Pinned revisions are in `src/interis/models.py`.
- **Pickle scanner** (`security/pickle_scan.py`): static allowlist check of every `.bin`
  checkpoint (wav2vec2 at setup; pyannote at setup **and before every load**, because pyannote
  4.0.7 uses `torch.load(weights_only=False)`).
- **Firewall:** a Windows venv `python.exe` is a launcher, and the real process is the base
  interpreter. `scripts/firewall.ps1` therefore blocks the uv-managed base interpreter,
  which this project uses exclusively (`python-preference = "only-managed"`).
- **Alignment:** own CTC Viterbi (`pipeline/align.py`) instead of `torchaudio.functional.
  forced_align` (deprecated in torchaudio 2.9+).
- **Measured on the dev PC (Ryzen 7 7800X3D), German TTS samples, int8:**
  - turbo: ASR 0.34× real time, ASR + alignment 0.25× (cached ASR);
  - large-v3: ASR + alignment 0.76–0.89× real time;
  - text 100 % correct with both models, 79/80 words aligned (the unaligned one is "2019").

  Expect roughly 2–3× slower on the target laptop. Re-measure there with real recordings.

## 6b. Phase 2 analysis (as built)

`src/interis/analysis/`:
- `sentences`: sentence split on Whisper punctuation (German abbreviations and ordinals
  handled).
- `questions`: German rules with reason codes:
  - `question_mark`, `interrogative`, `verb_first`, `narrative_prompt`, `interest`;
  - backchannels excluded.
- `roles`:
  - interviewer identified by voice profile (`interis enroll`, cosine similarity to pyannote
    speaker centroids, ≥ 0.5 with ≥ 0.1 lead), otherwise by the highest share of question
    sentences;
  - voice embeddings are biometric data, so they stay in `<data>/voices` and are never
    written to transcripts or exports.
- `guide`: Markdown guide format (sections, codes, `~` variants, `>` planned probes).
- `analyze`: asked questions → guide matching (main / probe / follow-up), direct answers
  (main questions keep their follow-ups), and "answered elsewhere" suggestions
  (anticipated / later / unasked).
- **Embedding calibration** (German paraphrases, follow-ups, answer passages):

  | model | correct matches | follow-ups | answer passage at rank 1 |
  |---|---|---|---|
  | e5-base | ≥ 0.887 | up to 0.898 (overlap) | 3/5 |
  | **e5-large** | ≥ 0.904, lead ≥ 0.068 | ≤ 0.879, lead ≤ 0.033 | 3/5 |
  | e5-large-instruct | ≥ 0.933, lead ≥ 0.054 | ≤ 0.907, lead ≤ 0.028 | 3/5 |

  The resulting rules:
  - **guide match:** score ≥ 0.89 and a lead ≥ 0.05 over the next guide question;
  - **answer suggestions:** relative, i.e. z-score ≥ 1.5 among all interviewee passages of
    the interview, plus a floor of 0.78, max 3 per question.
- **End-to-end test** (2-minute German TTS interview, simulated diarization):
  - all 6 interviewer questions were correctly marked (4 main, 1 planned probe, 1 ad-hoc
    follow-up), with no false positives;
  - the never-asked F3 was suggested at exactly the right passage ("unasked").

## 6c. Review website (as built)

The scope is focused on what matters for the thesis:
1. where each question was asked;
2. marking that an answer also answers another question (and that this question was
   therefore left out);
3. a side-by-side comparison of all interviews, synchronised per guide question.

The frontend was rewritten from plain HTML/JS (the earlier `web/static/` plan no longer
exists) to a React build. The 6c notes below describe the current state.

- **Frontend:** React 19 with TypeScript, built with Vite 8 and styled with Tailwind CSS 4.
  UI components are in `frontend/src/components/ui` (shadcn style on Radix primitives, icons
  from lucide-react). Dependencies have exact versions in `frontend/package.json`. The build
  (`npm run build`, i.e. `tsc -b && vite build`) writes to `src/interis/web/dist`
  (`emptyOutDir: true`); the output is checked in. FastAPI serves `index.html` and `/assets`
  (`web/base.py`, `secure_app`).
- **Pages** (`frontend/src/pages/`): ProjectsPage; WorkflowPage ("Ablauf"); QuestionsPage
  ("Pro Frage"); ColumnsPage ("Nebeneinander"); InterviewPage (transcript, modes "Lesen",
  "Korrigieren", "Glätten"); ExtractPage ("Auswertung"); SetupPage ("Leitfaden & Gespräche",
  tabs "Gespräche", "Leitfaden", "Einstellungen").
- **Text rendering:** interview text is only passed to React as text nodes. No
  `dangerouslySetInnerHTML` is used in `frontend/src`.
- **Drag and drop** (`lib/review.tsx`, `ColumnsPage.tsx`): question chips and interviewee
  turns are `draggable`. The payload is JSON under the type `application/x-interis` with
  `kind` (question or answer), `interview`, `turn`, `first`, `last`. Dropping on a guide
  question row posts to `/api/questions` (match "main") or `/api/links`; dropping on the
  spontaneous row posts a follow-up question without a guide code. The payload names the
  interview, so a drop cannot target another interview's column. Every drop also has a dialog
  path; dragging is an accelerator only.
- **Backend:** FastAPI and uvicorn. SQLite through the standard library `sqlite3`
  (`web/store.py`, parameterised SQL) in `<data>/interis.db`. Manual question marks
  (`question_marks`) and "also answers" links with an `omitted` flag (`answer_links`) are keyed
  by position (interview, turn, word range). Transcript JSONs are not changed by the website.
  Section 6d lists the tables added for the review steps.
- **Effective state** (`web/review.py`, pure functions) = machine analysis + word edits +
  your decisions. Direct answers are recomputed after reassignments. Each link's type
  (anticipated / later / unasked) is derived from when the question was actually asked. Cell
  status precedence in `interview_state`: asked > omitted > answered_elsewhere > explained >
  missing.
- **Security as built** (`web/base.py`, `cli.py`, `desktop.py`):
  - the server listens on 127.0.0.1 (`cli.py`) and has a Host allow-list
    (`TrustedHostMiddleware`);
  - the login token is part of the URL fragment; `POST /api/login` exchanges it for an
    HttpOnly, SameSite=Strict session cookie, and every `/api/` route requires that cookie;
  - every non-GET request must send `X-Interis: 1`. If an `Origin` header is sent, it must be
    the local origin. There is no CORS middleware;
  - a Content-Security-Policy and the headers nosniff, no-referrer and frame-deny are set;
    API docs routes are disabled;
  - every write checks spans against the transcript and guide codes against the guide
    (422 otherwise), and request fields have length limits (pydantic).
- **Tests:** `tests/test_web.py`, `tests/test_workflow_api.py`, `tests/test_edits.py`,
  `tests/test_web_dist.py` (referenced files of the built UI exist).
- **Browser check of the earlier build:** two German TTS interviews were checked in a browser
  for the side-by-side grid (differently worded questions are synchronised, e.g. "sensible
  Daten" to F3), linking via the arrow button and via text selection, the "weggelassen -
  schon beantwortet" status, reassigning a follow-up to "F2 Nachfrage", and audio streaming
  (HTTP 206). The transcript edits, the workflow page, the decisions on missing questions, the
  extracts and the exports are not covered by such a browser check in this document.

## 6d. Transcript edits, workflow and extracts (as built)

These are the review steps between transcription and export (the researcher's view is in
docs/ABLAUF.md). Modules: `web/edits.py` (pure edit logic), `web/review.py` (effective state),
`web/workflow.py` (steps and done rules), `web/extracts.py` (extract table and exports),
`web/store.py` (SQLite), `web/app.py` (routes), `web/jobs.py` and `cli.py` (analysis with edits).

### Edit overlay on the immutable transcript

- The raw transcript JSON (`<data>/exports/<ID>/<ID>.json`) is not changed by the website.
  Edits are rows in `word_edits`, keyed by (interview, turn, word).
- `apply_edits(raw, edits)` returns an effective copy in memory. Word indices never move. A
  deleted word keeps its timing and gets empty text. A replace span puts the new text into its
  first word and deletes the other words of the span.
- Question marks, answer links, decisions and extracts address words by position, so they stay
  valid after edits. Passages are recomputed from the effective words (`review.passage`).
- Views and exports use the effective text. In `GET /api/interviews/{id}` a changed word carries
  `o` (original text), `k` (kind) and, for smoothing, `g` (tag).
- A correction has no tag. A smoothing edit needs a tag from the project's effective tag list
  (`project_tags(smoothing_tags)`; defaults in `DEFAULT_TAGS`). Replacement text is limited to
  200 characters (`MAX_TEXT_LEN`), tags to 40 (`MAX_TAG_LEN`).

### Analysis digest and re-analysis

- `edits_digest(edits)` is a SHA-256 over the sorted edit rows. The analysis stores it as
  `analysis["edits_digest"]`. `edits_stale` is true when the current digest differs
  (`EMPTY_DIGEST` when there are no edits). The UI shows this as "Analyse veraltet".
- Saving an edit does not queue an analysis. `POST /api/interviews/{id}/analyze` queues one
  analysis job (same de-duplication as `_queue_analysis`).
- For an analyze job with edits, `jobs.py` writes the rows to `<data>/tmp/edits-<job>.json`,
  passes `--edits`, and removes the file in a `finally` block. `cmd_analyze` in `cli.py` runs the
  analysis on `apply_edits(raw, edits)` and writes back only the analysis block plus the digest.
  The raw words are unchanged.
- Until the next analysis, the displayed text is current, but question detection, guide matches
  and suggestions come from the last analysis.

### Reviewed flag and re-transcription

- "Korrektur abgeschlossen" is stored as `interviews.reviewed_at` (`PUT
  /api/interviews/{id}/reviewed`). The flag does not check the text.
- Starting a transcription for an interview that already has markings returns 409 unless
  `discard_markings` is set. The discard path calls `store.delete_decisions`, which clears every
  table in `DECISION_TABLES` and `reviewed_at`.
- Edits are refused (409) while a transcription job of that interview is queued or running
  (`_not_transcribing`).

### Decisions on guide questions

- `question_decisions` holds the reason (`not_asked`, `not_relevant`, `other`) and a note of up
  to 2000 characters. `PUT /api/interviews/{id}/questions/{code}/decision` sets it; `reason: null`
  deletes it. An unknown guide code returns 422.
- In `interview_state` a cell gets status `explained` when there is neither an asked question
  nor a confirmed link, but a decision exists.

### Workflow state

- `GET /api/projects/{pid}/workflow` returns the eight `steps` (`STEPS` in `web/workflow.py`,
  with the German texts) and one row per interview.
- Done rules (`interview_row`): transcribe = transcribed; correct = reviewed; smooth = at least
  one smoothing edit (informational, never blocks); assign = transcribed and no question left
  unmatched (computed by the server, but the "Ablauf" page shows counts instead of a check);
  explain = transcribed and no guide question missing; extract = at least one extract.

### Extracts and exports

- Table `extracts` (id, interview, guide code, span, paraphrase, updated_at). The paraphrase is
  required (non-empty, at most 2000 characters). The span is checked against the transcript.
- `GET /api/projects/{pid}/extracts` returns the effective passage text and the start and end
  times of the effective transcript.
- `GET /api/projects/{pid}/extracts/export?format=docx|csv` builds the file in memory (python-docx
  for DOCX, the `csv` module for CSV) and returns it with `Content-Disposition: attachment`.
  Nothing is written to disk. Columns: Gespräch, Frage, Leitfadenfrage, Kernaussage, Zitat, Zeit.
  CSV: UTF-8 with BOM, `;` as delimiter, CRLF line ends. In CSV, a cell starting with `=`, `+`,
  `-`, `@`, tab or CR gets a leading apostrophe (`safe_cell`).

### Tables and columns added

| Name | Purpose |
|---|---|
| `word_edits` | one row per edited word: action (replace or delete), kind, text, tag |
| `extracts` | a passage with the researcher's paraphrase, assigned to a guide question |
| `question_decisions` | reason and note for a guide question without an answer |
| `interviews.reviewed_at` | time of "Korrektur abgeschlossen"; NULL means open |
| `projects.smoothing_tags` | newline-separated tags; empty means the defaults |

### Endpoints added or changed

All under `/api`. Every non-GET request needs the `X-Interis: 1` header and the session cookie.

| Method and path | Purpose |
|---|---|
| `GET /api/interviews/{id}` | changed: effective text, `o`/`k`/`g` on changed words, `reviewed`, `edits_stale`, `decisions`, `edits` |
| `GET /api/projects/{pid}/compare` | changed: cells use the effective text |
| `PATCH /api/projects/{pid}` | accepts `smoothing_tags`; `GET /api/projects/{pid}` returns `tags` |
| `POST /api/interviews/{id}/edits` | replace or delete a word span (correction or smoothing) |
| `POST /api/interviews/{id}/edits/revert` | remove the edits in a span |
| `PUT /api/interviews/{id}/reviewed` | set or clear "Korrektur abgeschlossen" |
| `POST /api/interviews/{id}/analyze` | queue one analysis job |
| `PUT /api/interviews/{id}/questions/{code}/decision` | set or delete the reason for a guide question |
| `GET /api/projects/{pid}/workflow` | steps and progress per interview |
| `GET /api/projects/{pid}/extracts` | extracts of the project |
| `POST /api/extracts` | create an extract |
| `PATCH /api/extracts/{id}` | change the paraphrase |
| `DELETE /api/extracts/{id}` | delete an extract |
| `GET /api/projects/{pid}/extracts/export?format=docx\|csv` | export file, generated in memory |

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
  web/       package.json package-lock.json .npmrc src/ (React + TS)
  tests/     unit/ pipeline/ (short German sample) api/ security/ (guard, host, csrf)
  scripts/   firewall.ps1  create-container.md
```
