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

A Programação FNO 2026 vigente está disponível no MIDR e foi aprovada em nova versão pela Resolução Condel/Sudam nº 141, de 23/02/2026. Para o PNMPO Rural operado por instituição repassadora, ela manda observar as normas do crédito rural e atribui à operadora o risco, o controle e o envio periódico de informações. Em atividades florestais, exige, conforme o caso, licença, PMFS/POA e AUTEX/AUTEF. A Programação pública ainda não substitui o contrato de repasse nem o manual/checklist operacional interno da instituição.

## Vocabulário exibido no plugin

Os identificadores `mutuarios`, `propriedades`, `operacoes`, `complementos` e `glebas` são componentes técnicos da importação Sicor. Eles não são exibidos ao analista como se fossem cinco requisitos independentes. A tela de atualização os organiza assim:

| Nome apresentado ao analista | Componentes/fonte | Necessidade atendida | Limite declarado |
|---|---|---|---|
| Operação de crédito e vínculos CPF/CNPJ–CAR — Sicor/BCB | mutuários, propriedades, operações e complementos | Identificar operação, beneficiário, imóvel, fonte/programa | O vínculo não comprova sozinho titularidade ou elegibilidade. |
| Área financiada e geometria das glebas — Sicor/BCB | glebas | Delimitar a geometria declarada da operação | Não substitui a área contínua efetivamente explorada. |
| Impedimentos ambientais publicados para o crédito rural — MMA/MCR | publicação MMA/MCR | Triagem dos impedimentos publicados | Requer conferência de vigência, motivo e exceções. |
| Impedimento social: Cadastro de Empregadores — MTE/MCR | lista federal do MTE | Consulta dos documentos associados ao CAR | Cobre a lista federal, não todas as fontes trabalhistas. |
| Situação cadastral e geometria dos imóveis rurais — SICAR | arquivos estaduais do CAR | Localização e evidência cadastral | A situação vigente deve ser confirmada no SICAR. |
| Embargos ambientais vigentes — Ibama (cobertura federal) | Ibama | Cruzamento territorial | Não cobre sozinho órgãos estaduais e ICMBio. |
| Terras indígenas: interferência e exceções — MCR | camada oficial | Cruzamento territorial e encaminhamento documental | Sobreposição não é reprovação automática. |
| Territórios quilombolas: interferência e exceções — MCR | Incra/Ibama | Cruzamento territorial e encaminhamento documental | Exige confirmar condição do beneficiário e exceções. |
| Unidades de conservação: categoria e autorização — MCR | camada oficial | Cruzamento territorial | Exige categoria, plano de manejo e eventual autorização. |
| Florestas públicas tipo B não destinadas — MCR | CNFP | Cruzamento territorial | A camada precisa ser filtrada; nem toda floresta pública é impeditiva. |
| PRODES após 2020 — cobertura parcial da regra desde 31/07/2019 | PRODES | Evidência de supressão | A cobertura atual é incompleta para a data inicial do MCR. |

Licença, alvará, outorga, CCIR, projeto técnico, garantias, assistência técnica, fiscalização e condições de desembolso não são renomeados como “bases”. Eles pertencem ao checklist documental e ao fluxo decisório da instituição.

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
- Cartilha FCO 2026: https://www.gov.br/sudeco/pt-br/assuntos/fundo-constitucional-de-financiamento-do-centro-oeste/publicacoes-e-informacoes-gerenciais/CartilhaFCO2026v424Mar2026compactada.pdf
- Resoluções Condel/Sudam, incluindo FNO 2026: https://www.gov.br/sudam/pt-br/composicao-1/condel/notas-e-resolucoes
- Programação Financeira FNO 2026: https://www.gov.br/mdr/pt-br/assuntos/fundos-regionais-e-incentivos-fiscais/fundos-constitucionais-de-financiamento-fno-fne-e-fco/fundo-constitucional-de-financiamento-do-norte-fno/ProgramaoFinanceiraFNO2026.pdf
