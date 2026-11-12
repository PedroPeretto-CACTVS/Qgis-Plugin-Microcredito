# Bases Plugin — Kit do Publicador

## Objetivo

Separar a operação administrativa da experiência do usuário. **Bases Plugin** é
o nome da release geral de dados. A release completa contém todas as 11 bases
lógicas, não apenas a base do CAR. O plugin QGIS não
consulta fontes oficiais, não guarda credenciais e não publica dados. Ele recebe
um arquivo `.carbases`, confere integridade e compatibilidade e ativa somente
um conjunto validado. A publicação pré-montada instala por cópia; o formato
anterior, de fontes brutas assinadas, continua suportado.

No Windows, o destino é sempre `%LOCALAPPDATA%\Cactvs\BasesPlugin`.
O banco `car_microcredito.db`, `car/`, `ambientais/` e o histórico de atualização
ficam nessa mesma raiz, sem versão no caminho. A atualização do plugin preserva
esse conjunto; as telas não exibem campos ou seletores de banco e polígonos.
A configuração técnica fica interna ao plugin, sem ocupar a tela de consulta.
Na primeira aplicação de uma publicação, o banco é inicializado automaticamente.
O arquivo `.carbases` pode estar em qualquer pasta: ela não se torna a pasta ativa
das consultas.

## Cobertura obrigatória da release completa

Uma release **Bases Plugin completa** somente pode ser publicada quando a
auditoria confirmar 36 pacotes técnicos cobrindo estas 11 bases lógicas:

- 1 pacote Sicor compartilhado por operação/vínculos CPF/CNPJ–CAR e geometria
  das glebas;
- 27 pacotes SICAR, um para cada UF, compondo a base cadastral e geométrica dos
  imóveis rurais;
- 6 pacotes ambientais: desmatamento após 2020, embargos, florestas públicas,
  terras indígenas, territórios quilombolas e unidades de conservação;
- 1 pacote MMA/MCR;
- 1 pacote MTE.

Catálogo parcial, pacote legado ou ausência de qualquer UF bloqueiam a
publicação como release completa.

O formato dos payloads também integra o contrato: substituições geográficas
usam `.gpkg`; MMA/MCR usa `.csv` ou `.gz`; MTE usa `.csv`; e os arquivos Sicor
usam `.csv` ou `.gz`. Um ZIP oficial deve ser extraído e validado antes de virar
payload — ZIP aninhado é rejeitado pela auditoria.

O formato anterior `.carbases` é um ZIP64 com catálogo assinado e 36 pacotes:

```text
catalog.json
catalog.json.sig
packages/<id-do-pacote>.zip
```

O nome também integra o contrato de publicação e deve seguir exatamente
`bases-plugin-DD-MM-AAAA.carbases`. A data identifica a emissão da atualização e
deve coincidir com a data de `issued_at` do catálogo assinado no formato anterior,
ou de `prebuilt.json` no formato pré-montado. Nome sem data,
data inexistente, outra extensão ou divergência com o catálogo bloqueiam a
montagem do arquivo.

O formato pré-montado é um ZIP64 distinto, identificado por `prebuilt.json`:

```text
prebuilt.json
catalog.source.json
catalog.source.json.sig
data/car_microcredito.db
data/car/<UF>/<UF>_AREA_IMOVEL.gpkg
data/ambientais/<base>.gpkg
data/.atualizacoes/estado.json
```

São 35 arquivos de dados, além dos três metadados. O manifesto pré-montado
declara esquema, compatibilidade, origem, identidade, tamanho e SHA-256 de cada
arquivo. O catálogo/assinatura de origem já existentes são conferidos
automaticamente; não há nova assinatura manual do banco derivado. Os hashes
detectam alteração/corrupção dos arquivos em relação ao manifesto, sem atribuir
autenticação criptográfica ao banco derivado. A distribuição prevista é por
biblioteca corporativa controlada do SharePoint e download local pelo usuário.

No formato anterior, o catálogo assinado declara o tamanho e o SHA-256 de cada pacote. Arquivos
ausentes, adicionais, duplicados ou divergentes bloqueiam a publicação antes de
qualquer alteração local. Se uma base falhar durante a aplicação, as bases já
aplicadas no mesmo lote são restauradas automaticamente.

## Rotina quinzenal

### Execução local fora do QGIS

