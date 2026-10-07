import copy
import unittest

from qgis_plugin_microcredito.application.pre_analysis import (
    INCONCLUSIVE,
    POSSIBLE_IMPEDIMENT,
    TECHNICAL_REVIEW,
    build_pre_analysis,
)


def analysis_with(
    layer, mma="sem_ocorrencia_identificada", mte="sem_ocorrencia_identificada"
):
    return {
        "resultado_fontes": {"mma_mcr": mma, "mte": mte},
        "ambiental": {"resultado_geral": layer.get("resultado"), "camadas": [layer]},
    }


def analysis_with_identity():
    analysis = analysis_with(
        {
            "codigo": "embargos",
            "resultado": "sem_ocorrencia_identificada",
            "ocorrencias": [],
            "sha256_conjunto_fonte": "ambiental-v1",
        }
    )
    analysis.update(
        {
            "car": "PA-1500800-IDENTIDADE",
            "documentos_consultados_mte": ["12345678901", "11222333000181"],
            "evidencia_geometria": {"sha256": "geometria-v1"},
            "mma_fonte": {"sha256": "mma-v1"},
            "mte_fonte": {"sha256": "mte-v1"},
            "importacoes_sicor_mma": [
                {"tipo": "sicor", "escopo": "operacoes", "sha256": "sicor-v1"},
                {"tipo": "mma_mcr", "escopo": "nacional", "sha256": "mma-v1"},
            ],
        }
    )
    return analysis


