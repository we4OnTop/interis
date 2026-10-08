# Interis – Dependency & Security Review

Status: researched 2026-10-06. Version floors are **minimums that exclude known CVEs as of
this date**. The exact versions come from `uv.lock` / `frontend/package-lock.json` and are re-checked
with `pip-audit`, `osv-scanner` and `npm audit` before every update.

Legend: 🌐 = can make network calls → how it is neutralised · ⚠ = known issue/CVE → mitigation

---

## 1. Python runtime – ML pipeline

| Package | Purpose | Maintainer / trust | License | Min version | Security notes |
|---|---|---|---|---|---|
| **torch** (CPU wheel) | tensor runtime for pyannote + alignment + embeddings | Meta / PyTorch Foundation | BSD-3 | **≥ 2.10** | ⚠ CVE-2025-32434 (RCE via `torch.load(weights_only=True)`, fixed 2.6) and **CVE-2026-24747** (CVSS 9.8, memory corruption in weights_only unpickler, fixed 2.10). This is why we don't use the `whisperx` package (it pins torch 2.8). Installed only from the official `download.pytorch.org/whl/cpu` index. |
| **torchaudio** | required by pyannote. Possibly the German alignment bundle. | PyTorch | BSD-2 | match torch | Library is in maintenance mode. If its wav2vec2 pipelines are gone, we use the HF German model via transformers instead (decided in Phase 1). |
| **faster-whisper** | Whisper inference on CPU (int8/float32), word timestamps, bundled Silero VAD (ONNX) | SYSTRAN | MIT | ≥ 1.2 | No known CVEs. 🌐 Downloads models from HF if given a name → we always pass a **local path**. |
| **ctranslate2** | inference engine under faster-whisper | OpenNMT | MIT | **≥ 4.8.1** | ⚠ CVE-2026-102566 (heap overflow, CVSS 7.8) and CVE-2026-102567 (OOB read) in the model loader, fixed 4.8.1. We only load models we converted ourselves. |
| **onnxruntime** | runs the Silero VAD (faster-whisper dependency) | Microsoft | MIT | latest 1.x | Native code, covered by the firewall rule. |
| **av** (PyAV) | the **only** audio decoder (bundles FFmpeg libs) | PyAV project | BSD-3 (FFmpeg LGPL) | latest | FFmpeg parsers have had CVEs over time. Inputs are your own recordings (low risk). Keep updated. Uploads are checked by extension only (magic-byte sniffing is not implemented). |
| **pyannote.audio** | speaker diarization + speaker embeddings | Hervé Bredin / pyannoteAI (CNRS origin) | MIT | ≥ 4.0 | 🌐 **OpenTelemetry usage metrics ON by default** (pipeline name, version, audio *duration*, speaker counts, session id → otel.pyannote.ai). No audio content, but still disabled: `PYANNOTE_METRICS_ENABLED=0` **before import**. pyannote writes `true` into the env if the variable is unset. Also pulls `pyannoteai-sdk` (cloud API client, never called) and `opentelemetry-exporter-otlp`. Both are blocked by the guard and firewall. Audio passed in memory; `interis` does not import `torchcodec`, but pyannote installs it, so its native FFmpeg libraries are in the runtime set. |
| ↳ transitive: lightning, pytorch-metric-learning, torch-audiomentations, torchmetrics, asteroid-filterbanks, pyannote-core/-database/-metrics/-pipeline, safetensors, einops, rich, matplotlib, omegaconf | pyannote internals | various, well known | MIT/Apache/BSD | latest | ⚠ `lightning` has had CVEs (in its app/server parts, not used here). Keep latest, covered by pip-audit. |
| **huggingface_hub** | model download in `setup-models` only | Hugging Face | Apache-2.0 | latest | 🌐 Telemetry HEAD requests and downloads → `HF_HUB_OFFLINE=1` + `HF_HUB_DISABLE_TELEMETRY=1` at runtime. Token is used only during setup and never saved. |
| **transformers** | wav2vec2 alignment model (if HF model) + backbone for sentence-transformers. Also the Whisper→CTranslate2 converter at setup. | Hugging Face | Apache-2.0 | **≥ 5.3** | ⚠ CVE-2026-4372 (RCE via crafted model config, 4.56–5.2.x, fixed 5.3). ⚠ CVE-2026-1839 and the Dec-2025 series (deserialization in Trainer/conversion scripts; code paths we do not use). Never `trust_remote_code`. Load only pinned local safetensors. |
| **sentence-transformers** | multilingual embeddings for question↔guide matching and answer suggestions | Hugging Face (originally UKP Lab, TU Darmstadt) | Apache-2.0 | latest | 🌐 HF download → offline env + local path. |
| **safetensors** | safe weight format (no code execution) | Hugging Face | Apache-2.0 | latest | Preferred format for all models. |
| **numpy** | arrays | NumFOCUS | BSD-3 | ≥ 2.1 | – |