A validação do `.carbases`, a instalação por cópia ou importação e a restauração são executadas por um
processo Python separado, usando o runtime da instalação QGIS. A janela apenas
envia a solicitação e recebe progresso, atividade e resultado. Ela não cria
outra aplicação Qt nem usa um comando de shell. O catálogo é assinado e
revalidado na aplicação; trocar o arquivo após validar exige nova confirmação.

O tempo decorrido e a última resposta do processo são exibidos mesmo quando uma
etapa permanece no mesmo percentual. O sinal de atividade comprova que o
processo responde, não que a importação avançou. Não há encerramento automático
por falta de mudança no percentual. Fechar a janela ou o QGIS pela janela
principal fica bloqueado enquanto a operação está em andamento.

Consultas, mapa e relatórios mantêm um bloqueio local durante toda a operação.
Uma atualização não pode substituir as bases nesse intervalo, e uma consulta
não começa durante a aplicação/restauração. Ao terminar uma operação, o bloqueio
é liberado. Uma interrupção sem confirmação deixa um marcador persistente
`.atualizacoes/external-update-pending.json`: consultas e novas mutações ficam
bloqueadas até recuperação técnica; não remova esse arquivo para contornar o aviso.

**Limites operacionais:** no formato anterior, a importação continua local e
fora do QGIS. No pré-montado, a importação ocorre no publicador; no cliente
restam download, extração/cópia, hashes e validação dos dados, cujo tempo depende
do volume e do disco. Não há promessa de instalação instantânea.

A cópia mantém a raiz fixa e seus locks; prepara os dados em estágio no mesmo
volume, verifica banco/GeoPackages/versões e promove o banco por último. Falhas
tratadas desfazem apenas as renomeações da transação. Relatórios e exportações
do usuário não são substituídos. O histórico de restauração anterior é retirado
após sucesso porque seus registros não descrevem mais o conjunto instalado;
esse formato não cria ponto de restauração manual integral.

Queda de energia/encerramento forçado mantém o bloqueio para verificação
técnica; retomada automática não faz parte deste incremento. A rotina quinzenal
é independente da execução local e não é criada pela instalação do plugin.

### Preparação de bases pré-montadas pelo publicador

O comando `car-microcredito-installer prepare-bases --release PUBLICACAO.carbases
--output PASTA_NOVA` executa a importação uma vez, em estágio isolado do
publicador. A entrada deve ser uma publicação assinada com catálogo v3 e os 36
pacotes completos. `--public-key CHAVE_PUBLICA.pem` permite selecionar a chave
de verificação do publicador; nenhuma chave privada é usada pelo preparador.

O resultado é uma pasta candidata com banco SQLite autossuficiente, 27 CAR,
seis ambientais e registro das versões: 35 arquivos de dados. O preparador
confere esquema, integridade, vínculos, cargas ativas, UFs e as exceções
estaduais assinadas. Conserva também o catálogo e a assinatura de origem e
gera `snapshot.candidate.json` com os tamanhos e hashes dos arquivos derivados.
Históricos de restauração e arquivos temporários não integram o candidato.
Um destino existente é rejeitado; falha na preparação não publica a pasta final.

Antes da exportação, somente no publicador, a preparação exige pelo menos uma
propriedade Sicor ativa com CAR formal, documento completo não mascarado e
operação ativa com a mesma `REF_BACEN` e `NU_ORDEM`. O CAR deve conter UF válida,
sete dígitos de município e 32 caracteres hexadecimais; isso confere o formato,
sem comprovar situação cadastral ou existência do imóvel. O documento deve ter
11 ou 14 dígitos, sem exigir dígitos verificadores nesta etapa. Aceita-se o
documento no registro da propriedade ou o mutuário da mesma referência Bacen,
mantendo a distinção de vínculo já utilizada nas consultas. O vínculo por
operação não comprova titularidade.

O bloco `sicor_link_coverage` de `snapshot.candidate.json` registra contagens
agregadas de propriedades ativas: CAR formal, indisponível ou malformado e,
dentro do grupo com CAR formal, documento direto, documento de mutuário e
operação compatível. `properties_with_usable_link` conta cada propriedade uma
vez, mesmo quando há vários documentos ou os dois tipos de vínculo.
`minimum_required: 1` e `full_coverage_required: false` indicam um mínimo
funcional positivo, sem afirmar cobertura de 100% dos registros ou homologação
funcional global. As contagens dos dois tipos de documento podem se sobrepor.

