# Automação CAR para microcrédito rural

Versão **0.8.0**. Núcleo Python, plugin QGIS, consulta em massa, testes, instalador e documentação.

Leia [o guia da versão 0.8](docs/GUIA_VERSAO_0_8.md) para migração de banco e ativação de publicações.

O plano desta reestruturação está em [docs/REFACTOR_PLAN.md](docs/REFACTOR_PLAN.md). O contrato de comportamento permanece o de [docs/REFACTOR.md](docs/REFACTOR.md).

## Ambiente de desenvolvimento

Python 3.13+, [uv](https://docs.astral.sh/uv/).

```bash
uv sync
make format lint typecheck test
```

CLI administrativa:

```bash
uv run car-microcredito --db dados/car_microcredito.db init-db
uv run car-microcredito --help
```

Instalador e empacotamento:

```bash
uv run car-microcredito-installer verify caminho/do/pacote
uv run car-microcredito-installer install caminho/do/pacote
uv run build --variant all
uv run car-microcredito-installer package-build --dados dados --variant all
```

## Estrutura

- `src/qgis_plugin_microcredito`: domínio, casos de uso e infraestrutura não-QGIS
- `src/database`: SQLAlchemy, schema v3, repositórios
- `src/cli`: CLI `car-microcredito`
- `src/plugin`: superfície QGIS
- `src/installer`: verify/install/plugin-build/package-build
- `test`: pytest (marcador `qgis` quando PyQGIS está instalado)

## Dados após a implantação

```
dados/
├── car_microcredito.db
├── car/<UF>/<UF>_AREA_IMOVEL.gpkg
└── ambientais/*.gpkg
```

No QGIS: **Complementos > CAR Microcrédito**. Os resultados são evidências para revisão humana, não decisão automática de crédito.

QGIS mínimo: **3.40**.
