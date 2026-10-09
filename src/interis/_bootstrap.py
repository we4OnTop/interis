"""Process-wide privacy settings.

Must run before any ML library (huggingface_hub, transformers, pyannote) is imported,
because several of them read their configuration at import time. pyannote.audio, for
example, writes ``PYANNOTE_METRICS_ENABLED=true`` into the environment if the variable is
unset when it is imported.

Two modes:

* :func:`disable_telemetry` – used by ``interis setup-models``. Network allowed for the
  explicit model download, but no telemetry.
* :func:`go_offline` – used by every other command. Telemetry off, all libraries in
  offline mode, and an audit hook that blocks every non-loopback socket operation made from
  Python (connect, send, name lookups and reverse lookups). Proxy settings are ignored.
  Audit hooks cannot be removed, so this lasts for the whole process.

What the hook does NOT see: child processes and native code that open sockets themselves.
Those are covered by the Windows Firewall rule (``scripts/firewall.ps1``), which blocks the
Python interpreter, and by ``interis doctor``, which checks that the rule exists. Both
layers are needed; the hook alone is not a complete barrier.
"""

from __future__ import annotations

import ipaddress
import os
import sys
import urllib.request
from typing import Any

TELEMETRY_OFF: dict[str, str] = {
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
    "PYANNOTE_METRICS_ENABLED": "0",
    "OTEL_SDK_DISABLED": "true",
    "DO_NOT_TRACK": "1",
}

OFFLINE: dict[str, str] = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
}


class NetworkBlockedError(ConnectionError):
    """Raised when code inside the Interis process tries to reach a non-loopback host."""


_state = {"telemetry_off": False, "offline": False, "guard": False}
blocked_attempts: list[str] = []


def disable_telemetry() -> None:
    # Override (not setdefault): an inherited "true" must not re-enable telemetry.
    os.environ.update(TELEMETRY_OFF)
    _state["telemetry_off"] = True


# Proxy settings make libraries connect to the proxy instead of the real host. A proxy on
# 127.0.0.1 would be "local" to the audit hook, which would then never see the destination.
PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
              "http_proxy", "https_proxy", "all_proxy")
# Removed proxy settings, kept so that the explicit model download can still use them.
proxy_env_removed: dict[str, str] = {}


def _no_proxies() -> dict[str, str]:
    return {}


def go_offline() -> None:
    disable_telemetry()
    os.environ.update(OFFLINE)
    for key in PROXY_VARS:
        if key in os.environ:
            proxy_env_removed[key] = os.environ.pop(key)
    # On Windows urllib also reads the system proxy from the registry, which the environment
    # check above does not see. Replacing the lookup covers both sources.
    urllib.request.getproxies = _no_proxies  # type: ignore[assignment]
    install_network_guard()
    _state["offline"] = True


def is_offline() -> bool:
    return _state["offline"] and _state["guard"]


def require_offline() -> None:
    """Called by modules that touch interview data; refuses to run without the guard."""
    if not is_offline():
        raise RuntimeError(
            "Interis privacy bootstrap not active. Call interis._bootstrap.go_offline() "
            "before processing interview data."
        )


def _is_allowed_host(host: Any) -> bool:
    if host is None or host == "" or host == b"":
        return True  # local bind / unspecified
    if isinstance(host, bytes):
        host = host.decode(errors="replace")
    name = str(host).strip("[]").split("%", 1)[0].lower()
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False  # any other hostname would need DNS → not allowed


def _address_host(address: Any) -> Any:
    if isinstance(address, tuple) and address:
        return address[0]
    return None  # AF_UNIX path or similar local address


def _audit_hook(event: str, args: tuple[Any, ...]) -> None:
    if not event.startswith("socket."):
        return
    if event in ("socket.connect", "socket.sendto", "socket.sendmsg"):
        host = _address_host(args[1]) if len(args) > 1 else None
    elif event in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex"):
        host = args[0]
    elif event == "socket.gethostbyaddr":  # reverse lookup: the address itself is the host
        host = args[0]
    elif event == "socket.getnameinfo":  # reverse lookup from a socket address
        host = _address_host(args[0])
    else:
        return
    if not _is_allowed_host(host):
        message = f"Interis network guard blocked {event} to {host!r}"
        blocked_attempts.append(message)
        print(f"[interis] {message}", file=sys.stderr)
        raise NetworkBlockedError(message)


def install_network_guard() -> None:
    if _state["guard"]:
        return
    sys.addaudithook(_audit_hook)
    _state["guard"] = True
