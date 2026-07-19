from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path

from space_map import ReportNode, ScanOptions, ScanResult, ScanWarning, write_html_report


def test_write_html_report_creates_a_self_contained_collapsible_and_escaped_tree(
    tmp_path: Path,
) -> None:
    started = datetime(2026, 7, 18, 12, 0, 0, 123456, tzinfo=UTC)
    nested = ReportNode(
        kind="directory",
        name="nested & things",
        path=tmp_path / "nested & things",
        allocated_bytes=2 * 1024**3,
        children=(
            ReportNode(
                kind="file",
                name="<script>.bin",
                path=tmp_path / "nested & things" / "<script>.bin",
                allocated_bytes=2 * 1024**3,
            ),
        ),
    )
    result = ScanResult(
        root=ReportNode(
            kind="root",
            name=str(tmp_path),
            path=tmp_path,
            allocated_bytes=2 * 1024**3,
            children=(nested,),
        ),
        started_at=started,
        completed_at=started + timedelta(seconds=90),
        elapsed_seconds=90,
        directories_scanned=2,
        files_scanned=1,
        warnings=(
            ScanWarning(path=tmp_path / "protected" / "one", message="Permission <denied>"),
            ScanWarning(path=tmp_path / "protected" / "two", message="Operation not permitted"),
        ),
        suppressed_warning_count=0,
        options=ScanOptions(),
    )
    output = tmp_path / "report.html"

    write_html_report(result, output)

    html = output.read_text()
    assert "<!doctype html>" in html
    assert '<p class="subtitle">' not in html
    assert '<details class="tree-branch root-branch" open>' in html
    assert '<details class="tree-branch">' in html
    assert "nested &amp; things" in html
    assert "&lt;script&gt;.bin" in html
    assert "2.0 GB" in html
    assert (
        '<span class="node-name-group"><span class="node-name">nested &amp; things</span>'
        '<button type="button" class="copy-path"'
    ) in html
    assert (
        '<span class="node-name-group"><span class="node-name">&lt;script&gt;.bin</span>'
        '<button type="button" class="copy-path"'
    ) in html
    assert html.count('class="copy-path"') == 3
    assert 'data-copy-path="' in html
    assert 'aria-label="Copy full path" title="Copy full path"' in html
    assert "navigator.clipboard.writeText(path)" in html
    assert 'document.execCommand("copy")' in html
    assert 'aria-label="Directory" title="Directory" viewBox="0 0 24 24">' in html
    assert 'aria-label="File" title="File">📄</span>' in html
    assert "--folder: #74aee0" in html
    assert '<span class="node-kind">directory</span>' not in html
    assert '<span class="node-kind">file</span>' not in html
    assert '<div class="tree-region"><div class="filter-bar">' in html
    tree_end = html.index("</section></div>")
    warning = html.index('<aside class="warning-panel"><details class="warning-details">')
    footer = html.index("<footer>")
    assert tree_end < warning < footer
    assert '<details class="warning-details" open>' not in html
    assert '<span class="warning-heading">Partial scan</span>' in html
    assert "2 filesystem errors were encountered. Reported totals are a lower bound." in html
    assert '<div class="warning-tree" aria-label="Filesystem errors by path">' in html
    assert '<span class="node-name">protected</span>' in html
    assert '<span class="node-name">one</span>' in html
    assert '<span class="node-name">two</span>' in html
    assert '<span class="warning-message">Permission &lt;denied&gt;</span>' in html
    assert '<span class="warning-message">Operation not permitted</span>' in html
    assert "<ul>" not in html
    assert ".warning-panel { margin: 20px 0 0;" in html
    assert ".tree-region { width: max-content; max-width: 100%; }" in html
    assert '<input id="tree-filter" type="search"' in html
    assert ".filter-input { width: 100%" in html
    assert 'aria-label="Filter files and directories by name or full path"' in html
    assert "No files or directories match this filter." in html
    assert ".filter-ancestor" in html
    assert 'row.dataset.path || row.querySelector(".node-name").textContent' in html
    assert "nameOrPath.toLocaleLowerCase().includes(query)" in html
    nested_path = escape(str(tmp_path / "nested & things"), quote=True)
    file_path = escape(str(tmp_path / "nested & things" / "<script>.bin"), quote=True)
    assert f'data-path="{nested_path}"' in html
    assert f'data-copy-path="{nested_path}"' in html
    assert f'data-path="{file_path}"' in html
    assert f'data-copy-path="{file_path}"' in html
    assert 'datetime="2026-07-18T12:01:30+00:00"' in html
    assert "123456" not in html
    assert "less than an hour ago" in html
    assert "elapsedHours < 24" in html
    assert "border-bottom: 1px solid var(--border)" not in html
    assert ".tree-children { position: relative; margin-left: 20px" in html
    assert ".tree-children > :last-child::after" in html
    assert '<dl class="summary-grid">' not in html
    assert "Allocated regular-file bytes; directory metadata is excluded." not in html
    assert "Symlinks and special files are not followed." not in html
    assert "Sizes use 1024-based units labelled MB, GB, and TB." not in html
    assert "<script>.bin" not in html
    assert "http://" not in html
    assert "https://" not in html
    assert "Expand all" not in html
    assert "Collapse all" not in html
