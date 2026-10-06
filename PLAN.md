# Interis – Local Interview Transcription & Comparison Tool (Plan v2)

Status: plan, updated 2026-10-06
**See [ARCHITECTURE.md](ARCHITECTURE.md) and [DEPENDENCIES.md](DEPENDENCIES.md). They take
precedence over this file where they differ.** In particular:
- the `whisperx` *package* is replaced by its components built directly (torch 2.8 pin
  → CVE-2026-24747; runtime downloads);
- large-v3 is used for the final, precise transcript;
- transcription rules come later, as export transformations. Stored data stays raw.
Goal: manage and transcribe the German interviews (interviewer + one interviewee) for the
master thesis, show **who spoke when**, **find and mark the interviewer's questions**, and
**compare the answers to each question side by side across all interviews**. This includes
answers given at a different point in the interview than where the question was asked.

Target machine: **laptop, Intel Core i7 11th gen, 32 GB RAM, no NVIDIA GPU** (assumed
Windows 11) → CPU-only processing.

---

## 1. Guiding principles

1. **Everything runs locally/offline.** Interviews are personal data (DSGVO). No cloud APIs,
   no telemetry. Models are downloaded once, then the app runs with `HF_HUB_OFFLINE=1`.
2. **Only established, published, widely used components.** They can be cited in the thesis
   methods section.
3. **The machine suggests, the human decides.** Every automatic result (transcript, speaker,
   question mark, answer link) is a suggestion that you confirm or correct. The model and
   version are stored with each transcript.
4. **Pinned, verifiable dependencies.**
   - Use a `uv` lockfile with hashes and run `pip-audit`.
   - Pin model revisions to a Hugging Face commit and never use `trust_remote_code`.
   - Use PyTorch ≥ 2.6 (safe `torch.load`).

## 2. Technology choices

| Concern | Choice | Why |
|---|---|---|
| Speech-to-text | **Whisper large-v3-turbo** via **faster-whisper** (CTranslate2, int8 on CPU) | De-facto standard with very good German accuracy. Turbo is about 6× faster than large-v3, which matters on a laptop CPU. Language is fixed to `de`. |
| Word timestamps | **WhisperX** (VAD + wav2vec2 German alignment) | Word-level timing. VAD reduces hallucinations in silence. Paper: Bain et al., Interspeech 2023. |
| Speaker diarization | **pyannote.audio 4.x + `speaker-diarization-community-1`** (CC-BY-4.0), `num_speakers=2` | State-of-the-art open diarization and the WhisperX default. *Exclusive* mode gives one speaker per word. Paper: Bredin, Interspeech 2023. |
| "Which speaker is me?" | **Voice enrollment** (~60 s of your voice → speaker embedding → cosine similarity). Fallback: the speaker with more question-like turns. | Automatic "Interviewer"/"Befragte:r" labels, correctable with one click. |
| Question detection & answer suggestions | Rules + **multilingual sentence-transformers** (e.g. `intfloat/multilingual-e5-base`, runs on CPU) | See sections 5–6. |
| Audio | **ffmpeg** (16 kHz mono WAV) | Standard. |
| Backend | **Python 3.11, FastAPI, SQLModel + SQLite (with FTS5 full-text search)** | Well-known and simple. Binds to `127.0.0.1` only. |
| Background jobs | One worker process with a persistent job table; each pipeline step is cached | Long CPU runs survive restarts and resume at the last finished step. |
| Frontend (website) | **React + TypeScript + Vite**, **TanStack Query**, **Mantine** UI, **wavesurfer.js** for audio | Mainstream, well-maintained libraries. |
| Export (now) | JSON (lossless), DOCX (python-docx), **XLSX comparison matrix** (openpyxl) | Usable in the thesis right away. |
| Export (later) | MAXQDA / ATLAS.ti / NVivo formats via a pluggable exporter interface | Decide once the QDA software is chosen. Nothing in the design blocks it. |

### Performance expectations on the laptop (to be measured in Phase 1)

- An 11th-gen i7 (typically 4 cores / 8 threads) running turbo int8 plus alignment plus
  diarization: expect roughly **1–3× the audio length**, so a 1 h interview may take
  1–3 h. → Treat processing as an **overnight batch job**, with a progress bar in the website.
