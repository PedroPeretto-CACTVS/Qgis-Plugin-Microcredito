# Análise técnica do plugin CAR Microcrédito

Documento para aprovação de mudanças

**Data:** 13 de setembro de 2026  
**Responsável pela análise:** Codex  
**Destinatário:** Equipe responsável pelo projeto  
**Situação:** propostas pendentes de aprovação

## Parecer

O projeto tem uma base útil para triagem: separa consultas, geometria, cruzamentos ambientais e relatórios; utiliza parâmetros nas consultas SQL; registra hashes das importações Sicor/MMA; e reaproveita camadas e índices durante os lotes. Recomendo manter essa estrutura e corrigir primeiro a confiabilidade dos resultados, antes de ampliar funcionalidades ou buscar velocidade.

Os pontos mais relevantes são: resultado favorável quando a disponibilidade das listas não foi comprovada, possibilidade de analisar a gleba de outro CAR, mistura de versões importadas, aceitação de geometrias incompletas e perda da base MTE em uma importação sem registros válidos. Há também problemas na atualização da planilha de lote, na rastreabilidade dos relatórios e no empacotamento do banco.

**Nenhuma correção foi aplicada.** A revisão foi estática, por leitura dos arquivos. Não executei o plugin, importadores, instaladores, downloads, testes ou migrações; não abri o banco operacional para consultas. Os cenários e testes abaixo são propostas para uma etapa posterior à sua aprovação. A leitura do código comprova os caminhos descritos, mas não comprova que cada situação já aconteceu nos dados reais.

## Escopo e limites

Foram examinados os módulos centrais em `src/car_microcredito`, os fluxos de consulta individual e lote em `qgis_plugin/car_microcredito_qgis`, os cruzamentos, o mapa, os relatórios, a leitura de XLSX e a coleta de evidências. Também foram examinados os importadores e downloads principais, os scripts de montagem e instalação, os testes do núcleo e trechos dos validadores de instalação.

Referências de linha correspondem aos arquivos-fonte presentes nesta revisão. O plugin declara versão **0.7.0**; o pacote Python declara **0.1.0**. Versões diferentes de componentes não são, por si, um defeito. Não foi verificada a equivalência entre os fontes, os ZIPs já gerados e o plugin instalado no QGIS.

Esta análise trata do comportamento técnico. A matriz regulatória existente foi lida como documentação do projeto; sua atualização jurídica não foi auditada. Não foram aferidos tempos, consumo de memória, integridade do banco, atualização efetiva das bases ou compatibilidade em diferentes instalações do QGIS.

**Classificação:** alta = pode comprometer a evidência, selecionar dados incorretos ou perder uma base válida; média = prejudica exatidão, rastreabilidade ou operação; otimização = melhoria cujo ganho precisa ser medido. Os efeitos condicionais estão explicitados em cada achado.

## Correções de prioridade alta

### A01 Ausência de base pode ser interpretada como ausência de ocorrência

**Evidência:** `qgis_plugin/car_microcredito_qgis/report.py`, linhas 288 a 328; `plugin.py`, linhas 1193 a 1203; `batch_window.py`, linhas 270 a 278; `evidence.py`, função `collect_database_evidence`.

**Comportamento:** listas vazias de resultados MMA/MTE não distinguem base instalada e consultada com sucesso de base nunca importada. A geração do relatório escreve “APTA NA ETAPA MMA/MCR” quando não há resultado MMA, sem exigir evidência de uma importação válida. Para o MTE, documentos pesquisados e nenhum resultado produzem mensagem de não localização, mesmo com a tabela vazia. A existência de metadados não participa da conclusão geral.

**Cenário:** um banco inicializado, com camadas ambientais disponíveis, mas sem importações MMA/MTE, pode gerar um resultado geral sem ocorrência e texto favorável na etapa MMA. Um valor MMA inesperado também cai no ramo favorável se não corresponder aos poucos valores tratados como ocorrência.

**Proposta:** representar separadamente disponibilidade, versão, validade da carga e resultado da consulta de cada fonte. Usar resultado inconclusivo quando a fonte necessária não estiver validada ou houver valor desconhecido. Preservar a distinção entre “não localizado nesta publicação” e “apto”. Não afirmar “lista vigente do MTE” sem uma política verificável de atualização.

