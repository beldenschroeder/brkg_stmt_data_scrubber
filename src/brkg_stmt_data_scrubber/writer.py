"""CSV output for parsed account sections.

The CSV is written with:

  - ``newline=""`` so Python's csv module controls line endings.
  - ``utf-8-sig`` encoding (UTF-8 with BOM) so Microsoft Excel on Windows
    auto-detects the encoding when the file is opened directly. This has
    no effect on Excel for Mac, LibreOffice, Numbers, or pandas.
  - ``QUOTE_MINIMAL`` quoting so plain numbers and ISO dates remain
    unquoted — Excel will then interpret them natively as Number and Date.
"""

import csv
import logging
from pathlib import Path

from .config import Config
from .models import (
    BROKERAGE_ACCOUNT,
    CSV_COLUMNS,
    RETIREMENT_BROKERAGE_ACCOUNT,
    AccountSection,
)

logger = logging.getLogger(__name__)


def write_account_csv(
    section: AccountSection,
    output_dir: Path,
    cfg: Config,
) -> Path:
    """Write a single AccountSection out as a CSV.

    Filename comes from the Config (BROKERAGE_CSV_NAME or
    RETIREMENT_BROKERAGE_CSV_NAME), with a ".csv" suffix appended.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if section.account_name == BROKERAGE_ACCOUNT:
        base = cfg.brokerage_csv_name
    elif section.account_name == RETIREMENT_BROKERAGE_ACCOUNT:
        base = cfg.retirement_brokerage_csv_name
    else:
        # Fallback: slugify the account name
        base = section.account_name.lower().replace(" ", "_")

    out_path = output_dir / f"{base}.csv"

    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(CSV_COLUMNS)
        for txn in section.transactions:
            writer.writerow(txn.to_row())

    logger.info("Wrote %d row(s) to %s", len(section.transactions), out_path)
    return out_path
