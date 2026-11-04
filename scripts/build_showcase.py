"""Original vector illustrations; benchmark charts are generated from retained data."""

from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/assets"
OUT.mkdir(exist_ok=True)
BG, PANEL, LINE, CYAN, WHITE, MUTED = (
    "#0b1118",
    "#14212c",
    "#29404d",
    "#43e0d0",
    "#f0f7fa",
    "#9eb2bf",
)


def text(x, y, value, size=20, color=WHITE, weight=400):
    return (f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" '
            f'font-weight="{weight}">{escape(value)}</text>')


def box(x, y, w, h, title, lines=(), accent=False):
    content = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" '
               f'fill="{PANEL}" stroke="{CYAN if accent else LINE}"/>')
    content += text(x + 22, y + 36, title, 22, CYAN if accent else WHITE, 600)
    for i, label in enumerate(lines):
        content += text(x + 22, y + 68 + i * 26, label, 17, MUTED)
    return content


def arrow(x1, y1, x2, y2):
    return (f'<path d="M{x1},{y1} L{x2},{y2}" fill="none" stroke="{CYAN}" '
            'stroke-width="2" marker-end="url(#arrow)"/>')


def save(name, height, title, content):
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}"
viewBox="0 0 1200 {height}"
role="img" aria-labelledby="title"><title id="title">{escape(title)}</title>
<defs>

<marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4"
orient="auto"><path d="M0,0 L8,4 L0,8" fill="{CYAN}"/></marker>

<pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
<path d="M40 0H0V40" fill="none" stroke="{LINE}" stroke-opacity=".22"/></pattern>

</defs>
<rect width="1200" height="{height}" rx="22" fill="{BG}"/>
<rect width="1200" height="{height}" fill="url(#grid)"/>
<g font-family="Inter,DejaVu Sans,Arial,sans-serif">{content}</g></svg>'''
    (OUT / name).write_text(svg + "\n")


s = text(55, 64, "LOCAL-FIRST WEB INFRASTRUCTURE", 17, CYAN, 600)
s += text(50, 155, "dethrottled", 88, WHITE, 700)
s += text(55, 207, "Web evidence. One local engine.", 29, MUTED)
s += text(55, 252, "Discover sources. Read deeply. Drive the browser.", 21, WHITE)
s += text(55, 291, "Keyless default stack · Python + Docker · REST + MCP", 18, MUTED)
for i, (title, subtitle) in enumerate(
    [
        ("SEARCH", "Compact source choices"),
        ("READ", "Pages, files and tables"),
        ("DRIVE", "Native browser actions"),
        ("RETAIN", "Evidence you can revisit"),
    ]
):
    x = 55 + i * 285
    s += box(x, 335, 260, 100, title, [subtitle], accent=i == 2)
    if i < 3:
        s += arrow(x + 263, 385, x + 279, 385)
save("hero.svg", 470, "Dethrottled: discover, read, drive and retain web evidence", s)

s = text(45, 55, "ONE INTERFACE, A COMPLETE LOCAL STACK", 28, WHITE, 600)
s += text(45, 88, "REST and optional MCP adapters expose the same evidence workflow.", 19, MUTED)
s += box(45, 128, 245, 130, "YOUR CLIENT", ["Agent or application", "No model API required"])
s += box(
    350,
    128,
    805,
    130,
    "DETHROTTLED API",
    [
        "Search · fetch · research · drive · retained documents",
        "Acquisition policy, content assessment, provenance and continuation",
    ],
    True,
)
s += arrow(295, 193, 345, 193)
for i, (name, lines) in enumerate(
    [
        ("Browser", ["Headed Chromium", "DDG + interaction"]),
        ("SearXNG", ["Supplementary search", "Private engine gateway"]),
        ("Crawl4AI", ["JavaScript rendering", "Private Chromium pool"]),
        ("Format reader", ["MSG and XLSB", "Private Apache Tika"]),
    ]
):
    x = 45 + i * 285
    s += arrow(x + 130, 270, x + 130, 307)
    s += box(x, 317, 260, 144, name, lines)
s += box(
    45,
    510,
    545,
    119,
    "PERSISTENT EVIDENCE",
    ["Documents, tables, cache, jobs and corpus", "Named data volume; survives stack down"],
)
s += box(
    615,
    510,
    540,
    119,
    "OPTIONAL INFERENCE",
    [
        "Speech transcription · PDF layout + tables",
        "Local models; separate profiles and model volumes",
    ],
)
save("architecture.svg", 665, "Dethrottled architecture and local service boundaries", s)

s = text(45, 55, "AUTONOMOUS READING, WITH A VISIBLE STOPPING POINT", 27, WHITE, 600)
s += text(
    45,
    90,
    "The reader chooses recovery from observed gaps; the agent can continue explicitly.",
    19,
    MUTED,
)
s += box(45, 135, 270, 130, "ACQUIRE", ["Direct HTTP / TLS", "Read source + metadata"])
s += box(
    395,
    135,
    365,
    130,
    "ASSESS",
    ["Useful text? Missing material?", "Challenge, shell or error banner?"],
    True,
)
s += box(
    845,
    135,
    310,
    130,
    "RETURN EVIDENCE",
    ["Quality + warnings + origin", "Document ID + next actions"],
)
s += arrow(320, 200, 385, 200) + arrow(765, 200, 835, 200)
s += arrow(575, 270, 575, 320)
s += box(
    45,
    335,
    350,
    145,
    "PUBLISHER REPRESENTATIONS",
    ["Observed feed / print / structured data", "Keep original source provenance"],
)
s += box(
    425,
    335,
    350,
    145,
    "BROWSER RECOVERY",
    ["Render JS, then headed interaction", "Scroll, details, observed responses"],
)
s += box(
    805,
    335,
    350,
    145,
    "AGENT CONTINUATION",
    ["Reuse /drive session or read ranges", "Inspect pixels and collect downloads"],
)
s += arrow(575, 320, 220, 328) + arrow(575, 320, 600, 328) + arrow(575, 320, 980, 328)
s += (
    '<path d="M600 485 V525 H1170 V200 H1157" stroke="'
    + CYAN
    + '" stroke-width="2" fill="none" marker-end="url(#arrow)"/>'
)
s += text(
    45,
    542,
    "Bounded retries and deadlines. Partial, polluted and blocked outcomes stay explicit.",
    20,
    MUTED,
)
save("escalation.svg", 590, "Acquire, assess, recover and return inspectable evidence", s)

s = text(45, 55, "CHOOSE CAPABILITY, KEEP THE SAME WORKFLOW", 28, WHITE, 600)
s += text(
    45,
    90,
    "Installing the Python package starts nothing. Explicit stack up builds and starts services.",
    18,
    MUTED,
)
s += box(
    45,
    135,
    545,
    215,
    "DEFAULT · FIVE SERVICES",
    [
        "API + document libraries + OCR + corpus models",
        "Headed browser + SearXNG + Crawl4AI",
        "Format reader for MSG / XLSB",
        "No GPU, worker URL or API key required",
    ],
    True,
)
s += box(
    620, 135, 535, 100, "MEDIA PROFILE", ["Adds CPU speech recognition; first-use model download"]
)
s += box(
    620, 255, 535, 100, "LAYOUT PROFILE", ["Adds PDF layout / tables; first-use model download"]
)
s += box(45, 390, 545, 110, "FULL PROFILE", ["Default + media + layout; costs measured separately"])
s += box(
    620,
    390,
    535,
    110,
    "STANDALONE PYTHON",
    ["HTTP/library server; external worker capabilities vary"],
)
save("profiles.svg", 540, "Default stack and optional worker profiles", s)