**Aceitação:** banco sem MMA; banco sem MTE; lista válida sem correspondência; fonte desatualizada segundo política aprovada; valor de domínio desconhecido. Apenas a consulta válida sem correspondência deve produzir ausência de ocorrência naquela fonte.

### A02 CAR digitado pode usar a gleba da linha anteriormente selecionada

**Evidência:** `plugin.py`, funções `_selected_result` na linha 859 e `analyze_selected` na linha 1109, especialmente linhas 1125 a 1133 e o fallback de geometria.

**Comportamento:** a análise começa com a operação selecionada na tabela. A busca pelo CAR do formulário só substitui esse resultado se ele for `None`. Não existe, nesse caminho, comparação obrigatória entre o CAR digitado e o CAR da operação selecionada.

**Cenário:** selecionar uma operação do CAR A, digitar CAR B diretamente no campo e iniciar a análise. Se B não for localizado na base cadastral, a geometria pode vir da gleba de A, enquanto consultas e identificação do relatório usam B.

**Proposta:** invalidar a seleção incompatível ao alterar o CAR; validar a relação CAR–operação antes de construir a gleba; exigir escolha explícita quando houver ambiguidade. CAR sem polígono cadastral e sem gleba comprovadamente associada deve permanecer inconclusivo.

**Aceitação:** repetir o cenário A/B com polígonos distantes e garantir que nenhum relatório de B use a geometria de A.

### A03 Novas importações podem misturar versões históricas e atuais

**Evidência:** `src/car_microcredito/sicor.py`, funções `_begin_import` na linha 188, `import_file` na linha 215, `find_by_document` na linha 394, `find_by_car` na linha 432 e `find_mma_mcr_by_car` na linha 533; `geo.py`, função `build_glebas_geojson`.

**Comportamento:** o hash evita reimportar o mesmo arquivo, mas um arquivo diferente é acrescentado às tabelas. As consultas não selecionam um conjunto ativo por competência, escopo ou edição. A consulta MMA ordena registros encontrados do CAR pela importação mais recente, mas não restringe a pesquisa à edição atualmente válida da publicação.

**Cenário:** um CAR removido de uma nova edição MMA ainda pode retornar da edição antiga. Arquivos Sicor sobrepostos podem duplicar vínculos e pontos. Ao reconstruir glebas, pontos de versões distintas são agrupados sem discriminar a importação.

**Proposta:** cadastrar edição, competência, abrangência e estado de ativação; importar em preparação e ativar um conjunto coerente somente após validação. Preservar histórico para auditoria. Não substituir indiscriminadamente tudo pela última importação: arquivos de competências ou abrangências diferentes podem ser complementares.

**Aceitação:** atualizar duas versões sobrepostas; remover um CAR da nova edição; alterar a geometria de uma gleba; manter arquivos históricos complementares. A consulta deve usar exclusivamente o conjunto aprovado para aquele escopo.

### A04 Geometrias problemáticas podem ser ignoradas sem tornar a análise inconclusiva

**Evidência:** `analysis.py`, linhas 118 a 156; `src/car_microcredito/geo.py`, linhas 55 a 129.

**Comportamento:** o motor verifica se a camada abriu, mas não valida explicitamente a topologia de cada geometria, a completude das feições-alvo ou o CRS antes das operações. Geometrias ausentes são descartadas; interseção nula ou vazia é ignorada. No construtor de glebas, coordenadas fora do intervalo, grupos insuficientes e WKT não interpretável podem ser descartados, enquanto os demais polígonos seguem para análise. O contador `poligonos_validos` não representa uma validação topológica.

**Consequência condicionada:** um empreendimento parcialmente reconstruído pode parecer completamente analisado. Um erro geométrico que retorne interseção nula pode ser tratado como ausência de ocorrência. Outros erros podem interromper a análise, em vez de registrar o problema da camada.

**Proposta:** validar CRS, tipo geométrico, topologia e completude; registrar descartes e erros por feição; distinguir interseção realmente vazia de falha da operação. Uma correção automática de geometria deve conservar o original e registrar alteração de área ou componentes. A conclusão deve indicar cobertura incompleta quando houver perdas relevantes.

