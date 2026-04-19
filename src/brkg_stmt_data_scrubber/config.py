"""Configuration loaded from environment / .env file."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


@dataclass(frozen=True)
class Config:
    """Resolved runtime configuration."""

    input_pdf: Path | None
    output_dir: Path
    brokerage_csv_name: str
    retirement_brokerage_csv_name: str
    include_trades: bool
    log_level: str

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from .env and environment variables."""
        load_dotenv()

        input_pdf_raw = os.getenv("INPUT_PDF", "").strip()
        input_pdf: Path | None = (
            Path(input_pdf_raw).expanduser().resolve() if input_pdf_raw else None
        )

        output_dir = Path(os.getenv("OUTPUT_DIR", "./output")).expanduser().resolve()

        return cls(
            input_pdf=input_pdf,
            output_dir=output_dir,
            brokerage_csv_name=os.getenv("BROKERAGE_CSV_NAME", "brokerage_income"),
            retirement_brokerage_csv_name=os.getenv(
                "RETIREMENT_BROKERAGE_CSV_NAME", "retirement_brokerage_income"
            ),
            include_trades=_env_bool("INCLUDE_TRADES", True),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )


def configure_logging(level: str) -> None:
    """Configure root logger with a sensible default format."""
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
