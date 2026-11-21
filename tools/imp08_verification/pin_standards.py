"""Explicit read-only official-source pinning; never updates live control policy."""

import hashlib
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    "asvs": "https://raw.githubusercontent.com/OWASP/ASVS/v5.0.0/5.0/en/0x17-V8-Authorization.md",
    "llm01": "https://genai.owasp.org/llmrisk/llm01-prompt-injection/",
    "llm06": "https://genai.owasp.org/llmrisk/llm062025-excessive-agency/",
    "agentic": "https://genai.owasp.org/download/52117/",
}


def fetch(url: str) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("HTTPS official sources only")
    request = urllib.request.Request(  # noqa: S310
        url, headers={"User-Agent": "CARE-Link-source-pin/1"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        value = response.read(16_000_001)
    if len(value) > 16_000_000:
        raise ValueError("Source exceeds bounded pinning size")
    return value


def main() -> None:
    # Pin ATLAS to its actual repository revision rather than a moving latest URL.
    commit = json.loads(fetch("https://api.github.com/repos/mitre-atlas/atlas-data/commits/main"))[
        "sha"
    ]
    urls = {
        **SOURCES,
        "atlas": f"https://raw.githubusercontent.com/mitre-atlas/atlas-data/{commit}/dist/v6/ATLAS-2026.10.yaml",
    }
    output = {}
    for name, url in urls.items():
        value = fetch(url)
        if name == "asvs" and b"8.3.2" not in value:
            raise ValueError("ASVS identifier missing")
        if name == "atlas" and b"AML.T0051" not in value:
            raise ValueError("ATLAS identifier missing")
        output[name] = {
            "url": url,
            "sha256": hashlib.sha256(value).hexdigest(),
            "bytes": len(value),
            "retrieved_at": datetime.now(UTC).isoformat(),
        }
    target = ROOT / "config/demo/imp08/standards-sources.json"
    target.write_text(json.dumps(output, indent=2) + "\n")
    print("Pinned five official source artifacts; no live policy changed.")


if __name__ == "__main__":
    main()
