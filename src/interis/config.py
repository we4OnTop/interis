"""Locations of all data. Everything lives under one data directory, which should be on an
encrypted (VeraCrypt) volume. The directory must be configured explicitly – there is no
default, so interview data never lands somewhere unintended (e.g. a OneDrive folder)."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

DATA_DIR_ENV = "INTERIS_DATA_DIR"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def models(self) -> Path:
        return self.root / "models"

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


def resolve_paths(cli_value: str | None) -> Paths:
    value = cli_value or os.environ.get(DATA_DIR_ENV)
    if not value:
        raise ConfigError(
            f"No data directory configured. Set {DATA_DIR_ENV} or pass --data-dir. "
            "It should point to a folder on your encrypted VeraCrypt volume, "
            r"e.g. X:\interis-data"
        )
    root = Path(value).expanduser().resolve()
    if not root.exists():
        raise ConfigError(f"Data directory does not exist: {root}")
    return Paths(root)


def apply_paths(paths: Paths) -> None:
    """Redirect library caches and temp files into the data directory.

    Must run before huggingface_hub / torch are imported."""
    paths.ensure()
    os.environ["HF_HOME"] = str(paths.hf_home)
    os.environ["TORCH_HOME"] = str(paths.models / "torch_home")
    os.environ["TMP"] = os.environ["TEMP"] = os.environ["TMPDIR"] = str(paths.tmp)
    tempfile.tempdir = str(paths.tmp)
