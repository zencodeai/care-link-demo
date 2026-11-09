"""Small escaped Markdown subset for the accepted public support card.

No raw HTML, images, script, embedded content or request-time network fetches.
Unknown/unsafe markup remains readable escaped text rather than executable input.
"""

import base64
import hashlib
import re
from html import escape
from urllib.parse import parse_qsl, urlsplit

from .publication import PublicText

STYLES = """html{font-family:system-ui,sans-serif;color:#183a3a;background:#fff;line-height:1.65}
*{box-sizing:border-box}body{margin:0}main{max-width:48rem;margin:auto;padding:1.25rem}
h1{font-size:clamp(1.6rem,5vw,2.3rem);line-height:1.25}h2{font-size:1.3rem;margin-top:1.6em}
h3{font-size:1.15rem}p,li,h1,h2,h3,a{overflow-wrap:anywhere}ul{padding-inline-start:1.4em}
a{color:#175a75;text-decoration:underline;text-underline-offset:.15em}
a:focus-visible{outline:3px solid #a84d00;outline-offset:3px}
.review-status{border:2px solid #7a5b25;padding:1rem}
@media(min-width:40rem){main{padding:2rem}}"""
STYLE_HASH = base64.b64encode(hashlib.sha256(STYLES.encode()).digest()).decode()
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; "
    f"style-src 'sha256-{STYLE_HASH}'"
)
INLINE = re.compile(r"\[([^\[\]\n]{1,200})\]\(([^()\s]{1,2048})\)|\*\*([^*\n]{1,1000})\*\*")


def safe_link(value: str) -> bool:
    if not value or any(ord(character) < 33 or character == "\\" for character in value):
        return False
    try:
        url = urlsplit(value)
        if url.scheme == "https":
            return bool(
                value.startswith("https://")
                and url.hostname
                and not url.username
                and not url.password
            )
        if url.scheme in {"tel", "sms"}:
            return bool(
                not url.netloc
                and not url.fragment
                and re.fullmatch(r"\+?[0-9][0-9 .-]{0,31}", url.path)
                and all(key == "oai_link_source" for key, _value in parse_qsl(url.query))
            )
    except ValueError:
        return False
    return False


def inline(raw: str) -> str:
    result: list[str] = []
    position = 0
    for match in INLINE.finditer(raw):
        result.append(escape(raw[position : match.start()]))
        label, target, strong = match.groups()
        if strong is not None:
            result.append(f"<strong>{escape(strong)}</strong>")
        elif label is not None and target is not None and safe_link(target):
            result.append(
                f'<a href="{escape(target, quote=True)}" rel="noreferrer noopener">'
                f"{escape(label)}</a>"
            )
        else:
            result.append(escape(match.group()))
        position = match.end()
    result.append(escape(raw[position:]))
    return "".join(result)


def markdown(raw: str) -> str:
    blocks: list[str] = []
    paragraph: list[str] = []
    items: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append(f"<p>{inline(' '.join(paragraph))}</p>")
            paragraph.clear()
        if items:
            blocks.append("<ul>" + "".join(f"<li>{inline(item)}</li>" for item in items) + "</ul>")
            items.clear()

    for line in raw.splitlines():
        if not line.strip():
            flush()
        elif line.startswith(("## ", "### ")):
            flush()
            level, content = (3, line[4:]) if line.startswith("### ") else (2, line[3:])
            blocks.append(f"<h{level}>{inline(content)}</h{level}>")
        elif line.startswith("- "):
            if paragraph:
                flush()
            items.append(line[2:])
        else:
            if items:
                flush()
            paragraph.append(line)
    flush()
    return "".join(blocks)


def page(text: PublicText, *, owner_demo: bool = False) -> str:
    status = ""
    if owner_demo:
        notice = (
            "Owner-reviewed local engineering demo. Independent review is not established. "
            "Participant admission is disabled."
            if text.locale == "en-CA"
            else "Démonstration technique locale révisée par le propriétaire. La révision "
            "indépendante n’est pas établie. L’admission des participants est désactivée."
        )
        status = f'<p class="review-status">{escape(notice)}</p>'
    return (
        f'<!doctype html><html lang="{text.locale}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(text.title)}</title><style>{STYLES}</style></head>"
        f"<body><main><h1>{escape(text.title)}</h1>{status}{markdown(text.text)}</main></body></html>"
    )
