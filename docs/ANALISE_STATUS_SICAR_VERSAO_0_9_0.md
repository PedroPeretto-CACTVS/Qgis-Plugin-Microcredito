# Análise simples — situação do CAR no SICAR

**Proposta de versão:** 0.9.0  
**Data da análise:** 14/09/2026  
**Situação:** aguardando aprovação para alterar o plugin

## É possível fazer?

Sim. As bases oficiais do SICAR que já acompanham o pacote possuem as informações necessárias. O plugin hoje usa essas bases para localizar o polígono, mas ainda não apresenta claramente a situação cadastral encontrada.

O status principal será obrigatoriamente um destes quatro valores oficiais:

- **Ativo** (`AT`);
- **Pendente** (`PE`);
- **Suspenso** (`SU`);
- **Cancelado** (`CA`).

Também existem dados complementares que podem aparecer separadamente no detalhamento:

- condição da análise: aguardando análise, em análise, aguardando notificação, em regularização e outras;
- data de criação do cadastro;
- data da última atualização do imóvel;
- município, área e quantidade de módulos fiscais;
- arquivo oficial usado como fonte.

## Exemplos já conferidos

Os dois CARs abaixo, usados anteriormente nos testes, foram localizados nas bases instaladas:

| CAR | Situação | Condição no SICAR | Última atualização |
|---|---|---|---|
| CAR de teste do Acre | Ativo | Aguardando análise | 26/11/2025 |
| CAR de teste de Rondônia | Ativo | Analisado, aguardando atendimento a notificação | 06/08/2026 |

Isso confirma que a melhoria pode ser feita com os dados que já estão no pacote.

## Como a informação aparecerá

### Consulta individual

Depois que o CAR for localizado, o plugin mostrará primeiro o status oficial, por exemplo:

> Status do CAR no SICAR: ATIVO

A condição será apresentada em uma linha separada, como informação complementar:

> Etapa da análise: Aguardando análise. Cadastro atualizado em 26/11/2025.

A tela também mostrará um botão para abrir a consulta pública do SICAR quando for necessária uma conferência manual.

### Consulta em massa

A tabela terá uma coluna chamada **Status SICAR**. Cada linha mostrará somente um dos quatro valores oficiais, por exemplo:

> ATIVO

Se o CAR não existir na base instalada, a mensagem informará claramente:

> Situação cadastral não localizada na base SICAR instalada.

Essa mensagem indica uma falha de localização e não será tratada como um quinto status.

### Relatórios PDF e JSON

Cada CAR terá uma seção chamada **Situação cadastral no SICAR**, contendo:

- status por extenso e código oficial, limitado a Ativo, Pendente, Suspenso ou Cancelado;
- condição no processo de análise, identificada separadamente como informação complementar;
- data de criação e última atualização;
- município, área e módulos fiscais;
- identificação do arquivo oficial consultado;
- data da base instalada;
- aviso de que o resultado corresponde à versão da base do pacote.

O JSON guardará os mesmos dados completos para auditoria.

## Significado das situações

| Código | Status que será exibido |
|---|---|
| AT | Ativo |
| PE | Pendente |
| SU | Suspenso |
| CA | Cancelado |

## A situação mudará a conclusão do relatório?

Minha recomendação inicial é **mostrar e destacar a situação, sem alterar automaticamente a conclusão da operação**. Assim o plugin não cria uma nova regra de crédito sem uma decisão formal da instituição.

Visualmente:

- ativo: destaque verde;
- pendente: destaque amarelo e indicação para análise;
- suspenso: destaque cinza e indicação para análise;
- cancelado: destaque vermelho e indicação para análise;
- não localizado: destaque cinza e aviso para conferência manual.

Se a instituição decidir depois que alguma situação deve bloquear ou tornar a operação inconclusiva, essa regra poderá ser acrescentada separadamente e testada.

## Consulta local ou consulta online

### Solução recomendada para a versão 0.9.0

Usar a base oficial do SICAR já instalada no pacote. A consulta será rápida, funcionará sem internet e suportará o processamento em massa. O relatório deixará evidente a data da informação.

### Consulta online em tempo real

