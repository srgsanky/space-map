from datetime import UTC, datetime, timedelta
from pathlib import Path

from space_map import ReportNode, ScanOptions, ScanResult, write_html_report


def test_write_html_report_creates_a_self_contained_collapsible_and_escaped_tree(
    tmp_path: Path,
) -> None:
    started = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
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
        warnings=(),
        suppressed_warning_count=0,
        options=ScanOptions(),
    )
    output = tmp_path / "report.html"

    write_html_report(result, output)

    html = output.read_text()
    assert "<!doctype html>" in html
    assert '<details class="tree-branch root-branch" open>' in html
    assert '<details class="tree-branch">' in html
    assert "nested &amp; things" in html
    assert "&lt;script&gt;.bin" in html
    assert "2.0 GB" in html
    assert '<input id="tree-filter" type="search"' in html
    assert 'aria-label="Filter files and directories by name"' in html
    assert "No files or directories match this filter." in html
    assert ".filter-ancestor" in html
    assert "toLocaleLowerCase().includes(query)" in html
    assert '<dl class="summary-grid">' not in html
    assert "Allocated regular-file bytes; directory metadata is excluded." not in html
    assert "Symlinks and special files are not followed." not in html
    assert "Sizes use 1024-based units labelled MB, GB, and TB." not in html
    assert "<script>.bin" not in html
    assert "http://" not in html
    assert "https://" not in html
    assert "Expand all" not in html
    assert "Collapse all" not in html
