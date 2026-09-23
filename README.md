# CAR Microcrédito

**Versão 0.9.4** — triagem socioambiental de operações de microcrédito rural com apoio do QGIS.

O plugin automatiza a consulta de dados públicos (Sicor, MMA/MCR, MTE), o cruzamento espacial do CAR com camadas ambientais nacionais, a pré-análise explicável e a atualização assinada das bases. Cada análise produz **evidências para revisão humana** (PDF, JSON, mapa e metadados das fontes). **Não substitui a decisão de crédito** nem declara conformidade integral com o MCR.

Leia [o registro da migração 0.9.4](docs/MIGRACAO_GPT_0_9_4.md), o [fluxograma funcional](docs/FLUXOGRAMA_APLICACAO_0_9_4.md), o [guia da versão 0.8](docs/GUIA_VERSAO_0_8.md) para bancos antigos e a [matriz de cobertura regulatória](docs/matriz_conformidade_mcr_fno_fco.md).

## O que o sistema faz

### Consulta individual (QGIS)

1. Localiza o CAR por documento (CPF/CNPJ), número do CAR ou operação Sicor.
2. Obtém a geometria no SICAR (GPKG por UF) ou reconstrói a gleba da operação.
3. Consulta a publicação MMA/MCR e o cadastro MTE de trabalho análogo ao escravo.
4. Cruza o polígono com camadas ambientais (embargos, terras indígenas, territórios quilombolas, unidades de conservação, florestas públicas, PRODES pós-2020).
5. Gera relatório consolidado com vereditos, referências MCR e evidências auditáveis.

### Consulta em lote (Usuário Supremo)

Variante do plugin com `supreme_mode.txt` habilitada. Processa planilha Excel com múltiplos CPF/CNPJ, registra falhas por linha e permite retomada após cancelamento.

### CLI administrativa

Importação de bases Sicor, MMA e MTE; consultas por documento ou CAR; migração segura de banco; exportação de glebas em GeoJSON — sem interface gráfica.

## Regras de negócio

### Vereditos

Cada verificação retorna um dos três estados:

| Veredito | Significado |
|----------|-------------|
| `sem_ocorrencia_identificada` | Nenhuma ocorrência localizada na fonte consultada. **Não comprova regularidade integral.** |
| `ocorrencia_para_analise` | Achado que exige revisão documental e decisão humana. |
| `inconclusivo` | A verificação não pôde ser concluída (fonte ausente, vencida, geometria inválida, dados insuficientes). |

A agregação prioriza `ocorrencia_para_analise` sobre `inconclusivo` e `sem_ocorrencia_identificada`.

### Fontes de dados

| Fonte | Conteúdo | Requisito para consulta válida |
|-------|----------|-------------------------------|
| **Sicor** | Mutuários, propriedades, operações, complementos e glebas | Importação ativa com `--escopo` explícito |
| **MMA/MCR** | Lista oficial de imóveis para atendimento ao MCR | Carga validada, sem rejeições e com `validade-ate` vigente |
| **MTE** | Cadastro de empregadores com trabalho análogo ao escravo | Publicação importada com `validade-ate` vigente |

Listas sem carga validada ou com validade vencida produzem consulta **inconclusiva**, nunca um resultado aparentemente favorável.

### Camadas ambientais

Cruzamento espacial com interseção do polígono do imóvel/gleba:

- Embargos ambientais (Ibama)
- Terras indígenas
- Territórios quilombolas
- Unidades de conservação
- Florestas públicas (tipo B não destinada — exige confirmação documental)
- Desmatamento PRODES após 2020 (recorte solicitado; MCR 2-9-17/18 exige avaliação desde 31/07/2019)

Sobreposição territorial gera pendência para análise, não reprovação automática. Geometria incompleta ou inválida produz aviso sem considerar a área totalmente analisada.

### Princípios operacionais

- O CAR informado é conferido contra a gleba usada na análise; polígono de operação anterior não é reutilizado sem compatibilidade comprovada.
- Cada relatório é guardado em pasta própria (PDF, JSON, mapa, conferência de arquivos).
- Importações antigas permanecem como histórico; apenas edições ativadas por escopo participam das consultas.
- Arquivo vazio ou inválido na importação MTE não substitui a publicação anterior.
- Valores como `-1` (CAR não informado pelo Sicor) não são tratados como número de CAR.

## Requisitos

