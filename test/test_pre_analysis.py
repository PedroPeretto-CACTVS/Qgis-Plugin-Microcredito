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


class PreAnalysisTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
