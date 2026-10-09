"""Pickle scanner regression tests that do not need torch.

They craft the opcode streams of the bypasses found in the security audit (a POP that
desynchronises a STACK_GLOBAL, a zip with junk in front, extension opcodes) and check that
the scanner refuses them, and that ordinary pickles still pass.
"""

import io
import pickle
import zipfile
from collections import OrderedDict

import pytest

from interis.security.pickle_scan import (
    UnsafeCheckpointError,
    assert_safe_checkpoint,
    iter_pickle_globals,
    scan_checkpoint,
)


def _zip(path, blob: bytes, prefix: bytes = b""):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("archive/data.pkl", blob)
    path.write_bytes(prefix + buf.getvalue())
    return path


class _Payload:
    def __reduce__(self):
        import os

        return (os.system, ("echo should-not-run",))


@pytest.mark.parametrize("protocol", range(0, pickle.HIGHEST_PROTOCOL + 1))
def test_ordinary_ordered_dict_is_accepted(tmp_path, protocol):
    blob = pickle.dumps(OrderedDict([("weight", 1)]), protocol=protocol)
    path = _zip(tmp_path / "ok.bin", blob)
    assert assert_safe_checkpoint(path).ok
    assert "collections:OrderedDict" in scan_checkpoint(path).globals_found


@pytest.mark.parametrize("protocol", range(0, pickle.HIGHEST_PROTOCOL + 1))
def test_os_system_reduce_is_rejected(tmp_path, protocol):
    path = _zip(tmp_path / "bad.bin", pickle.dumps(_Payload(), protocol=protocol))
    result = scan_checkpoint(path)
    # os.system is pickled as posix:system on Linux and nt:system on Windows
    assert not result.ok and any(r.endswith(":system") for r in result.rejected)


def test_pop_cannot_desynchronise_stack_global(tmp_path):
    # push 'os', push 'system', POP, POP, STACK_GLOBAL: the real stack is empty here, so the
    # real unpickler fails. The old string-tracking scanner resolved os.system and passed it.
    blob = (b"\x80\x02" b"\x8c\x02os" b"\x8c\x06system" b"0" b"0" b"\x93" b".")
    path = _zip(tmp_path / "desync.bin", blob)
    result = scan_checkpoint(path)
    assert not result.ok
    assert any("refused" in r for r in result.rejected)


def test_stack_global_with_real_strings_is_still_seen(tmp_path):
    blob = b"\x80\x02" b"\x8c\x02os" b"\x8c\x06system" b"\x93" b"\x8c\x04echo" b"\x85" b"R" b"."
    globals_ = list(iter_pickle_globals(blob))
    assert ("os", "system") in globals_


def test_junk_before_the_zip_is_refused(tmp_path):
    # torch reads a file whose first bytes are not the zip signature as a legacy pickle,
    # which a zip-only scan never sees. Such files are refused outright.
    blob = pickle.dumps(OrderedDict(), protocol=2)
    path = _zip(tmp_path / "prefixed.bin", blob, prefix=b"\x80\x02junk-prefix")
    assert not scan_checkpoint(path).ok


def test_extension_opcode_is_refused(tmp_path):
    blob = b"\x80\x02" b"\x82\x01" b"."  # EXT1 with registry code 1
    result = scan_checkpoint(_zip(tmp_path / "ext.bin", blob))
    assert not result.ok and any("EXT1" in r for r in result.rejected)


@pytest.mark.filterwarnings("ignore:Duplicate name")
def test_duplicate_entry_names_are_refused(tmp_path):
    path = tmp_path / "dup.bin"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("a/data.pkl", pickle.dumps(OrderedDict(), protocol=2))
        zf.writestr("a/data.pkl", pickle.dumps(_Payload(), protocol=2))
    assert not scan_checkpoint(path).ok


def test_unsafe_checkpoint_error_is_raised_for_assert(tmp_path):
    with pytest.raises(UnsafeCheckpointError):
        assert_safe_checkpoint(_zip(tmp_path / "bad.bin", pickle.dumps(_Payload(), protocol=2)))
