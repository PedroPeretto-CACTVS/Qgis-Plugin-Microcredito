import sqlite3

from database.repositories import find_fiscal_module
from database.schema import SCHEMA_VERSION, initialize
from qgis_plugin_microcredito.domain.fiscal_modules import (
    EXPECTED_MUNICIPALITIES,
    assess_car_fiscal_modules,
    assess_fiscal_modules,
    fiscal_module_sizes,
    municipality_code_from_car,
)


def test_official_catalog_has_all_municipalities_and_current_examples():
    values = fiscal_module_sizes()

    assert len(values) == EXPECTED_MUNICIPALITIES == 5_571
    assert values["1100015"] == 60
    assert values["1200013"] == 100
    assert values["2700102"] == 70
    assert values["5101837"] == 90


def test_municipality_code_is_read_from_formatted_or_normalized_car():
    assert municipality_code_from_car("AC-1200013-abc") == "1200013"
    assert municipality_code_from_car("AC1200013abc") == "1200013"
    assert municipality_code_from_car("CAR inválido") == ""


def test_exactly_four_modules_meets_only_the_territorial_criterion():
    result = assess_fiscal_modules("AC-1200013-abc", "400,00", "4")

    assert result.status == "atende_limite"
    assert result.module_size_ha == "100"
    assert result.module_count == "4"
    assert result.four_modules_ha == "400"
    assert result.family_farming_qualification.startswith("não determinada")


def test_area_above_four_modules_does_not_meet_general_limit():
    result = assess_fiscal_modules("AL-2700102-abc", 280.01)

    assert result.status == "nao_atende_limite"
    assert result.module_size_ha == "70"
    assert result.module_count == "4.0001"


def test_official_calculation_flags_divergent_declared_module_count():
    result = assess_fiscal_modules("AC-1200013-abc", 200, "3")

    assert result.module_count == "2"
    assert "diverge" in result.consistency_note
    assert "diverge" in result.rationale


def test_declared_module_count_is_fallback_when_official_lookup_is_impossible():
    result = assess_fiscal_modules("CAR sem código", None, "3,5")

    assert result.status == "atende_limite"
    assert result.module_count == "3.5"
    assert result.module_size_ha == ""


def test_missing_area_and_module_count_is_inconclusive():
    result = assess_fiscal_modules("CAR sem código", None)

    assert result.status == "nao_verificado"
    assert "Não foi possível" in result.status_label


def test_mma_record_is_used_when_local_sicar_attributes_are_unavailable():
    result = assess_car_fiscal_modules(
        "AL-2700102-abc",
        {},
        [{"area_total_ha": "140", "codigo_municipio": "2700102"}],
    )

    assert result["status"] == "atende_limite"
    assert result["module_count"] == "2"
    assert result["property_data_source"] == "Publicação MMA/MCR"


def test_schema_seeds_official_fiscal_module_table():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        initialize(connection)

        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert (
            connection.execute("SELECT count(*) FROM incra_modulo_fiscal").fetchone()[0]
            == EXPECTED_MUNICIPALITIES
        )
        row = find_fiscal_module(connection, "5101837")
        assert row["modulo_fiscal_ha"] == 90
        assert "INCRA" in row["norma_fonte"]
    finally:
        connection.close()
