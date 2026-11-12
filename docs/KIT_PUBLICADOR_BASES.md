# Bases Plugin — Kit do Publicador

## Objetivo

Separar a operação administrativa da experiência do usuário. **Bases Plugin** é
o nome da release geral de dados. A release completa contém todas as 11 bases
lógicas, não apenas a base do CAR. O plugin QGIS não
consulta fontes oficiais, não guarda credenciais e não publica dados. Ele recebe
um arquivo `.carbases`, confere a assinatura e aplica somente os pacotes
compatíveis e íntegros.

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

O arquivo `.carbases` é um ZIP64 com esta estrutura fixa:

```text
catalog.json
catalog.json.sig
packages/<id-do-pacote>.zip
```

O nome também integra o contrato de publicação e deve seguir exatamente
`bases-plugin-DD-MM-AAAA.carbases`. A data identifica a emissão da atualização e
deve coincidir com a data de `issued_at` do catálogo assinado. Nome sem data,
data inexistente, outra extensão ou divergência com o catálogo bloqueiam a
montagem do arquivo.

O catálogo assinado declara o tamanho e o SHA-256 de cada pacote. Arquivos
ausentes, adicionais, duplicados ou divergentes bloqueiam a publicação antes de
qualquer alteração local. Se uma base falhar durante a aplicação, as bases já
aplicadas no mesmo lote são restauradas automaticamente.

## Rotina quinzenal

### Execução local fora do QGIS

A validação do `.carbases`, a importação e a restauração são executadas por um
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

**Limites desta etapa:** o motor ainda importa os dados na máquina do usuário,
fora do QGIS; disco, CPU e duração continuam relevantes. Não é ainda uma
publicação com banco nacional pré-montado e ativação instantânea. A preparação
atual é feita por componente, com reversão do lote nas falhas tratadas. O botão
de restauração manual restaura o último componente, não a publicação inteira.
Queda de energia/encerramento forçado requer verificação técnica, não há retomada
automática prometida. A rotina quinzenal abaixo é independente desta execução
local e não é criada automaticamente ao instalar o plugin.

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
5. Gerar pacote candidato somente quando a edição ou o conteúdo oficial mudar.
   Uma consulta sem novidade mantém a versão da fonte e ainda integra o relatório
   quinzenal.
6. Executar `tools/publisher_cycle.py validate`. Nenhuma das 11 fontes pode ficar
   pendente.
7. Auditar os 36 pacotes e exigir cobertura exata das 11 bases lógicas. Depois,
   montar `catalog.candidate.json`, revisar o relatório HTML e obter aprovação
   de uma segunda pessoa sobre o hash exato do catálogo.
8. Assinar fora do repositório. A chave privada não entra no Git, no plugin, no
   OneDrive nem na tarefa agendada.
9. Montar o arquivo final com `car-microcredito-installer base-release` e homologar
   aplicação, consulta, mapa, pré-análise, relatórios e restauração em cópia
   isolada.
10. Distribuir o `.carbases` aprovado. O usuário apenas seleciona o arquivo e
    clica em **Validar Bases Plugin** e **Aplicar Bases Plugin**.

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
