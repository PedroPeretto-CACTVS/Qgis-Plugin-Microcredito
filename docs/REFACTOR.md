# REFACTOR.md — CAR Microcrédito migration guide

This document is the single source of truth for refactoring this repository. An implementing agent or developer should be able to execute the migration from this file alone.

**Product (one sentence):** Local automation for socio-environmental triage of rural microcredit operations — imports Sicor/MMA/MTE data, cross-checks CAR geometry against national environmental layers in QGIS, and produces PDF + JSON evidence for human review (never automatic credit approval).

**Current version:** `0.8.0` (`pyproject.toml`, `qgis_plugin/car_microcredito_qgis/metadata.txt`)

---

## Why this refactor exists

This is **not** a feature release. It is a deliberate engineering reset with two equal objectives:

### Objective 1 — Adopt a current gold-standard Python stack

Replace the legacy toolchain (minimal `pyproject.toml`, stdlib-only core, raw `sqlite3`, `unittest`, ad-hoc scripts, PowerShell installers) with the project's modern template:

| Tool | Role in target stack |
|------|----------------------|
| **uv** | Dependency management, lockfile, virtualenvs, scripts |
| **ruff** | Lint + format (single formatter/linter) |
| **mypy** | Static typing across core and installer packages |
| **pytest** | Test runner and fixtures (replaces `unittest discover`) |
| **SQLAlchemy 2.x** | Persistence layer (replaces hand-written SQL in `db.py` / `sicor.py`) |
| **Pydantic v2** | Validated domain models, CLI I/O, import row parsing, report payloads |

The stack change is the **reason** the refactor happens now: the current codebase works but is hard to evolve safely without typed models, migration tooling, and consistent tooling.

### Objective 2 — Improve codebase quality and maintainability

Restructure and rewrite implementation code to follow clean, testable patterns:

- **Layered project layout** — separate `domain/`, `application/`, `infrastructure/`, `interfaces/` (exact names follow the modern template)
- **Thin boundaries** — QGIS plugin and CLIs call application services; no business rules in UI or SQL strings scattered across modules
- **Explicit domain types** — Pydantic models for imports, queries, verdicts, evidence; enums for verdict constants
- **Repository pattern** — SQLAlchemy repositories encapsulate Sicor/MMA/MTE queries; `ativo_*` view semantics preserved
- **Testability** — pytest fixtures, parametrized policy tests, integration tests against in-memory SQLite
- **Single version source** — one place for `0.8.0` → next release
- **Replace the end-user installer** — retire Windows `.ps1`/`.bat` stack; ship a typed Python installer CLI (see §8)

### What must NOT change (behavior contract)

**Product behavior and business rules are frozen.** Users, analysts, and downstream reports must see the same outcomes for the same inputs. The refactor changes *how* the code is written, not *what* it decides.

Regression tests — migrated to pytest and extended — are the acceptance gate. See §9 and §12.

---

## 1. Refactor scope

### 1.1 Preserve behavior, reimplement freely (domain contract)

These areas encode product semantics. Code **will be rewritten** (SQLAlchemy, Pydantic, new module paths), but **observable behavior must remain identical**: CLI flags, query results, verdict values, PDF/JSON shape, import activation rules, error messages that operators rely on.

| Area | Path | Why it is sacred |
|------|------|-------------------|
| Normalization | `src/car_microcredito/normalize.py` | CPF/CNPJ/CAR/header rules used everywhere |
| Policy / verdicts | `src/car_microcredito/policy.py` | MMA/MTE triage rules; aggregate semantics |
| Database | `src/car_microcredito/db.py` | Schema v3, migrations, `configure_import`, `ativo_*` views |
| Sicor import & queries | `src/car_microcredito/sicor.py` | ETL, link types, activation rules |
| MTE import | `src/car_microcredito/mte.py` | Slave-labor registry |
| Geo export | `src/car_microcredito/geo.py` | Gleba GeoJSON reconstruction |
| File validation | `src/car_microcredito/downloads.py` | GPKG/ZIP checks before data promotion |
| DB backup/migrate | `src/car_microcredito/backup.py` | Safe copy migration |
| Admin CLI | `src/car_microcredito/cli.py`, `__main__.py` | Data import, query, migration commands |
| QGIS plugin UI & flows | `qgis_plugin/car_microcredito_qgis/*.py` (except packaging glue) | User-facing triage workflow |
| Report content | `qgis_plugin/car_microcredito_qgis/report.py` | PDF/JSON structure, disclaimers, MCR references |
| Environmental analysis | `qgis_plugin/car_microcredito_qgis/analysis.py`, `worker.py` | Spatial cross-check rules |
| CAR polygon lookup | `qgis_plugin/car_microcredito_qgis/car_source.py` | SICAR geometry, Google Maps parsing |
| Evidence audit | `qgis_plugin/car_microcredito_qgis/evidence.py` | Source metadata in reports |
| Batch Excel | `qgis_plugin/car_microcredito_qgis/batch.py`, `batch_window.py` | Supreme-user mass consultation |
| Map output | `qgis_plugin/car_microcredito_qgis/map_output.py` | Satellite PNG for PDF |
| Admin scripts (data ops) | `scripts/importar_trabalho_escravo.py`, `scripts/baixar_*.py`, … | Fold into admin CLI or `uv run` tasks |

### 1.2 Rewrite completely (implementation + tooling)

These areas are **intentionally replaced**, not ported line-by-line:

**A. Persistence and data access**

