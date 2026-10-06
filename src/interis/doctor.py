"""``interis doctor`` – checks the privacy and integrity guarantees on this machine."""

from __future__ import annotations

import os
import socket
import subprocess  # noqa: S404 – fixed argument list, no shell
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from packaging.version import Version

from interis import _bootstrap
from interis.config import Paths
from interis.models import MODELS, ModelError, verify_ready

# Floors that exclude known CVEs (see DEPENDENCIES.md).
MIN_VERSIONS = {
    "torch": "2.10",
    "transformers": "5.3",
    "ctranslate2": "4.8.1",
    "pyannote.audio": "4.0",
    "faster-whisper": "1.2",
}

OK, WARN, FAIL = "OK", "WARN", "FAIL"


@dataclass
class Check:
    status: str
    name: str
    detail: str


def _check_interpreter() -> Check:
    base = Path(getattr(sys, "_base_executable", sys.executable))
    if "WindowsApps" in str(base):
        return Check(FAIL, "Python interpreter", f"Microsoft Store Python: {base}")
    managed = os.sep + "uv" + os.sep + "python" + os.sep in str(base)
    return Check(OK if managed else WARN, "Python interpreter",
                 f"{base}" + ("" if managed else " (not uv-managed)"))


def _check_versions() -> list[Check]:
    checks = []
    for pkg, floor in MIN_VERSIONS.items():
        try:
            installed = version(pkg)
        except PackageNotFoundError:
            checks.append(Check(FAIL, f"package {pkg}", "not installed"))
            continue
        ok = Version(installed.split("+")[0]) >= Version(floor)
        checks.append(Check(OK if ok else FAIL, f"package {pkg}", f"{installed} (min {floor})"))
    return checks


def _check_env() -> Check:
    wanted = {**_bootstrap.TELEMETRY_OFF, **_bootstrap.OFFLINE}
    wrong = [k for k, v in wanted.items() if os.environ.get(k) != v]
    return Check(FAIL if wrong else OK, "telemetry off / offline mode",
                 f"wrong: {wrong}" if wrong else "all set")


def _check_guard() -> Check:
    try:
        socket.create_connection(("192.0.2.1", 443), timeout=1).close()  # TEST-NET-1
    except _bootstrap.NetworkBlockedError:
        pass
    except OSError as e:
        return Check(FAIL, "network guard", f"connection not blocked by guard: {e!r}")
    else:
        return Check(FAIL, "network guard", "connection to a public IP succeeded")
    try:
        socket.getaddrinfo("huggingface.co", 443)
    except _bootstrap.NetworkBlockedError:
        return Check(OK, "network guard", "public connections and DNS are blocked")
    return Check(FAIL, "network guard", "DNS lookup was not blocked")


def _check_firewall() -> Check:
    if sys.platform != "win32":
        return Check(WARN, "firewall rule", "only checked on Windows")
    base = str(Path(getattr(sys, "_base_executable", sys.executable)).resolve())
    quoted = base.replace("'", "''")
    script = (
        f"$p = '{quoted}'; "
        "@(Get-NetFirewallApplicationFilter | Where-Object { $_.Program -eq $p } | "
        "Get-NetFirewallRule | Where-Object { $_.Direction -eq 'Outbound' -and "
        "$_.Action -eq 'Block' -and $_.Enabled -eq 'True' }).Count"
    )
    # Absolute path, so a manipulated PATH cannot substitute another "powershell".
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows"),
                      "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    try:
        out = subprocess.run(  # noqa: S603
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=60, check=False,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return Check(WARN, "firewall rule", f"could not query firewall: {e}")
    if out.isdigit() and int(out) > 0:
        return Check(OK, "firewall rule", f"outbound block active for {base}")
    return Check(WARN, "firewall rule",
                 "no outbound block rule yet – run scripts\\firewall.ps1 as administrator "
                 "(after `interis setup-models`)")


def _check_data_dir(paths: Paths) -> list[Check]:
    root = paths.root
    checks = [Check(OK, "data directory", str(root))]
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        od = os.environ.get(var)
        if od and root.is_relative_to(Path(od).resolve()):
            checks.append(Check(FAIL, "data dir not in OneDrive", f"{root} is inside {od}"))
            break
    else:
        checks.append(Check(OK, "data dir not in OneDrive", "no OneDrive path"))
    home = Path.home()
    risky = [home / "Desktop", home / "Documents", home / "Pictures"]
    if any(root.is_relative_to(r) for r in risky):
        checks.append(Check(WARN, "data dir location",
                            "inside Desktop/Documents – Windows may back these up to OneDrive; "
                            "use the encrypted VeraCrypt volume instead"))
    if root.drive.upper() == Path(os.environ.get("SystemDrive", "C:") + "\\").drive.upper():
        checks.append(Check(WARN, "data dir encryption",
                            "on the system drive – make sure it is a mounted VeraCrypt volume or "
                            "an encrypted disk"))
    return checks


def _check_models(paths: Paths) -> list[Check]:
    checks = []
    for key in MODELS:
        try:
            verify_ready(paths, key)
            checks.append(Check(OK, f"model {key}", "present, hashes verified"))
        except ModelError as e:
            status = WARN if "not set up" in str(e) else FAIL
            checks.append(Check(status, f"model {key}", str(e)))
    return checks


def run_doctor(paths: Paths) -> int:
    checks: list[Check] = [_check_interpreter(), *_check_versions(), _check_env(),
                           _check_guard(), _check_firewall(), *_check_data_dir(paths),
                           *_check_models(paths)]
    width = max(len(c.name) for c in checks)
    for c in checks:
        print(f"[{c.status:4}] {c.name:<{width}}  {c.detail}")
    failed = sum(c.status == FAIL for c in checks)
    warned = sum(c.status == WARN for c in checks)
    print(f"\n{failed} failed, {warned} warnings")
    return 1 if failed else 0
