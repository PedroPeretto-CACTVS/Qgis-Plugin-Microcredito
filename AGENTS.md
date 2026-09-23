# Agent guide — qgis-plugin-microcredito

Python QGIS plugin for rural microcredit demographic mapping. Agents working here follow the conventions below so changes stay **tight**, testable, and consistent with the toolchain already configured in `pyproject.toml` and `Makefile`.

## Recon before editing

1. Read the module you are changing and its nearest callers/tests.
2. Match existing naming, imports, and layering — do not introduce a new pattern when a local one already exists.
3. Keep diffs **scoped** to the requested task; reuse existing abstractions instead of parallel implementations.

**Done when:** you can name which layer owns the change (`plugin/`, `qgis_plugin_microcredito/`, `database/`, `cli/`) and which quality gates apply.

## Repository layout

| Path | Owns |
|------|------|
| `src/qgis_plugin_microcredito/` | Installable package: domain logic, services, entrypoints (`main`) |
| `src/plugin/` | QGIS plugin surface: `classFactory`, actions, dialogs, map integration |
| `src/database/` | SQLAlchemy models, sessions, repositories, migrations |
| `src/cli/` | Standalone CLI commands (non-QGIS runtime) |
| `assets/` | Icons, UI files, static resources referenced by the plugin |
| `test/` | Pytest suite and fixtures |

Package and script names come from `pyproject.toml` — treat that file as the source of truth for dependencies, tool config, and the `qgis-plugin-microcredito` console script.

## Environment