Removed on purpose: `whisperx` (torch 2.8 pin, runtime downloads), `nltk` (runtime
`punkt_tab` download; we split sentences on Whisper punctuation). `torchcodec` is not imported by
Interis, but pyannote requires it, so it stays installed (see the pyannote row).

## 2. Python runtime – server, storage, export

| Package | Purpose | License | Min version | Security notes |
|---|---|---|---|---|
| **fastapi** | API | MIT | release that allows starlette ≥ 1.3.1 | Inherits Starlette CVEs. Pin both. |
| **starlette** | ASGI core | BSD-3 | **≥ 1.3.1** | ⚠ CVE-2026-48710 "BadHost" (Host header → middleware bypass, fixed 1.0.1). ⚠ CVE-2026-54283 (form limits ignored for urlencoded → DoS, fixed 1.3.1). ⚠ CVE-2025-62727 (Range-header DoS in FileResponse). We also allow-list Host ourselves. |
| **uvicorn** (plain, no `[standard]`) | ASGI server | BSD-3 | latest | Bound to 127.0.0.1. Fewer native extras means a smaller attack surface. |
| **python-multipart** | file upload parsing | Apache-2.0 | latest | Has had DoS CVEs (2024). Covered by pip-audit, plus our own size limits. |
| **pydantic**, **pydantic-settings** | validation, config | MIT | v2 latest | – |
| **sqlmodel** + **SQLAlchemy** | ORM over SQLite | MIT | latest | Parameterised queries only. No raw string SQL. |
| **alembic** | DB migrations | MIT | latest | – |
| **python-docx** | DOCX export | MIT | latest | Writes only. |
| **openpyxl** | XLSX comparison matrix | MIT | latest | Writes only. Cells are escaped against formula injection (`=`, `+`, `-`, `@` prefixes). |
| SQLite (stdlib `sqlite3`, FTS5) | storage + full-text search | public domain | Python 3.11 bundled | – |

## 3. Dev / evaluation only (never imported by the running app)

`pytest`, `ruff`, `mypy`, `pip-audit` (PyPA), `osv-scanner` (Google), `jiwer` (WER),
`pyannote.metrics` (DER, already present), `pre-commit`.

## 4. Frontend (build time only; output is static files served by FastAPI)

Source in `frontend/` (React + TypeScript + shadcn/ui). `npm run build` writes plain files
to `src/interis/web/dist/`, which is committed: the laptop never runs Node or npm.

Runtime packages (bundled into the static JS):

| Package | Purpose | License |
|---|---|---|
| react, react-dom 19.3 | UI | MIT (Meta) |
| radix-ui 1.6 | accessible primitives behind shadcn (dialog, select, tabs, tooltip, checkbox, progress) | MIT (WorkOS) |
| class-variance-authority, clsx, tailwind-merge | class name helpers used by shadcn | MIT/Apache-2.0 |
| lucide-react | icons (only used ones are bundled) | ISC |

