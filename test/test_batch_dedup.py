from dataclasses import replace

from qgis_plugin_microcredito.application.batch_xlsx import batch_task_identity
from qgis_plugin_microcredito.domain.models import BatchRow


def test_batch_task_identity_preserves_financing_context():
    original = BatchRow(
        source_row=2,
        document="12345678901",
        car="MT-123",
        resource_source="FNO",
        credit_line="Pronaf B",
    )
    other_source = replace(original, source_row=3, resource_source="OGU")
    other_credit_line = replace(
        original,
        source_row=4,
        credit_line="Pronaf B para mulheres",
    )

    identities = {
        batch_task_identity(row, "MT123")
        for row in (original, other_source, other_credit_line)
    }

    assert len(identities) == 3


def test_batch_task_identity_deduplicates_same_analysis_context():
    original = BatchRow(
        source_row=2,
        document="12345678901",
        car="MT-123",
        resource_source="FNO",
        credit_line="Pronaf B",
    )
    repeated = replace(original, source_row=8, observation="linha repetida")

    assert batch_task_identity(original, "MT123") == batch_task_identity(
        repeated, "MT123"
    )