class PreAnalysisTests(unittest.TestCase):
    def test_fingerprint_changes_when_consulted_evidence_identity_changes(self):
        original = analysis_with_identity()
        original_hash = build_pre_analysis(original)["sha256"]
        changes = {
            "car": lambda item: item.update({"car": "PA-1500800-OUTRO-CAR"}),
            "documento MTE": lambda item: item.update(
                {"documentos_consultados_mte": ["98765432100"]}
            ),
            "geometria": lambda item: item["evidencia_geometria"].update(
                {"sha256": "geometria-v2"}
            ),
            "publicação MMA": lambda item: item["mma_fonte"].update(
                {"sha256": "mma-v2"}
            ),
            "publicação MTE": lambda item: item["mte_fonte"].update(
                {"sha256": "mte-v2"}
            ),
            "edição ativa": lambda item: item["importacoes_sicor_mma"][0].update(
                {"sha256": "sicor-v2"}
            ),
            "camada ambiental": lambda item: item["ambiental"]["camadas"][0].update(
                {"sha256_conjunto_fonte": "ambiental-v2"}
            ),
        }

        for label, change in changes.items():
            with self.subTest(label=label):
                changed = copy.deepcopy(original)
                change(changed)
                self.assertNotEqual(
                    build_pre_analysis(changed)["sha256"], original_hash
                )

    def test_fingerprint_ignores_order_and_local_import_metadata(self):
        original = analysis_with_identity()
        equivalent = copy.deepcopy(original)
        equivalent["documentos_consultados_mte"].reverse()
        equivalent["importacoes_sicor_mma"].reverse()
        equivalent["importacoes_sicor_mma"][0].update(
            {
                "arquivo": "C:/outro/local/base.csv",
                "importado_em": "2099-01-01T00:00:00",
                "id": 999,
            }
        )

        self.assertEqual(
            build_pre_analysis(original)["sha256"],
            build_pre_analysis(equivalent)["sha256"],
        )

    def test_type_b_forest_is_possible_impediment_with_exception_checklist(self):
        result = build_pre_analysis(
            analysis_with(
                {
                    "codigo": "florestas_publicas",
                    "fonte": "Florestas públicas",
                    "resultado": "ocorrencia_para_analise",
                    "area_sobreposta_ha": 12.5,
                    "ocorrencias": [
                        {
                            "atributos": {
                                "tipo": "TIPO B",
                                "categoria": "GLEBA ARRECADADA",
                            }
                        }
                    ],
                }
            )
        )
        forest = result["regras"][-1]
        self.assertEqual(forest["classificacao"], POSSIBLE_IMPEDIMENT)
        self.assertIn("matrícula", forest["providencia_tecnica"])
        self.assertIn("15 módulos fiscais", forest["providencia_tecnica"])
        self.assertEqual(result["classificacao_geral"], POSSIBLE_IMPEDIMENT)
        self.assertEqual(len(result["sha256"]), 64)
        self.assertEqual(
            result["sha256"],
            build_pre_analysis(
                analysis_with(
                    {
                        "codigo": "florestas_publicas",
                        "fonte": "Florestas públicas",
                        "resultado": "ocorrencia_para_analise",
                        "area_sobreposta_ha": 12.5,
                        "ocorrencias": [
                            {
                                "atributos": {
                                    "tipo": "TIPO B",
                                    "categoria": "GLEBA ARRECADADA",
                                }
                            }
                        ],
                    }
                )
            )["sha256"],
        )

    def test_type_a_does_not_trigger_type_b_impediment(self):
        result = build_pre_analysis(
            analysis_with(
                {
                    "codigo": "florestas_publicas",
                    "fonte": "Florestas públicas",
                    "resultado": "ocorrencia_para_analise",
                    "ocorrencias": [
                        {"atributos": {"tipo": "TIPO A", "categoria": "PA"}}
                    ],
                }
            )
        )
        forest = result["regras"][-1]
        self.assertEqual(forest["classificacao"], TECHNICAL_REVIEW)
        self.assertIn("não como Tipo B", forest["fundamento_resultado"])

    def test_forest_overlap_without_type_is_inconclusive(self):
        result = build_pre_analysis(
            analysis_with(
                {
                    "codigo": "florestas_publicas",
                    "resultado": "ocorrencia_para_analise",
                    "ocorrencias": [{"atributos": {"categoria": "Não informada"}}],
                }
            )
        )
        self.assertEqual(result["regras"][-1]["classificacao"], INCONCLUSIVE)

    def test_clear_post_2020_deforestation_layer_does_not_claim_full_coverage(self):
        result = build_pre_analysis(
            analysis_with(
                {
                    "codigo": "desmatamento_pos_2020",
                    "resultado": "sem_ocorrencia_identificada",
                    "ocorrencias": [],
                }
            )
        )
        rule = result["regras"][-1]
        self.assertEqual(rule["classificacao"], INCONCLUSIVE)
        self.assertIn("31/07/2019", rule["fundamento_resultado"])

    def test_clear_sources_still_require_fno_fco_technical_validation(self):
        result = build_pre_analysis(
            analysis_with(
                {
                    "codigo": "embargos",
                    "resultado": "sem_ocorrencia_identificada",
                    "ocorrencias": [],
                }
            )
        )
        self.assertEqual(result["classificacao_geral"], TECHNICAL_REVIEW)
        fund_rule = next(
            item
            for item in result["regras"]
            if item["codigo"] == "fundos_constitucionais"
        )
        self.assertIn("fonte de recursos", fund_rule["fundamento_resultado"].lower())
        self.assertIn("não aprovação", result["resumo"])
        self.assertIn("decisão", result["resumo"])

    def test_ogu_and_fixed_pronaf_line_are_explained_as_structured_inputs(self):
        analysis = analysis_with(
            {
                "codigo": "embargos",
                "resultado": "sem_ocorrencia_identificada",
                "ocorrencias": [],
            }
        )
        analysis.update(
            {
                "fundo_constitucional": "OGU",
                "programa_financiamento": "Pronaf B para mulheres",
            }
        )
        result = build_pre_analysis(analysis)
        fund_rule = next(
            item
            for item in result["regras"]
            if item["codigo"] == "fundos_constitucionais"
        )
        self.assertEqual(fund_rule["classificacao"], TECHNICAL_REVIEW)
        self.assertIn("OGU", fund_rule["fundamento_resultado"])
        self.assertIn("Pronaf B para mulheres", fund_rule["fundamento_resultado"])
        self.assertIn("norma aplicável ao OGU", fund_rule["referencia"])

    def test_automatic_resource_source_is_identified_as_suggestion_to_confirm(self):
        analysis = analysis_with(
            {
                "codigo": "embargos",
                "resultado": "sem_ocorrencia_identificada",
                "ocorrencias": [],
            }
        )
        analysis.update(
            {
                "fundo_constitucional": "FNO",
                "fonte_recursos_modo": "sugerida_pela_uf",
                "fonte_recursos_uf": "PA",
                "programa_financiamento": "Pronaf B",
            }
        )
        result = build_pre_analysis(analysis)
        fund_rule = next(
            item
            for item in result["regras"]
            if item["codigo"] == "fundos_constitucionais"
        )
        self.assertIn("UF PA", fund_rule["fundamento_resultado"])
        self.assertIn("confirmada pelo técnico", fund_rule["fundamento_resultado"])

    def test_fiscal_module_rule_never_declares_family_farmer_automatically(self):
        analysis = analysis_with(
            {
                "codigo": "embargos",
                "resultado": "sem_ocorrencia_identificada",
                "ocorrencias": [],
            }
        )
        analysis["modulo_fiscal"] = {
            "status": "atende_limite",
            "rationale": "O CAR corresponde a 2 módulos fiscais.",
            "technical_action": "Validar CAF e os demais requisitos.",
            "source_rule": "IE INCRA nº 6/2025",
        }

        result = build_pre_analysis(analysis)

        rule = next(
            item
            for item in result["regras"]
            if item["codigo"] == "modulo_fiscal_agricultura_familiar"
        )
        self.assertEqual(rule["classificacao"], TECHNICAL_REVIEW)
        self.assertIn("apenas um dos requisitos", rule["entendimento_regra"])
        self.assertIn("CAF", rule["providencia_tecnica"])


if __name__ == "__main__":
    unittest.main()
