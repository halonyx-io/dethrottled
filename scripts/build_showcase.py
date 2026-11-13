"""Architecture and profile illustrations.

The README hero and escalation images are built by build_readme_art.py.
"""

from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/assets"
OUT.mkdir(exist_ok=True)
BG, PANEL, LINE, CYAN, WHITE, MUTED = (
    "#0F1720",
    "#16212C",
    "#2A3540",
    "#22D3EE",
    "#F8FAFC",
    "#93A3B2",
)


def text(x, y, value, size=20, color=WHITE, weight=400):
    return (
        f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" '
        f'font-weight="{weight}">{escape(value)}</text>'
    )


def box(x, y, w, h, title, lines=(), accent=False):
    content = (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" '
        f'fill="{PANEL}" stroke="{CYAN if accent else LINE}"/>'
    )
    content += text(x + 22, y + 36, title, 22, CYAN if accent else WHITE, 600)
    for i, label in enumerate(lines):
        content += text(x + 22, y + 68 + i * 26, label, 17, MUTED)
    return content


def arrow(x1, y1, x2, y2):
    return (
        f'<path d="M{x1},{y1} L{x2},{y2}" fill="none" stroke="{CYAN}" '
        'stroke-width="2" marker-end="url(#arrow)"/>'
    )


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
<rect width="1200" height="{height}" rx="16" fill="{BG}"/>

<g font-family="Inter,DejaVu Sans,Arial,sans-serif">{content}</g></svg>'''
    (OUT / name).write_text(svg + "\n")


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
s += f'<path d="M750 258 V290 H220 M750 290 H980" stroke="{CYAN}" stroke-width="2" fill="none"/>'
for i, (name, lines) in enumerate(
    [
        ("DNB browser", ["Headed Chromium", "DDG, rendering and drive", "Sessions + checkpoints"]),
        ("SearXNG", ["Supplementary search", "Private engine gateway"]),
        ("Format reader", ["MSG and XLSB", "Private Apache Tika"]),
    ]
):
    x = 45 + i * 380
    s += arrow(x + 175, 290, x + 175, 307)
    s += box(x, 317, 350, 144, name, lines)
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
    "DEFAULT · FOUR SERVICES",
    [
        "API + document libraries + OCR + corpus models",
        "DNB browser (search, rendering, drive) + SearXNG",
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