| Current | Target |
|---------|--------|
| Raw `sqlite3` + string SQL in `db.py`, `sicor.py`, `mte.py` | SQLAlchemy 2.x models, Alembic migrations, repository classes |
| `PRAGMA user_version` manual migrations in `initialize()` | Alembic revision chain; schema v3 as baseline migration |
| `sqlite3.Row` dicts returned to callers | Pydantic read models at repository boundaries |
| `connect(readonly=True)` guard | Session factory with read-only connection mode |

**B. Domain modeling and validation**

| Current | Target |
|---------|--------|
| Ad-hoc `dict[str, object]` everywhere | Pydantic models: `ImportRecord`, `CarCandidate`, `Verdict`, `EnvironmentalLayerResult`, … |
| Constants in `policy.py` | `StrEnum` or typed literals + pure functions (same logic) |
| CSV row parsing inline in `sicor.py` | Pydantic-validated row schemas with alias maps for BCB column names |

**C. Tooling and project skeleton**

| Current | Target |
|---------|--------|
| Minimal `pyproject.toml`, no lockfile | **uv** `pyproject.toml` + `uv.lock`, dev dependency groups |
| No linter/formatter | **ruff** check + format in CI and pre-commit |
| No static typing | **mypy** strict on `src/` (QGIS plugin modules exempt or partially typed) |
| `unittest` in `tests/` | **pytest** + fixtures; keep same test cases during port |
| Scattered `scripts/*.py` | `uv run` tasks or package CLI subcommands |

**D. End-user installation and distribution**

Windows-centric portable installer stack — redesign from scratch as a typed Python installer CLI:

| Current artifact | Role | Replace with |
|------------------|------|--------------|
| `portable/Instalar CAR Microcredito.ps1` | Legacy installer (0.7-era, simpler) | New installer CLI |
| `portable/Verificar pacote.ps1` | SHA256 manifest verification | New verify subcommand |
| `portable/Instalar CAR Microcredito.bat` | Launches PS1 | New entry point (cross-platform if template supports it) |
| `portable/Verificar pacote.bat` | Launches verify PS1 | New verify entry point |
| `portable/LEIA_ME.txt` | User instructions (**stale: says 0.7.0**) | Generated from template |
| `portable/VERSAO.txt` | Version stamp (**stale: says 0.7.0**) | Generated at build time |
| `scripts/build_portable_release.py` | Embeds PS1 templates; builds full ZIP packages | New package builder integrated with template |
| `scripts/build_portable_package.py` | Alternate portable builder with DB snapshots | Merge into new builder or retire |
| `scripts/validate_portable_installer.py` | Tests PS1 in isolated profiles | New installer integration tests |

**E. QGIS plugin structure (quality pass, same UX)**

| Current pain | Target improvement |
|--------------|-------------------|
| `plugin.py` ~1000+ lines mixing UI and orchestration | Split: UI widgets, `AnalysisService`, presenters; plugin calls application layer |
| Core imported via `sys.path` hack | Editable install or bundled wheel from uv build |
| Duplicated document normalization helpers | Import from core domain module |

QGIS/PyQt/reportlab remain runtime dependencies of the plugin layer — they are not replaced.

**F. Packaging/build scripts**

| Current artifact | Target |
|------------------|--------|
| `scripts/build_release.py` | `uv run car-microcredito plugin build` — preserve ZIP layout (see §6) |
| `scripts/build_qgis_plugin*.ps1` | Removed; uv task |
| Duplicate version strings | Single source in `pyproject.toml` / `[tool.uv]` metadata |

### 1.3 Target project structure (follow modern template)

Adapt names to the template repo, but the **separation of concerns** is mandatory:

```
src/
├── car_microcredito/              # Core package (installable)
│   ├── domain/                    # Pydantic models, enums, policy (pure functions)
│   ├── application/               # Use cases: ImportSicor, SearchByDocument, EvaluateAnalysis
│   ├── infrastructure/
│   │   ├── persistence/           # SQLAlchemy models, repositories, session
│   │   ├── csv/                   # Sicor/MMA/MTE file readers
│   │   └── geo/                   # GeoJSON export (non-QGIS)
│   └── interfaces/
│       └── cli/                   # Admin CLI (Typer/Click — match template)
├── car_microcredito_installer/    # User-facing install/verify/package CLI
└── car_microcredito_qgis/         # QGIS plugin (or plugins/ at repo root per template)

tests/
├── unit/                          # Policy, normalization, pydantic validators
├── integration/                   # Repositories + import pipeline (in-memory DB)
├── qgis/                          # Plugin regressions (optional marker)
└── installer/                     # Portable package verify/install

alembic/                           # DB migrations from schema v3 baseline
```

Legacy flat files (`db.py`, `sicor.py`, …) map to the layers above — do not keep monoliths “for convenience.”

### 1.4 Explicit non-goals

- Do not implement missing MCR compliance features (continuous activity area, remote monitoring, document checklist) unless separately requested — see `docs/matriz_conformidade_mcr_fno_fco.md`.
- Do not change verdict semantics (`ocorrencia_para_analise`, `sem_ocorrencia_identificada`, `inconclusivo`).
- Do not auto-approve credit based on clear environmental results.
- Do not store large geodata in Git (`dados/`, `*.db`, `*.gpkg` remain gitignored).
- Do not block the refactor waiting for new MCR features — stack and structure come first.

---

## 2. Tech stack migration map

### 2.1 Current → target by concern

