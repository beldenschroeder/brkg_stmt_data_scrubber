"""Command line interface for brkg_stmt_data_scrubber.

Usage:
    brkg_scrubber                          # uses INPUT_PDF & OUTPUT_DIR from .env
    brkg_scrubber path/to/statement.pdf    # overrides INPUT_PDF
    brkg_scrubber path/to/statement.pdf -o ./out
    brkg_scrubber --help
"""

import logging
import sys
from pathlib import Path

import click

from .config import Config, configure_logging
from .parser import parse_statement
from .writer import write_account_csv

logger = logging.getLogger(__name__)


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
    help=(
        "Scrub a JPMorgan brokerage statement PDF and emit two CSV files "
        "(one for BROKERAGE income, one for RETIREMENT BROKERAGE income). "
        "If no PDF path is given on the command line, the value of INPUT_PDF "
        "from the .env file is used."
    ),
)
@click.argument(
    "pdf_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    required=False,
)
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(file_okay=False, writable=True, path_type=Path),
    default=None,
    help="Directory to write CSV files (default: OUTPUT_DIR from .env, or ./output).",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    default=False,
    help="Enable DEBUG-level logging.",
)
@click.option(
    "--no-trades",
    is_flag=True,
    default=False,
    help="Skip BUY/SELL transactions (overrides INCLUDE_TRADES from .env).",
)
def main(
    pdf_path: Path | None,
    output_dir: Path | None,
    verbose: bool,
    no_trades: bool,
) -> None:
    """CLI entry point — registered as the `brkg_scrubber` script."""
    cfg = Config.load()
    log_level = "DEBUG" if verbose else cfg.log_level
    configure_logging(log_level)

    # Resolve input PDF: CLI arg wins, then env, then error.
    resolved_pdf = pdf_path or cfg.input_pdf
    if resolved_pdf is None:
        click.echo(
            "Error: no PDF path provided. Either pass one on the command line "
            "or set INPUT_PDF in your .env file.",
            err=True,
        )
        sys.exit(2)
    if not resolved_pdf.exists():
        click.echo(f"Error: input PDF not found: {resolved_pdf}", err=True)
        sys.exit(2)

    out_dir = output_dir or cfg.output_dir
    include_trades = cfg.include_trades and not no_trades

    logger.info("Input PDF:        %s", resolved_pdf)
    logger.info("Output directory: %s", out_dir)
    logger.info("Include trades:   %s", include_trades)

    try:
        sections = parse_statement(resolved_pdf, include_trades=include_trades)
    except Exception as exc:
        logger.error("Failed to parse statement: %s", exc)
        sys.exit(1)

    written_paths = []
    for section in sections:
        path = write_account_csv(section, out_dir, cfg)
        written_paths.append((section, path))

    click.echo("Done. Wrote:")
    for section, path in written_paths:
        click.echo(f"  - {path}  ({len(section.transactions)} row(s))")


if __name__ == "__main__":
    main()