- **Python:** 3.13+ (see `.python-version`)
- **Package manager:** [uv](https://docs.astral.sh/uv/) — sync deps with `uv sync` before running tools
- **Virtual env:** `.venv/` (gitignored); prefix commands with `uv run` or use `Makefile` targets

Do not commit secrets. `.env` is gitignored; load configuration from environment variables or explicit config modules, never hard-code credentials.

## Version control and pull requests

Follow this workflow whenever the user asks for branches, commits, or pull requests:

### Git-flow (main-based)

1. **`main`** is the integration branch — keep it deployable.
2. Branch **from `main`** for every change (`git checkout main && git pull && git checkout -b <branch>`).
3. Open a pull request **back into `main`**; do not commit directly to `main`.

### Semantic branches

Name branches with a **type prefix** and a short, kebab-case slug:

| Prefix | Use for |
|--------|---------|
| `feat/` | New behavior or user-facing capability |
| `fix/` | Bug fixes |
| `refactor/` | Behavior-preserving structural changes |
| `test/` | Test-only changes |
| `chore/` | Tooling, deps, CI, formatting sweeps |

Examples: `feat/export-demographic-layer`, `fix/session-leak-on-unload`.

### Semantic commits

Use [Conventional Commits](https://www.conventionalcommits.org/) — same type prefixes as branches (`feat`, `fix`, `refactor`, `test`, `chore`, `docs`). Subject line in imperative mood, lowercase after the colon, no period at the end.

```
feat(plugin): add demographic export action
fix(database): close session after repository errors
```

One logical change per commit when possible; avoid mixing unrelated types in a single commit.

### Pull requests

- **One feature or fix per PR** — scope matches a single `feat/` or `fix/` (or equivalent) branch.
- **Granular** — prefer several small PRs over one large PR that mixes layers (plugin + database + unrelated refactors).
- PR title and description should state the user-visible or behavioral outcome; link related issues when applicable.
- Do not bundle drive-by refactors, dependency upgrades, or unrelated files with feature work — split or defer them.

Commits and pushes remain **out of scope** unless the user explicitly requests them (see below); when they do, apply this section.

## Architecture

Separate concerns so core logic stays testable outside QGIS:

```
plugin/ (PyQGIS, UI, map events)
    ↓ calls
qgis_plugin_microcredito/ (use cases, orchestration)
    ↓ calls
database/ (SQLAlchemy persistence)
```

- **Pydantic** — validate external input, config payloads, and API boundaries. Prefer `BaseModel` with explicit field types over ad-hoc dicts.
- **SQLAlchemy 2.x** — use typed `Mapped[...]` models, explicit sessions, and repository-style access from services. Keep raw SQL in migrations or narrowly scoped queries.
- **QGIS code** — stays in `src/plugin/`. Import business logic from `qgis_plugin_microcredito`; avoid embedding domain rules in UI handlers.

When QGIS APIs are unavailable (CI, local unit tests), mock or stub at the plugin boundary — test domain and database layers directly.

## Python style

Tooling enforces style; run it instead of debating formatting:

| Gate | Command |
|------|---------|
| Format | `make format` → `uv run ruff format .` |
| Lint | `make lint` → `uv run ruff check . --fix` |
| Types | `make typecheck` → `uv run mypy src` |
| Tests | `make test` → `uv run pytest` |

### Types (strict mypy)

- Every public function and method gets explicit parameter and return annotations.
- Prefer `TypedDict`, `Protocol`, and Pydantic models over bare `dict` / `Any`.
- Use `from __future__ import annotations` when forward references simplify signatures.
- Narrow optional values early; avoid `# type: ignore` unless the QGIS stubs force it — then comment why.

### Formatting and imports (ruff)

- Line length: 88; double quotes; 4-space indent (`pyproject.toml` → `[tool.ruff]`)
- Import order: stdlib → third party → local, sorted by isort rules (ruff `I`)
- Enabled rule sets: `E`, `W`, `F`, `I`, `B`, `UP` — fix violations, do not disable rules without team agreement

### Naming and modules

- `snake_case` for functions, variables, modules; `PascalCase` for classes; `UPPER_SNAKE` for constants
- One primary concept per module; keep files focused
- Prefer absolute imports within the package (`from qgis_plugin_microcredito.services import ...`)

### Functions and errors

- Write small, single-purpose functions; extract when a block mixes I/O, validation, and persistence
- Raise specific exceptions (`ValueError`, domain errors) with actionable messages; catch at boundaries (CLI, plugin handlers), not deep in repositories
- Use context managers for sessions, files, and QGIS layers

### Comments and docstrings

- Code should read without comments for straightforward logic
- Add docstrings for public modules, classes, and non-obvious business rules (especially microcredit domain invariants)
- Do not restate types already visible in annotations

## Testing

- Tests live in `test/`; mirror the package structure (`test/test_<module>.py`)
- Shared data in `test/fixtures/`
- Name tests `test_<behavior>_<expected_outcome>`
- Unit-test domain and database code without QGIS; integration tests that need QGIS should be clearly marked and kept minimal
- Add tests when fixing bugs or adding behavior; skip trivial tests that only assert library defaults
- Run `make test` before finishing; new code should not reduce coverage on touched modules

## QGIS plugin checklist

When touching `src/plugin/`:

1. Keep `classFactory(iface)` as the QGIS entrypoint; register/unregister resources in `initGui` / `unload`
2. Load UI from `assets/`; do not embed large XML or icons inline in Python
3. Long-running work off the main thread — use QGIS task managers or Qt signals to keep the UI responsive
4. Guard QGIS/PyQt imports so non-QGIS tests can import pure Python modules

## Database changes

1. Model change → update SQLAlchemy models in `src/database/`
2. Add a migration alongside existing migration tooling in that directory
3. Update repositories and tests that exercise the changed schema
4. Verify queries remain parameterized — no string-interpolated SQL with user input

## Definition of done

Before marking work complete, all of the following must pass:

1. `make format lint typecheck test` — zero failures
2. No unrelated files changed; no committed `.env`, build artifacts, or `__pycache__`
3. New modules follow the layout table above
4. Public APIs are typed; behavior changes include or update tests
5. QGIS-specific code remains isolated in `src/plugin/`

## Out of scope unless asked

- Drive-by refactors, dependency upgrades, or config churn unrelated to the task
- New documentation files beyond what the task requires
