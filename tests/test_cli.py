import json
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


def test_cli_optionally_writes_a_machine_readable_report(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "data.bin").write_bytes(b"content")
    html_output = tmp_path / "report.html"
    json_output = tmp_path / "report.json"

    result = CliRunner().invoke(
        main,
        [
            str(root),
            "--output",
            str(html_output),
            "--json-output",
            str(json_output),
            "--threshold-mb",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert f"Report written: {html_output.resolve()}" in result.output
    assert f"JSON written: {json_output.resolve()}" in result.output
    document = json.loads(json_output.read_text())
    assert document["format"] == "space-map"
    assert document["scan"]["root_path"] == str(root.resolve())
    assert document["nodes"][0]["allocated_bytes"] > 0


def test_cli_rejects_the_same_html_and_json_destination(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    output = tmp_path / "report"

    result = CliRunner().invoke(
        main,
        [str(root), "--output", str(output), "--json-output", str(output)],
    )

    assert result.exit_code == 2
    assert "--output and --json-output must be different paths" in result.output
