# Plano de implementação do CAR Microcrédito

**Situação: planejamento e backup antes das alterações.**

## Objetivo

Corrigir os problemas encontrados na revisão, mantendo uma cópia do projeto atual para permitir o retorno à versão anterior. Primeiro vamos melhorar a confiança nos resultados; depois, a organização dos relatórios e a velocidade.

Este plano não significa que as correções já foram feitas. A etapa atual inclui apenas preparar o plano, criar o backup e verificar a cópia.

## 1 Guardar o projeto atual

- Criar uma pasta com data e hora dentro de `backups`.
- Guardar os códigos, as bases de dados, os mapas, os relatórios, os documentos e os pacotes de instalação existentes.
- Copiar os bancos de dados com um procedimento que mantenha a consistência mesmo quando estiverem abertos para consulta.
- Conferir os arquivos copiados e registrar o resultado da verificação.
- Registrar separadamente o vínculo `node_modules`, que aponta para bibliotecas externas do ambiente Codex. Essas bibliotecas não fazem parte dos arquivos próprios do plugin e não serão duplicadas.

**Condição para avançar:** backup concluído e verificado. Se houver erro ou mudança dos arquivos durante a cópia, resolver antes de começar as correções.

O backup ficará no mesmo computador e na mesma pasta principal. Ele permite recuperar a versão anterior às mudanças, mas não substitui uma cópia em outro dispositivo para proteção contra perda do computador. A instalação atual dentro dos perfis do QGIS não faz parte desta cópia do projeto.

## 2 Preparar uma cópia para trabalhar

Após a autorização das implementações, criar uma cópia separada do código e bases pequenas de teste. Preservar o backup sem alterações e evitar testes que modifiquem as bases usadas no trabalho diário.

Registrar quais versões do QGIS e do plugin serão utilizadas na conferência.

## 3 Corrigir os pontos que podem alterar a conclusão

| Ordem | O que será corrigido | Como conferir |
|---|---|---|
| 1 | Avisar quando faltar uma lista necessária à análise | Retirar uma lista da base de teste e confirmar que o resultado fica inconclusivo |
| 2 | Garantir que o CAR informado corresponde à área analisada | Trocar o CAR após selecionar uma operação e conferir que não usa a área anterior |
| 3 | Impedir a mistura indevida de informações antigas e novas | Carregar duas versões de teste e confirmar que a consulta usa a versão correta para aquele período e abrangência |
| 4 | Avisar quando o desenho do imóvel estiver incompleto ou errado | Testar desenhos com falhas e confirmar que a limitação aparece no resultado |
| 5 | Proteger a lista de empregadores durante atualizações | Tentar atualizar com arquivo vazio ou inadequado e confirmar que a lista anterior permanece |
| 6 | Usar a planilha efetivamente escolhida pelo usuário | Validar uma planilha, trocar por outra e conferir quais dados são processados |
| 7 | Evitar CAR inválido e escolha indevida de operação | Testar códigos ausentes e imóveis com várias operações |

**Entrega:** demonstração dos casos de teste e das correções, com explicação simples do resultado esperado e do obtido.

## 4 Melhorar a atualização e a distribuição dos dados

- Separar as consultas comuns das tarefas que alteram o banco.
- Conferir se downloads e bases estaduais estão completos e corretamente identificados.
- Preparar os pacotes de instalação a partir da versão certa do código.
- Usar cópia consistente do banco nos futuros pacotes e testar sua abertura.

Mudanças na organização do banco devem ser testadas em cópia, incluindo como retornar à versão anterior. Não apagar o histórico sem uma regra definida.

## 5 Melhorar mapas e relatórios

- Mostrar a área afetada sem contar duas vezes o mesmo trecho.
- Guardar relatórios anteriores quando o mesmo CAR for consultado novamente.
- Registrar quando a análise foi feita e quais versões das informações foram usadas.
- Mostrar itens concluídos, falhos e pendentes quando uma consulta em lista for cancelada.
- Corrigir a leitura da aba e a indicação das linhas da planilha, preservando documentos com zero inicial.
- Garantir que as informações apresentadas no mapa correspondam às fontes analisadas.

**Condição para concluir:** relatórios de teste claros, completos e coerentes com as áreas e os dados utilizados.

## 6 Melhorar a velocidade

Somente após estabilizar os resultados, medir o tempo das consultas e o consumo de memória. Melhorar buscas e reaproveitar informações já carregadas, evitando trabalho repetido. Manter a tela respondendo durante operações demoradas.

Não há promessa de ganho percentual antes das medições. Uma melhoria só será aceita se preservar a correção dos resultados.

## 7 Apresentar a versão corrigida antes de instalar

Apresentar uma lista do que mudou, os resultados dos testes, eventuais limitações e exemplos de relatórios. Depois da aprovação da implantação, instalar a versão corrigida no QGIS e conferir uma consulta individual e uma consulta em lista.

Se a implantação apresentar problema, restaurar o código e os dados compatíveis do backup, com o QGIS fechado e preservando os arquivos produzidos depois da cópia. Não substituir o projeto atual sem conferir o que precisa ser conservado.

## Decisão para a próxima etapa

**Agora:** criar e verificar o backup; entregar este plano.

**Depois da sua autorização:** iniciar as implementações em cópia de trabalho, seguindo as etapas acima. A instalação no ambiente utilizado no dia a dia será apresentada para aprovação após os testes.