- Plug in the laptop and turn off sleep during runs. The app can keep the system awake while a
  job runs.
- Optional later speed-up: whisper.cpp with the **OpenVINO** encoder (Intel iGPU/CPU), behind
  the same `AsrBackend` interface.
- Fallback setting: `medium` model for quick drafts, turbo for the final transcript.

## 3. Processing pipeline

```
upload audio ─► ffmpeg normalize (sha256 recorded)
             ─► VAD + faster-whisper (de, large-v3-turbo)
             ─► WhisperX forced alignment (word timestamps)
             ─► pyannote community-1 (num_speakers=2, exclusive)
             ─► words → speakers → turns
             ─► speaker identification (enrollment → Interviewer / Befragte:r)
             ─► question detection + linking to interview guide
             ─► answer segmentation + "answered elsewhere" suggestions
             ─► Transcript v1 (machine)  → your review → v2 (verified)
```

## 4. Core concept: interview guide ↔ questions ↔ answers

```
Guide (Leitfaden, versioned)
 └─ Section / Theme  (e.g. "Einstieg", "Erfahrungen mit X")
     └─ GuideQuestion   (ID, canonical wording, optional variants, optional probes/Nachfragen)

Interview
 └─ Transcript → Turns → Words
     ├─ AskedQuestion   (span in an interviewer turn → GuideQuestion | "ad-hoc follow-up")
     └─ AnswerLink      (span in interviewee turns → GuideQuestion, with a type)
```

**AnswerLink types:**
- `direct`: the answer right after the question was asked
- `anticipated`: answered *before* the question was asked, elsewhere in the interview
- `later`: picked up again later in the interview
- `partial`: touches the question only partly
- `skipped_because_answered`: marks a guide question that was not asked because it had already
  been answered (it points to the anticipated passage)

Each link stores: span (start/end word), `source` (auto/manual), `status`
(suggested/confirmed/rejected), and a note.

## 5. Speaker recognition & question marking

1. Diarize with `num_speakers=2`. Each word goes to exactly one speaker, and overlaps are
   flagged.
2. The enrolled voice identifies the interviewer. You confirm once per interview.
3. **Question candidates** in interviewer turns:
   - the sentence ends with `?`;
   - it starts with a German interrogative (wer, was, wann, wie, warum, weshalb, wo, welche,
     inwiefern, inwieweit…);
   - it has verb-first order ("Haben Sie…", "Können Sie…", "Gibt es…");
   - it is a narrative prompt ("Erzählen Sie mal…", "Beschreiben Sie…", "Wenn Sie an … denken").
   - Backchannels ("mhm", "okay", "ja") are excluded.
4. **Guide matching:** the semantic similarity between each candidate and each guide question
   (its wording and variants) gives a suggested `GuideQuestion`. Below the threshold it counts
   as an **ad-hoc follow-up**.
5. In the transcript view, questions are highlighted with their guide-ID badge. You can
   toggle a mark, relink it, or mark any span manually.

## 6. Answers & "answered elsewhere"

1. **Direct answer (automatic):** the interviewee turns after an asked question, up to the
   next *main* question. Follow-ups in between stay attached to that question, but can be
   split off.
2. **Answered-elsewhere suggestions (automatic):** each interviewee passage (sentence windows)
   is embedded and compared with every guide question. Strong matches outside the direct
   answer show up as **"maybe answered here"** suggestions (`anticipated` / `later`), which
   you accept or reject.
3. **Manual linking:** select any text in the transcript, choose "Link to question…", then
   pick the guide question and the link type.
4. **Guide coverage per interview:** each question is shown as asked ✔ / answered elsewhere ↺ /
   missing ✘.

## 7. The website (local, http://127.0.0.1:PORT)

1. **Dashboard:** the interviews (pseudonym, date, duration, status: uploaded → processing →
   needs review → verified) and the job progress.
2. **Interview guide editor ("question setting"):**
   - create and order sections and questions, add alternative wordings and probes;
   - versioned, so a later change to the guide keeps the old links valid;
   - import/export as a simple text or DOCX list.
