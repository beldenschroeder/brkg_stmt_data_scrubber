# Contributing

## Development setup

Follow the [First-time setup](README.md#first-time-setup) steps in the README,
including step 4 (install the pre-commit hooks).

## Run the test suite

```bash
uv run pytest
```

With coverage:

```bash
uv run pytest --cov
```

## Lint and format

```bash
# Lint (with autofix)
uv run ruff check --fix .

# Format
uv run ruff format .
```

VSCode users: open the project and accept the recommended extensions
(see `.vscode/extensions.json`). Format-on-save with Ruff is preconfigured
in `.vscode/settings.json`.

## Pre-commit (manual run on all files)

```bash
uv run pre-commit run --all-files
```