**Aceitação:** polígono auto-intersectante, WKT malformado, CRS ausente, uma feição sem geometria entre outras válidas e uma gleba descartada entre várias glebas. Conferir resultados e mensagens de cobertura. A API QGIS documenta mecanismos de validação e diagnóstico geométrico [S3].

### A05 Importação MTE vazia pode apagar uma base válida

**Evidência:** `scripts/importar_trabalho_escravo.py`, linhas 30 a 54.

**Comportamento:** a transação apaga `trabalho_escravo` antes de processar o CSV e confirma a operação mesmo com zero registros válidos. O cabeçalho é pulado sem conferir os campos; a leitura depende de posições fixas. Linhas curtas ou documentos não normalizáveis são apenas rejeitados.

**Cenário:** arquivo contendo apenas cabeçalho ou arquivo cujo novo leiaute faça todas as linhas serem rejeitadas. Como não há necessariamente exceção, ocorre `commit` da tabela vazia. O rollback existente protege falhas com exceção, mas não esse caso.

**Proposta:** validar o esquema e importar em tabela de preparação; conferir contagens, duplicidades e rejeições antes da troca. Zero registros deve exigir tratamento explícito e comprovado da publicação, jamais apagar silenciosamente o estado anterior. Registrar hash, edição e estatísticas da carga MTE.

**Aceitação:** CSV vazio, só cabeçalho, colunas trocadas e 100% de rejeição devem preservar a base anterior e gerar diagnóstico.

### A06 Planilha alterada pode continuar usando as linhas da validação anterior

**Evidência:** `batch_window.py`, linhas 148 a 152, 168 a 184 e 302 a 304.

**Comportamento:** a validação preenche `self.rows`. O botão processar só valida novamente quando essa lista está vazia. Trocar o caminho ou editar o arquivo depois de validar não invalida as linhas armazenadas. A origem registrada pode ser o caminho atual do campo, embora os dados tenham vindo da planilha anterior.

**Proposta:** revalidar no início ou vincular o resultado da validação ao hash do arquivo. Congelar entradas durante o lote e registrar qual conteúdo foi efetivamente processado.

**Aceitação:** validar planilha A, selecionar B sem clicar em validar e processar; editar A depois de validá-la; tentar trocar entradas durante o lote. Os dados usados e a origem registrada devem coincidir.

### A07 Empacotamento copia diretamente um banco configurado para WAL

**Evidência:** `src/car_microcredito/db.py`, função `connect`; `scripts/build_portable_package.py`, linhas 36 e 78.

**Comportamento:** o pacote recebe diretamente `car_microcredito.db`, sem obter uma cópia consistente via SQLite e sem garantir ausência de gravações concorrentes. A comparação posterior de tamanho não comprova consistência lógica.

**Risco condicionado:** em WAL, transações confirmadas podem estar no arquivo de log e ainda não no `.db`. Se houver conexões ativas e alterações pendentes de checkpoint, a cópia pode omitir dados; copiar durante gravações também não constitui um procedimento de backup consistente. Isso não prova que os ZIPs existentes estejam defeituosos [S1].

**Proposta:** produzir uma cópia consistente usando a API de backup SQLite, validar essa cópia e empacotá-la [S2]. Aplicar procedimento coerente também a GeoPackages que possam estar sendo atualizados.

**Aceitação:** empacotar uma base de teste com alterações confirmadas ainda no WAL e conferir os registros na cópia restaurada, além da integridade e das relações entre tabelas.

## Correções de prioridade média

### M01 Área sobreposta pode ser contada mais de uma vez

**Evidência:** `analysis.py`, linhas 148 a 164.

O total é a soma das áreas de cada interseção. Se duas feições da mesma fonte se sobrepõem no imóvel, sua área comum entra duas vezes. Isso é válido como soma por ocorrência, mas não equivale à área territorial única afetada.

**Proposta:** preservar a área de cada ocorrência e separar “soma das áreas das ocorrências” de “área única sobreposta”, calculada pela união das interseções. Tratar contato apenas de borda separadamente. **Aceitação:** duas ocorrências idênticas de 10 ha devem continuar sendo duas ocorrências, mas a área única deve ser 10 ha, não 20 ha.

### M02 Lote usa a primeira operação disponível como alternativa ao SICAR

