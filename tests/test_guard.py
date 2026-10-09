"""The network guard is installed via an (irremovable) audit hook, so each test runs in a
fresh subprocess."""

import subprocess
import sys
import textwrap


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True, text=True, timeout=60, check=False,
    )


def test_public_connection_and_dns_are_blocked():
    r = _run("""
        import socket
        from interis import _bootstrap
        _bootstrap.go_offline()
        for attempt in (lambda: socket.create_connection(("192.0.2.1", 443), timeout=1),
                        lambda: socket.getaddrinfo("huggingface.co", 443)):
            try:
                attempt()
            except _bootstrap.NetworkBlockedError:
                print("BLOCKED")
        """)
    assert r.stdout.split() == ["BLOCKED", "BLOCKED"], r.stderr


def test_loopback_is_allowed():
    r = _run("""
        import socket
        from interis import _bootstrap
        _bootstrap.go_offline()
        srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
        c = socket.create_connection(srv.getsockname(), timeout=2)
        c.close(); srv.close()
        print("OK")
        """)
    assert r.stdout.strip() == "OK", r.stderr


def test_http_library_cannot_reach_internet():
    r = _run("""
        import urllib.request
        from interis import _bootstrap
        _bootstrap.go_offline()
        try:
            urllib.request.urlopen("https://huggingface.co", timeout=2)
            print("LEAK")
        except Exception as e:
            print("BLOCKED" if _bootstrap.blocked_attempts else f"OTHER {e!r}")
        """)
    assert r.stdout.strip() == "BLOCKED", r.stdout + r.stderr


def test_offline_env_and_telemetry_overrides():
    r = _run("""
        import os
        os.environ["PYANNOTE_METRICS_ENABLED"] = "true"   # inherited opt-in must be overridden
        from interis import _bootstrap
        _bootstrap.go_offline()
        print(os.environ["PYANNOTE_METRICS_ENABLED"], os.environ["HF_HUB_OFFLINE"],
              os.environ["HF_HUB_DISABLE_TELEMETRY"], _bootstrap.is_offline())
        """)
    assert r.stdout.split() == ["0", "1", "1", "True"], r.stderr


def test_require_offline_refuses_without_bootstrap():
    r = _run("""
        from interis import _bootstrap
        try:
            _bootstrap.require_offline()
            print("RAN")
        except RuntimeError:
            print("REFUSED")
        """)
    assert r.stdout.strip() == "REFUSED"


def test_proxy_settings_are_removed_so_the_hook_sees_real_destinations():
    r = _run("""
        import os
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9"
        from interis import _bootstrap
        _bootstrap.go_offline()
        print("GONE" if "HTTPS_PROXY" not in os.environ else "STILL SET")
        print("SAVED" if _bootstrap.proxy_env_removed.get("HTTPS_PROXY") else "NOT SAVED")
        """)
    assert r.stdout.split() == ["GONE", "SAVED"], r.stdout + r.stderr


def test_reverse_dns_lookups_are_blocked_but_loopback_is_not():
    r = _run("""
        import socket
        from interis import _bootstrap
        _bootstrap.go_offline()
        for attempt in (lambda: socket.gethostbyaddr("8.8.8.8"),
                        lambda: socket.getnameinfo(("8.8.8.8", 53), 0)):
            try:
                attempt()
            except _bootstrap.NetworkBlockedError:
                print("BLOCKED")
        print("LOOPBACK-OK" if socket.gethostbyaddr("127.0.0.1") else "")
        """)
    assert r.stdout.split() == ["BLOCKED", "BLOCKED", "LOOPBACK-OK"], r.stdout + r.stderr


def test_system_proxy_lookup_returns_nothing_after_go_offline():
    r = _run("""
        import os, urllib.request
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9"
        from interis import _bootstrap
        _bootstrap.go_offline()
        print("PROXIES", urllib.request.getproxies())
        """)
    assert r.stdout.strip() == "PROXIES {}", r.stdout + r.stderr
