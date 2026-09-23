"""Schema v3 bootstrap, v2 import table migration, and import activation."""

from __future__ import annotations

import sqlite3
from datetime import date

SCHEMA_VERSION = 3

# Pre-v3 CREATE script used to reconstruct historical files in tests.
SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS importacao (
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL CHECK (tipo IN (
        'mutuarios', 'propriedades', 'operacoes', 'complementos', 'glebas', 'mma_mcr'
    )),
    arquivo TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    importado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_linhas INTEGER NOT NULL DEFAULT 0,
    linhas_validas INTEGER NOT NULL DEFAULT 0,
    linhas_rejeitadas INTEGER NOT NULL DEFAULT 0,
    UNIQUE (tipo, sha256)
);

CREATE TABLE IF NOT EXISTS sicor_mutuario (
    id INTEGER PRIMARY KEY,
    importacao_id INTEGER NOT NULL REFERENCES importacao(id) ON DELETE CASCADE,
    ref_bacen TEXT NOT NULL,
    documento_original TEXT,
    documento_normalizado TEXT,
    documento_mascarado INTEGER NOT NULL DEFAULT 0,
    tipo_beneficiario TEXT,
    dap_caf TEXT
);

CREATE TABLE IF NOT EXISTS sicor_propriedade (
    id INTEGER PRIMARY KEY,
    importacao_id INTEGER NOT NULL REFERENCES importacao(id) ON DELETE CASCADE,
    ref_bacen TEXT NOT NULL,
    nu_ordem TEXT,
    documento_original TEXT,
    documento_normalizado TEXT,
    documento_mascarado INTEGER NOT NULL DEFAULT 0,
    car_original TEXT,
    car_normalizado TEXT,
    sncr TEXT,
    nirf_cib TEXT
);

CREATE TABLE IF NOT EXISTS sicor_operacao (
    id INTEGER PRIMARY KEY,
    importacao_id INTEGER NOT NULL REFERENCES importacao(id) ON DELETE CASCADE,
    ref_bacen TEXT NOT NULL,
    nu_ordem TEXT NOT NULL,
    data_emissao TEXT,
    data_vencimento TEXT,
    cnpj_if TEXT,
    estado TEXT,
    fonte_recurso TEXT,
    empreendimento TEXT,
    programa TEXT,
    subprograma TEXT,
    area_financiada TEXT,
    area_informada TEXT,
    bonus_car TEXT
);

CREATE TABLE IF NOT EXISTS sicor_complemento_operacao (
    id INTEGER PRIMARY KEY,
    importacao_id INTEGER NOT NULL REFERENCES importacao(id) ON DELETE CASCADE,
    ref_bacen TEXT NOT NULL,
    nu_ordem TEXT NOT NULL,
    ref_bacen_efetivo TEXT,
    agencia_if TEXT,
    municipio_ibge TEXT,
    numero_cedula_if TEXT
);

CREATE TABLE IF NOT EXISTS sicor_ponto_gleba (
    id INTEGER PRIMARY KEY,
    importacao_id INTEGER NOT NULL REFERENCES importacao(id) ON DELETE CASCADE,
    ref_bacen TEXT NOT NULL,
    nu_ordem TEXT NOT NULL,
    identificador TEXT,
    indice_gleba INTEGER,
    indice_ponto INTEGER,
    latitude REAL,
    longitude REAL,
    altitude TEXT,
    id_ponto TEXT
);