**Evidência:** `batch_window.py`, linhas 229 a 241; `sicor.py`, função `find_by_car`.

`operations[0]` é escolhido segundo a ordenação por referência e ordem, não por confirmação de vínculo com o documento da linha, existência de gleba ou atualidade. Sem polígono cadastral, uma operação sem gleba pode impedir a análise mesmo quando outra tem geometria; uma gleba parcial também pode representar indevidamente o CAR inteiro.

**Proposta:** registrar todas as alternativas e aplicar uma seleção documentada, com tratamento explícito de ambiguidade e abrangência da gleba. Não unir automaticamente áreas financiadas em épocas diferentes. **Aceitação:** CAR com duas operações, sendo apenas uma com gleba, e CAR com operações de mutuários distintos.

### M03 Cancelamento e falhas totais deixam lacunas na auditoria do lote

**Evidência:** `batch_window.py`, linhas 317 a 359; `report.py`, função `write_batch_report`.

O cancelamento interrompe a iteração, mas os itens restantes não são registrados como não processados. O estado “Lote parcial” fica na interface e não é passado explicitamente ao documento. Se todos os itens falharem, ou nenhuma tarefa puder ser expandida, o fluxo lança uma exceção antes de gravar o relatório de falhas.

**Proposta:** sempre gerar um manifesto com total recebido, duplicados, analisados, falhos, cancelados e pendentes, incluindo o estado final do lote. **Aceitação:** cancelamento após o primeiro CAR, todas as tarefas falhando e nenhum CAR encontrado; a soma dos estados deve explicar toda a entrada.

### M04 Relatórios sobrescritos e identificação insuficiente da evidência

**Evidência:** `plugin.py`, final de `analyze_selected`; `report.py`, linhas 144 a 178 e 352 a 376.

A consulta individual utiliza nomes fixos por CAR. Repetir a análise na mesma pasta substitui PDF, JSON e mapa. O JSON é escrito antes do PDF, permitindo que uma falha deixe arquivos de execuções diferentes com o mesmo nome.

Além disso, a sanitização remove hashes e metadados de origem, reduzindo a capacidade de reproduzir o resultado. A ocultação de caminhos e dados Sicor é deliberada e é verificada pelos testes existentes; não deve ser revertida indiscriminadamente.

**Proposta:** identificar cada execução de forma única; publicar o conjunto de arquivos apenas após conclusão; preservar versões anteriores. Acrescentar identificadores e hashes de bases e geometria que não exponham caminhos locais, além de versão do motor e das regras. Se necessário, manter evidência interna protegida separada do relatório compartilhável.

**Aceitação:** duas consultas do mesmo CAR devem coexistir; falha na geração do PDF não pode apresentar JSON novo junto com PDF antigo; manter os testes de não exposição de caminhos e informações reservadas.

### M05 Normalização divergente aceita sentinelas como CAR no lote

**Evidência:** `src/car_microcredito/normalize.py`, função `normalize_car`; `car_source.py`, função homônima; `batch_window.py`, linhas 204 a 221.

O núcleo converte `-1` e outros valores de ausência em vazio. O módulo cartográfico apenas remove caracteres não alfanuméricos: `-1` vira `1`. A expansão do lote usa essa segunda função e aproveita `car_original`, podendo preparar uma tarefa fictícia para o valor sentinela que o Sicor identificou como ausente.

**Proposta:** centralizar normalização e validação, distinguindo valor ausente, identificador inválido e identificador aceito. Definir validação de CPF/CNPJ para entrada manual sem confundi-la com mera remoção de pontuação. **Aceitação:** `-1`, `0`, `N/A`, campo vazio e CAR com diferentes formatos devem ter o mesmo tratamento em núcleo, interface e lote.

### M06 Leitura XLSX pode usar aba errada e informar linha incorreta

**Evidência:** `batch.py`, funções `_first_sheet_path`, `read_xlsx_rows` e `read_batch_xlsx`.

O leitor usa a primeira aba, embora o fluxo oriente preencher `Consultas`. A numeração de linhas é reconstruída pela posição na lista, ignorando o atributo original da linha no XML. Linhas ausentes ou vazias podem deslocar o número registrado. Células numéricas não recebem tratamento específico para identificadores e podem perder zeros ou chegar em notação científica.