Sem vínculo utilizável, a preparação é bloqueada antes de exportar ou promover
a pasta candidata; o erro informa somente as contagens e a publicação de origem
permanece preservada. Se não houver CAR formal, não são executadas buscas de
vínculo por registro. Não se alteram sentinelas ou a normalização Sicor, não se
misturam coortes externas e não se infere CAR por interseção de glebas. A regra
vale para novas preparações; não muda a leitura de publicações legadas nem
acrescenta importação ou validação relacional no computador do cliente.

O diretório candidato é convertido em arquivo de distribuição com
`car-microcredito-installer prebuilt-release --candidate PASTA_NOVA --output
bases-plugin-DD-MM-AAAA.carbases`. A data deve coincidir com `prepared_at` no
manifesto, respeitando o fuso declarado. O empacotador confere o candidato e o
ZIP final antes de publicá-lo no destino; um arquivo existente é preservado.

No QGIS, o usuário seleciona esse arquivo e usa os mesmos botões Validar e
Aplicar. O processo externo reconhece o formato e copia os dados sem ETL.
Seu identificador inclui o manifesto inteiro, impedindo reutilizar validação
anterior se o snapshot mudar, mesmo mantendo as versões das fontes. A primeira
migração para pré-montado é oferecida também quando as fontes brutas já estão
atuais. A repetição do mesmo snapshot é identificada como instalada.

A aprovação do publicador e a homologação continuam necessárias. O ensaio
nacional R3 foi concluído em 30/10/2026, em ambiente isolado: instalação nova,
upgrade, reinício, consultas Sicor/CAR, mapa, pré-análise e PDF passaram nos dois
cenários, com 12 páginas de relatório revistas. A maior pausa Qt medida foi de
0,547 s, abaixo do limite de cinco segundos. Esse resultado técnico não
substitui a revisão e integração dos PRs nem autoriza uma distribuição sozinho.

O histórico Sicor do ensaio foi adquirido em 29/10, desde 2013; as emissões de
operações de 2026 observadas vão até 30/09. As outras nove fontes não foram
renovadas nesse ensaio. Casos positivos selecionados não comprovam cobertura
universal, titularidade nem validade topológica de todos os imóveis. Cada novo
ciclo deve renovar a conferência de todas as fontes, registrar suas evidências
e repetir os aceites antes de disponibilizar o pacote.

Restauração integral manual e retomada automática após queda não são novos
recursos prioritários desta evolução. Mantém-se como critério obrigatório que
nenhum conjunto incompleto seja liberado para consulta durante a instalação.

### Procedimento do publicador

1. Iniciar um ciclo com `tools/publisher_cycle.py start`.
2. Consultar todas as 11 fontes de `updates/publisher/sources.json`, mesmo quando
   não houver indício de mudança.
3. Registrar data e hora da consulta, página oficial, edição encontrada e uma
   nota curta de evidência. CAPTCHA e autenticação são marcados para revisão
   humana; nunca devem ser contornados.
4. Baixar novamente o artefato oficial quando aplicável, calcular SHA-256 e
   validar estrutura e cobertura em uma pasta de estágio. O banco ativo dos
   usuários nunca é usado como destino desta etapa.
5. Atualizar os pacotes de origem cujo conteúdo ou edição oficial mudou.
   Sem novidade, manter a versão, os bytes e o hash da fonte, registrando a nova
   conferência. Ao fim de cada ciclo quinzenal, gerar uma nova distribuição
   integral datada, mesmo quando nenhuma fonte tiver nova edição.
6. Executar `tools/publisher_cycle.py validate`. Nenhuma das 11 fontes pode ficar
   pendente.
7. Auditar os 36 pacotes e exigir cobertura exata das 11 bases lógicas. Depois,
   montar `catalog.candidate.json`, revisar o relatório HTML e obter aprovação
   de uma segunda pessoa sobre o hash exato do catálogo.
8. Assinar fora do repositório. A chave privada não entra no Git, no plugin, no
   OneDrive nem na tarefa agendada.
9. Montar a publicação de origem com `car-microcredito-installer base-release`.
   Para distribuir bases prontas, executar `prepare-bases` e `prebuilt-release`.
   Homologar instalação nova, upgrade, reinício, consulta, mapa, pré-análise e
   relatórios em cópia isolada; exercitar falhas tratadas e preservação do estado.
   A restauração manual do formato bruto permanece um fluxo separado.
10. Distribuir o `.carbases` integral aprovado. O usuário baixa o arquivo para o
    disco local e clica em **Validar Bases Plugin** e **Aplicar Bases Plugin**.

## Comandos principais