| Concern | Today | After refactor |
|---------|-------|----------------|
| Package manager | pip / manual `PYTHONPATH` | **uv** (`uv sync`, `uv run`) |
| Config | `pyproject.toml` (minimal) | Full `[project]`, `[tool.ruff]`, `[tool.mypy]`, `[tool.pytest]` |
| Database | `sqlite3` + inline SQL | **SQLAlchemy 2.x** + **Alembic** |
| DTOs / validation | dicts, manual checks | **Pydantic v2** models |
| Tests | `unittest` | **pytest** (port existing cases first) |
| Lint/format | none | **ruff** |
| Types | untyped | **mypy** on core + installer |
| Admin CLI | `argparse` in `cli.py` | Template CLI (Typer recommended if template uses it) |
| User installer | PowerShell + `.bat` | Python CLI in `car_microcredito_installer` |
| CI | none (only `CODEOWNERS`) | uv sync → ruff → mypy → pytest |

### 2.2 SQLAlchemy migration notes

- Model all tables in §5.3 as SQLAlchemy ORM models; preserve table and column names for **existing `.db` file compatibility**.
- Replace `ativo_*` views with either:
  - SQLAlchemy hybrid queries filtering `importacao.ativo == 1`, or
  - Keep DB views via Alembic `op.execute(CREATE VIEW …)` — preferred if query parity is easier to prove.
- `configure_import()` → service method with same validation rules; run in transaction.
- `backup.migrate_copy()` → still file-level SQLite backup before Alembic upgrade on copy (preserve safety model from `docs/GUIA_VERSAO_0_8.md`).
- Readonly sessions must enforce same schema version check as today.

### 2.3 Pydantic migration notes

- **Input boundary:** CLI args, CSV rows, batch Excel rows → validated models; reject with same user-facing Portuguese messages where tested.
- **Output boundary:** Query results and report JSON → serialization from models (field names unchanged).
- **Policy layer:** Keep functions pure; accept/return Pydantic models or typed enums internally.
- Do not over-model QGIS types — only data crossing the plugin/core boundary.

### 2.4 pytest migration notes

Port `tests/test_*.py` to pytest incrementally:

1. Rename `test_*` methods → functions; keep assertions identical.
2. Replace `unittest.TestCase.setUp` with `@pytest.fixture` for in-memory DB.
3. Add `@pytest.mark.qgis` for tests requiring QGIS runtime.
4. Target: `uv run pytest` replaces `python -m unittest discover`.