3. **Transcript view (one interview):**
   - audio player with waveform; click a word to jump there, and the current word is
     highlighted during playback;
   - turns coloured by speaker; edit text, reassign a speaker, split or merge turns;
   - left sidebar: the guide with coverage icons, click to jump;
   - right sidebar: the suggestions to accept or reject;
   - low-confidence words are underlined so you know where to listen again.
4. **Comparison view (the main analysis screen):**
   - pick a guide question, and you get **one column per interview, side by side**:
     - the question as actually asked (exact wording), with a play button;
     - the direct answer;
     - other passages that answer it (anticipated/later), clearly labelled with timestamps;
       clicking one jumps into the transcript;
   - or the **matrix mode**: rows are guide questions, columns are interviews, and each cell
     shows a short answer preview and the coverage icon;
   - filters: confirmed only, link type, interview subset;
   - personal notes/memos per cell;
   - export the matrix to **XLSX/DOCX** for the thesis appendix.
5. **Search:** full-text search across all transcripts (SQLite FTS5) with a "link this to
   question…" action on each hit.
6. **Settings:** model, voice enrollment (record in the browser), pseudonymization list, data
   folder.

## 8. Security & data protection

- The data folder (audio, DB, exports) lives in a **VeraCrypt** container or on a disk with
  Windows Device Encryption. Backups are encrypted.
- Server on `127.0.0.1` only, with no external calls at runtime (`HF_HUB_OFFLINE=1`).
- The HF token is used only for the one-time model download, then removed or stored in the OS
  keyring.
- **Pseudonymization** at export: names and places are replaced using a mapping list stored
  separately.
- "Delete original audio" action per interview, according to your consent form and data
  management plan.

## 9. Implementation phases

| Phase | Deliverable | Est. effort |
|---|---|---|
| 0. Setup | uv project, ffmpeg, HF model download (pinned), offline cache, encrypted data folder | ½ day |
| 1. Pipeline CLI | `interis transcribe file.m4a`, which writes JSON + DOCX with speakers. **Measure the speed on the laptop.** | 2–3 days |
| 2. Speakers + questions | Enrollment, rule-based question detection, guide matching (from a guide text file) | 2 days |
| 3. Backend | SQLite models (guide, interviews, turns, links), FastAPI, job worker with resume | 2–3 days |
| 4. Website I | Dashboard, upload, guide editor, transcript view with player and editing | 4–5 days |
| 5. Website II | Answer linking (auto + manual), suggestions, **comparison view + matrix**, search | 4–5 days |
| 6. Export | DOCX transcripts, XLSX/DOCX comparison matrix, pseudonymization | 1–2 days |
| 7. Evaluation & hardening | Hand-correct 10 min, report WER (jiwer) and DER (pyannote.metrics). Tests, pip-audit. | 1–2 days |
| Later | QDA export (MAXQDA/ATLAS.ti/NVivo), OpenVINO speed-up | – |

## 10. Repository layout

```
interis/
  pyproject.toml, uv.lock
  src/interis/
    pipeline/  audio.py asr.py align.py diarize.py merge.py speaker_id.py
               questions.py answers.py embeddings.py
    db/        models.py repo.py migrations/
    api/       main.py routes/ (interviews, guide, transcripts, links, compare, jobs)
    worker/    jobs.py
    export/    docx.py xlsx.py json.py  (qda/ later)
    cli.py
  web/         React + Vite + TS
  tests/
  data/        (git-ignored, inside the encrypted container)
```

## 11. Remaining open points

- Laptop OS: assumed Windows 11. Tell me if it is Linux or macOS.
- Does your university or ethics board prescribe transcription rules (e.g. Dresing & Pehl,
  simplified)? This affects the DOCX format and whether to keep "ähm" and pauses.

## References

- WhisperX: https://github.com/m-bain/whisperX
- pyannote community-1: https://huggingface.co/pyannote/speaker-diarization-community-1
- pyannote.audio: https://github.com/pyannote/pyannote-audio
- faster-whisper: https://github.com/SYSTRAN/faster-whisper
- whisper.cpp (OpenVINO option): https://github.com/ggml-org/whisper.cpp
- noScribe (comparable tool): https://github.com/kaixxx/noScribe
- aTrain (comparable tool): https://www.sciencedirect.com/science/article/pii/S2214635024000066
