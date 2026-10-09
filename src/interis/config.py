"""Locations of all data. Interview data lives under one data directory, which should be
on an encrypted (VeraCrypt) volume. It must be configured explicitly – there is no
default, so interview data never lands somewhere unintended (e.g. a OneDrive folder).

The models (~8 GB, no personal data) can live elsewhere, e.g. on a USB stick or a second
drive, and are only *referenced* ("linked"), never copied.

Where the folders are is taken, in this order, from: command line, environment variables
(``INTERIS_DATA_DIR`` / ``INTERIS_MODELS_DIR``), the settings file ``interis.json``
(next to ``Interis.exe`` in the portable version, else ``%APPDATA%/Interis``)."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

DATA_DIR_ENV = "INTERIS_DATA_DIR"
MODELS_DIR_ENV = "INTERIS_MODELS_DIR"
HOME_ENV = "INTERIS_HOME"  # set by Interis.exe: folder of the portable version


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Paths:
    root: Path
    models_dir: Path | None = None  # default: <root>/models

    @property
    def models(self) -> Path:
        return self.models_dir or self.root / "models"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def exports(self) -> Path:
        return self.root / "exports"

    @property
    def audio(self) -> Path:
        """Recordings uploaded through the website (named by interview ID only)."""
        return self.root / "audio"

    @property
    def tmp(self) -> Path:
        return self.root / "tmp"

    @property
    def voices(self) -> Path:
        """Voice profiles (biometric data – stays in the encrypted data directory)."""
        return self.root / "voices"

    @property
    def hf_home(self) -> Path:
        return self.models / "hf_home"

    def ensure(self) -> None:
        for p in (self.models, self.cache, self.exports, self.tmp, self.hf_home):
            p.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------ settings file

def settings_file() -> Path:
    home = os.environ.get(HOME_ENV)
    if home:
        return Path(home) / "interis.json"
    return Path(os.environ.get("APPDATA") or Path.home()) / "Interis" / "interis.json"


def _store_path(p: Path, base: Path) -> str:
    """Relative to the settings file when on the same drive, so a portable copy on a USB
    stick keeps working when Windows assigns another drive letter."""
    try:
        if p.drive.lower() == base.drive.lower():
            return os.path.relpath(p, base)
    except ValueError:
        pass
    return str(p)


def load_settings() -> dict[str, Path]:
    f = settings_file()
    if not f.is_file():
        return {}
    raw = json.loads(f.read_text(encoding="utf-8"))
    out = {}
    for key in ("data_dir", "models_dir"):
        if raw.get(key):
            p = Path(raw[key])
            out[key] = (p if p.is_absolute() else f.parent / p).resolve()
    return out


def save_settings(data_dir: Path, models_dir: Path | None) -> Path:
    f = settings_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    body = {"data_dir": _store_path(data_dir.resolve(), f.parent)}
    if models_dir is not None:
        body["models_dir"] = _store_path(models_dir.resolve(), f.parent)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, indent=2), encoding="utf-8")
    os.replace(tmp, f)
    return f


def _refuse_network_path(value: str) -> None:
    """Interview data must stay on the local encrypted volume: UNC shares are refused."""
    if value.startswith(("\\\\", "//")):
        raise ConfigError(
            f"Netzwerkpfade werden nicht unterstützt: {value}. Bitte einen Ordner auf dem "
            "lokalen, verschlüsselten Laufwerk verwenden.")


def resolve_paths(cli_value: str | None, cli_models: str | None = None) -> Paths:
    settings = load_settings()
    value = cli_value or os.environ.get(DATA_DIR_ENV) or settings.get("data_dir")
    if not value:
        raise ConfigError(
            f"No data directory configured. Set {DATA_DIR_ENV} or pass --data-dir. "
            "It should point to a folder on your encrypted VeraCrypt volume, "
            r"e.g. X:\interis-data"
        )
    _refuse_network_path(str(value))
    root = Path(value).expanduser().resolve()
    if not root.exists():
        raise ConfigError(f"Data directory does not exist: {root}")
    models = cli_models or os.environ.get(MODELS_DIR_ENV) or settings.get("models_dir")
    if models:
        _refuse_network_path(str(models))
    models_dir = Path(models).expanduser().resolve() if models else None
    if models_dir is not None and not models_dir.exists():
        raise ConfigError(f"Models directory does not exist: {models_dir}")
    return Paths(root, models_dir)


def apply_paths(paths: Paths) -> None:
    """Redirect library caches and temp files into the data directory.

    Must run before huggingface_hub / torch are imported."""
    paths.ensure()
    os.environ["HF_HOME"] = str(paths.hf_home)
    os.environ["TORCH_HOME"] = str(paths.models / "torch_home")
    os.environ["TMP"] = os.environ["TEMP"] = os.environ["TMPDIR"] = str(paths.tmp)
    tempfile.tempdir = str(paths.tmp)
