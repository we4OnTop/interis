import os
import pickle
import zipfile
from collections import OrderedDict

import pytest
import torch

from interis.security.pickle_scan import (
    UnsafeCheckpointError,
    assert_safe_checkpoint,
    is_allowed,
    iter_pickle_globals,
    scan_checkpoint,
)


class _Evil:
    def __reduce__(self):
        return (os.system, ("echo pwned",))


def _zip_with_pickle(path, payload: bytes):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("archive/data.pkl", payload)


def test_regular_torch_state_dict_is_accepted(tmp_path):
    path = tmp_path / "model.bin"
    torch.save(OrderedDict(w=torch.zeros(2, 3), b=torch.ones(3)), path)
    result = assert_safe_checkpoint(path)
    assert result.ok
    assert any("torch._utils:_rebuild_tensor" in g for g in result.globals_found)


@pytest.mark.parametrize("protocol", [2, 4])
def test_os_system_payload_is_rejected(tmp_path, protocol):
    path = tmp_path / "evil.bin"
    _zip_with_pickle(path, pickle.dumps(_Evil(), protocol=protocol))
    result = scan_checkpoint(path)
    assert not result.ok
    assert any("system" in g for g in result.rejected)
    with pytest.raises(UnsafeCheckpointError):
        assert_safe_checkpoint(path)


def test_legacy_non_zip_format_is_rejected(tmp_path):
    path = tmp_path / "legacy.bin"
    path.write_bytes(pickle.dumps({"a": 1}))
    with pytest.raises(UnsafeCheckpointError):
        scan_checkpoint(path)


@pytest.mark.parametrize(
    ("module", "attr", "allowed"),
    [
        ("torch._utils", "_rebuild_tensor_v2", True),
        ("collections", "OrderedDict", True),
        ("builtins", "set", True),
        ("builtins", "eval", False),
        ("builtins", "getattr", False),
        ("os", "system", False),
        ("subprocess", "Popen", False),
        ("torch", "load", False),
        ("torch.serialization", "load", False),
        ("pathlib", "Path.write_text", False),   # getattr chain
        ("pyannote.audio.core.task", "Specifications", True),
        ("pyannote.audio.core.task", "__init__", False),
        ("_codecs", "encode", True),
        ("_codecs", "decode", False),
    ],
)
def test_allowlist(module, attr, allowed):
    assert is_allowed(module, attr) is allowed


def test_stack_global_with_memo_is_resolved():
    data = pickle.dumps(_Evil(), protocol=4)
    found = list(iter_pickle_globals(data))
    assert any(attr == "system" for _m, attr in found)
