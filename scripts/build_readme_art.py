"""Build the README hero and escalation illustrations (Halonyx house style).

    python scripts/build_readme_art.py --fonts DIR

DIR holds the Halonyx style kit's static fonts (Inter-Regular.ttf,
Inter-SemiBold.ttf, SpaceGrotesk-SemiBold.ttf, SpaceGrotesk-Bold.ttf); see
https://halonyx.io/style/. GitHub shows SVGs as images, which cannot load web
fonts, so each file embeds a WOFF2 subset of exactly the glyphs it uses.
Needs fontTools and brotli. Palette and type follow the kit's tokens.json.
"""

from __future__ import annotations

import argparse
import base64
import io
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/assets"

INK, CARD, SURFACE = "#0F1720", "#16212C", "#1D2B38"
OFFWHITE, MUTED, CYAN, RULE = "#F8FAFC", "#93A3B2", "#22D3EE", "#2A3A48"
FONTS = {  # family name in the SVG -> kit file
    "hx-inter": "Inter-Regular.ttf",
    "hx-inter-semibold": "Inter-SemiBold.ttf",
    "hx-grotesk": "SpaceGrotesk-SemiBold.ttf",
    "hx-grotesk-bold": "SpaceGrotesk-Bold.ttf",
}


class Canvas:
    def __init__(self, width, height, title):
        self.width, self.height, self.title = width, height, title
        self.parts, self.used = [], {name: set() for name in FONTS}

    def text(self, x, y, value, *, size=16, family="hx-inter", fill=OFFWHITE,
             spacing=0.0, anchor="start"):
        self.used[family].update(value)
        extra = f' letter-spacing="{spacing:.2f}"' if spacing else ""
        self.parts.append(
            f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
            f'fill="{fill}" text-anchor="{anchor}"{extra}>{escape(value)}</text>')

    def spans(self, x, y, pieces, *, size=16, family="hx-inter"):
        """One line of differently coloured runs: [(text, colour), ...]."""
        runs = ""
        for value, colour in pieces:
            self.used[family].update(value)
            runs += f'<tspan fill="{colour}">{escape(value)}</tspan>'
        self.parts.append(f'<text x="{x}" y="{y}" font-family="{family}" '
                          f'font-size="{size}" xml:space="preserve">{runs}</text>')

    def raw(self, svg):
        self.parts.append(svg)

    def card(self, x, y, w, h, *, fill=CARD, rule=True, radius=12):
        self.raw(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" '
                 f'fill="{fill}" stroke="{RULE}"/>')
        if rule:  # house style: 2px cyan top rule on cards
            self.raw(f'<path d="M{x + radius} {y + 1}H{x + w - radius}" stroke="{CYAN}" '
                     f'stroke-width="2" stroke-linecap="round"/>')

    def chip(self, x, y, label):
        width = round(len(label) * 8.9 + 40)
        self.raw(f'<rect x="{x}" y="{y}" width="{width}" height="34" rx="17" '
                 f'fill="{CARD}" stroke="{RULE}"/>')
        self.raw(f'<circle cx="{x + 16}" cy="{y + 17}" r="3.5" fill="{CYAN}"/>')
        self.text(x + 27, y + 22, label, size=14, family="hx-inter-semibold")
        return x + width + 10

    def save(self, name, fonts_dir):
        faces = "".join(_face(family, fonts_dir / file, self.used[family])
                        for family, file in FONTS.items() if self.used[family])
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" '
               f'height="{self.height}" viewBox="0 0 {self.width} {self.height}" '
               f'role="img" aria-labelledby="t"><title id="t">{escape(self.title)}</title>'
               f'<defs><style>{faces}</style>'
               f'<pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">'
               f'<path d="M32 0H0V32" fill="none" stroke="{SURFACE}" stroke-width="1"/>'
               f'</pattern>'
               f'<marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" '
               f'markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" '
               f'fill="{CYAN}"/></marker></defs>'
               f'<rect width="{self.width}" height="{self.height}" rx="16" fill="{INK}"/>'
               f'<rect width="{self.width}" height="{self.height}" rx="16" fill="url(#grid)" '
               f'opacity=".55"/>' + "".join(self.parts) + "</svg>\n")
        (OUT / name).write_text(svg)
        return len(svg)


def _face(family, path, chars):
    from fontTools import subset
    from fontTools.ttLib import TTFont
    font = TTFont(path)
    options = subset.Options()
    options.flavor, options.layout_features, options.name_IDs = "woff2", ["kern"], []
    subsetter = subset.Subsetter(options)
    subsetter.populate(text="".join(sorted(chars | {" "})))
    subsetter.subset(font)
    buffer = io.BytesIO()
    font.flavor = "woff2"
    font.save(buffer)
    data = base64.b64encode(buffer.getvalue()).decode()
    return (f'@font-face{{font-family:"{family}";'
            f'src:url(data:font/woff2;base64,{data}) format("woff2")}}')


