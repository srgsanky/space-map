from __future__ import annotations

import html
import os
import tempfile
from pathlib import Path
from typing import TextIO

from .formatting import format_size
from .model import ReportNode, ScanResult


def write_html_report(result: ScanResult, output_path: Path | str) -> None:
    """Atomically write a self-contained HTML report."""
    output = Path(output_path).expanduser().resolve(strict=False)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_name = stream.name
            _write_document(stream, result)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, output)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def _write_document(stream: TextIO, result: ScanResult) -> None:
    root_name = html.escape(result.root.name, quote=True)
    partial = result.root.incomplete or bool(result.warnings) or result.suppressed_warning_count > 0
    warning_count = len(result.warnings) + result.suppressed_warning_count
    stream.write(
        f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Space Map — {root_name}</title>
<style>
:root {{
  --surface: #f7f4ee; --panel: #fffcf7; --sunken: #f1ede5;
  --text: #24211c; --secondary: #625c52; --muted: #8f877a;
  --border: #e4ded4; --border-strong: #c8bdac; --accent: #6f4f2a;
  --warning: #9a650f; --bar: #b9cbd8; --folder: #74aee0; --folder-outline: #477da9;
  color: var(--text); background: var(--surface);
  font-family: Aptos, "Segoe UI", system-ui, -apple-system, sans-serif;
  font-synthesis: none; text-rendering: optimizeLegibility;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; min-width: 320px; background: var(--surface); }}
main {{ width: 100%; padding: 40px 20px 56px; }}
h1, h2, p {{ margin: 0; }}
h1 {{ font-size: 30px; letter-spacing: -.03em; }}
.warning-panel {{ margin: 0 0 20px; padding: 16px; border-left: 3px solid var(--warning); background: var(--sunken); }}
.warning-panel h2 {{ color: var(--warning); font-size: 15px; }}
.warning-panel p, .warning-panel li {{ margin-top: 6px; color: var(--secondary); font-size: 13px; line-height: 1.45; overflow-wrap: anywhere; }}
.filter-bar {{ display: flex; margin-top: 20px; }}
.filter-input {{ width: min(100%, 38ch); min-height: 40px; padding: 8px 12px; border: 1px solid var(--border-strong); border-radius: 6px; color: var(--text); background: var(--sunken); font: inherit; }}
.filter-input::placeholder {{ color: var(--muted); }}
.filter-empty {{ margin-top: 16px; color: var(--muted); font-size: 13px; }}
.tree-shell {{ overflow-x: auto; margin-top: 20px; padding: 4px 0; }}
.tree-shell.is-filtering summary {{ cursor: default; }}
.root-branch {{ width: max-content; }}
.tree-branch {{ margin: 0; }}
.tree-branch > summary {{ list-style: none; cursor: pointer; }}
.tree-branch > summary::-webkit-details-marker {{ display: none; }}
.tree-children {{ margin-left: 12px; padding-left: 18px; border-left: 1px solid var(--border-strong); }}
.tree-node {{ position: relative; display: grid; grid-template-columns: minmax(max-content, 1fr) 90px 64px 90px; align-items: center; gap: 16px; width: 100%; min-height: 36px; padding: 5px 8px; border-bottom: 1px solid var(--border); }}
.tree-node:hover {{ background: var(--panel); }}
.tree-node::before {{ content: ""; position: absolute; left: -19px; top: 50%; width: 18px; border-top: 1px solid var(--border-strong); }}
.root-branch > summary .tree-node::before {{ display: none; }}
.node-main {{ display: flex; align-items: center; gap: 9px; min-width: 0; }}
.node-marker {{ display: inline-grid; flex: 0 0 24px; place-items: center; width: 24px; height: 24px; color: var(--accent); font-family: ui-monospace, monospace; font-weight: 700; }}
.tree-branch > summary .node-marker::before {{ content: "+"; display: grid; place-items: center; width: 22px; height: 22px; border: 1px solid var(--border-strong); border-radius: 5px; background: var(--sunken); }}
.tree-branch[open] > summary .node-marker::before {{ content: "−"; }}
.node-leaf .node-marker::before {{ content: "·"; color: var(--muted); }}
.node-name {{ color: var(--text); font-family: ui-monospace, monospace; font-size: 14px; font-weight: 680; white-space: nowrap; }}
.node-kind-icon {{ flex: 0 0 auto; font-family: "Apple Color Emoji", "Segoe UI Emoji", sans-serif; font-size: 15px; font-weight: 400; line-height: 1; }}
.node-kind-directory {{ width: 18px; height: 16px; color: var(--folder); overflow: visible; }}
.node-kind-directory path {{ stroke: var(--folder-outline); stroke-width: 1.4; stroke-linejoin: round; }}
.node-kind {{ color: var(--muted); font-size: 12px; white-space: nowrap; }}
.node-share, .node-size {{ color: var(--secondary); font-family: ui-monospace, monospace; font-size: 12px; font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }}
.node-size {{ color: var(--text); font-size: 13px; font-weight: 700; }}
.usage-track {{ height: 6px; overflow: hidden; border-radius: 999px; background: var(--sunken); }}
.usage-fill {{ display: block; width: var(--share); height: 100%; border-radius: inherit; background: var(--bar); }}
.node-incomplete {{ color: var(--warning); }}
.tree-node.filter-ancestor {{ opacity: .42; }}
.tree-branch.filter-terminal > summary .node-marker::before {{ content: "·"; border-color: transparent; background: transparent; color: var(--muted); }}
[hidden] {{ display: none !important; }}
footer {{ margin-top: 28px; padding-top: 12px; border-top: 1px solid var(--border); color: var(--muted); font-size: 12px; line-height: 1.5; }}
summary:focus-visible, .filter-input:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }}
@media (max-width: 720px) {{ main {{ padding: 24px 12px 40px; }} }}
@media print {{ body, :root {{ background: white; }} main {{ padding: 0; }} .filter-bar, .filter-empty {{ display: none; }} details {{ display: block; }} details > .tree-children {{ display: block; }} .tree-node {{ break-inside: avoid; }} }}
</style>
</head>
<body>
<main>
<header>
<h1>Space Map</h1>
</header>
"""
    )
    if partial:
        stream.write(
            '<aside class="warning-panel"><h2>Partial scan</h2>'
            f"<p>{warning_count:,} filesystem errors were encountered. "
            "Reported totals are a lower bound.</p>"
        )
        if result.warnings:
            stream.write("<ul>")
            for warning in result.warnings:
                path = html.escape(str(warning.path), quote=True)
                message = html.escape(warning.message, quote=True)
                stream.write(f"<li><strong>{path}</strong>: {message}</li>")
            stream.write("</ul>")
        if result.suppressed_warning_count:
            stream.write(f"<p>{result.suppressed_warning_count:,} additional warnings omitted.</p>")
        stream.write("</aside>")

    stream.write(
        '<div class="filter-bar">'
        '<input id="tree-filter" type="search" class="filter-input" '
        'placeholder="Filter files and directories" '
        'aria-label="Filter files and directories by name" '
        'aria-controls="disk-space-tree" autocomplete="off" spellcheck="false">'
        "</div>"
        '<p id="tree-filter-empty" class="filter-empty" role="status" hidden>'
        "No files or directories match this filter."
        "</p>"
        '<section id="disk-space-tree" class="tree-shell" aria-label="Disk space hierarchy">'
    )
    _write_tree(stream, result.root)
    stream.write(
        "</section>"
        f"<footer>Generated {html.escape(result.completed_at.isoformat(), quote=True)}.</footer>"
        "</main>"
        """<script>
