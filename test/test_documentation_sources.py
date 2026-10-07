from pathlib import Path

MATRIX = (
    Path(__file__).resolve().parents[1] / "docs" / "matriz_conformidade_mcr_fno_fco.md"
)


def test_fco_matrix_references_current_official_editions():
    text = MATRIX.read_text(encoding="utf-8")

    assert "Atualização: 29/09/2026" in text
    assert "programacao_fco_2026_9a-ed.pdf" in text
    assert "cartilha-fco-2026-v6-03-09-2026.pdf" in text
    assert "encargos de inadimplemento" in text
    assert "Programacao_FCO_2026_3ED_jp.pdf" not in text
    assert "CartilhaFCO2026v424Mar2026compactada.pdf" not in text
