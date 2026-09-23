# Refactor plan — OLD-qgis-plugin → qgis-plugin-microcredito

Product behavior is frozen (verdicts, CLI flags, PDF/JSON shape, schema v3).
This plan maps the legacy monolith onto the modern template in `AGENTS.md`.

## Target layout

| Path | Owns |
|------|------|
| `src/qgis_plugin_microcredito/domain/` | Pydantic models, `StrEnum` verdicts, normalize, policy |
| `src/qgis_plugin_microcredito/application/` | Import, search, activate, backup, geo, evidence, hashing, batch XLSX |
| `src/qgis_plugin_microcredito/infrastructure/` | CSV readers, GPKG/ZIP validation |
| `src/database/` | SQLAlchemy models, session, repositories, schema v3, Alembic |
| `src/cli/` | Admin CLI (`car-microcredito`) — argparse flags unchanged |
| `src/plugin/` | QGIS surface: UI, analysis, report, worker, map |
| `src/installer/` | `verify`, `install`, `plugin-build`, `package-build` |
| `test/` | pytest regression suite; QGIS tests marked optional |
| `alembic/` | Baseline migration for schema v3 + `ativo_*` views |
| `assets/` | Icons and batch Excel template |

## Acceptance gates

`uv sync` then `make format lint typecheck test` (Makefile targets are `.PHONY`; required so `make test` is not shadowed by the `test/` directory). QGIS-marked tests skip without PyQGIS.
