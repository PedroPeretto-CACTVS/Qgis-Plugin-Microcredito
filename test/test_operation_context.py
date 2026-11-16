from __future__ import annotations

import sqlite3
import unittest

from database.schema import initialize
from qgis_plugin_microcredito.application.query_service import find_operation_context


class OperationContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        initialize(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def _import_id(self, kind: str, *, active: bool = True) -> int:
        cursor = self.db.execute(
            """INSERT INTO importacao (tipo, arquivo, sha256, ativo)
               VALUES (?, 'synthetic.csv', ?, ?)""",
            (kind, f"synthetic-{kind}-{self.db.total_changes}", int(active)),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def test_context_lookup_does_not_scan_unrelated_complements(self) -> None:
        operation = self._import_id("operacoes")
        complement = self._import_id("complementos")
        self.db.execute(
            """INSERT INTO sicor_operacao
               (importacao_id, ref_bacen, nu_ordem, estado)
               VALUES (?, 'TARGET', '1', 'XX')""",
            (operation,),
        )
        self.db.executemany(
            """INSERT INTO sicor_complemento_operacao
               (importacao_id, ref_bacen, nu_ordem, municipio_ibge)
               VALUES (?, ?, '1', '0000000')""",
            ((complement, f"UNRELATED-{index}") for index in range(20_000)),
        )
        self.db.execute(
            """INSERT INTO sicor_complemento_operacao
               (importacao_id, ref_bacen, nu_ordem, municipio_ibge)
               VALUES (?, 'TARGET', '1', '1111111')""",
            (complement,),
        )
        steps = 0

        def stop_unbounded_query() -> int:
            nonlocal steps
            steps += 100
            return int(steps >= 10_000)

        self.db.set_progress_handler(stop_unbounded_query, 100)
        try:
            context = find_operation_context(self.db, "TARGET", "1")
        finally:
            self.db.set_progress_handler(None, 0)

        self.assertEqual(context["municipio_ibge"], "1111111")
        self.assertEqual(context["estado"], "XX")
        self.assertEqual(context["total_glebas"], 0)
        self.assertEqual(context["total_pontos"], 0)

    def test_context_uses_latest_active_operation_and_matching_active_data(
        self,
    ) -> None:
        operation = self._import_id("operacoes")
        inactive_operation = self._import_id("operacoes", active=False)
        complement = self._import_id("complementos")
        inactive_complement = self._import_id("complementos", active=False)
        plots = self._import_id("glebas")
        inactive_plots = self._import_id("glebas", active=False)
        self.db.executemany(
            """INSERT INTO sicor_operacao
               (importacao_id, ref_bacen, nu_ordem, estado)
               VALUES (?, 'TARGET', '1', ?)""",
            ((operation, "OLD"), (operation, "NEW"), (inactive_operation, "INACTIVE")),
        )
        self.db.executemany(
            """INSERT INTO sicor_complemento_operacao
               (importacao_id, ref_bacen, nu_ordem,
                municipio_ibge, agencia_if, ref_bacen_efetivo)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                (inactive_complement, "TARGET", "1", "0000000", "old", "old"),
                (complement, "TARGET", "2", "2222222", "other-order", "other"),
                (complement, "OTHER", "1", "3333333", "other-ref", "other"),
                (complement, "TARGET", "1", "1111111", "agency", "effective"),
            ),
        )
        self.db.executemany(
            """INSERT INTO sicor_ponto_gleba
               (importacao_id, ref_bacen, nu_ordem, indice_gleba)
               VALUES (?, ?, ?, ?)""",
            (
                (plots, "TARGET", "1", 1),
                (plots, "TARGET", "1", 1),
                (plots, "TARGET", "1", 2),
                (plots, "TARGET", "1", None),
                (plots, "TARGET", "2", 3),
                (plots, "OTHER", "1", 4),
                (inactive_plots, "TARGET", "1", 5),
            ),
        )
        self.db.executemany(
            """INSERT INTO sicor_gleba_wkt
               (importacao_id, ref_bacen, nu_ordem, indice_gleba, geometria_wkt)
               VALUES (?, ?, ?, ?, 'POLYGON ((0 0,1 0,1 1,0 0))')""",
            (
                (plots, "TARGET", "1", 0),
                (plots, "TARGET", "1", 1),
                (plots, "TARGET", "2", 2),
                (plots, "OTHER", "1", 3),
                (inactive_plots, "TARGET", "1", 4),
            ),
        )

        context = find_operation_context(self.db, "TARGET", "1")

        self.assertEqual(context["estado"], "NEW")
        self.assertEqual(context["importacao_id"], operation)
        self.assertEqual(context["municipio_ibge"], "1111111")
        self.assertEqual(context["agencia_if"], "agency")
        self.assertEqual(context["ref_bacen_efetivo"], "effective")
        self.assertEqual(context["total_glebas"], 4)
        self.assertEqual(context["total_pontos"], 4)

    def test_context_preserves_operation_without_complement_and_missing_key(
        self,
    ) -> None:
        operation = self._import_id("operacoes")
        complement = self._import_id("complementos")
        self.db.execute(
            """INSERT INTO sicor_operacao
               (importacao_id, ref_bacen, nu_ordem, estado)
               VALUES (?, 'TARGET', '1', 'XX')""",
            (operation,),
        )
        self.db.execute(
            """INSERT INTO sicor_complemento_operacao
               (importacao_id, ref_bacen, nu_ordem, municipio_ibge)
               VALUES (?, 'TARGET', '2', '2222222')""",
            (complement,),
        )

        context = find_operation_context(self.db, "TARGET", "1")

        self.assertEqual(context["estado"], "XX")
        self.assertIsNone(context["municipio_ibge"])
        self.assertIsNone(context["agencia_if"])
        self.assertIsNone(context["ref_bacen_efetivo"])
        self.assertEqual(context["total_glebas"], 0)
        self.assertEqual(context["total_pontos"], 0)
        self.assertEqual(find_operation_context(self.db, "MISSING", "1"), {})
        self.assertEqual(find_operation_context(self.db, "TARGET", "2"), {})

    def test_duplicate_complements_return_one_complete_matching_row(self) -> None:
        operation = self._import_id("operacoes")
        complement = self._import_id("complementos")
        self.db.execute(
            """INSERT INTO sicor_operacao
               (importacao_id, ref_bacen, nu_ordem, estado)
               VALUES (?, 'TARGET', '1', 'XX')""",
            (operation,),
        )
        self.db.executemany(
            """INSERT INTO sicor_complemento_operacao
               (importacao_id, ref_bacen, nu_ordem,
                municipio_ibge, agencia_if, ref_bacen_efetivo)
               VALUES (?, 'TARGET', '1', ?, ?, ?)""",
            (
                (complement, "1111111", "first-agency", "first-effective"),
                (complement, "1111111", "first-agency", "first-effective"),
                (complement, "2222222", "second-agency", "second-effective"),
            ),
        )

        context = find_operation_context(self.db, "TARGET", "1")

        self.assertEqual(context["estado"], "XX")
        self.assertIn(
            (
                context["municipio_ibge"],
                context["agencia_if"],
                context["ref_bacen_efetivo"],
            ),
            {
                ("1111111", "first-agency", "first-effective"),
                ("2222222", "second-agency", "second-effective"),
            },
        )
        self.assertEqual(context["total_glebas"], 0)
        self.assertEqual(context["total_pontos"], 0)