### 2.5 Quality gates (must pass before merge)

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src/car_microcredito src/car_microcredito_installer
uv run pytest
```

QGIS plugin tests may run in a separate optional job with QGIS installed.

---

## 3. Product variants

Two distributable products share the same core but differ by plugin packaging:

| Variant | Plugin folder | Marker | Menu label | Extra assets |
|---------|---------------|--------|------------|--------------|
| **Individual** | `car_microcredito_qgis` | none | CAR Microcrédito | Manual individual |
| **Supreme / massa** | `car_microcredito_supremo_qgis` | `supreme_mode.txt` | CAR Microcrédito — Consulta em massa | Manual massa, `modelo_consulta_lote.xlsx` |

Supreme build changes (`scripts/build_release.py`):

- Renames plugin in `metadata.txt` to `CAR Microcrédito - Usuário Supremo`
- Adds `supreme_mode.txt` with content `enabled\n`
- Swaps icon to `icon_option_car_check.svg`
- Bundles core under `lib/car_microcredito/*.py`

Runtime detection: `SUPREME_MODE = (Path(__file__).parent / "supreme_mode.txt").is_file()` in `plugin.py`.

---

## 4. Runtime data layout

After deployment, local data lives under a single **`dados/`** root (path configured at install time):

```
dados/
├── car_microcredito.db          # SQLite: Sicor, MMA/MCR, MTE
├── car/
│   └── <UF>/
│       └── <UF>_AREA_IMOVEL.gpkg   # 27 UFs required for full national package
└── ambientais/
    ├── embargos.gpkg
    ├── terras_indigenas.gpkg
    ├── territorios_quilombolas.gpkg
    ├── unidades_conservacao.gpkg
    ├── florestas_publicas.gpkg
    └── desmatamento_pos_2020.gpkg
```

Portable/full packages additionally create output dirs beside the package:

```
<package_root>/arquivos/output/pdf/
<package_root>/arquivos/output/lotes/
<package_root>/arquivos/resultados/
```

**QGIS settings** (`QSettings("Cactvs", "CARMicrocredito")`):

| Key | Purpose | Set by installer |
|-----|---------|------------------|
| `database` | Path to `car_microcredito.db` | Yes |
| `car_base` | Path to `dados/car` | Yes |
| `report_output_dir` | User preference | No (UI) |
| `batch_report_output_dir` | Batch output | No (UI) |
| `window_geometry`, `content_splitter` | UI persistence | No |

**Environment variables:**

| Variable | Purpose |
|----------|---------|
| `CAR_MICROCREDITO_TEMP_DIR` | Override temp dir for reports/batch (default: `%LOCALAPPDATA%/Cactvs/CAR_Microcredito/temporarios` on Windows) |
| `CAR_MICROCREDITO_INSTALLED_PLUGIN` | Used by validation scripts to point at installed plugin path |
| `PYTHONPATH` | Dev mode: repo `src/` for core imports |

---

## 5. Core library contract (`car_microcredito`)

### 5.1 Package entrypoints

| Mechanism | Location |
|-----------|----------|
| `python -m car_microcredito` | `src/car_microcredito/__main__.py` → `cli.main()` |
| Console script `car-microcredito` | `pyproject.toml` → `car_microcredito.cli:main` |

**Version inconsistency to fix during refactor:** `src/car_microcredito/__init__.py` has `__version__ = "0.1.0"` while project is `0.8.0`. Align to single source.

### 5.2 Admin CLI commands (preserve)

Global: `--db` (default `dados/car_microcredito.db`)

| Command | Writable DB | Function |
|---------|-------------|----------|
| `init-db` | Yes | `db.initialize()` |
| `migrar-copia --origem --destino` | No (copies file) | `backup.migrate_copy()` |
| `ativar-importacao ID --escopo … [--validade-ate …]` | Yes | `db.configure_import()` |
| `import-sicor --mutuarios … --propriedades … [--operacoes …] [--complementos …] [--glebas …] --escopo …` | Yes | Transactional `sicor.import_file()` |
| `import-mma-mcr --arquivo … --validade-ate …` | Yes | MMA list import |
| `buscar-documento`, `buscar-car`, `buscar-documentos-car`, `buscar-operacao` | Readonly | Query functions |
| `exportar-glebas REF NU_ORDEM --saida PATH` | Readonly | GeoJSON export |
| `consultar-mma-mcr CAR [--json]` | Readonly | MMA lookup; synthetic row if not found |
| `status` | Readonly | List `importacao` rows |

Exit codes: `0` success, `2` on `OSError`, `ValueError`, `sqlite3.Error`.

**Gap:** MTE import has no CLI subcommand — only `scripts/importar_trabalho_escravo.py`. Optional improvement: add `import-mte` to admin CLI; not required for parity refactor.

### 5.3 Database schema (SCHEMA_VERSION = 3)

File: `src/car_microcredito/db.py`

**Tables:**

- `importacao` — metadata for all imports; columns added in v3: `escopo`, `ativo`, `validade_ate`
- `sicor_mutuario`, `sicor_propriedade`, `sicor_operacao`, `sicor_complemento_operacao`, `sicor_ponto_gleba`, `sicor_gleba_wkt`
- `mma_mcr`
- `trabalho_escravo`
- `mte_publicacao` (created in `initialize()`)

**Views:** `ativo_<table>` for each Sicor/MMA table — rows from active import only.

**Readonly guard:** Opening with `readonly=True` rejects DB if `PRAGMA user_version != 3` with message requiring admin migration.

**Migration from v2:** `_migrate_import_table()` expands `importacao.tipo` CHECK to include `mma_mcr`. Legacy imports get `ativo=0`, `escopo='legado:<id>'`.

**Activation rules (`configure_import`):**

- Requires `linhas_validas > 0`, `linhas_rejeitadas == 0`, non-empty `escopo`
- MMA requires `escopo == "nacional"` and `validade_ate`
- Deactivates other imports of same `tipo` + `escopo`, activates selected row

### 5.4 Import activation rules (`sicor.import_file`)

Critical invariants:

1. New import starts `ativo=0`; auto-activates only if **all rows valid and zero rejected** at end of import.
2. Duplicate file (`tipo` + `sha256`) → skipped (`ignorado=True`) unless different `escopo` → error.
3. SHA256 checked before and after import — tamper during import aborts.
4. Partial Sicor import (`import-sicor`) is transactional — one failure rolls back all files in that call.
5. `CD_CAR = -1` and placeholders (`N/A`, `NULL`, etc.) → `car_normalizado = ''` (CAR not informed).

### 5.5 Normalization rules (`normalize.py`)

| Function | Rule |
|----------|------|
| `normalize_document` | Strip non-digits; valid only if length 11 or 14 |
| `normalize_car` | Uppercase alphanumeric key; empty for `-1`, `0`, `N/A`, `NA`, `NULL`, `NONE` |
| `is_masked_document` | Contains `*`, `X`, or `x` |
| `normalize_header` | NFKD → uppercase underscore CSV headers |

### 5.6 Policy / verdict rules (`policy.py`) — DO NOT CHANGE

**Constants:**

```python
INCONCLUSIVE = "inconclusivo"
CLEAR = "sem_ocorrencia_identificada"
REVIEW = "ocorrencia_para_analise"
```

**`aggregate(results)`:** Any `REVIEW` → `REVIEW`; else if empty or any ≠ `CLEAR` → `INCONCLUSIVE`; else → `CLEAR`.

**`available(source, count_field)`:** Source usable iff count > 0, sha256 present, zero rejections, `validade_ate >= today`.

**`evaluate_lists(mma, labor, evidence, documents)`:**

| Source | REVIEW when | CLEAR when | Default |
|--------|-------------|------------|---------|
| MMA/MCR | `status_imovel` in `{SU, CA}` OR `dentro_criterio` in `{sim,s,yes}` | `status_imovel == AT` AND `dentro_criterio` in `{nao,n,no}` | `INCONCLUSIVE` |
| MTE | Any labor hit for provided documents | No hits | `INCONCLUSIVE` if no valid MTE source |

**`compatible_operation` / `unique_operation`:** Match normalized CAR on operation; multiple matches without SICAR polygon → `ValueError`.

**Disclaimers:** `list_message()` and `consultar-mma-mcr` synthetic row explicitly state absence does not prove regularity.

### 5.7 Sicor link types (query semantics)

| `tipo_vinculo` | Meaning |
|----------------|---------|
| `documento_na_propriedade` | CPF/CNPJ on `SICOR_PROPRIEDADES` row |
| `associacao_por_operacao` | Mutuário shares `REF_BACEN` with property |
| `mutuario_da_operacao` | Document linked via mutuário for a CAR |
| `car_nao_informado_pelo_sicor` | `car_normalizado` empty |

### 5.8 Sicor CSV column aliases

Defined in `sicor.py` — importers must continue accepting BCB field names:

- Mutuários: `REF_BACEN`, `CD_CPF_CNPJ`, …
- Propriedades: `REF_BACEN`, `NU_ORDEM`, `CD_CAR`, `CD_SNCR`, …
- Glebas: point indices + lat/lon
- MMA: `COD_IMOVEL`, `CD_CAR`, `status_imovel`, `dentro_criterio`, …

Encodings tried: UTF-8, Windows-1252. Delimiter auto-detected.

---

## 6. QGIS plugin contract

### 6.1 Registration

- `metadata.txt`: QGIS 3.40–3.99, category Vector, `experimental=True`
- `__init__.py`: `classFactory(iface)` → `CarMicrocreditoPlugin`
- Core import path: bundled `lib/` in plugin, else repo `../../src`

### 6.2 Individual query flow (`SearchWindow` in `plugin.py`)

**Inputs:** CPF/CNPJ, CAR, owner document, lat/lon, Google Maps URL

**Pipeline (`analyze_selected`):**

1. Core DB queries (operations, MMA, documents, MTE)
2. Geometry: SICAR polygon (`car_source.export_car_feature`) OR Sicor gleba (`geo.build_glebas_geojson`)
3. Environmental: `run_environment()` → `EnvironmentalWorker` thread
4. Policy: `evaluate_lists` + `aggregate`
5. Map PNG: `render_analysis_map()`
6. Report: `write_report()` → PDF + JSON + manifest

**Modes:** `"final"`, `"interferences"` (preview table), `"report_preview"` (provisional PDF)

**UX rules:**

- CAR-only query without Sicor documents → owner field required (red), MTE checked manually
- Multiple CAR polygons or multiple CARs for one document → selection dialog
- Google short links require internet for redirect resolution
- Processing bar; user must wait for completion before next query

### 6.3 Environmental analysis (`analysis.py`)

Six sources from `default_sources(base_directory)`:

| Code | File | MCR reference |
|------|------|---------------|
| `embargos` | `embargos.gpkg` | MCR 2-9 embargos |
| `terras_indigenas` | `terras_indigenas.gpkg` | MCR 2-9 TI |
| `territorios_quilombolas` | `territorios_quilombolas.gpkg` | MCR 2-9 quilombolas |
| `unidades_conservacao` | `unidades_conservacao.gpkg` | MCR 2-9 UC |
| `florestas_publicas` | `florestas_publicas.gpkg` | MCR 2-9 florestas tipo B |
| `desmatamento_pos_2020` | `desmatamento_pos_2020.gpkg` | MCR 2-9-17/18 (note: layer is post-2020; report warns about 31/07/2019 rule) |

**Per-layer outcomes:**

- Intersection with area > 0 → `ocorrencia_para_analise`
- No intersection → `sem_ocorrencia_identificada`
- Missing file, invalid geometry, reprojection failure, unrepairable source geometry → `inconclusivo`

**Geometry repair:** Invalid source polygons may be `makeValid()` with `geometrias_reparadas` logged; unrepairable → inconclusive.

**Worker:** `EnvironmentalWorker(QThread)` — QGIS objects off UI thread; LRU cache (32 entries) keyed by geometry + source signatures.

### 6.4 Batch / Supreme flow (`batch_window.py`)

**Excel contract** (`batch.py`):

- Sheet name: `Consultas`
- Required headers: `CPF_CNPJ`, `CAR`, `PROPRIETARIO_POSSUIDOR`, `REFERENCIA_INTERNA`, `OBSERVACAO`
- `CPF_CNPJ` required; others optional
- Empty `CAR` → expand to all distinct CARs for document from Sicor
- Validation errors block processing; row failures don't stop batch
- Output: consolidated PDF by CPF/CNPJ + audit JSON

### 6.5 Report outputs (`report.py`)

| Output | Naming | Contents |
|--------|--------|----------|
| PDF | `analise_car_{key}.pdf`, `previa_relatorio_car_{key}.pdf`, batch variants | ReportLab A4; map image; layer table; MMA/MTE sections |
| JSON | Same basename `.json` | Structured audit; paths stripped; SHA256 manifest |
| Manifest | `manifesto_arquivos.json` in output folder | File hashes |

Footer text (preserve): *"Triagem socioambiental - evidência para revisão humana"*

### 6.6 Plugin ZIP layout (must remain compatible)

Built by `build_release.py` — new builder must produce equivalent structure:

```
car_microcredito_qgis/          # or car_microcredito_supremo_qgis/
├── metadata.txt
├── plugin.py
├── __init__.py
├── … (all plugin .py and assets)
├── lib/
│   └── car_microcredito/
│       └── *.py                 # full core copied
├── manifesto_codigo.json        # SHA256 of every file in package
└── supreme_mode.txt             # supreme variant only
```

QGIS installs by extracting to: `%APPDATA%/QGIS/QGIS3/profiles/<profile>/python/plugins/<folder>/`

Alternative install path: **Complementos → Instalar a partir do ZIP** with `dist/car_microcredito_qgis.zip`.

---

## 7. Current installation system (to be replaced)

### 7.1 Full portable package structure

Built by `scripts/build_portable_release.py` → `dist/pacote de instalação 0.8.0/`:

```
CAR_Microcredito_Portatil_0.8.0/          # or CAR_Microcredito_Consulta_em_Massa_0.8.0/
├── Instalar CAR Microcredito.bat
├── Instalar CAR Microcredito.ps1       # generated from embedded template
├── Verificar pacote.bat
├── Verificar pacote.ps1
├── LEIA_ME.txt
├── VERSAO.txt
├── TIPO_PACOTE.txt
├── Manual_CAR_Microcredito_0.8.0.docx  # or Manual_Consulta_em_Massa_0.8.0.docx
├── modelo_consulta_lote.xlsx           # massa only
├── MANIFESTO_SHA256.json
├── MANIFESTO_ARQUIVOS.txt
└── arquivos/
    ├── plugin/
    │   └── car_microcredito_qgis/      # or car_microcredito_supremo_qgis/
    ├── dados/
    │   ├── car_microcredito.db
    │   ├── car/<UF>/<UF>_AREA_IMOVEL.gpkg  × 27
    │   └── ambientais/*.gpkg           × 6
    ├── output/pdf/
    ├── output/lotes/
    └── resultados/
```

### 7.2 What the current installer does

`Instalar CAR Microcredito.ps1` (generated template in `build_portable_release.py`):

1. **Preflight:** Fail if QGIS process running (`qgis-bin`, `qgis-ltr-bin`, `qgis`)
2. **Verify:** Run `Verificar pacote.ps1` — SHA256 manifest + 27 UFs + 6 environmental files + plugin version
3. **Plugin install:** For each QGIS profile under `%APPDATA%/QGIS/QGIS3/profiles/`:
   - Backup existing plugin dir to `<plugin>_backup_<timestamp>`
   - Copy `arquivos/plugin/<folder>/` → `python/plugins/<folder>/`
   - Verify installed `metadata.txt` has `version=0.8.0`
   - Rollback on failure
4. **Registry:** Write `HKCU:\Software\Cactvs\CARMicrocredito` keys `database`, `car_base`
5. **Output dirs:** Create `arquivos/output/pdf`, `output/lotes`, `resultados`
6. **User message:** Restart QGIS, enable plugin in Installed tab

**Parameters for testing:** `-ProfilesRoot`, `-SkipRegistry`, `-SkipQgisCheck`

### 7.3 Verification rules (`Verificar pacote.ps1`)

- Every entry in `MANIFESTO_SHA256.json` exists and matches SHA256
- Path traversal guard (files must stay under package root)
- Exactly 27 `*_AREA_IMOVEL.gpkg` with UFs `AC…TO`
- All 6 environmental `.gpkg` present
- Plugin `metadata.txt` contains `version=0.8.0`

### 7.4 Build prerequisites for portable packages

`build_portable_release.py` → `validate_sources()` requires:

- `dados/car_microcredito.db` with `PRAGMA user_version == 3`
- 27 state GPKGs at `dados/car/<UF>/<UF>_AREA_IMOVEL.gpkg`
- 6 environmental GPKGs at `dados/ambientais/`
- Optional: `dados/FONTES_DADOS.md`

`build_portable_package.py` additionally requires at least one active import in DB.

### 7.5 Known problems in current installer stack

| Issue | Location | Impact |
|-------|----------|--------|
| Stale version in static `portable/` | `LEIA_ME.txt`, `VERSAO.txt` say **0.7.0** | User confusion; superseded by generated files in `build_portable_release.py` |
| Two parallel builders | `build_portable_release.py` vs `build_portable_package.py` | Maintenance burden |
| PS1 embedded as Python strings | `build_portable_release.py` lines 47–204 | Hard to edit/test |
| Windows-only | `.bat`/`.ps1`, `%APPDATA%`, Registry | No Linux/macOS install path |
| QGIS min version mismatch | `VERSAO.txt` says 3.28; `metadata.txt` requires **3.40** | Incorrect user expectation |
| Plugin folder name vs QGIS convention | Copies to `car_microcredito_qgis` | Must match `metadata.txt` and menu registration |

---

## 8. New installer CLI — functional requirements

The replacement installer is a **user-facing tool** (not the admin `car-microcredito` CLI). It must satisfy all behaviors in §7.2–7.3 unless explicitly improved with documented rationale.

### 8.1 Required subcommands (minimum)

| Subcommand | Behavior |
|------------|----------|
| `verify` | Equivalent to `Verificar pacote.ps1` — manifest, 27 UFs, 6 layers, plugin version |
| `install` | Equivalent to `Instalar CAR Microcredito.ps1` — plugin copy, settings, output dirs |
| `package build` (maintainer) | Replace `build_portable_release.py` — produce distributable ZIP(s) |
| `plugin build` (maintainer) | Replace `build_release.py` — produce QGIS ZIP(s) |

Optional but recommended: `install --profile NAME`, `install --dry-run`, `uninstall`, `doctor` (QGIS detection + settings check).

### 8.2 Install behavior checklist

- [ ] Refuse install while QGIS is running (configurable skip for CI)
- [ ] Verify package integrity before copying
- [ ] Install to all QGIS profiles (or selected profile)
- [ ] Atomic install with backup/rollback on failure
- [ ] Set `QSettings`/`database` and `car_base` to absolute paths inside package
- [ ] Preserve path format expected by plugin (`/` separators in settings OK on Windows)
- [ ] Create output directories
- [ ] Support both variants (`individual`, `massa`) via package type marker (`TIPO_PACOTE.txt` or CLI flag)
- [ ] Print actionable post-install instructions

### 8.3 Package build checklist

- [ ] Embed plugin from current sources via same logic as `plugin_files()` in `build_release.py`
- [ ] Include homologated `dados/` snapshot (maintainer supplies path)
- [ ] Generate `MANIFESTO_SHA256.json` and human-readable manifest
- [ ] Produce `.sha256.txt` sidecar for ZIP
- [ ] Validate 27 UFs + 6 environmental + DB schema before building
- [ ] Two ZIP outputs: individual + massa (or `--variant` flag)
- [ ] Include correct manual `.docx` per variant
- [ ] Include `modelo_consulta_lote.xlsx` in massa package only

### 8.4 Integration with modern template

When mapping to the new template, place components as follows (adjust paths to match template conventions):

| Concern | Suggested slot in modern template |
|---------|-------------------------------------|
| Core library | `src/car_microcredito/` (keep) |
| QGIS plugin | `plugins/car_microcredito_qgis/` or template's plugin dir |
| Admin CLI | `car-microcredito` console script (keep) |
| **New user installer CLI** | `src/car_microcredito_installer/` or `tools/installer/` — **new package** |
| Maintainer build | Template's `task`/`just`/`make` targets calling Python builders |
| Tests | `tests/` + installer integration tests replacing `validate_portable_installer.py` |
| Docs | `docs/` — migrate `GUIA_VERSAO_0_8.md` content into installer `--help` and README |

**Dependency note:** Core library runtime deps become SQLAlchemy + Pydantic (managed by uv). QGIS plugin adds PyQt/reportlab at runtime. Installer package may add Typer/rich/platformdirs per template.

---

## 9. Test suite as regression contract

Run before and after refactor:

```bash
# Legacy (baseline before port)
PYTHONPATH=src python -m unittest discover -s tests -v

# Target
uv run pytest
```

| Test file | Guards |
|-----------|--------|
| `tests/test_core.py` | Normalization, import, queries, MMA/MTE policy, gleba GeoJSON, batch template headers |
| `tests/test_regressions.py` | Version 0.8 behavioral regressions |
| `tests/test_qgis_regressions.py` | Plugin-layer regressions (requires QGIS env for full run) |
| `tests/test_distribution.py` | Plugin ZIP hashes, supreme marker, 27-UF validation |

**Installer tests to rewrite:**

- `scripts/validate_portable_installer.py` → new test module invoking installer CLI with `-ProfilesRoot` equivalent and isolated temp dirs

**Scripts using QGIS for validation** (maintainer-only, not CI-critical):

- `scripts/validar_plugins_0_8_instalados.py`
- `scripts/validar_plugin_supremo_instalado.py`

---

## 10. Documentation to preserve or link

| Doc | Role |
|-----|------|
| `README.md` | User + admin overview |
| `docs/GUIA_VERSAO_0_8.md` | Migration procedure, activation, packaging |
| `docs/matriz_conformidade_mcr_fno_fco.md` | Compliance scope (partial coverage explicit) |
| `docs/DECISOES_DADOS_PENDENTES.md` | Pending data decisions |
| `docs/plano_implementacao_car_microcredito.md` | Implementation history |

Do not duplicate business rules across docs — `policy.py` and `analysis.py` are authoritative for behavior.

---

## 11. Migration execution checklist

### Phase A — Modern stack bootstrap (Objective 1)

1. Apply modern template: **uv** project init, lockfile, `[tool.ruff]`, `[tool.mypy]`, `[tool.pytest]`.
2. Add dependencies: SQLAlchemy, Alembic, Pydantic; dev: ruff, mypy, pytest.
3. Create target directory layout (§1.3); move packages under `src/`.
4. Port tests to pytest without changing assertions — green baseline.
5. Enable ruff + mypy; fix issues incrementally with QGIS modules excluded initially.

### Phase B — Core reimplementation (Objectives 1 + 2)

6. Alembic baseline migration reproducing schema v3 (§5.3) and `ativo_*` views.
7. SQLAlchemy models + repositories; port `sicor.py` import/query logic to services.
8. Pydantic domain models; port `policy.py` and `normalize.py` (pure, typed).
9. Rewire admin CLI to call application services; preserve all commands (§5.2).
10. Split QGIS plugin orchestration from UI; plugin calls application layer only.
11. Delete legacy monolith modules once parity tests pass.

### Phase C — New installer (Objective 2)

12. Implement `verify` matching §7.3 rules.
13. Implement `install` matching §7.2 rules (profile detection, rollback, settings).
14. Implement maintainer `package build` replacing `build_portable_release.py`.
15. Implement `plugin build` replacing `build_release.py`.
16. Write installer integration tests replacing `validate_portable_installer.py`.
17. Remove: `portable/*.ps1`, `portable/*.bat`, embedded PS1 strings, stale static docs.

### Phase D — Validation

18. `uv run ruff check . && uv run mypy … && uv run pytest` — all green.
19. Build both plugin ZIPs; install in QGIS 3.40+; smoke-test individual + supreme flows.
20. Build portable package; run `verify` + `install` on clean Windows profile.
21. Compare output PDF/JSON structure against golden samples if available.
22. Confirm `QSettings` paths resolve after install without manual UI configuration.

### Phase E — Cleanup

23. Centralize version in `pyproject.toml` only.
24. Align QGIS minimum version messaging everywhere (**3.40**, not 3.28).
25. Update README: stack, dev setup (`uv sync`), new installer CLI.
26. CI pipeline: ruff → mypy → pytest on every push.
27. Tag release; publish ZIPs to GitHub Releases (data not in Git).

---

## 12. Acceptance criteria

Refactor is complete when **both objectives** are met:

### Stack and quality (Objective 1 + 2)

1. **uv** is the only documented way to install deps and run tools (`uv sync`, `uv run pytest`, …).
2. **ruff** and **mypy** pass on core + installer packages (documented QGIS exemptions).
3. **pytest** replaces unittest; all ported tests green.
4. **SQLAlchemy + Alembic** own persistence; no raw SQL in application/domain layers.
5. **Pydantic** models validate imports, queries, and report payloads at boundaries.
6. **Layered structure** (§1.3) — no business logic in `plugin.py` UI handlers or CLI argparse blocks.
7. Legacy monolith files (`db.py`, `sicor.py` flat layout) removed after parity proven.

### Product behavior (frozen contract)

8. **Zero behavior change** in triage outcomes for existing test cases.
9. **Admin CLI** commands unchanged in name, flags, and output shape.
10. **Plugin ZIP structure** installable by QGIS and by new `install` command.
11. **Portable package** contains same logical assets (DB, 27 UFs, 6 layers, plugin, manuals, manifests).
12. **Settings contract** (`Cactvs/CARMicrocredito`, env vars) unchanged.

### Installer replacement

13. **Old PowerShell installer** fully removed — no dual path.
14. **New installer** passes automated integration tests for both variants.

---

## 13. Quick reference — file inventory

### Core Python (`src/car_microcredito/`)

| File | Lines of responsibility |
|------|-------------------------|
| `__init__.py` | Package version |
| `__main__.py` | Module entry |
| `cli.py` | Admin CLI |
| `db.py` | SQLite schema v3 |
| `sicor.py` | Sicor/MMA ETL + queries |
| `mte.py` | MTE CSV import |
| `normalize.py` | Document/CAR normalization |
| `policy.py` | Verdict rules |
| `geo.py` | Gleba GeoJSON |
| `downloads.py` | GPKG/ZIP validation |
| `backup.py` | DB snapshot/migrate |

### QGIS plugin (`qgis_plugin/car_microcredito_qgis/`)

| File | Role |
|------|------|
| `plugin.py` | Plugin class + `SearchWindow` UI |
| `batch_window.py` | Supreme batch UI |
| `batch.py` | XLSX parsing |
| `analysis.py` | Environmental cross-check |
| `worker.py` | Background analysis thread |
| `report.py` | PDF/JSON generation |
| `evidence.py` | Audit metadata |
| `car_source.py` | CAR lookup, Maps URLs, basemap |
| `map_output.py` | Map PNG rendering |
| `metadata.txt` | QGIS plugin manifest |
| `modelo_consulta_lote.xlsx` | Batch template |
| `icon*.svg` | Icons |

### Replace entirely (installer/distribution)

| File | Role |
|------|------|
| `portable/Instalar CAR Microcredito.ps1` | Legacy install |
| `portable/Verificar pacote.ps1` | Legacy verify |
| `portable/*.bat` | Launchers |
| `portable/LEIA_ME.txt`, `VERSAO.txt` | Stale static docs |
| `scripts/build_portable_release.py` | Primary portable builder |
| `scripts/build_portable_package.py` | Alternate portable builder |
| `scripts/validate_portable_installer.py` | Installer test harness |
| `scripts/build_qgis_plugin*.ps1` | Thin PS wrappers |

### Refactor packaging only

| File | Role |
|------|------|
| `scripts/build_release.py` | Plugin ZIP builder (logic reference) |
| `pyproject.toml` | Project metadata |

---

## 14. External integrations (unchanged)

| System | Direction | Code touchpoint |
|--------|-----------|-----------------|
| Sicor BCB microdata | In (CSV/GZ) | `sicor.py` |
| MMA MCR list | In (CSV) | `sicor.py` |
| MTE employer CSV | In (CSV) | `mte.py` |
| SICAR CAR GeoPackages | In (local files) | `car_source.py`, `downloads.py` |
| Environmental GPKGs | In (local files) | `analysis.py` |
| Google Maps / Satellite | Out (HTTP) | `car_source.py`, `map_output.py` |
| ReportLab | Out (PDF) | `report.py` |

No API keys. Internet optional except Maps short links and satellite tiles.

---

## 15. Glossary

| Term | Definition |
|------|------------|
| CAR | Cadastro Ambiental Rural property code |
| Sicor | BCB rural credit microdatabase |
| SICAR | National CAR polygon registry |
| Gleba | Financed plot geometry from Sicor |
| MMA/MCR | Official MMA publication for MCR item 17 |
| MTE | Federal slave-labor employer registry |
| Escopo | Import edition identifier (scope + competence) |
| Triagem | Screening for human review, not credit decision |
| Usuário Supremo | Batch/mass consultation build variant |

---

*Refactor goals: (1) modern stack — uv, ruff, mypy, pytest, SQLAlchemy, Pydantic; (2) maintainable structure and clean patterns. Product behavior frozen. Update this file when stack or contracts change.*