CREATE TABLE IF NOT EXISTS sicor_gleba_wkt (
    id INTEGER PRIMARY KEY,
    importacao_id INTEGER NOT NULL REFERENCES importacao(id) ON DELETE CASCADE,
    ref_bacen TEXT NOT NULL,
    nu_ordem TEXT NOT NULL,
    indice_gleba INTEGER,
    geometria_wkt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mma_mcr (
    id INTEGER PRIMARY KEY,
    importacao_id INTEGER NOT NULL REFERENCES importacao(id) ON DELETE CASCADE,
    car_original TEXT NOT NULL,
    car_normalizado TEXT NOT NULL,
    status_imovel TEXT,
    condicao TEXT,
    data_atualizacao TEXT,
    area_declarada TEXT,
    area_total_ha TEXT,
    modulos_fiscais TEXT,
    uf TEXT,
    municipio TEXT,
    codigo_municipio TEXT,
    tipo_imovel TEXT,
    julgamento_status TEXT,
    soma_desmatamento TEXT,
    dentro_criterio TEXT,
    criterio_aplicado TEXT,
    resultados TEXT,
    bioma TEXT
);

CREATE TABLE IF NOT EXISTS trabalho_escravo (
    id INTEGER PRIMARY KEY,
    identificador_fonte TEXT,
    documento_original TEXT NOT NULL,
    documento_normalizado TEXT NOT NULL,
    empregador TEXT,
    uf TEXT,
    estabelecimento TEXT,
    ano_acao_fiscal TEXT,
    trabalhadores_envolvidos TEXT,
    cnae TEXT,
    decisao_procedencia TEXT,
    inclusao_cadastro TEXT,
    fonte_url TEXT NOT NULL,
    arquivo_fonte TEXT NOT NULL,
    importado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (identificador_fonte, documento_normalizado, inclusao_cadastro)
);

CREATE TABLE IF NOT EXISTS mte_publicacao (
    id INTEGER PRIMARY KEY,
    sha256 TEXT NOT NULL,
    arquivo_fonte TEXT NOT NULL,
    fonte_url TEXT NOT NULL,
    importado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_registros INTEGER NOT NULL,
    validade_ate TEXT NOT NULL
);
"""

INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_importacao_ativa ON importacao(tipo, escopo, ativo)",
    "CREATE INDEX IF NOT EXISTS ix_mutuario_documento ON sicor_mutuario(documento_normalizado)",
    "CREATE INDEX IF NOT EXISTS ix_mutuario_ref ON sicor_mutuario(ref_bacen)",
    "CREATE INDEX IF NOT EXISTS ix_propriedade_documento ON sicor_propriedade(documento_normalizado)",
    "CREATE INDEX IF NOT EXISTS ix_propriedade_car ON sicor_propriedade(car_normalizado)",
    "CREATE INDEX IF NOT EXISTS ix_propriedade_ref ON sicor_propriedade(ref_bacen)",
    "CREATE INDEX IF NOT EXISTS ix_operacao_chave ON sicor_operacao(ref_bacen, nu_ordem)",
    "CREATE INDEX IF NOT EXISTS ix_complemento_chave ON sicor_complemento_operacao(ref_bacen, nu_ordem)",
    "CREATE INDEX IF NOT EXISTS ix_gleba_chave ON sicor_ponto_gleba(ref_bacen, nu_ordem, indice_gleba, indice_ponto)",
    "CREATE INDEX IF NOT EXISTS ix_gleba_wkt_chave ON sicor_gleba_wkt(ref_bacen, nu_ordem, indice_gleba)",
    "CREATE INDEX IF NOT EXISTS ix_mma_mcr_car ON mma_mcr(car_normalizado)",
    "CREATE INDEX IF NOT EXISTS ix_trabalho_escravo_documento ON trabalho_escravo(documento_normalizado)",
)

ACTIVE_VIEW_TABLES = (
    "sicor_mutuario",
    "sicor_propriedade",
    "sicor_operacao",
    "sicor_complemento_operacao",
    "sicor_ponto_gleba",
    "sicor_gleba_wkt",
    "mma_mcr",
)

IMPORT_TABLE_V2 = """
CREATE TABLE importacao_nova (
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL CHECK (tipo IN (
        'mutuarios', 'propriedades', 'operacoes', 'complementos', 'glebas', 'mma_mcr'
    )),
    arquivo TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    importado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_linhas INTEGER NOT NULL DEFAULT 0,
    linhas_validas INTEGER NOT NULL DEFAULT 0,
    linhas_rejeitadas INTEGER NOT NULL DEFAULT 0,
    UNIQUE (tipo, sha256)
)
"""


def configure_import(
    connection: sqlite3.Connection,
    import_id: int,
    escopo: str,
    validade_ate: str | None = None,
) -> None:
    if validade_ate:
        date.fromisoformat(validade_ate)
    row = connection.execute(
        "SELECT * FROM importacao WHERE id = ?", (import_id,)
    ).fetchone()
    if (
        not row
        or not escopo.strip()
        or row["linhas_validas"] <= 0
        or row["linhas_rejeitadas"]
    ):
        raise ValueError(
            "Só é possível ativar carga validada, sem rejeições e com escopo definido."
        )
    if row["tipo"] == "mma_mcr" and (escopo != "nacional" or not validade_ate):
        raise ValueError("A edição MMA exige escopo nacional e validade aprovada.")
    with connection:
        connection.execute(
            "UPDATE importacao SET ativo = 0 WHERE tipo = ? AND escopo = ?",
            (row["tipo"], escopo),
        )
        connection.execute(
            "UPDATE importacao SET escopo = ?, ativo = 1, validade_ate = ? WHERE id = ?",
            (escopo, validade_ate, import_id),
        )


def _migrate_import_table(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'importacao'"
    ).fetchone()
    if not row or "mma_mcr" in (row["sql"] or ""):
        return
    connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(IMPORT_TABLE_V2)
        connection.execute(
            """INSERT INTO importacao_nova
               (id, tipo, arquivo, sha256, importado_em, total_linhas,
                linhas_validas, linhas_rejeitadas)
               SELECT id, tipo, arquivo, sha256, importado_em, total_linhas,
                      linhas_validas, linhas_rejeitadas
                 FROM importacao"""
        )
        connection.execute("DROP TABLE importacao")
        connection.execute("ALTER TABLE importacao_nova RENAME TO importacao")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def _create_active_views(connection: sqlite3.Connection) -> None:
    for table in ACTIVE_VIEW_TABLES:
        connection.execute(
            f"""CREATE VIEW IF NOT EXISTS ativo_{table} AS
            SELECT t.* FROM {table} t JOIN importacao i ON i.id = t.importacao_id
            WHERE i.ativo = 1"""
        )


def _create_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)


def _create_indexes(connection: sqlite3.Connection) -> None:
    for statement in INDEXES:
        connection.execute(statement)


def initialize(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise ValueError(
            "Banco criado por uma versão mais nova; não é seguro migrá-lo."
        )
    _migrate_import_table(connection)
    _create_tables(connection)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(importacao)")}
    if "escopo" not in columns:
        connection.execute(
            "ALTER TABLE importacao ADD COLUMN escopo TEXT NOT NULL DEFAULT 'nacional'"
        )
        connection.execute(
            "ALTER TABLE importacao ADD COLUMN ativo INTEGER NOT NULL DEFAULT 1 "
            "CHECK(ativo IN (0,1))"
        )
        connection.execute("ALTER TABLE importacao ADD COLUMN validade_ate TEXT")
        connection.execute("UPDATE importacao SET ativo = 0, escopo = 'legado:' || id")
    _create_indexes(connection)
    _create_active_views(connection)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.execute(
        """UPDATE sicor_propriedade SET car_normalizado = ''
             WHERE trim(upper(coalesce(car_original, ''))) IN
                   ('', '-1', '0', 'N/A', 'NA', 'NULL', 'NONE')
               AND car_normalizado <> ''"""
    )
    connection.commit()
