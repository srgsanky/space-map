from pathlib import Path

from click.testing import CliRunner

from space_map.cli import main


def test_cli_scans_a_root_shows_required_progress_and_writes_report(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / ".hidden.bin").write_bytes(b"content")
    output = tmp_path / "space report.html"

    result = CliRunner().invoke(
        main,
        [str(root), "--output", str(output), "--threshold-mb", "1"],
    )

    assert result.exit_code == 0, result.output
    assert "Elapsed" in result.output
    assert "Current" in result.output
    assert "Found so far" in result.output
    assert "Report written" in result.output
    assert str(output.resolve()) in result.output
    assert output.exists()
    assert str(root.resolve()) in output.read_text()
