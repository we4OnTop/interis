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


class UnsafeCheckpointError(Exception):
    pass


_MARK = object()  # sentinel for MARK on the emulated stack
_CONST = ("NONE", "NEWTRUE", "NEWFALSE", "INT", "BININT", "BININT1", "BININT2", "LONG",
          "LONG1", "LONG4", "BINFLOAT", "FLOAT", "BINBYTES", "SHORT_BINBYTES", "BINBYTES8",
          "BYTEARRAY8", "EMPTY_LIST", "EMPTY_DICT", "EMPTY_TUPLE", "EMPTY_SET", "PERSID")
_STRING_OPS = ("SHORT_BINUNICODE", "BINUNICODE", "BINUNICODE8", "UNICODE", "SHORT_BINSTRING",
               "BINSTRING", "STRING")
_TO_MARK = ("LIST", "TUPLE", "DICT", "FROZENSET", "POP_MARK", "APPENDS", "SETITEMS",
            "ADDITEMS")


def iter_pickle_globals(data: bytes) -> Iterator[tuple[str, str]]:
    """Yield ``(module, name)`` for every global a pickle pushes onto its stack.

    The opcodes are executed on an emulated stack, so a global is found wherever the real
    unpickler would find it (no guessing from recent strings). Opcodes that are not modelled
    here, extension opcodes, out-of-band buffers and stack underflows are refused: the
    checkpoint is treated as unsafe rather than scanned partially.
    """
    stack: list[object] = []
    memo: dict[int, object] = {}

    def pop() -> object:
        if not stack:
            raise UnsafeCheckpointError("pickle stack underflow")
        return stack.pop()

    def pop_to_mark() -> list[object]:
        items: list[object] = []
        while stack and stack[-1] is not _MARK:
            items.append(stack.pop())
        if not stack:
            raise UnsafeCheckpointError("pickle MARK not found")
        stack.pop()  # the marker itself
        return items

    def push_global(module: object, name: object) -> tuple[str, str]:
        if not (isinstance(module, tuple) and module[0] == "str"
                and isinstance(name, tuple) and name[0] == "str"):
            raise UnsafeCheckpointError("STACK_GLOBAL without two strings")
        found = (module[1], name[1])
        stack.append(("global", found))
        return found

    for opcode, arg, _pos in pickletools.genops(data):
        op = opcode.name
        if op in ("PROTO", "FRAME"):
            continue
        if op == "STOP":
            return
        if op in ("GLOBAL", "INST"):
            module, attr = str(arg).split(" ", 1)
            if op == "INST":
                pop_to_mark()
            stack.append(("global", (module, attr)))
            yield module, attr
        elif op == "STACK_GLOBAL":
            name = pop()
            module = pop()
            yield push_global(module, name)
        elif op in _STRING_OPS:
            stack.append(("str", str(arg)))
        elif op in _CONST:
            stack.append(("other", None))
        elif op == "BINPERSID":
            pop()
            stack.append(("other", None))
        elif op == "MARK":
            stack.append(_MARK)
        elif op in _TO_MARK:
            pop_to_mark()
            if op != "POP_MARK" and op not in ("APPENDS", "SETITEMS", "ADDITEMS"):
                stack.append(("other", None))
        elif op in ("TUPLE1", "TUPLE2", "TUPLE3"):
            for _ in range({"TUPLE1": 1, "TUPLE2": 2, "TUPLE3": 3}[op]):
                pop()
            stack.append(("other", None))
        elif op == "APPEND":
            pop()
        elif op == "SETITEM":
            pop()
            pop()
        elif op == "BUILD":
            pop()
        elif op == "REDUCE":
            pop()
            pop()
            stack.append(("other", None))
        elif op == "NEWOBJ":
            pop()
            pop()
            stack.append(("other", None))
        elif op == "NEWOBJ_EX":
            pop()
            pop()
            pop()
            stack.append(("other", None))
        elif op == "OBJ":
            pop_to_mark()
            stack.append(("other", None))
        elif op == "POP":
            pop()
        elif op == "DUP":
            if not stack:
                raise UnsafeCheckpointError("pickle stack underflow")
            stack.append(stack[-1])
        elif op in ("MEMOIZE",):
            if not stack:
                raise UnsafeCheckpointError("pickle stack underflow")
            memo[len(memo)] = stack[-1]
        elif op in ("PUT", "BINPUT", "LONG_BINPUT"):
            if not stack:
                raise UnsafeCheckpointError("pickle stack underflow")
            memo[int(arg)] = stack[-1]
        elif op in ("GET", "BINGET", "LONG_BINGET"):
            if int(arg) not in memo:
                raise UnsafeCheckpointError("pickle GET of an unset memo entry")
            value = memo[int(arg)]
            stack.append(value)
            if isinstance(value, tuple) and value[0] == "global":
                yield value[1]
        else:
            # EXT1/EXT2/EXT4, NEXT_BUFFER, READONLY_BUFFER and anything unknown.
            raise UnsafeCheckpointError(f"unsupported pickle opcode {op}")


def _pickle_blobs(path: Path) -> Iterator[bytes]:
    """The pickles torch would read from this file, or refusal.

    torch decides the format by the signature at offset 0 alone. A zip with junk in front
    is therefore read by torch as a legacy pickle that a zip-based scan would never see.
    """
    with path.open("rb") as f:
        if f.read(4) != b"PK\x03\x04":
            raise UnsafeCheckpointError(
                f"{path}: not a zip archive at offset 0 (legacy checkpoint format is not accepted)")
    if not zipfile.is_zipfile(path):
        raise UnsafeCheckpointError(f"{path}: unreadable zip archive")
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        names = [i.filename for i in infos]
        if len(set(names)) != len(names):
            raise UnsafeCheckpointError(f"{path}: duplicate entry names")
        for info in infos:
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise UnsafeCheckpointError(f"{path}: unsupported compression in {info.filename}")
        for info in infos:
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


def scan_checkpoint(path: Path) -> ScanResult:
    result = ScanResult(path=Path(path))
    try:
        for blob in _pickle_blobs(Path(path)):
            for module, attr in iter_pickle_globals(blob):
                name = f"{module}:{attr}"
                result.globals_found.add(name)
                if not is_allowed(module, attr):
                    result.rejected.add(name)
    except UnsafeCheckpointError as e:
        result.rejected.add(f"<refused: {e}>")
    return result


def assert_safe_checkpoint(path: Path) -> ScanResult:
    result = scan_checkpoint(path)
    if not result.ok:
        raise UnsafeCheckpointError(
            f"{path}: checkpoint imports non-allowlisted globals {sorted(result.rejected)}; "
            "refusing to load it."
        )
    return result