O governo possui APIs do SICAR no Conecta Gov, inclusive uma API de demonstrativo que retorna a situação e a etapa do cadastro. O público indicado no catálogo oficial são órgãos e entidades públicas. A integração depende de credenciamento e autenticação, portanto não deve ser colocada no plugin sem acesso oficial concedido à instituição.

Não recomendo copiar dados automaticamente da página pública do SICAR por automação de navegador. Esse método seria instável e poderia parar quando o portal fosse alterado.

## Alterações previstas

1. Ler os campos cadastrais junto com o polígono do CAR.
2. Traduzir os códigos oficiais para textos simples.
3. Mostrar o status oficial na consulta individual, sem misturá-lo com a etapa da análise.
4. Acrescentar a coluna Status SICAR na consulta em massa, limitada aos quatro valores oficiais.
5. Incluir a nova seção no PDF e os campos no JSON.
6. Exibir a data e a fonte da base utilizada.
7. Corrigir o enquadramento do mapa para centralizar e aproximar a feição do CAR carregado.
8. Acrescentar testes para ativo, pendente, suspenso, cancelado e não localizado.
9. Repetir os testes reais da consulta individual e da planilha com 93 itens.
10. Atualizar os dois manuais.
11. Gerar e validar novamente os dois pacotes de instalação.
12. Instalar a nova versão no QGIS somente depois que os testes forem aprovados.

## Correção do zoom ao carregar o CAR no mapa

O botão **Carregar no mapa** atualmente pode deixar o QGIS afastado, mostrando uma área muito maior do que o imóvel analisado.

Na versão 0.9.0, depois de adicionar a camada do CAR, o plugin deverá:

1. obter a extensão exata da feição carregada;
2. centralizar o mapa nessa feição;
3. acrescentar uma margem visual pequena ao redor do imóvel, para o contorno não encostar nas bordas;
4. atualizar a tela somente depois que todas as camadas necessárias forem adicionadas;
5. manter o foco no CAR mesmo quando as camadas ambientais tiverem extensão nacional.

O enquadramento será baseado no polígono do CAR, e não na extensão total das camadas ambientais. A mesma regra será aplicada sempre que o imóvel for carregado novamente.

## Nova versão e pacotes

Como se trata de uma nova função visível, a versão recomendada é **0.9.0**.

Serão entregues separadamente:

- `CAR_Microcredito_0.9.0.zip` — consulta individual;
- `CAR_Microcredito_Consulta_em_Massa_0.9.0.zip` — consulta em massa;
- `Manual_CAR_Microcredito_0.9.0.docx`;
- `Manual_Consulta_em_Massa_0.9.0.docx`;
- arquivos SHA-256 para conferir cada pacote.

## Testes obrigatórios antes da entrega

- confirmar os quatro códigos de situação;
- conferir situação e condição em CARs reais;
- validar a mensagem na consulta individual;
- validar a nova coluna na consulta em massa;
- conferir a seção SICAR no PDF e no JSON;
- testar CAR não localizado e campo ausente;
- carregar CARs pequenos e grandes no mapa e confirmar que a feição fica centralizada, com margem e em escala legível;
- confirmar que uma camada ambiental nacional não provoca novo afastamento do mapa;
- executar novamente os testes automatizados existentes;
- processar novamente a planilha real de 93 itens;
- abrir visualmente as páginas do relatório com os novos dados;
- validar instalação limpa dos dois pacotes no QGIS 3.40.10.

## Fontes oficiais consultadas

- Catálogo da API SICAR Demonstrativo: https://www.gov.br/conecta/catalogo/apis/api-sicar-demonstrativo
- Informações oficiais sobre o CAR e o SICAR: https://www.gov.br/agricultura/pt-br/assuntos/florestal/cadastro-ambiental-rural-1/o-que-e-o-cadastro-ambiental-rural
- Base pública utilizada pelo projeto: https://consulta.car.gov.br/api

## Recomendação para aprovação

Implementar a versão 0.9.0 usando a base oficial instalada. O status principal será exclusivamente Ativo, Pendente, Suspenso ou Cancelado. Condição, datas e fonte aparecerão separadamente como detalhes. Nesta primeira etapa, o status será informativo e destacado, sem modificar automaticamente a conclusão da análise de crédito.