- **Python** 3.13+
- **QGIS** 3.40+ (plugin)
- **[uv](https://docs.astral.sh/uv/)** para dependências e scripts

## Ambiente de desenvolvimento

```bash
uv sync
make format lint typecheck test
```

| Comando | Função |
|---------|--------|
| `make format` | Formatação com ruff |
| `make lint` | Lint com ruff |
| `make typecheck` | Tipagem estática com mypy |
| `make test` | Testes com pytest (marcador `qgis` quando PyQGIS está instalado) |

Os alvos do `Makefile` são declarados como `.PHONY` para que o Make sempre execute os comandos. Sem isso, `make test` pode confundir o alvo `test` com a pasta `test/` e exibir `make: 'test' is up to date.` sem rodar o pytest — nesse caso, `uv run pytest` ainda funciona, mas o alvo `make test` deve ser usado após `uv sync`.

## Estrutura do projeto

```
src/
├── qgis_plugin_microcredito/   # Núcleo: domínio, casos de uso e infraestrutura
│   ├── domain/                 # Dataclasses, enums e regras puras (policy)
│   ├── application/            # Serviços: importação, consulta, geo, backup
│   └── infrastructure/         # Leitura de CSV, validação de downloads
├── database/                   # SQLAlchemy, schema v3, repositórios, migrações
├── cli/                        # CLI `car-microcredito`
├── plugin/                     # Superfície QGIS (UI, análise espacial, relatório)
└── installer/                  # verify, install, plugin-build, package-build, update-package
assets/                         # Ícones e recursos estáticos do plugin
test/                           # pytest (espelha a estrutura do pacote)
docs/                           # Guias, matriz MCR e documentação de refatoração
```

Arquitetura em camadas: `plugin/` chama `qgis_plugin_microcredito/`, que persiste via `database/`. Regras de negócio ficam em `domain/` e não devem ser duplicadas na interface.

## CLI administrativa

```bash
# Banco
uv run car-microcredito --db dados/car_microcredito.db init-db
uv run car-microcredito --db dados/car_microcredito.db status

# Migração segura (nunca altera o banco de origem)
uv run car-microcredito migrar-copia --origem BANCO_ANTERIOR.db --destino BANCO_NOVO.db
uv run car-microcredito --db BANCO_NOVO.db ativar-importacao ID --escopo COMPETENCIA_ABRANGENCIA

# Importação Sicor (todos os arquivos da edição na mesma chamada)
uv run car-microcredito --db dados/car_microcredito.db import-sicor \
  --mutuarios mutuarios.csv --propriedades propriedades.csv \
  --operacoes operacoes.csv --glebas glebas.csv \
  --escopo 2026-08-nacional

# Publicações nacionais
uv run car-microcredito --db dados/car_microcredito.db import-mma-mcr \
  --arquivo mma_mcr.csv --validade-ate 2026-12-31
uv run car-microcredito --db dados/car_microcredito.db import-mte \
  --arquivo mte.csv --validade-ate 2026-12-31

# Consultas
uv run car-microcredito --db dados/car_microcredito.db buscar-documento 12345678901
uv run car-microcredito --db dados/car_microcredito.db buscar-car SP-1234567-ABCDEF
uv run car-microcredito --db dados/car_microcredito.db consultar-mma-mcr SP-1234567-ABCDEF

uv run car-microcredito --help
```

## Instalação e empacotamento

```bash
# Gera ZIPs do plugin (individual e Usuário Supremo)
uv run build --variant all

# Monta pacote completo com dados (27 UFs + camadas ambientais)
uv run car-microcredito-installer package-build --dados dados --variant all

# Verifica integridade e instala no QGIS
uv run car-microcredito-installer verify caminho/do/pacote
uv run car-microcredito-installer install caminho/do/pacote

# Prepara pacotes e catálogo assinado de atualização
uv run car-microcredito-installer update-package --help
uv run python tools/inventory_production_sources.py --help
uv run python tools/validate_production_sources.py --help
uv run python tools/audit_sicar_state_routing.py --help
pwsh tools/build_signed_catalog.ps1 -PrepareOnly -TemplatePath catalog.template.json -OutputDirectory saida
```

| Variante | Diretório do plugin | Diferença |
|----------|---------------------|-----------|
| Individual | `car_microcredito_qgis` | Consulta unitária |
| Usuário Supremo | `car_microcredito_supremo_qgis` | Inclui `supreme_mode.txt` e consulta em lote |

## Dados após a implantação

```
dados/
├── car_microcredito.db
├── car/<UF>/<UF>_AREA_IMOVEL.gpkg    # geometria SICAR por estado (27 UFs)
└── ambientais/
    ├── embargos.gpkg
    ├── terras_indigenas.gpkg
    ├── territorios_quilombolas.gpkg
    ├── unidades_conservacao.gpkg
    ├── florestas_publicas.gpkg
    └── desmatamento_pos_2020.gpkg
```

## Uso no QGIS

A pré-análise organiza evidências e regras para o técnico; a ferramenta não aprova nem recusa crédito automaticamente.

1. Instale o plugin (ZIP ou instalador).
2. Ative em **Complementos → Gerenciar e instalar complementos → Instalados**.
3. Abra **Complementos → CAR Microcrédito**.
4. Informe CPF/CNPJ, CAR ou operação Sicor e execute a análise.
5. Revise o relatório gerado e registre a decisão humana.

Os resultados são **evidências para triagem**, não aprovação automática de crédito.

## Documentação adicional

| Documento | Conteúdo |
|-----------|----------|
| [docs/MIGRACAO_GPT_0_9_4.md](docs/MIGRACAO_GPT_0_9_4.md) | Mapa das funcionalidades migradas e publicação segura |
| [docs/FLUXOGRAMA_APLICACAO_0_9_4.md](docs/FLUXOGRAMA_APLICACAO_0_9_4.md) | Todos os caminhos de consulta, decisão, atualização e restauração |
| [docs/GUIA_VERSAO_0_8.md](docs/GUIA_VERSAO_0_8.md) | Migração de banco, ativação de importações e mudanças da versão |
| [docs/matriz_conformidade_mcr_fno_fco.md](docs/matriz_conformidade_mcr_fno_fco.md) | Cobertura regulatória MCR, FNO e FCO |
| [docs/REFACTOR.md](docs/REFACTOR.md) | Contrato de comportamento e guia de refatoração |
| [AGENTS.md](AGENTS.md) | Convenções para desenvolvimento e contribuição |
