from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from database.schema import configure_import, initialize
from database.session import connect
from qgis_plugin_microcredito.application.backup_service import migrate_copy
from qgis_plugin_microcredito.application.geo_service import build_glebas_geojson
from qgis_plugin_microcredito.application.import_service import import_file
from qgis_plugin_microcredito.application.mte_service import import_mte
from qgis_plugin_microcredito.application.query_service import (
    find_by_car,
    find_by_document,
    find_documents_by_car,
    find_mma_mcr_by_car,
    find_operation_context,
    list_imports,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="car-microcredito", description="Núcleo de consulta CAR/Sicor"
    )
    parser.add_argument(
        "--db", default="dados/car_microcredito.db", help="Caminho do banco SQLite"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="Cria ou atualiza o banco")
    migration = sub.add_parser(
        "migrar-copia", help="Migra uma cópia nova; nunca altera a origem"
    )
    migration.add_argument("--origem", required=True)
    migration.add_argument("--destino", required=True)
    activate = sub.add_parser(
        "ativar-importacao",
        help="Define explicitamente o escopo de uma edição histórica",
    )
    activate.add_argument("id", type=int)
    activate.add_argument("--escopo", required=True)
    activate.add_argument("--validade-ate")

    importer = sub.add_parser("import-sicor", help="Importa arquivos públicos do Sicor")
    importer.add_argument("--mutuarios", required=True)
    importer.add_argument("--propriedades", required=True)
    importer.add_argument("--operacoes")
    importer.add_argument("--complementos")
    importer.add_argument("--glebas")
    importer.add_argument(
        "--escopo",
        required=True,
        help="Competência e abrangência, por exemplo 2026-08-nacional",
    )
    mma_importer = sub.add_parser(
        "import-mma-mcr", help="Importa a lista oficial do MMA para atendimento ao MCR"
    )
    mma_importer.add_argument("--arquivo", required=True)
    mma_importer.add_argument("--validade-ate", required=True)
    mte_importer = sub.add_parser(
        "import-mte", help="Importa a publicação MTE de trabalho escravo"
    )
    mte_importer.add_argument("--arquivo", required=True)
    mte_importer.add_argument("--validade-ate", required=True)

    by_document = sub.add_parser(
        "buscar-documento", help="Busca CAR candidatos por CPF/CNPJ"
    )
    by_document.add_argument("documento")
    by_document.add_argument("--json", action="store_true")

    by_car = sub.add_parser("buscar-car", help="Busca evidências pelo número do CAR")
    by_car.add_argument("car")
    by_car.add_argument("--json", action="store_true")
    by_car_docs = sub.add_parser(
        "buscar-documentos-car", help="Retorna CPF/CNPJ vinculados ao CAR no Sicor"
    )
    by_car_docs.add_argument("car")
    by_car_docs.add_argument("--json", action="store_true")
    operation = sub.add_parser(
        "buscar-operacao", help="Mostra contexto e cobertura geográfica da operação"
    )
    operation.add_argument("ref_bacen")
    operation.add_argument("nu_ordem")
    operation.add_argument("--json", action="store_true")
    exporter = sub.add_parser(
        "exportar-glebas", help="Exporta as glebas de uma operação em GeoJSON"
    )
    exporter.add_argument("ref_bacen")
    exporter.add_argument("nu_ordem")
    exporter.add_argument("--saida", required=True)
    mma_query = sub.add_parser(
        "consultar-mma-mcr", help="Consulta um CAR na publicação oficial do MMA"
    )
    mma_query.add_argument("car")
    mma_query.add_argument("--json", action="store_true")
    sub.add_parser("status", help="Mostra as importações realizadas")
    return parser


def _print_rows(rows: list[dict[str, object]], as_json: bool) -> None:
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        print("Nenhum vínculo localizado nas bases importadas.")
        return
    headers = list(rows[0])
    widths = {
        header: max(len(header), *(len(str(row.get(header, ""))) for row in rows))
        for header in headers
    }
    print(" | ".join(header.ljust(widths[header]) for header in headers))
    print("-+-".join("-" * widths[header] for header in headers))
    for row in rows:
        print(
            " | ".join(
                str(row.get(header, "")).ljust(widths[header]) for header in headers
            )
        )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    connection = None
    try:
        if args.command == "migrar-copia":
            print(migrate_copy(args.origem, args.destino))
            return 0
        administrative = args.command in {
            "init-db",
            "import-sicor",
            "import-mma-mcr",
            "import-mte",
            "ativar-importacao",
        }
        connection = connect(args.db, readonly=not administrative)
        if administrative:
            initialize(connection)
        if args.command == "init-db":
            print(f"Banco pronto: {Path(args.db).resolve()}")
        elif args.command == "ativar-importacao":
            configure_import(connection, args.id, args.escopo, args.validade_ate)
            print("Edição ativada no escopo informado.")
        elif args.command == "import-sicor":
            inputs = (
                ("mutuarios", args.mutuarios),
                ("propriedades", args.propriedades),
                ("operacoes", args.operacoes),
                ("complementos", args.complementos),
                ("glebas", args.glebas),
            )
            connection.execute("BEGIN IMMEDIATE")
            messages = []
            try:
                for tipo, path in inputs:
                    if path:
                        result = import_file(
                            connection, tipo, path, escopo=args.escopo, commit=False
                        )
                        messages.append(
                            f"{tipo}: {result.validas} válidas; {result.rejeitadas} rejeitadas"
                        )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            print("\n".join(messages), flush=True)
        elif args.command == "buscar-documento":
            _print_rows(find_by_document(connection, args.documento), args.json)
        elif args.command == "buscar-car":
            _print_rows(find_by_car(connection, args.car), args.json)
        elif args.command == "buscar-documentos-car":
            _print_rows(find_documents_by_car(connection, args.car), args.json)
        elif args.command == "buscar-operacao":
            operation = find_operation_context(
                connection, args.ref_bacen, args.nu_ordem
            )
            _print_rows([operation] if operation else [], args.json)
        elif args.command == "exportar-glebas":
            collection = build_glebas_geojson(connection, args.ref_bacen, args.nu_ordem)
            output = Path(args.saida)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                f"GeoJSON criado: {output.resolve()} "
                f"({collection['metadata']['poligonos_validos']} polígonos válidos)"
            )
        elif args.command == "import-mma-mcr":
            result = import_file(
                connection, "mma_mcr", args.arquivo, validade_ate=args.validade_ate
            )
            state = "já importado" if result.ignorado else "importado"
            print(
                f"mma_mcr: {state}; {result.validas} válidas; {result.rejeitadas} rejeitadas"
            )
        elif args.command == "import-mte":
            total = import_mte(connection, args.arquivo, validade_ate=args.validade_ate)
            print(f"Publicação MTE validada: {total} registros.")
        elif args.command == "consultar-mma-mcr":
            results = find_mma_mcr_by_car(connection, args.car)
            if not results:
                results = [
                    {
                        "car": args.car,
                        "situacao": "nao_localizado_na_publicacao_mma",
                        "observacao": (
                            "A ausência nesta lista não comprova regularidade "
                            "nem situação atual do CAR."
                        ),
                    }
                ]
            _print_rows(results, args.json)
        elif args.command == "status":
            _print_rows(list_imports(connection), False)
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    finally:
        if connection is not None:
            connection.close()