```powershell
uv run python tools/publisher_cycle.py start `
  --config updates/publisher/sources.json `
  --output C:\Projetos\QGIS-Microcredito-Publicador\ciclos\AAAA-MM-DD\revisao.json

uv run python tools/publisher_cycle.py validate `
  --input C:\Projetos\QGIS-Microcredito-Publicador\ciclos\AAAA-MM-DD\revisao.json

uv run car-microcredito-installer base-release `
  --catalog catalog.json `
  --signature catalog.json.sig `
  --package mte=C:\caminho\mte.zip `
  --package embargos=C:\caminho\embargos.zip `
  --output bases-plugin-DD-MM-AAAA.carbases
```

Todos os pacotes declarados no catálogo devem ser informados no último comando.

## Critérios de bloqueio

- fonte não consultada no ciclo;
- página não oficial ou sem HTTPS;
- data/hora de consulta ausente;
- nova edição sem URL do artefato, SHA-256 e pacote candidato;
- catálogo ou pacote incompatível com plugin, banco ou manifesto;
- quantidade diferente de 36 pacotes técnicos ou cobertura diferente das 11
  bases lógicas na release completa;
- divergência de tamanho ou hash;
- nome diferente de `bases-plugin-DD-MM-AAAA.carbases`, data inválida ou
  divergente da emissão do catálogo;
- teste de consulta, mapa, relatório ou restauração com falha;
- ausência de aprovação do hash exato do catálogo.

O ciclo pode terminar como **fonte indisponível** ou **revisão manual**, mas a
base correspondente não deve ser apresentada como atualizada até existir
evidência suficiente.


## Distribuição e recebimento pelo usuário

O fluxo previsto é publicador → biblioteca SharePoint do projeto → download
local pelo usuário → seleção do pacote no plugin já instalado no QGIS. O ZIP
do plugin e o pacote de bases são artefatos separados: a atualização de dados
não exige reinstalar o complemento. Nunca apontar o banco em uso para uma
pasta sincronizada ou abrir o SQLite diretamente no SharePoint.

A pasta de cada publicação deve identificar sua data em DD-MM-AAAA e conter o
pacote `bases-plugin-DD-MM-AAAA.carbases`, seu SHA-256 e uma nota de edição com
fontes conferidas, versões, limites e resultado da homologação. No formato
pré-montado, a data vem de `prepared_at`; o manifesto de integridade cobre os
35 arquivos de dados e conserva a assinatura do catálogo de origem. O banco
derivado não recebe uma nova assinatura manual de autoria.

Site, biblioteca, permissões de publicação/leitura e canal de aviso devem ser
configurados pela equipe antes da distribuição. O plugin não cria essa
biblioteca, não agenda o ciclo quinzenal e não faz download automático. A cópia
já baixada é instalada em processo externo na pasta local fixa; relatórios e
exportações do usuário são preservados.


## Aceites sintéticos no runtime do QGIS

Com o checkout de desenvolvimento e as dependências de teste disponíveis no
Python nativo do QGIS, execute os três pontos de entrada em processos separados:

```powershell
$qgisPython = "C:\Program Files\QGIS 3.40.10\bin\python-qgis-ltr.bat"
& $qgisPython -s -B tools/qgis_base_release_smoke.py --output-root C:\Homologacao\BasesPlugin
& $qgisPython -s -B tools/qgis_external_update_smoke.py --output-root C:\Homologacao\BasesPlugin
& $qgisPython -s -B tools/qgis_fixed_root_workflow_smoke.py --output-root C:\Homologacao\BasesPlugin
```

Cada execução cria uma subpasta nova, usa fixtures sintéticas e isola perfil,
INI, autenticação, temporários e pasta de bases antes de iniciar Qt. Os casos
cobrem pacote/rollback, processo externo e ZIP distribuído, consultas, mapa,
pré-análise e relatório. Resultado, XML e provas de isolamento ficam na saída
informada; falhas ou testes omitidos impedem o aceite.

`--run-id` pode nomear uma execução, desde que a pasta ainda não exista.
`--qa-support` é opcional para dependências somente de teste e é acrescentado
depois das bibliotecas nativas. Não inserir a .venv de desenvolvimento antes das
bibliotecas do QGIS. O bootstrap utiliza o interpretador da própria distribuição
para que os subprocessos isolados encontrem a biblioteca padrão e suas DLLs.

Esses aceites verificam regressões com dados pequenos e não substituem o ensaio
do pacote nacional a distribuir. Nenhum comando acima seleciona a base em uso
na instalação operacional ou exige alterar a política de execução do Windows.