**Proposta:** selecionar a aba pelo nome, preservar o número real da linha e exigir texto para identificadores quando a representação numérica for ambígua. Não completar zeros por suposição. **Aceitação:** reordenar abas, inserir linhas vazias e incluir documento com zero inicial e célula numérica em notação científica.

### M07 Downloads e verificação do pacote não comprovam completude

**Evidência:** `scripts/download_arcgis_geojson.py`, função `main`; `scripts/baixar_car_brasil.py`, funções `valid_geopackage` e `download_state`; `scripts/baixar_terrabrasilis_brasil.py`, função `download`; `portable/Verificar pacote.ps1`.

O downloader ArcGIS acumula respostas sem reconciliar os IDs solicitados com os recebidos. O downloader TerraBrasilis reutiliza ZIP por tamanho e promove o arquivo baixado sem testar sua estrutura. O validador CAR verifica integridade SQLite, mas não comprova a estrutura GeoPackage, a camada esperada ou a UF. As tentativas CAR não envolvem tratamento de exceções de rede, portanto um erro de conexão pode interromper a primeira tentativa.

O verificador portátil exige 27 arquivos CAR e um tamanho mínimo do banco, mas não identifica as 27 UFs individualmente nem verifica conteúdo ou hashes. O build usa uma pasta de estágio já existente, sem comprovar que corresponde aos fontes atuais.

**Proposta:** reconciliar IDs e completude; validar estrutura, camadas e abrangência; adicionar repetição controlada de erros transitórios; gerar manifesto com versão e hashes por arquivo; verificar identidade das UFs e reconstruir o estágio de forma reproduzível. **Aceitação:** resposta parcial, ZIP contendo HTML, SQLite sem tabelas GeoPackage, UF duplicada e estágio desatualizado devem ser detectados.

### M08 Consultas comuns também inicializam e alteram o banco

**Evidência:** `plugin.py`, função `_connection`; `batch_window.py`, início de `process_batch`; `src/car_microcredito/db.py`, função `initialize`; `src/car_microcredito/cli.py`, função `main`.

As consultas chamam a inicialização, que pode migrar esquema, criar índices e executar atualização de normalização. Assim, consultar não é uma operação exclusivamente de leitura e pode disputar escrita com importações. Há ainda trabalho repetido de manutenção.

**Proposta:** separar conexão de consulta, verificação de compatibilidade e migração administrativa; versionar esquema; executar manutenção uma vez por atualização. **Aceitação:** consultar uma cópia compatível em modo somente leitura sem alterar seu conteúdo; esquema incompatível deve gerar orientação clara, não migração silenciosa durante a consulta.

## Melhorias de desempenho e manutenção

| Proposta | Motivo observado no código | Como verificar depois da aprovação |
|---|---|---|
| Consultar candidatos pelo índice persistente do GeoPackage | A consulta individual reconstrói `QgsSpatialIndex` das fontes; o lote já reaproveita índices, o que é positivo | Comparar consulta espacial do provedor com índice em memória, medindo tempo, memória e igualdade dos resultados |
| Preparar a geometria do empreendimento uma vez | União das feições é refeita por fonte em `analyze_layer` | Medir consultas repetidas com a mesma geometria e manter equivalência espacial |
| Reaproveitar trabalho ambiental para CAR repetido em CPFs distintos | O lote elimina duplicados por documento e CAR, mas ainda pode cruzar o mesmo imóvel várias vezes | Cache por geometria, edição das fontes e regras; manter consultas pessoais separadas |
| Indexar busca de CAR e manter catálogo das bases | `candidate_files` percorre a pasta e prioriza UF pela presença da sigla no nome; as camadas são reabertas nas buscas | Conferir índice do identificador, roteamento por UF e seleção explícita da camada dentro do GPKG |
| Tirar tarefas longas do fluxo da interface | Chamadas síncronas, `processEvents` e espera do mapa podem bloquear a interface por trechos longos | Implementar tarefa em segundo plano com objetos apropriados ao contexto de execução, progresso e cancelamento; medir responsividade |
| Importar registros em blocos | O importador usa `execute` por linha, embora já reúna operações em transação | Comparar `executemany` em blocos sem enfraquecer atomicidade, diagnóstico ou contagem de rejeições |
| Centralizar regras de resultado | Individual, lote e relatório repetem decisões MMA/MTE | Um conjunto de testes deve produzir a mesma classificação em todas as saídas |
| Reutilizar resolução de camadas no mapa | O analisador aceita alternativas SHP/GeoJSON; o mapa abre o caminho originalmente configurado | Testar fonte alternativa e garantir que a ocorrência analisada também possa aparecer no mapa |

