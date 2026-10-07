"""The committed web build must be complete: every file that ``index.html`` references has
to be in the repository, or the portable app opens on a blank page."""

import re
from pathlib import Path

DIST = Path(__file__).resolve().parents[1] / "src" / "interis" / "web" / "dist"


def test_every_asset_referenced_by_index_html_exists():
    html = (DIST / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="/([^"]+)"', html)
    assert refs, "index.html references no assets"
    missing = [r for r in refs if not (DIST / r).is_file()]
    assert not missing, f"committed build is incomplete, missing: {missing}"
