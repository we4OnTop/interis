"""The page's Content-Security-Policy: strict, with a fresh nonce per response for the
styles the UI library injects. Nothing may re-enable inline styles in general."""

import re

from fastapi.testclient import TestClient

from interis.config import Paths
from interis.web.app import create_app

BASE = "http://127.0.0.1:8765"


def _client(tmp_path) -> TestClient:
    paths = Paths(tmp_path)
    paths.ensure()
    return TestClient(create_app(paths, "test-token", 8765), base_url=BASE)  # noqa: S106


def test_index_policy_allows_only_the_page_nonce_and_one_known_hash(tmp_path):
    r = _client(tmp_path).get("/")
    csp = r.headers["content-security-policy"]
    style = re.search(r"style-src ([^;]+);", csp).group(1).split()
    nonces = [s for s in style if s.startswith("'nonce-")]
    assert len(nonces) == 1 and "'self'" in style
    assert "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
    assert "script-src 'self';" in csp  # scripts stay same-origin files only
    nonce = nonces[0][len("'nonce-"):-1]
    assert f'<meta name="csp-nonce" content="{nonce}"' in r.text
    assert "__CSP_NONCE__" not in r.text


def test_every_response_gets_a_new_nonce(tmp_path):
    c = _client(tmp_path)
    nonces = {re.search(r"'nonce-([^']+)'", c.get("/").headers["content-security-policy"]).group(1)
              for _ in range(3)}
    assert len(nonces) == 3