**Não há estimativa de ganho percentual nesta revisão.** Não recomendo paralelizar indiscriminadamente as camadas nem substituir SQLite por PostgreSQL/PostGIS apenas com base na leitura. Essa decisão depende de volume, simultaneidade, necessidade de serviço compartilhado e medições. Para uso local, vale primeiro corrigir os fluxos e aproveitar os índices existentes.

## Testes e pontos positivos a preservar

Os testes existentes cobrem normalização, sentinela Sicor, importação repetida por hash, vínculos, consulta MTE, glebas por pontos e WKT, cabeçalho inválido, consulta MMA e migração de esquema. A integração QGIS contempla ocorrência sintética e fonte ausente. Os validadores também verificam interface, legendas e exclusão de dados reservados dos relatórios. Esses testes foram lidos, não executados.

Priorizar novos testes sobre os cenários A01 a A07. Em seguida, testar cancelamento e falhas totais, versões de importação sobrepostas, área única, seleção da aba e preservação da linha, relatórios repetidos e falha de escrita. Usar dados sintéticos ou cópias descartáveis; os validadores atuais que chamam `initialize` ou checkpoint não devem ser tratados como estritamente somente leitura.

Preservar as consultas SQL parametrizadas, os tipos de vínculo explícitos, o resultado inconclusivo para fonte ambiental ausente, a separação entre ocorrência e decisão de crédito, os hashes de importação e o cache já existente no lote. Manter também a proteção contra exposição de caminhos locais no relatório compartilhável.

## Plano de execução sujeito à aprovação

| Etapa | Entrega proposta | Condição de conclusão |
|---|---|---|
| 1 Confiabilidade | A01 a A06, com M02 e M05 pelos vínculos e normalização | Cenários críticos reproduzidos em dados de teste e corrigidos |
| 2 Dados e distribuição | A07, M07 e M08 | Cópia restaurável, versões verificáveis e consulta separada de manutenção |
| 3 Evidência e precisão | M01, M03, M04 e M06 | Área sem dupla contagem territorial, lote explicável e relatórios preservados |
| 4 Desempenho | Melhorias selecionadas após medições | Menor custo comprovado sem alterar resultados corretos |

Após aprovação, o trabalho deve começar em uma cópia de desenvolvimento, com registro do estado anterior. Uma alteração de esquema exige migração testada e plano de retorno. A instalação no QGIS e substituição do banco operacional só devem ocorrer após validação da versão produzida e aprovação dessa implantação.

### Registro da decisão

**Decisão:** ______________________________________________  
**Itens autorizados:** ______________________________________  
**Itens a discutir ou adiar:** _________________________________  
**Responsável e data:** _____________________________________

Recomendo aprovar primeiro a etapa de confiabilidade. A aprovação deste documento pode ser parcial, pelos identificadores dos achados; ela não implica concordância automática com todas as otimizações.

## Referências técnicas

Os caminhos citados são relativos à raiz do projeto CAR Microcrédito examinada nesta revisão. As fontes primárias abaixo apoiam somente os pontos técnicos indicados, sem constituir auditoria regulatória.

- **S1** [SQLite Write Ahead Logging](https://www.sqlite.org/wal.html) — persistência no WAL e checkpoint, fundamento do risco de copiar apenas o arquivo principal enquanto há alterações não incorporadas.
- **S2** [SQLite Online Backup API](https://www.sqlite.org/backup.html) — mecanismo de cópia consistente proposto para o empacotamento.
- **S3** [QGIS QgsGeometry](https://api.qgis.org/api/classQgsGeometry.html) — operações geométricas, validação e diagnóstico. A compatibilidade das chamadas escolhidas deverá ser conferida na versão QGIS homologada pelo projeto.