def hero(fonts):
    c = Canvas(1280, 440, "dethrottled: self-hosted web access for AI agents. "
               "Search it, read it, drive it, keep it, with no API keys.")
    c.text(64, 92, "SELF-HOSTED WEB ACCESS FOR AI AGENTS", size=14,
           family="hx-inter-semibold", fill=CYAN, spacing=1.2)
    c.text(60, 178, "dethrottled", size=84, family="hx-grotesk-bold")
    c.text(64, 232, "Search it. Read it. Drive it. Keep it.", size=28, family="hx-grotesk")
    c.text(64, 274, "On your own hardware, with results that say exactly", size=18, fill=MUTED)
    c.text(64, 300, "what they got and what to try next.", size=18, fill=MUTED)
    x = 64
    for label in ("No API keys", "AMD64 + ARM64", "MCP + REST", "MIT licensed"):
        x = c.chip(x, 340, label)

    # A real /fetch response, trimmed (README "What a result looks like").
    left, top, width, height = 724, 56, 492, 336
    c.card(left, top, width, height)
    c.text(left + 28, top + 40, "POST /fetch", size=13, family="hx-inter-semibold",
           fill=CYAN, spacing=0.9)
    c.text(left + 132, top + 40, "sqlite.org/wal.html", size=14, fill=MUTED)
    c.raw(f'<path d="M{left + 28} {top + 58}H{left + width - 28}" stroke="{RULE}"/>')
    rows = [("quality", "ok"), ("content_status", "complete"), ("tier", "direct/trafilatura"),
            ("published", "2026-08-25"), ("date_source", "page"),
            ("document_id", "doc_8a903f5c…"), ("warnings", None)]
    y = top + 92
    c.spans(left + 28, y, [("{", OFFWHITE)], size=17)
    for index, (key, value) in enumerate(rows):
        y += 28
        tail = "," if index < len(rows) - 1 else ""
        shown = [("[]", OFFWHITE)] if value is None else [(f'"{value}"', CYAN)]
        c.spans(left + 48, y, [(f'"{key}"', MUTED), (": ", OFFWHITE), *shown,
                                (tail, OFFWHITE)], size=17)
    c.spans(left + 28, y + 28, [("}", OFFWHITE)], size=17)
    return c.save("hero.svg", fonts)


def escalation(fonts):
    c = Canvas(1280, 760, "How a read escalates: plain HTTP, TLS impersonation, a "
               "JavaScript renderer, then a real browser. The result is assessed after "
               "every step and the read stops at the first step that yields the page.")
    c.text(56, 76, "HOW A READ ESCALATES", size=14, family="hx-inter-semibold",
           fill=CYAN, spacing=1.2)
    c.text(56, 118, "Each read climbs only as far as the page needs", size=34,
           family="hx-grotesk")
    c.text(56, 154, "It stops at the first step that yields the page. Steps that cannot "
           "help are skipped, and every step has a deadline.", size=17, fill=MUTED)

    steps = [
        ("01", "Plain HTTP", ["Static pages, PDFs and", "files usually stop here."]),
        ("02", "TLS impersonation", ["A browser-grade handshake", "for sites that refuse",
                                     "plain clients."]),
        ("03", "JavaScript render", ["Headless Chromium. Waits", "for text to settle and",
                                     "scrolls endless feeds."]),
        ("04", "Real browser", ["Headed Chromium clears", "challenges, opens collapsed",
                                "sections, waits out loaders."]),
    ]
    width, gap, base = 262, 40, 352
    for index, (number, title, lines) in enumerate(steps):
        x, y = 56 + index * (width + gap), base - index * 54
        height = 150
        c.card(x, y, width, height)
        c.text(x + 24, y + 42, number, size=15, family="hx-grotesk", fill=CYAN)
        c.text(x + 60, y + 42, title, size=20, family="hx-grotesk")
        for row, line in enumerate(lines):
            c.text(x + 24, y + 76 + row * 23, line, size=15, fill=MUTED)
        if index < len(steps) - 1:
            sx, sy = x + width + 4, y + 30
            c.raw(f'<path d="M{sx} {sy}C{sx + 18} {sy} {sx + 18} {sy - 54} {sx + 32} '
                  f'{sy - 54}" fill="none" stroke="{CYAN}" stroke-width="2" '
                  f'marker-end="url(#arrow)"/>')

    # Outcome: what comes back, whichever step read the page.
    ox, oy, ow, oh = 56, 538, 1168, 132
    c.card(ox, oy, ow, oh, fill=SURFACE)
    c.text(ox + 28, oy + 40, "WHICHEVER STEP READS THE PAGE, THE RESULT CARRIES",
           size=13, family="hx-inter-semibold", fill=CYAN, spacing=0.9)
    for index, (label, detail) in enumerate([
            ("quality, warnings", "ok, thin, partial or failed, and why"),
            ("provenance", "every attempt, tier, timing and hash"),
            ("document_id", "read further without fetching again"),
            ("next_actions", "the exact next call when something is missing")]):
        x, y = ox + 28 + (index % 2) * 572, oy + 78 + (index // 2) * 30
        c.raw(f'<circle cx="{x + 4}" cy="{y - 5}" r="3.5" fill="{CYAN}"/>')
        c.text(x + 18, y, label, size=16, family="hx-inter-semibold")
        c.text(x + 178, y, detail, size=15, fill=MUTED)

    c.text(56, 720, "Assessed after every attempt:", size=15, family="hx-inter-semibold")
    x = 292
    for label in ("readable text?", "app shell?", "challenge page?", "error banner?",
                  "only a teaser?"):
        x = c.chip(x, 698, label)
    return c.save("escalation.svg", fonts)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fonts", type=Path, required=True)
    args = parser.parse_args()
    for build in (hero, escalation):
        print(build.__name__, build(args.fonts), "bytes")


if __name__ == "__main__":
    main()
