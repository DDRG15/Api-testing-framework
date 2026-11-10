"""Render the documentation's Mermaid blocks into a self-contained interactive HTML file."""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DEFAULT_SOURCE = DOCS / "ARCHITECTURE.md"
SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG)
ET.register_namespace("xhtml", "http://www.w3.org/1999/xhtml")


def hover_styles(node_ids: list[str]) -> str:
    rules = [".root:has(.node:hover) .edgePaths path { opacity: 0.16; }"]
    for node_id in node_ids:
        scope = f'.root:has(.node[id*="flowchart-{node_id}-"]:hover)'
        rules.append(f'{scope} path[id*="_{node_id}_"], {scope} path[id*="-{node_id}-"] '
                     '{ stroke: #58a6ff !important; stroke-width: 3.5px !important; opacity: 1 !important; }')
        rules.append(f'{scope} path[id*="L_{node_id}_"], {scope} path[id*="L-{node_id}-"] '
                     '{ stroke: #ffb454 !important; stroke-width: 3.5px !important; opacity: 1 !important; }')
    return "\n".join(rules)


def enrich_svg(source: str) -> tuple[str, list[str], int]:
    root = ET.fromstring(source)
    nodes = {}
    for node in root.iter(f"{{{SVG}}}g"):
        if "node" not in node.get("class", "").split():
            continue
        match = re.search(r"flowchart-(.+)-\d+$", node.get("id", ""))
        if not match:
            raise ValueError(f"Unrecognized Mermaid node ID: {node.get('id')}")
        node_id = match.group(1)
        node.set("data-node-id", node_id)
        label_element = next((e for e in node.iter() if "nodeLabel" in e.get("class", "").split()), node)
        label = " ".join(" ".join(label_element.itertext()).split())
        node.set("data-label", label)
        nodes[node_id] = node
    edges = 0
    for path in root.iter(f"{{{SVG}}}path"):
        if "flowchart-link" not in path.get("class", "").split():
            continue
        edge_id = path.get("id", "")
        pairs = [(a, b) for a in nodes for b in nodes
                 if re.search(rf"(?:^|-)L_{re.escape(a)}_{re.escape(b)}_\d+$", edge_id)]
        if len(pairs) != 1:
            raise ValueError(f"Unrecognized or ambiguous Mermaid edge ID: {edge_id}")
        path.set("data-source", pairs[0][0])
        path.set("data-target", pairs[0][1])
        path.set("class", path.get("class", "") + " edge-connection")
        edges += 1
    if not nodes or not edges:
        raise ValueError("A diagram without nodes or mapped connections cannot be interactive")
    # The standalone viewer owns interaction colors; Markdown hover CSS is not
    # carried over, so its hover state cannot override pinned selection.
    for style in list(root.iter(f"{{{SVG}}}style")):
        style.text = re.sub(r"#\S+\s+\.root:has[^}]*}", "", style.text or "")
    markup = ET.tostring(root, encoding="unicode")
    # HTML parsing enters HTML mode inside foreignObject; preserve ordinary
    # div/span/br tags rather than serializing prefixed custom HTML elements.
    markup = re.sub(r"<(/?)xhtml:", r"<\1", markup)
    return markup, list(nodes), edges


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mmdc", default=shutil.which("mmdc"))
    parser.add_argument("--browser", default=shutil.which("google-chrome") or shutil.which("chromium"))
    parser.add_argument("--work-dir", type=Path, default=Path.home() / "sandbox/enterprise-api-testing-framework/diagram-builds")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DOCS / "architecture.html")
    parser.add_argument("--add-hover", action="store_true", help="Update Markdown hover styles from the rendered node IDs")
    args = parser.parse_args()
    if not args.mmdc or not args.browser:
        parser.error("Provide --mmdc and --browser; see the architecture document's build instructions")
    text = args.source.read_text(encoding="utf-8")
    matches = list(re.finditer(r"```mermaid\n(.*?)```", text, re.S))
    blocks = [match.group(1) for match in matches]
    if not 1 <= len(blocks) <= 2:
        raise ValueError("Expected one or two Mermaid diagrams in the source document")
    titles = []
    for index, match in enumerate(matches):
        headings = re.findall(r"^## (.+)$", text[:match.start()], re.M)
        title = re.sub(r"^\d+\.\s*", "", headings[-1]) if headings else f"Diagram {index + 1}"
        titles.append(title)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    panels = []
    updated_blocks = []
    with tempfile.TemporaryDirectory(prefix="render-", dir=args.work_dir) as temporary:
        directory = Path(temporary)
        browser_config = directory / "browser.json"
        browser_config.write_text(json.dumps({"executablePath": args.browser,
                                              "userDataDir": str(directory / "chrome-profile"),
                                              "args": ["--no-sandbox"]}))
        config = directory / "mermaid.json"
        config.write_text(json.dumps({"theme": "dark", "securityLevel": "strict",
                                      "flowchart": {"htmlLabels": True}}))
        for index, block in enumerate(blocks):
            # Regenerate hover styles rather than accumulating old directives.
            block = re.sub(r"\A---\nconfig:\n  themeCSS: \|\n.*?\n---\n", "", block, flags=re.S)
            input_path, output_path = directory / f"{index}.mmd", directory / f"{index}.svg"
            input_path.write_text(block, encoding="utf-8")
            subprocess.run([args.mmdc, "-i", str(input_path), "-o", str(output_path),
                            "-p", str(browser_config), "-c", str(config),
                            "-b", "transparent", "-I", f"diagram-{index}"], check=True)
            markup, node_ids, edge_count = enrich_svg(output_path.read_text(encoding="utf-8"))
            styles = hover_styles(node_ids)
            updated_blocks.append("---\nconfig:\n  themeCSS: |\n" +
                                  "\n".join("    " + line for line in styles.splitlines()) + "\n---\n" + block)
            title = titles[index]
            panels.append(f'''<section id="panel-{index}" role="tabpanel" aria-labelledby="tab-{index}" {'hidden' if index else ''}>
<div class="toolbar"><div class="controls"><button type="button" data-zoom="0.25" aria-label="Zoom in">+</button><button type="button" data-zoom="-0.25" aria-label="Zoom out">−</button><button type="button" data-zoom="fit">Fit</button><button type="button" data-action="clear">Clear selection</button></div><span>{html.escape(title)}</span></div>
<div class="canvas">{markup}</div>
<div class="details"><strong class="selection-title"></strong><p class="status" role="status" aria-live="polite"></p><div class="connections"></div></div></section>''')
            print(f"{title}: {len(node_ids)} nodes, {edge_count} mapped connections")
    css = (DOCS / "diagram-viewer.css").read_text(encoding="utf-8")
    js = (DOCS / "diagram-viewer.js").read_text(encoding="utf-8")
    tabs = "".join(
        f'<button id="tab-{index}" role="tab" aria-selected="{str(index == 0).lower()}" '
        f'aria-controls="panel-{index}">{html.escape("Architecture" if index == 0 else title)}</button>'
        for index, title in enumerate(titles)
    )
    page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Framework diagrams — interactive explorer</title><style>{css}</style></head>
<body><header><h1>Framework diagrams</h1><p class="hint">Hover to trace connections. Click or press Enter to pin a node. Press Escape to clear.</p>
<div class="toolbar"><nav class="controls" role="tablist" aria-label="Choose diagram">{tabs}</nav><div class="legend"><span><i class="swatch incoming"></i>Incoming</span><span><i class="swatch outgoing"></i>Outgoing</span></div></div></header>
<main>{''.join(panels)}<footer>Generated from {html.escape(args.source.name)}. All scripts and diagram assets are embedded; no server or network connection is required.</footer></main><script>{js}</script></body></html>'''
    args.output.write_text(page, encoding="utf-8")
    if args.add_hover:
        updated = iter(updated_blocks)
        args.source.write_text(re.sub(r"```mermaid\n(.*?)```", lambda _: "```mermaid\n" + next(updated) + "```", text, flags=re.S), encoding="utf-8")
    print(f"Interactive viewer: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
