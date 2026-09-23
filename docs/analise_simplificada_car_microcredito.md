# Revisão simplificada do CAR Microcrédito

**Documento para sua aprovação — 13 de setembro de 2026**

## Minha avaliação

O plugin tem uma boa estrutura para ajudar na análise dos imóveis. Recomendo corrigir alguns pontos para tornar os resultados mais confiáveis e, depois, melhorar a velocidade.

**O principal cuidado é garantir que o sistema só informe “nenhuma ocorrência encontrada” quando realmente tiver conseguido fazer a verificação.**

Examinei como o programa foi escrito, mas não executei testes nem alterei seu funcionamento. Os problemas abaixo podem acontecer nas situações descritas; isso não significa que todos já aconteceram nos seus relatórios.

## O que recomendo corrigir primeiro

### 1 Avisar quando faltarem informações para analisar

**O que pode acontecer:** se a lista ambiental do Ministério do Meio Ambiente ou a lista de empregadores do Ministério do Trabalho não tiver sido carregada, o sistema pode apresentar uma mensagem que parece favorável.

**Como deve funcionar:** avisar “não foi possível concluir esta verificação” quando faltar a lista. Não encontrar uma ocorrência em uma lista consultada é diferente de não ter a lista para consultar.

### 2 Garantir que a área analisada pertença ao CAR informado

**O que pode acontecer:** você seleciona uma operação de um imóvel e depois digita outro CAR. Se o sistema não encontrar o desenho desse segundo imóvel, pode aproveitar a área da operação selecionada anteriormente.

**Como deve funcionar:** conferir se o CAR e a área pertencem ao mesmo imóvel. Se houver dúvida, pedir a escolha correta ou informar que não foi possível concluir.

### 3 Evitar misturar informações antigas e novas

**O que pode acontecer:** ao carregar uma lista atualizada, registros antigos podem continuar participando da consulta. Por exemplo, uma ocorrência retirada da nova publicação pode continuar aparecendo por causa da versão anterior.

**Como deve funcionar:** identificar qual versão deve ser usada em cada consulta e guardar as anteriores como histórico.

### 4 Identificar áreas incompletas ou com erro no mapa

**O que pode acontecer:** se parte do desenho do imóvel estiver com problema, o sistema pode ignorar essa parte e analisar somente o restante, sem deixar clara a limitação.

**Como deve funcionar:** conferir o desenho antes da análise e avisar quando não conseguir verificar toda a área.

### 5 Proteger as listas durante uma atualização

**O que pode acontecer:** um arquivo vazio ou inadequado pode substituir a lista de empregadores do Ministério do Trabalho e deixar o sistema sem os registros anteriores.

**Como deve funcionar:** conferir o arquivo novo antes de substituir a lista que já está funcionando. Se houver problema, manter a anterior e avisar.

### 6 Processar a planilha que você realmente escolheu

**O que pode acontecer:** você confere uma planilha, troca por outra e manda processar. O sistema pode continuar usando os dados da primeira. Também precisa melhorar a identificação da aba, das linhas e dos documentos com zero no início.

**Como deve funcionar:** conferir novamente o arquivo escolhido no início do processamento e apontar os erros na linha correta.

### 7 Garantir que o pacote de instalação leve os dados completos

**O que pode acontecer:** montar o pacote enquanto o banco está sendo atualizado pode deixar informações recentes fora da cópia. As verificações atuais também não comprovam que todos os arquivos baixados estão completos e corretos.

**Como deve funcionar:** preparar uma cópia segura e conferir seu conteúdo antes de distribuir. Não confirmei defeito nos pacotes já existentes.

## Outras melhorias importantes

- **Calcular a área afetada sem duplicação:** se duas ocorrências cobrem os mesmos 10 hectares, mostrar que a área ocupada é de 10 hectares, mesmo existindo duas ocorrências.
- **Escolher melhor a operação usada na análise em lista:** quando um CAR tiver várias operações, evitar usar simplesmente a primeira, principalmente quando faltar o desenho cadastral do imóvel.
- **Explicar o que faltou analisar:** se você cancelar uma lista ou ocorrerem falhas, o relatório deve mostrar o que foi concluído e o que ficou pendente.
- **Guardar os relatórios anteriores:** uma nova análise do mesmo CAR não deve substituir automaticamente a anterior. Cada relatório deve identificar quando foi feito e quais versões das informações foram usadas.
- **Reconhecer códigos ausentes:** valores usados para indicar “CAR não informado”, como `-1`, não devem ser tratados como números de CAR.
- **Separar consulta de manutenção:** pesquisar um imóvel não deve fazer alterações desnecessárias na organização do banco de dados.

## Como melhorar a velocidade

O programa pode reaproveitar informações que já carregou, evitar repetir a mesma análise ambiental e buscar os imóveis de forma mais direta. Também pode manter a tela respondendo melhor enquanto trabalha.

O ganho de velocidade precisa ser medido. Minha recomendação é resolver primeiro os pontos que afetam a confiança no resultado.

## O que você está aprovando

Recomendo começar pelos **sete pontos prioritários**, fazendo as correções e os testes em uma cópia separada do projeto. Depois, apresentar os resultados para decidir sobre a instalação da versão corrigida no seu QGIS.

Você pode aprovar todos os pontos ou apenas os que considerar necessários.

**Nenhuma mudança no plugin ou no banco foi realizada. Este documento apresenta as propostas para sua decisão.**
