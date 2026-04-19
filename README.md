# brkg_stmt_data_scrubber

Scrubs JPMorgan Self-Directed Investing brokerage statement PDFs and exports
income & trade transactions from the **BROKERAGE** and **RETIREMENT BROKERAGE**
accounts to two separate CSV files.

The CSVs are formatted for native import into Excel:

- Dates are written in ISO 8601 (`YYYY-MM-DD`) — Excel auto-recognizes as Date.
- Numbers are plain unquoted decimals (`12.20`, `-25.00`, `10062.00`) — Excel
  auto-recognizes as Number.
- Files are written with a UTF-8 BOM so Excel on Windows correctly auto-detects
  the encoding when the file is opened directly.

---

## Features

- Parses PDF statements with [pdfplumber](https://github.com/jsvine/pdfplumber).
- Locates the BROKERAGE (TFR ON DEATH IND) and RETIREMENT BROKERAGE (JPMS LLC IRA)
  account sections automatically by per-page header markers.
- Extracts transactions from each account's `INCOME` → `Income from Taxable
  Investments` table and (optionally) the `TRADE AND INVESTMENT ACTIVITY` table.
- Applies the following mapping rules:
  - `DIVIDEND` → CSV `Account` = `Dividends`, `Description` = ticker (from
    `Symbol: XXX`), credit amount → `Credit`.
  - `BUY` → CSV `Account` = `N/A`, `Description` = `<TICKER> (buy)`, cost → `Debit`.
  - `SELL` → CSV `Account` = `N/A`, `Description` = `<TICKER> (sell)`, cost → `Debit`.
  - All other transaction types: PDF `Transaction` → CSV `Account`,
    PDF `Description` → CSV `Description`.
- Accounting-style negatives `(123.45)` are converted to floating negatives `-123.45`.
- `Statement Ending` is auto-populated from the page's `Statement Period Ending`.
- `Month Ending` is auto-populated as the last calendar day of the transaction's month.

---

## Requirements

- **Python `>=3.14`** (Python 3.14.0 was released October 7, 2025)
- [`uv`](https://github.com/astral-sh/uv) — for dependency management & the script entry point
- `git`

---

## First-time setup

### 1. Clone the repo

```bash
git clone https://github.com/beldenschroeder/brkg_stmt_data_scrubber.git
cd brkg_stmt_data_scrubber
```

### 2. Create your local `.env`

The project reads its configuration from a `.env` file at the project root.
This file is **gitignored** — it will never be committed.

```bash
cp .env.example .env
# Then edit .env to point at your statement PDF and chosen output dir.
```

The supported keys are:

| Variable                          | Default                              | Purpose                                                |
| --------------------------------- | ------------------------------------ | ------------------------------------------------------ |
| `INPUT_PDF`                       | `./input/statement.pdf`              | Path to the input PDF statement                        |
| `OUTPUT_DIR`                      | `./output`                           | Directory where CSVs are written                       |
| `BROKERAGE_CSV_NAME`              | `brokerage_income`                   | Filename (without `.csv`) for the brokerage output     |
| `RETIREMENT_BROKERAGE_CSV_NAME`   | `retirement_brokerage_income`        | Filename (without `.csv`) for the retirement output    |
| `INCLUDE_TRADES`                  | `true`                               | Include BUY/SELL trades in the CSV                     |
| `LOG_LEVEL`                       | `INFO`                               | Logging verbosity                                      |

### 3. Install dependencies

```bash
uv sync
```

This creates a `.venv/` in the project root and installs all runtime + dev dependencies.

If `uv` reports it doesn't have Python 3.14 installed locally, you can have it
fetch one for you:

```bash
uv python install 3.14
uv sync
```

### 4. Install the pre-commit hooks

```bash
uv run pre-commit install
```

Now Ruff lint + format will run automatically on every `git commit`.

---

## Usage

The project installs a console script called **`brkg_scrubber`**.

```bash
# Use INPUT_PDF and OUTPUT_DIR from .env
uv run brkg_scrubber

# Override the input PDF on the command line
uv run brkg_scrubber path/to/statement.pdf

# Override the output directory
uv run brkg_scrubber path/to/statement.pdf -o ./my_csvs

# Skip BUY/SELL trades for this run
uv run brkg_scrubber --no-trades

# Verbose logging
uv run brkg_scrubber -v

# Help
uv run brkg_scrubber --help
```

After running you'll find:

```
output/
├── brokerage_income.csv
└── retirement_brokerage_income.csv
```

(Filenames will reflect whatever you set in `BROKERAGE_CSV_NAME` /
`RETIREMENT_BROKERAGE_CSV_NAME`.)

Each file has the columns:

```
Date, Description, Account, Statement Ending, Month Ending, Debit, Credit
```

with dates in `YYYY-MM-DD` and numbers as plain decimals.

---

## Privacy

This project deliberately stores **no account numbers, account names, or other
identifying information** in the source code. Only the PDF content you supply
at runtime is processed. Generated CSVs and input PDFs are gitignored
(`*.pdf`, `*.csv`, `input/`, `output/`) so financial data is never accidentally
committed.

---

## Development

### Run the test suite

```bash
uv run pytest
```

With coverage:

```bash
uv run pytest --cov
```

### Lint and format

```bash
# Lint (with autofix)
uv run ruff check --fix .

# Format
uv run ruff format .
```

VSCode users: open the project and accept the recommended extensions
(see `.vscode/extensions.json`). Format-on-save with Ruff is preconfigured
in `.vscode/settings.json`.

### Pre-commit (manual run on all files)

```bash
uv run pre-commit run --all-files
```

---

## Project layout

```
brkg_stmt_data_scrubber/
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── .vscode/
│   ├── settings.json
│   └── extensions.json
├── pyproject.toml
├── README.md
├── src/brkg_stmt_data_scrubber/
│   ├── __init__.py
│   ├── cli.py          # `brkg_scrubber` entry point
│   ├── config.py       # .env loading
│   ├── models.py       # Transaction / AccountSection / CSV columns
│   ├── parser.py       # PDF parsing & rule application
│   └── writer.py       # CSV output
└── tests/
    ├── test_models.py
    ├── test_parser.py
    └── test_writer.py
```

---

## Notes & caveats

- The parser is tuned to the JPMorgan Self-Directed Investing layout that uses
  `DD MMM YYYY` dates (e.g. `02 Mar 2026`) and per-account headers like
  `TFR ON DEATH IND` / `JPMS LLC IRA`. If JPMorgan changes the statement
  layout in the future, the most likely places to tune are the regex constants
  at the top of `src/brkg_stmt_data_scrubber/parser.py`.
- BUY/SELL transactions live in the PDF's `TRADE AND INVESTMENT ACTIVITY`
  table, *not* under `INCOME`. They're parsed and emitted alongside dividends
  in the same CSV. Set `INCLUDE_TRADES=false` (or pass `--no-trades`) if you
  only want dividend/income rows.

---

## License

MIT — see the `[project]` table in `pyproject.toml`.
