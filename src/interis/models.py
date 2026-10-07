"""Model registry: pinned sources, one-time download + preparation, integrity checks.

* Every model is pinned to a Hugging Face commit and an explicit file list (no wildcard
  downloads, no pickle files where a safetensors file exists).
* Downloaded files are verified against the hashes the Hub reports for that commit.
* Whisper is converted locally from the official OpenAI safetensors to CTranslate2.
* The German wav2vec2 aligner only ships a pickle checkpoint: it is scanned, loaded once
  with ``weights_only`` loading (transformers + torch ≥ 2.10), and re-saved as safetensors.
* pyannote checkpoints are pickles loaded by pyannote itself with ``weights_only=False``;
  they are scanned now and again before every load (see ``pipeline/diarize.py``).
* The hashes of the prepared files are written to ``<data>/models/models.lock.json`` and
  checked before every use.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from interis.config import Paths
from interis.security.pickle_scan import assert_safe_checkpoint

Kind = Literal["whisper", "pyannote", "wav2vec2", "embedding"]
Log = Callable[[str], None]


@dataclass(frozen=True)
class ModelSpec:
    key: str
    repo: str
    revision: str
    kind: Kind
    files: tuple[str, ...]
    license: str
    gated: bool = False
    # Ungated mirror (repo, revision) of a gated model. Files are downloaded from it but
    # verified against the hashes the *official* repo publishes for the pinned revision.
    mirror: tuple[str, str] | None = None

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}"


_WHISPER_FILES = (
    "config.json", "generation_config.json", "preprocessor_config.json", "tokenizer.json",
    "tokenizer_config.json", "vocab.json", "merges.txt", "added_tokens.json",
    "special_tokens_map.json", "normalizer.json", "model.safetensors",
)

_E5_FILES = (
    "config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json",
    "special_tokens_map.json", "sentencepiece.bpe.model",
)

MODELS: dict[str, ModelSpec] = {
    s.key: s
    for s in (
        ModelSpec("whisper-large-v3", "openai/whisper-large-v3",
                  "06f233fe06e710322aca913c1bc4249a0d71fce1", "whisper", _WHISPER_FILES, "MIT"),
        ModelSpec("whisper-large-v3-turbo", "openai/whisper-large-v3-turbo",
                  "41f01f3fe87f28c78e2fbf8b568835947dd65ed9", "whisper", _WHISPER_FILES, "MIT"),
        ModelSpec("pyannote-community-1", "pyannote/speaker-diarization-community-1",
                  "3533c8cf8e369892e6b79ff1bf80f7b0286a54ee", "pyannote",
                  ("config.yaml", "embedding/pytorch_model.bin",
                   "segmentation/pytorch_model.bin", "plda/plda.npz",
                   "plda/xvec_transform.npz"),
                  "CC-BY-4.0", gated=True,
                  mirror=("pyannote-community/speaker-diarization-community-1",
                          "8a527374977391da736e0daaef26855d949d9685")),
        ModelSpec("wav2vec2-german", "jonatasgrosman/wav2vec2-large-xlsr-53-german",
                  "4b8a02957378d0f2da2ef74091156b032c485a89", "wav2vec2",
                  ("config.json", "preprocessor_config.json", "vocab.json",
                   "special_tokens_map.json", "pytorch_model.bin"),
                  "Apache-2.0"),
        ModelSpec("e5-large", "intfloat/multilingual-e5-large",
                  "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3", "embedding", _E5_FILES, "MIT"),
    )
}

ASR_MODELS = ("whisper-large-v3", "whisper-large-v3-turbo")
DIARIZATION_MODEL = "pyannote-community-1"
ALIGN_MODEL = "wav2vec2-german"
EMBEDDING_MODEL = "e5-large"


class ModelError(Exception):
    pass


# --------------------------------------------------------------------------- hashing

def sha256_file(path: Path, chunk: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def git_blob_sha1(path: Path) -> str:
    """Hash as git computes it for a blob (used by the Hub for non-LFS files)."""
    h = hashlib.sha1(usedforsecurity=False)
    h.update(f"blob {path.stat().st_size}\0".encode())
    with open(path, "rb") as f:
        while block := f.read(8 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def hash_tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): sha256_file(p)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# --------------------------------------------------------------------------- lock file

def _lock_path(paths: Paths) -> Path:
    return paths.models / "models.lock.json"


def read_lock(paths: Paths) -> dict[str, dict]:
    p = _lock_path(paths)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _write_lock(paths: Paths, lock: dict[str, dict]) -> None:
    p = _lock_path(paths)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(lock, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def ready_dir(paths: Paths, key: str) -> Path:
    return paths.models / key


def verify_ready(paths: Paths, key: str) -> Path:
    """Return the prepared model directory after checking every file hash."""
    spec = MODELS[key]
    entry = read_lock(paths).get(key)
    target = ready_dir(paths, key)
    if not entry or not target.is_dir():
        raise ModelError(f"Model '{key}' is not set up. Run: interis setup-models --only {key}")
    if entry.get("revision") != spec.revision:
        raise ModelError(f"Model '{key}' was prepared from another revision. Re-run setup.")
    actual = hash_tree(target)
    if actual != entry["files"]:
        changed = sorted(set(actual.items()) ^ set(entry["files"].items()))
        raise ModelError(
            f"Model '{key}' failed integrity check ({len(changed)} differing entries, "
            f"e.g. {changed[:3]}). Refusing to use it."
        )
    return target


def quick_status(paths: Paths, key: str) -> str:
    """'ready' | 'missing' | 'outdated' | 'incomplete' – without hashing (fast, for the UI).
    The full hash check still runs before every use (verify_ready)."""
    entry = read_lock(paths).get(key)
    target = ready_dir(paths, key)
    if not entry or not target.is_dir():
        return "missing"
    if entry.get("revision") != MODELS[key].revision:
        return "outdated"
    present = {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()}
    return "ready" if present == set(entry["files"]) else "incomplete"


def is_ready(paths: Paths, key: str) -> bool:
    try:
        verify_ready(paths, key)
        return True
    except ModelError:
        return False


# --------------------------------------------------------------------------- setup

def _verify_against_hub(spec: ModelSpec, raw: Path, token: str | None) -> None:
    from huggingface_hub import HfApi

    info = HfApi().model_info(spec.repo, revision=spec.revision, files_metadata=True,
                              token=token)
    siblings = {s.rfilename: s for s in info.siblings or []}
    for rel in spec.files:
        sib = siblings.get(rel)
        if sib is None:
            raise ModelError(f"{spec.repo}@{spec.revision} has no file {rel}")
        local = raw / rel
        if sib.lfs is not None:
            ok = sha256_file(local) == sib.lfs.sha256
        else:
            ok = git_blob_sha1(local) == sib.blob_id
        if not ok:
            raise ModelError(f"{spec.repo}/{rel}: hash does not match the Hub. Aborting.")


def _download(spec: ModelSpec, raw: Path, token: str | None, use_mirror: bool) -> None:
    from huggingface_hub import snapshot_download

    repo, revision = spec.mirror if use_mirror and spec.mirror else (spec.repo, spec.revision)
    snapshot_download(
        repo_id=repo,
        revision=revision,
        allow_patterns=list(spec.files),
        local_dir=raw,
        token=token if repo == spec.repo else None,
    )
    # Always verified against the official repo's published hashes.
    _verify_against_hub(spec, raw, token)


def _prepare_whisper(spec: ModelSpec, raw: Path, out: Path) -> None:
    from ctranslate2.converters import TransformersConverter

    converter = TransformersConverter(
        str(raw),
        copy_files=["tokenizer.json", "preprocessor_config.json"],
        load_as_float16=True,
    )
    converter.convert(str(out), quantization="float16", force=True)


def _prepare_wav2vec2(spec: ModelSpec, raw: Path, out: Path) -> None:
    assert_safe_checkpoint(raw / "pytorch_model.bin")
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

    processor = Wav2Vec2Processor.from_pretrained(raw, local_files_only=True)
    model = Wav2Vec2ForCTC.from_pretrained(raw, local_files_only=True)
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out)
    processor.save_pretrained(out)
    if not (out / "model.safetensors").exists() or any(out.glob("*.bin")):
        raise ModelError("wav2vec2 conversion did not produce a pure safetensors model")


def _prepare_pyannote(spec: ModelSpec, raw: Path, out: Path) -> None:
    for ckpt in ("embedding/pytorch_model.bin", "segmentation/pytorch_model.bin"):
        assert_safe_checkpoint(raw / ckpt)
    for rel in spec.files:
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(raw / rel, out / rel)


def _prepare_embedding(spec: ModelSpec, raw: Path, out: Path) -> None:
    # Already safetensors; copy only the pinned files (no .cache metadata).
    for rel in spec.files:
        shutil.copy2(raw / rel, out / rel)


_PREPARE = {"whisper": _prepare_whisper, "wav2vec2": _prepare_wav2vec2,
            "pyannote": _prepare_pyannote, "embedding": _prepare_embedding}


def setup_model(paths: Paths, key: str, token: str | None, log: Log = print,
                allow_mirror: bool = False) -> None:
    spec = MODELS[key]
    if is_ready(paths, key):
        log(f"[{key}] already set up and verified")
        return
    use_mirror = spec.gated and not token and allow_mirror and spec.mirror is not None
    if spec.gated and not token and not use_mirror:
        raise ModelError(
            f"[{key}] is a gated model. Accept its conditions at {spec.url} with your "
            "Hugging Face account, create a read token, and run setup with the token in the "
            "HF_TOKEN environment variable (it is used for this download only and never "
            "stored)."
        )
    raw = paths.models / "_download" / key
    staging = paths.models / f"_staging_{key}"
    target = ready_dir(paths, key)
    shutil.rmtree(staging, ignore_errors=True)

    source = spec.mirror[0] if use_mirror and spec.mirror else spec.repo
    log(f"[{key}] downloading {source} (pinned to {spec.repo}@{spec.revision[:10]}) …")
    _download(spec, raw, token, use_mirror)
    log(f"[{key}] download verified against the Hub, preparing …")
    staging.mkdir(parents=True)
    _PREPARE[spec.kind](spec, raw, staging)

    shutil.rmtree(target, ignore_errors=True)
    os.replace(staging, target)
    lock = read_lock(paths)
    lock[key] = {
        "repo": spec.repo,
        "revision": spec.revision,
        "downloaded_from": source,
        "license": spec.license,
        "prepared_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "prepared_with": {p: version(p) for p in ("ctranslate2", "transformers", "torch")},
        "files": hash_tree(target),
    }
    _write_lock(paths, lock)
    shutil.rmtree(raw, ignore_errors=True)
    log(f"[{key}] ready ({len(lock[key]['files'])} files hashed)")
