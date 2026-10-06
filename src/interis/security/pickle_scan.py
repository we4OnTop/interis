"""Static scan of PyTorch checkpoints for dangerous pickle imports.

Some models we depend on only exist as pickle-based checkpoints (``pytorch_model.bin``),
and pyannote.audio loads its checkpoints with ``torch.load(weights_only=False)``. Loading a
pickle can execute arbitrary code, so before any such file is loaded we list every global
(``module`` + ``name``) the pickle would import and reject anything outside a strict
allowlist. The scan never unpickles anything; it only walks the opcode stream.
"""

from __future__ import annotations

import pickletools
import re
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

_TORCH_DTYPE = re.compile(
    r"^(u?int(8|16|32|64)|float(16|32|64)|bfloat16|complex(32|64|128)|bool|half|double"
    r"|long|short|cfloat|cdouble|qint8|quint8|qint32|float8_\w+)$"
)


def _public(attr: str) -> bool:
    return not attr.startswith("_")


# module -> predicate on attribute name
_ALLOWED: dict[str, Callable[[str], bool]] = {
    "collections": lambda a: a in {"OrderedDict", "defaultdict", "deque"},
    "builtins": lambda a: a in {"set", "frozenset", "dict", "list", "tuple", "int", "float",
                                "bool", "str", "bytes", "bytearray", "slice", "complex"},
    "_codecs": lambda a: a == "encode",
    "torch": lambda a: a.endswith("Storage") or a in {"Size", "device", "dtype"}
    or bool(_TORCH_DTYPE.match(a)),
    "torch._utils": lambda a: a.startswith("_rebuild_"),
    "torch._tensor": lambda a: a == "_rebuild_from_type_v2",
    "torch.storage": lambda a: a in {"UntypedStorage", "TypedStorage"},
    "torch.serialization": lambda a: a == "_get_layout",
    "torch.nn.parameter": lambda a: a == "Parameter",
    "numpy": lambda a: a in {"ndarray", "dtype"},
    "numpy.core.multiarray": lambda a: a in {"_reconstruct", "scalar"},
    "numpy._core.multiarray": lambda a: a in {"_reconstruct", "scalar"},
    "numpy.dtypes": lambda a: a.endswith("DType"),
    "pathlib": lambda a: a in {"Path", "PosixPath", "WindowsPath", "PurePosixPath",
                               "PureWindowsPath"},
    "typing": _public,
}

# Module prefixes whose *public classes* are expected (hyper-parameters / specifications).
_ALLOWED_PREFIXES: dict[str, Callable[[str], bool]] = {
    "pyannote.audio.": _public,
    "pyannote.core.": _public,
    "omegaconf.": _public,
    "pytorch_lightning.utilities.parsing": lambda a: a == "AttributeDict",
    "lightning.pytorch.utilities.parsing": lambda a: a == "AttributeDict",
    "lightning_fabric.utilities.data": lambda a: a == "AttributeDict",
}


def is_allowed(module: str, attr: str) -> bool:
    # Dotted attribute names allow getattr chains (e.g. "Path.write_text") → never allowed.
    if "." in attr or attr.startswith("__"):
        return False
    rule = _ALLOWED.get(module)
    if rule is not None:
        return rule(attr)
    for prefix, rule in _ALLOWED_PREFIXES.items():
        if module == prefix.rstrip(".") or module.startswith(prefix):
            return rule(attr)
    return False


def iter_pickle_globals(data: bytes) -> Iterator[tuple[str, str]]:
    """Yield ``(module, name)`` for every GLOBAL / STACK_GLOBAL / INST in a pickle."""
    strings: list[str] = []
    memo: dict[int, object] = {}
    last: object = None
    for opcode, arg, _pos in pickletools.genops(data):
        op = opcode.name
        if op in ("GLOBAL", "INST"):
            module, attr = str(arg).split(" ", 1)
            yield module, attr
            last = None
        elif op == "STACK_GLOBAL":
            if len(strings) >= 2:
                yield strings[-2], strings[-1]
            else:
                yield "<unresolved>", "<STACK_GLOBAL>"
            last = None
        elif op in ("SHORT_BINUNICODE", "BINUNICODE", "BINUNICODE8", "UNICODE",
                    "SHORT_BINSTRING", "BINSTRING", "STRING"):
            last = str(arg)
            strings.append(last)
        elif op == "MEMOIZE":
            memo[len(memo)] = last
        elif op in ("PUT", "BINPUT", "LONG_BINPUT"):
            memo[int(arg)] = last
        elif op in ("GET", "BINGET", "LONG_BINGET"):
            value = memo.get(int(arg))
            if isinstance(value, str):
                strings.append(value)
            last = value
        else:
            last = None


def _pickle_blobs(path: Path) -> Iterator[bytes]:
    if not zipfile.is_zipfile(path):
        raise UnsafeCheckpointError(f"{path}: legacy non-zip checkpoint format is not accepted")
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.filename.endswith(".pkl"):
                yield zf.read(info)


@dataclass
class ScanResult:
    path: Path
    globals_found: set[str] = field(default_factory=set)
    rejected: set[str] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return not self.rejected


class UnsafeCheckpointError(Exception):
    pass


def scan_checkpoint(path: Path) -> ScanResult:
    result = ScanResult(path=Path(path))
    for blob in _pickle_blobs(Path(path)):
        for module, attr in iter_pickle_globals(blob):
            name = f"{module}:{attr}"
            result.globals_found.add(name)
            if not is_allowed(module, attr):
                result.rejected.add(name)
    return result


def assert_safe_checkpoint(path: Path) -> ScanResult:
    result = scan_checkpoint(path)
    if not result.ok:
        raise UnsafeCheckpointError(
            f"{path}: checkpoint imports non-allowlisted globals {sorted(result.rejected)}; "
            "refusing to load it."
        )
    return result
