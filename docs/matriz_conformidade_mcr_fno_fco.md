# Matriz de conformidade da triagem CAR - MCR, FNO e FCO

Atualização: 11/09/2026. Esta matriz descreve a cobertura da automação e deve ser revista quando o MCR ou as programações anuais forem alterados.

## Resultado da conferência

A automação cobre a identificação da operação no Sicor, a localização do CAR/gleba, a consulta da publicação MMA/MCR e cruzamentos com embargos do Ibama, terras indígenas, unidades de conservação, florestas públicas e PRODES. Ela produz evidência útil para triagem, mas ainda não pode declarar conformidade integral com o MCR nem autorizar a liberação do crédito sem revisão documental.

| Regra ou evidência | Cobertura atual | Tratamento correto |
|---|---|---|
| CAR e situação cadastral | Parcial | Localizar geometria e dados publicados; confirmar situação vigente no SICAR antes da decisão. |
| CPF/CNPJ associado ao CAR | Implementado | Retornar vínculo direto de `SICOR_PROPRIEDADES` e vínculo do mutuário pela mesma `REF_BACEN`, sempre com origem. Não declarar titularidade apenas por esse vínculo. |
| Embargos ambientais | Parcial | A interseção gera pendência. Confirmar vigência, órgão, alcance, atividade e exceções documentais. A base federal do Ibama não substitui bases estaduais e do ICMBio. |
| Terras indígenas | Parcial | Considerar também a área contínua usada na atividade financiada e verificar a condição do beneficiário e documentos aplicáveis. |
| Unidades de conservação | Parcial | Verificar categoria, plano de manejo, população tradicional e autorização. Sobreposição não é reprovação automática. |
| Floresta pública | Parcial | O MCR trata a floresta pública tipo B não destinada e prevê exceções. A camada não deve reprovar todas as florestas públicas indistintamente. |
| Supressão de vegetação | Parcial | A camada solicitada pelo projeto contém PRODES após 2020. Para MCR 2-9-17/18, a análise deve alcançar supressões posteriores a 31/07/2019 e aceitar os documentos de conformidade previstos no Sicor. |
| Territórios quilombolas | Parcial | A camada nacional Incra/Ibama está instalada; confirmar delimitação, área contínua, condição do beneficiário e exceções documentais. |
| Trabalho análogo ao escravo | Implementado para a lista federal | Consulta o cadastro vigente do MTE pelos CPF/CNPJ associados ao CAR e conserva arquivo, URL e data de importação. Em 11/09/2026 não havia camada geoespacial nacional oficial disponível: o Radar SIT informava estar temporariamente fora do ar e o CSV oficial contém estabelecimento textual, sem latitude/longitude. |
| Área contínua da atividade | Ausente | Receber ou produzir geometria da área efetivamente explorada, inclusive quando ultrapassar o limite de um CAR, nos casos previstos no MCR. |
| Monitoramento remoto | Ausente | Para operações alcançadas pela regra vigente desde 01/03/2026, manter monitoramento durante o crédito, inclusive compatibilidade da atividade, duplicidade, aplicação dos recursos, vegetação e, na pecuária, pastagem/instalações. |
| Exceções e documentos | Ausente | Criar checklist, anexação, validade, responsável pela conferência e decisão humana. |

## Regras dos fundos constitucionais

O FNO e o FCO rural usam recursos sujeitos aos impedimentos socioambientais do MCR. A origem do recurso deve ser identificada na operação do Sicor antes de escolher o checklist.

Para o FCO 2026, a Programação oficial exige cumprimento da legislação ambiental durante a vigência do financiamento, recibo de inscrição no CAR conforme o MCR em condições rurais aplicáveis, descrição das imposições ambientais e envio de licenças, outorgas, Certoh ou EIA/Rima quando existentes. Também deixa garantias, fiscalização, projeto técnico, assistência técnica, forma de pagamento e aspectos de liberação para a instituição financeira. Por isso, a Programação pública não substitui o manual operacional do agente.

A nova Programação FNO 2026 foi aprovada pela Resolução Condel/Sudam nº 141, de 23/02/2026. A conferência final do fluxo de liberação depende da versão integral vigente da Programação FNO 2026 e do manual/checklist da instituição operadora ou repassadora.

## Fluxo de decisão proposto

1. Identificar CPF/CNPJ, CAR, operação, ordem, fonte do recurso, programa, atividade e área financiada.
2. Resolver os vínculos CPF/CNPJ-CAR com tipo de vínculo e arquivo de origem.
3. Obter a geometria do CAR e a área contínua efetivamente usada pela atividade.
4. Consultar situação cadastral do CAR, publicação MMA/MCR e listas pessoais vigentes.
5. Executar os cruzamentos territoriais com data e versão de cada base.
6. Classificar cada achado como sem ocorrência, pendência documental, impedimento confirmado ou inconclusivo.
7. Solicitar os documentos de conformidade e exceções correspondentes ao achado.
8. Registrar a decisão humana, o fundamento, o responsável e a validade das evidências.
9. Quando aplicável, iniciar o monitoramento remoto periódico até o encerramento da operação.

## Fontes oficiais consultadas

- Banco Central: MCR e normas de sustentabilidade: https://www.bcb.gov.br/estabilidadefinanceira/sustentabilidade
- Resolução CMN nº 5.193/2024: https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?numero=5193&tipo=RESOLU%C3%87%C3%83O+CMN
- Resolução CMN nº 5.267/2025: https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?numero=5267&tipo=Resolu%C3%A7%C3%A3o+CMN
- Resolução CMN nº 5.303/2026: https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?numero=5303&tipo=Resolu%C3%A7%C3%A3o+CMN
- Programação FCO 2026: https://www.gov.br/sudeco/pt-br/assuntos/fundo-constitucional-de-financiamento-do-centro-oeste/programacao-anual-de-financiamento/programacao-2026/Programacao_FCO_2026_3ED_jp.pdf
- Resoluções Condel/Sudam, incluindo FNO 2026: https://www.gov.br/sudam/pt-br/composicao-1/condel/notas-e-resolucoes