Build-only: typescript 7, vite 8, @vitejs/plugin-react, tailwindcss 4 + @tailwindcss/vite,
tw-animate-css, @types/*. The shadcn components are copied into `frontend/src/components/ui`
by hand (that is how shadcn works); the `shadcn` CLI is not used, so it and its
dependencies never run here.

Deliberately not used: router, data-fetching, form, state-management and toast libraries,
web fonts, CDNs.

Hardening:
- `frontend/.npmrc`: `ignore-scripts=true` (no install scripts — the npm worms of 2025/26
  ran at install time), `save-exact=true`.
- Versions were resolved with `npm install --before=<7 days ago>`; `package-lock.json` pins
  every package with an integrity hash. Install with `npm ci`.
- `npm audit`: 0 findings. One override: `source-map-js` 1.2.2 (fix for
  GHSA-68fv-2mgg-jv7q, build-time only, same maintainer; released exactly 7 days before).
- Strict CSP stays: `script-src 'self'`, no `unsafe-inline`. The UI library's scroll-lock
  style tag gets a per-response nonce (see `web/base.py` and `tests/test_csp.py`); Radix
  Select's one fixed style tag is allowed by its hash. If a Radix upgrade changes that text,
  the scrollbar styling of the select is lost, and the hash in `web/base.py` must be updated.

## 5. Models (downloaded once by `interis setup-models`, pinned + hashed)

| Model | Use | Source / trust | License | Format & handling |
|---|---|---|---|---|
| **openai/whisper-large-v3** | final, max-precision ASR | Official OpenAI repo | MIT | safetensors → **converted locally** to CTranslate2 with `ct2-transformers-converter`. We don't depend on third-party pre-converted repos. |
| **openai/whisper-large-v3-turbo** | fast draft ASR | Official OpenAI repo | MIT | Same local conversion. |
| **pyannote/speaker-diarization-community-1** | diarization + embeddings | pyannote (gated: free HF account + accept conditions once) | CC-BY-4.0 (attribution in thesis) | Pinned revision, Hub hashes verified. ⚠ **pyannote 4.0.7 loads its checkpoints with `torch.load(weights_only=False)`** (`core/model.py`), i.e. full pickle, and we cannot change that without forking. Mitigations: pinned official revision, sha256 check before every use, and Interis' own **static pickle scanner** (`security/pickle_scan.py`) that rejects any checkpoint importing non-allowlisted globals (e.g. `os.system`, `builtins.eval`, getattr chains), run at setup and before every load. |
| German wav2vec2 aligner: **`jonatasgrosman/wav2vec2-large-xlsr-53-german`** (implemented) | word-level forced alignment | widely used community model | Apache-2.0 | Ships a **pickle checkpoint only** (`pytorch_model.bin`). It is scanned, loaded once via transformers (torch ≥ 2.10 `weights_only` loading), **re-saved as safetensors**, and the `.bin` is deleted. Afterwards it is loaded with `use_safetensors=True` only. The conversion load uses `weights_only=True`. |
| **intfloat/multilingual-e5-large** (implemented, Phase 2) | sentence embeddings (question ↔ guide matching, answer suggestions) | Microsoft Research | MIT | `model.safetensors`, loaded via transformers (no sentence-transformers dependency). Chosen over e5-base and e5-large-instruct after calibration (ARCHITECTURE.md §6a). `BAAI/bge-m3` was excluded because it ships only pickle weights. |
| Silero VAD | voice activity detection | bundled inside faster-whisper (ONNX) | MIT | No download. |

Pinned revisions live in `src/interis/models.py`. After preparation, the sha256 of every
prepared file is written to `<data>/models/models.lock.json`. Conversions are machine-
specific, so this file lives in the data directory, not the repo. Every pipeline run checks
the hashes and refuses to start on any difference, including extra files. Limitation: the lock is
written after the download and travels with a copied folder (`-ModelsFrom`), so a folder whose
files and lock were both replaced passes this check. The fix is to commit the expected hashes;
that needs a Hub-verified list, which is an open item.

### Verified mirror for the gated pyannote model

`pyannote/speaker-diarization-community-1` is gated: you need a free HF account and must
accept the conditions. `interis setup-models --allow-verified-mirror` instead downloads the
files from the ungated mirror `pyannote-community/speaker-diarization-community-1`. That
mirror is run by an unofficial organisation, so it is **not trusted**. Every file is
checked against the sha256 / git-blob hashes that the **official** repo publishes for the
pinned revision; this metadata is visible without a login. As of 2026-10-06 all five files
are byte-identical. The license (CC-BY-4.0) allows redistribution. For the thesis setup,
the official route with your own token is still preferred, because it also supports the
pyannote authors.

### Benchmark data (not shipped, downloaded on demand)

AMI Meeting Corpus (CC-BY-4.0, https://groups.inf.ed.ac.uk/ami/): audio of 4 meetings,
individual headset channels, and the manual annotations (`ami_public_manual_1.6.2.zip`).
These are stored under `<data>/bench/ami` with a `SHA256SUMS` file. The XML is parsed with
the stdlib (expat with entity-expansion protection).

### TLS interception (found on the development PC)

On the development machine, **Kaspersky Anti-Virus** re-signs all HTTPS traffic with its own
root certificate ("Kaspersky Anti-Virus Personal Root Certificate"). Python correctly refuses
these connections. `interis setup-models --use-system-certs` verifies TLS against the Windows
certificate store via [`truststore`](https://github.com/sethmlarson/truststore), which pip
itself vendors. It is never `verify=False`. This is only relevant for the one-time model
download. Interview data never goes over the network.

## 6. Host tools

| Tool | Purpose | Notes |
|---|---|---|
| Python 3.11, **uv-managed** (`python-preference = "only-managed"`) | runtime | Not the Microsoft Store Python. A Windows venv's `python.exe` is only a launcher, so the firewall rule must target the *base* interpreter. A dedicated uv-managed interpreter keeps that rule specific. |
| **truststore** | OS certificate store for the setup download | Opt-in via `--use-system-certs`. Same library pip vendors. |
| **uv** (Astral) | env + lockfile | `[tool.uv] exclude-newer = "7 days"` (dependency cooldown), `uv sync --locked`. |
| Node.js LTS + npm | frontend build only | Not needed at runtime. |
| **VeraCrypt** | encrypted data container | Open source, independently audited (Quarkslab 2016, Fraunhofer SIT for BSI 2020). |
| Windows Defender Firewall | outbound block for the venv python | Created by `scripts/firewall.ps1`, checked by `interis doctor`. |

## 7. Leak checklist (checked by `interis doctor`)

- [ ] `PYANNOTE_METRICS_ENABLED=0`, `HF_HUB_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`,
      `TRANSFORMERS_OFFLINE=1`, `OTEL_SDK_DISABLED=true` are active in the worker
- [ ] Network guard active; a test connection to a public IP is blocked
- [ ] Firewall outbound rule present for the base interpreter behind the venv `python.exe`
- [ ] Data dir is on the VeraCrypt volume and **not** under a OneDrive-synced folder
- [ ] Server listens on 127.0.0.1 only; a Host-header test with `evil.example` is rejected
- [ ] `models.lock.json` hashes match
- [ ] `pip-audit` / `npm audit` clean (or accepted findings documented). pip-audit skips
      `torch`/`torchaudio` because of the `+cpu` local version, so check those two on
      [osv.dev](https://osv.dev). (2026-10-06: torch 2.14.0 and torchaudio 2.11.0 have 0 known vulns.)

## Sources

- WhisperX dependencies (torch ~2.8 pin): https://github.com/m-bain/whisperX/blob/main/pyproject.toml
- WhisperX alignment (NLTK + model downloads): https://github.com/m-bain/whisperX/blob/main/whisperx/alignment.py
- pyannote.audio dependencies: https://github.com/pyannote/pyannote-audio/blob/main/pyproject.toml
- pyannote telemetry: https://github.com/pyannote/pyannote-audio/blob/main/src/pyannote/audio/telemetry/metrics.py · https://github.com/randomm/vemoizer/issues/103
- pyannote + torchcodec on Windows: https://github.com/pyannote/pyannote-audio/issues/1979
- torch CVE-2025-32434: https://github.com/advisories/GHSA-53q9-r3pm-6pq6 · CVE-2026-24747: https://github.com/advisories/GHSA-63cw-57p8-fm3p
- transformers CVE-2026-4372: https://pluto.security/blog/unauthenticated-remote-code-execution-in-huggingface-transformers-via-config-injection/ · CVE-2026-1839: https://access.redhat.com/security/cve/cve-2026-1839
- CTranslate2 CVEs: https://app.opencve.io/cve/?product=ctranslate2&vendor=opennmt
- Starlette BadHost CVE-2026-48710: https://www.ionix.io/threat-center/cve-2026-48710/ · CVE-2026-54283: https://osv.dev/vulnerability/CVE-2026-54283
- huggingface_hub telemetry: https://huggingface.co/docs/huggingface_hub/en/package_reference/utilities
- DNS rebinding on localhost: https://github.blog/security/application-security/dns-rebinding-attacks-explained-the-lookup-is-coming-from-inside-the-house/
- uv exclude-newer cooldown: https://pydevtools.com/handbook/how-to/how-to-protect-against-python-supply-chain-attacks-with-uv/
- npm and pnpm hardening (install scripts, release age): https://www.nodejs-security.com/blog/hardening-your-npm-pnpm-config-for-shai-hulud
- OneDrive auto folder backup: https://www.pcworld.com/article/2376883/attention-microsoft-activates-this-feature-in-windows-11-without-asking-you.html
- wav2vec2 German model files: https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-german
