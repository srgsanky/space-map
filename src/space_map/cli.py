from __future__ import annotations

import time
from pathlib import Path

import click
from rich.console import Console, RenderableType
from rich.live import Live
from rich.table import Table

from .formatting import format_elapsed, format_size
from .model import ScanOptions, ScanProgress
from .report import write_html_report
from .scanner import scan_tree

_MB = 1024**2


class _ProgressView:
    def __init__(self, root: Path, started_at: float) -> None:
        self.progress = ScanProgress(root, 0, 0, 0, 0)
        self.started_at = started_at

    def update(self, progress: ScanProgress) -> None:
        self.progress = progress

    def __rich__(self) -> RenderableType:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold cyan", no_wrap=True)
        table.add_column(overflow="fold")
        table.add_row("Elapsed", format_elapsed(time.monotonic() - self.started_at))
        table.add_row("Current", str(self.progress.current_directory))
        table.add_row("Found so far", format_size(self.progress.allocated_bytes))
        table.add_row(
            "Scanned",
            f"{self.progress.directories_scanned:,} directories · "
            f"{self.progress.files_scanned:,} files · {self.progress.error_count:,} errors",
        )
        return table


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument(
    "root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
)
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("space-map-report.html"),
    show_default=True,
    help="HTML report destination.",
)
@click.option(
    "--threshold-mb",
    type=click.IntRange(min=1),
    default=100,
    show_default=True,
    help="Minimum size for individual files and directories.",
)
@click.option(
    "--one-file-system",
    is_flag=True,
    help="Do not descend onto a filesystem different from ROOT.",
)
@click.option(
    "--include-time-machine",
    is_flag=True,
    help="Descend into external Time Machine backup volumes.",
)
def main(
    root: Path,
    output: Path,
    threshold_mb: int,
    one_file_system: bool,
    include_time_machine: bool,
) -> None:
    """Scan ROOT and generate a collapsible disk-space HTML report."""
    console = Console(stderr=True)
    root = root.expanduser().resolve(strict=True)
    output = output.expanduser().resolve(strict=False)
    started_at = time.monotonic()
    view = _ProgressView(root, started_at)
    last_plain_render = 0.0

    def update_progress(progress: ScanProgress, *, force: bool = False) -> None:
        nonlocal last_plain_render
        view.update(progress)
        if console.is_terminal:
            return
        now = time.monotonic()
        if force or last_plain_render == 0.0 or now - last_plain_render >= 5.0:
            console.print(view)
            last_plain_render = now

    options = ScanOptions(
        threshold_bytes=threshold_mb * _MB,
        one_file_system=one_file_system,
        skip_time_machine_volumes=not include_time_machine,
        excluded_paths=(output,),
    )

    try:
        if console.is_terminal:
            with Live(
                view,
                console=console,
                refresh_per_second=10,
                transient=True,
                redirect_stdout=False,
                redirect_stderr=False,
            ):
                result = scan_tree(root, options, update_progress)
        else:
            result = scan_tree(root, options, update_progress)
            update_progress(
                ScanProgress(
                    current_directory=root,
                    allocated_bytes=result.root.allocated_bytes,
                    directories_scanned=result.directories_scanned,
                    files_scanned=result.files_scanned,
                    error_count=len(result.warnings) + result.suppressed_warning_count,
                ),
                force=True,
            )
        write_html_report(result, output)
    except KeyboardInterrupt:
        console.print("[yellow]Scan interrupted; no report was written.[/yellow]")
        raise click.exceptions.Exit(130) from None
    except (OSError, ValueError) as error:
        raise click.ClickException(str(error)) from error

    status = "partial" if result.root.incomplete else "complete"
    click.echo(f"Report written: {output}", err=True)
    console.print(
        f"{format_size(result.root.allocated_bytes)} found in "
        f"{format_elapsed(result.elapsed_seconds)} ({status}; "
        f"{result.directories_scanned:,} directories, {result.files_scanned:,} files)"
    )


if __name__ == "__main__":
    main()
