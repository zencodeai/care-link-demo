"""Archived links require exact retained bytes; active broken links still fail."""

import hashlib
import json

from tools.imp05_verification.history_links import broken_links


def test_digest_bound_original_location_does_not_hide_active_broken_link(tmp_path):
    root = tmp_path / "doc"
    archive = root / "archive"
    archive.mkdir(parents=True)
    content = b"[target](target.md)\n"
    (archive / "old.md").write_bytes(content)
    (root / "target.md").write_text("Retained target\n")
    mapping = {
        "entries": [
            {
                "original_path": "doc/old.md",
                "path": "doc/archive/old.md",
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ]
    }
    (archive / "relocations.json").write_text(json.dumps(mapping))
    assert broken_links(root, tmp_path) == []
    (root / "current.md").write_text("[missing](absent.md)\n")
    assert broken_links(root, tmp_path) == [("current.md", "absent.md")]
    (root / "current.md").unlink()
    (archive / "old.md").write_text("Changed retained bytes [target](target.md)\n")
    assert broken_links(root, tmp_path) == [("archive/old.md", "target.md")]