(() => {
  const filter = document.querySelector("#tree-filter");
  const tree = document.querySelector("#disk-space-tree");
  const empty = document.querySelector("#tree-filter-empty");
  const rows = Array.from(tree.querySelectorAll(".tree-node"));
  const branches = Array.from(tree.querySelectorAll("details.tree-branch"));
  let savedOpenStates = null;

  function restoreTree() {
    for (const row of rows) {
      row.hidden = false;
      row.classList.remove("filter-ancestor");
      delete row.dataset.filterMatch;
    }
    for (const branch of branches) {
      branch.hidden = false;
      branch.classList.remove("filter-terminal");
    }
    if (savedOpenStates !== null) {
      branches.forEach((branch, index) => { branch.open = savedOpenStates[index]; });
      savedOpenStates = null;
    }
    tree.classList.remove("is-filtering");
    empty.hidden = true;
  }

  function applyFilter() {
    const query = filter.value.trim().toLocaleLowerCase();
    if (query.length === 0) {
      restoreTree();
      return;
    }

    if (savedOpenStates === null) {
      savedOpenStates = branches.map((branch) => branch.open);
    }
    tree.classList.add("is-filtering");

    let matchCount = 0;
    for (const row of rows) {
      const name = row.querySelector(".node-name").textContent;
      const matches = name.toLocaleLowerCase().includes(query);
      row.dataset.filterMatch = String(matches);
      if (matches) matchCount += 1;
      if (row.parentElement.tagName !== "SUMMARY") row.hidden = !matches;
    }

    for (const branch of [...branches].reverse()) {
      const ownRow = branch.querySelector(":scope > summary > .tree-node");
      const ownMatches = ownRow.dataset.filterMatch === "true";
      const children = branch.querySelector(":scope > .tree-children").children;
      const descendantMatches = Array.from(children).some((child) => !child.hidden);
      branch.hidden = !ownMatches && !descendantMatches;
      branch.open = descendantMatches;
      branch.classList.toggle("filter-terminal", ownMatches && !descendantMatches);
      ownRow.classList.toggle("filter-ancestor", !ownMatches && descendantMatches);
    }

    empty.hidden = matchCount !== 0;
  }

  filter.addEventListener("input", applyFilter);
  filter.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && filter.value.length > 0) {
      filter.value = "";
      applyFilter();
    }
  });
  tree.addEventListener("click", (event) => {
    if (tree.classList.contains("is-filtering") && event.target.closest("summary")) {
      event.preventDefault();
    }
  });
})();
</script>
</body></html>
"""
    )


def _write_tree(stream: TextIO, root: ReportNode) -> None:
    stack: list[tuple[str, ReportNode, int]] = [("node", root, root.allocated_bytes)]
    while stack:
        event, node, parent_bytes = stack.pop()
        if event == "close":
            stream.write("</div></details>")
            continue

        is_branch = node.kind in {"root", "directory"}
        if is_branch:
            classes = "tree-branch root-branch" if node.kind == "root" else "tree-branch"
            open_attribute = " open" if node.kind == "root" else ""
            stream.write(f'<details class="{classes}"{open_attribute}><summary>')
            _write_row(stream, node, parent_bytes, leaf=False)
            stream.write('</summary><div class="tree-children">')
            stack.append(("close", node, parent_bytes))
            for child in reversed(node.children):
                stack.append(("node", child, node.allocated_bytes))
        else:
            _write_row(stream, node, parent_bytes, leaf=True)


def _write_row(stream: TextIO, node: ReportNode, parent_bytes: int, *, leaf: bool) -> None:
    share = (
        100.0
        if node.kind == "root"
        else (
            min(100.0, max(0.0, node.allocated_bytes / parent_bytes * 100)) if parent_bytes else 0.0
        )
    )
    name = html.escape(node.name, quote=True)
    title = html.escape(str(node.path), quote=True) if node.path is not None else name
    kind_icon = _kind_icon(node)
    kind_detail = _kind_detail(node)
    incomplete = (
        '<span class="node-incomplete" title="Some entries could not be read">partial</span>'
        if node.incomplete
        else ""
    )
    leaf_class = " node-leaf" if leaf else ""
    stream.write(
        f'<div class="tree-node{leaf_class}" title="{title}">'
        '<span class="node-main"><span class="node-marker" aria-hidden="true"></span>'
        f'<span class="node-name">{name}</span>{kind_icon}{kind_detail}{incomplete}</span>'
        f'<span class="usage-track" aria-hidden="true"><span class="usage-fill" style="--share:{share:.2f}%"></span></span>'
        f'<span class="node-share">{share:.1f}%</span>'
        f'<span class="node-size">{format_size(node.allocated_bytes)}</span></div>'
    )


def _kind_icon(node: ReportNode) -> str:
    if node.kind in {"root", "directory", "misc_directories"}:
        return (
            '<svg class="node-kind-icon node-kind-directory" role="img" '
            'aria-label="Directory" title="Directory" viewBox="0 0 24 24">'
            '<path fill="currentColor" fill-opacity=".72" '
            'd="M3 10V5.8C3 4.8 3.8 4 4.8 4h4.5l2.1 2H19c1.1 0 2 .9 2 2v2z"></path>'
            '<path fill="currentColor" d="M3 9.5h18l-2.5 9.3h-13z"></path>'
            "</svg>"
        )
    return (
        '<span class="node-kind-icon node-kind-file" role="img" '
        'aria-label="File" title="File">📄</span>'
    )


def _kind_detail(node: ReportNode) -> str:
    if node.kind in {"misc_directories", "misc_files"}:
        return f'<span class="node-kind">{node.item_count:,} direct</span>'
    return ""
