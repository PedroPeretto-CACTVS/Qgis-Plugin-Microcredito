# Fluxograma funcional do CAR Microcrédito 0.9.4

Este documento descreve os caminhos da aplicação e os limites entre a
pré-análise automática e a decisão humana. A variante padrão abre a consulta
individual. A variante Usuário Supremo abre a consulta em massa e mantém a
consulta individual como opção separada. Ambas compartilham o mesmo núcleo de
consulta, regras, relatório e atualização.

Os fluxos abaixo cobrem todas as rotas funcionais expostas pelo plugin. Falhas
de validação, arquivo ausente, catálogo inválido ou cancelamento convergem para
um estado seguro: a operação é interrompida, o motivo é apresentado e a base
ativa não é substituída.

## 1. Mapa geral

```mermaid
flowchart TD
    A["QGIS > Complementos > CAR Microcrédito"] --> V{"Variante instalada"}
    V -->|"Padrão"| I["Consulta individual"]
    V -->|"Usuário Supremo"| L["Consulta em massa por Excel"]
    V -->|"Usuário Supremo"| I
    A --> U["Bases de consulta e atualizações"]

    I --> ID["Identificar operação e imóvel"]
    ID --> Q["Consultas locais e cruzamentos territoriais"]
    Q --> P["Pré-análise das regras"]
    P --> D["Decisão do técnico"]
    P --> R["Prévia ou relatório final"]
    D --> R

    L --> X["Validar e expandir linhas da planilha"]
    X --> QL["Executar o mesmo núcleo para cada CAR"]
    QL --> RL["PDF consolidado e JSON de auditoria"]

    U --> C["Inventário local e catálogo assinado"]
    C --> AT["Atualizar uma base"]
    C --> RE["Restaurar a versão anterior"]

    PUB["Fluxo externo do publicador"] --> QA["Inventariar e validar fontes"]
    QA --> PK["Montar pacote de base"]
    PK --> SG["Dupla aprovação e assinatura"]
    SG --> C
```

```mermaid
flowchart LR
    DB[("SQLite local\nSicor + MMA/MCR + MTE")]
    CAR[("GeoPackages SICAR\n27 UFs")]
    AMB[("GeoPackages ambientais")]
    UI["Plugin QGIS"]
    NET["Catálogo e pacotes\nHTTPS assinados"]
    OUT["Mapa, PDF e JSON locais"]

    DB --> UI
    CAR --> UI
    AMB --> UI
    UI --> OUT
    NET -->|"somente atualização"| UI
    UI -. "CPF/CNPJ, CAR, geometrias e resultados não são enviados" .-> OUT
```

## 2. Consulta individual

```mermaid
flowchart TD
    E["Abrir consulta individual"] --> CFG{"Banco SQLite e pasta CAR válidos?"}
    CFG -->|"Não"| CFGE["Selecionar os caminhos locais\ne interromper até corrigir"]
    CFG -->|"Sim"| EN{"Como o imóvel será localizado?"}

    EN -->|"CPF ou CNPJ"| DOC["Buscar operações no Sicor local"]
    DOC --> VD{"Documento válido e há vínculo?"}
    VD -->|"Não"| SEM["Mostrar ausência ou erro\ne permitir nova consulta"]
    VD -->|"Sim"| MC{"Há mais de um CAR?"}
    MC -->|"Sim"| ESC["Técnico escolhe o CAR"]
    MC -->|"Não"| CAR["CAR definido"]
    ESC --> CAR

    EN -->|"Número do CAR"| CAR
    EN -->|"Coordenada WGS84"| PT["Localizar polígono SICAR que contém o ponto"]
    EN -->|"Link Google Maps"| GM["Extrair coordenada do link"]
    GM --> PT
    PT --> MP{"Mais de um polígono?"}
    MP -->|"Sim"| ESC
    MP -->|"Não"| CAR

    CAR --> FIN["Resolver fonte: AUTO pela UF\nou FCO, FNO, OGU manual"]
    FIN --> LIN["Selecionar linha Pronaf B"]
    LIN --> MMA["Consultar MMA/MCR e operações no SQLite"]
    LIN --> DOK{"Já há documento associado\npara consultar o MTE?"}
    DOK -->|"Sim"| MTE["Consultar MTE com documentos associados"]
    DOK -->|"Não"| CP["Opcional: procurar CPF/CNPJ vinculado no Sicor"]
    CP --> CPH{"Documento encontrado?"}
    CPH -->|"Sim"| MASK["Mostrar mascarado; revelar item selecionado\npor 30 s somente após confirmação"]
    CPH -->|"Não"| OWNER["Técnico informa CPF/CNPJ\ndo proprietário ou possuidor"]
    MASK --> MTE
    OWNER --> MTE

    MMA --> GEO{"Geometria disponível?"}
    GEO -->|"Polígono SICAR local"| GS["Usar polígono cadastral"]
    GEO -->|"Sem polígono e uma operação compatível"| GG["Reconstruir gleba do Sicor"]
    GEO -->|"Ausente ou operação ambígua"| INC["Interromper como inconclusivo\nsem inventar geometria"]

    GS --> CR["Cruzar bases socioambientais locais"]
    GG --> CR
    MTE --> B["Consolidar listas e evidências do banco"]
    CR --> B
    B --> EVI["MMA/MCR + MTE + embargos + TI + quilombolas\n+ UC + florestas públicas tipo B + PRODES"]
    EVI --> PA["Gerar classificação preliminar por regra\ne hash da pré-análise"]
    PA --> OLD{"Existe decisão técnica anterior?"}
    OLD -->|"Não"| TEC{"Ação do técnico"}
    TEC -->|"Revisar regras"| CHECK["Conferir fundamento, exceções e documentos"]
    CHECK --> DEC["Registrar decisão, justificativa, data\ne hash da pré-análise"]
    TEC -->|"Carregar no mapa"| MAP["Criar grupo de camadas no projeto QGIS"]
    TEC -->|"Pré-análise"| RULES["Mostrar conclusão, fundamento\ne providência de cada regra"]
    TEC -->|"Prévia"| PRE["Gerar e abrir PDF provisório"]
    TEC -->|"Relatório final"| DIR["Escolher pasta de destino"]
    DIR --> OUT["Gerar PDF final e JSON de auditoria"]
    DEC --> OUT
    OLD -->|"Sim"| HASH{"Resultados ou regras mudaram\ndesde a decisão anterior?"}
    HASH -->|"Sim"| INVALID["Invalidar decisão antiga\ne exigir nova revisão humana"]
    HASH -->|"Não"| TEC
    INVALID --> TEC
```

Observações:

- a consulta de CPF/CNPJ por CAR usa somente o Sicor local e não prova
  titularidade atual;
- se nenhum documento for encontrado, o técnico informa o CPF/CNPJ do
  proprietário ou possuidor para a consulta MTE;
- a ferramenta aponta possível impedimento, ausência de indício, lacuna ou
  necessidade de validação. A contratação continua sendo decisão humana;
- a decisão fica vinculada ao hash da pré-análise e é invalidada se a
  pré-análise mudar.

## 3. Consulta em lote

```mermaid
flowchart TD
    A["Salvar o modelo Excel da versão instalada"] --> B["Preencher uma operação por linha"]
    B --> C["Obrigatórios: CPF_CNPJ, FONTE_RECURSOS e LINHA_CREDITO"]
    C --> D["Opcionais: CAR, PROPRIETARIO_POSSUIDOR,\nREFERENCIA_INTERNA e OBSERVACAO"]
    D --> V["Validar planilha e hash do arquivo"]
    V --> OK{"Todos os valores são válidos?"}
    OK -->|"Não"| ER["Bloquear antes de consultar\ne indicar a linha a corrigir"]
    OK -->|"Sim"| HC{"A linha possui CAR?"}
    HC -->|"Sim"| T["Criar uma tarefa para o CAR informado"]
    HC -->|"Não"| EX["Buscar no Sicor todos os CARs distintos do CPF/CNPJ"]
    EX --> NC{"Algum CAR válido?"}
    NC -->|"Não"| FL["Registrar falha da linha\ne seguir com as demais"]
    NC -->|"Sim"| T
    T --> DD["Remover pares CPF/CNPJ + CAR duplicados"]
    DD --> LOOP["Processar cada tarefa sem interromper as demais por uma falha"]
    LOOP --> GEO["Polígono SICAR; se ausente, gleba Sicor única"]
    GEO --> GEOK{"Geometria confiável encontrada?"}
    GEOK -->|"Não"| TF["Registrar falha da tarefa\ne seguir o lote"]
    GEOK -->|"Sim"| BASES["Consultar MTE, MMA/MCR e cruzar bases ambientais"]
    BASES --> PA["Pré-análise com fonte e linha daquela linha do Excel"]
    PA --> MAP{"Incluir mapa em cada CAR?"}
    MAP -->|"Sim"| IMG["Renderizar mapa"]
    MAP -->|"Não"| AG["Agregar resultado"]
    IMG --> AG
    AG --> CANCEL{"Usuário solicitou cancelamento?"}
    CANCEL -->|"Sim"| PART["Marcar tarefas restantes como canceladas"]
    CANCEL -->|"Não"| NEXT{"Restam tarefas?"}
    NEXT -->|"Sim"| LOOP
    NEXT -->|"Não"| OUT["PDF consolidado + JSON de auditoria"]
    FL --> NEXT
    TF --> NEXT
    PART --> OUT
    OUT --> SUM["Resumo: linhas, tarefas, analisados,\nduplicados, falhas, cancelados e SHA-256"]
```

### Interação dos novos campos

| Campo | Consulta individual | Consulta em lote | Saída |
|---|---|---|---|
| Fonte de recursos | sugestão pela UF ou escolha manual | `FONTE_RECURSOS` com AUTO, FCO, FNO ou OGU | pré-análise, PDF e JSON, incluindo o modo de seleção |
| Linha de crédito | lista fechada na tela | `LINHA_CREDITO` por linha, com lista suspensa | pré-análise, PDF e JSON |

As combinações não são escolhidas uma única vez para o lote. Isso permite,
por exemplo, que uma linha seja FNO/Pronaf B e outra seja OGU/Pronaf B para
mulheres sem mistura de contexto. OGU é tratado como fonte de recursos, não
como fundo constitucional.

## 4. Pesquisa, aplicação e restauração de atualizações

```mermaid
flowchart TD
    A["Abrir Bases de consulta e atualizações"] --> DB{"car_microcredito.db válido?"}
    DB -->|"Não"| DBE["Solicitar banco existente\nsem alterar dados"]
    DB -->|"Sim"| LOCK{"Há outra atualização em curso?"}
    LOCK -->|"Sim"| STOP["Bloquear operação concorrente"]
    LOCK -->|"Não"| INV["Inventariar 11 bases lógicas,\nversões e cobertura locais"]
    INV --> PC["Procurar atualizações"]
    PC --> AUTH{"Catálogo privado do GitHub?"}
    AUTH -->|"Sim"| TOKEN["Ler token somente de leitura do banco de autenticação do QGIS"]
    AUTH -->|"Não"| GET["Baixar catálogo e assinatura por HTTPS"]
    TOKEN --> GET
    GET --> VAL["Validar HTTPS, redirecionamentos, limites,\nesquema, datas, URLs e assinatura RSA/SHA-256"]
    VAL -->|"Inválido"| SAFE["Bloquear e preservar a base ativa"]
    VAL -->|"Válido"| CMP["Comparar versões, pacotes e hashes\ncom o inventário local"]
    CMP -->|"Nenhuma nova"| ATUAL["Mostrar bases atualizadas"]
    CMP -->|"Disponível"| SEL["Selecionar base e confirmar"]
    SEL --> DL["Baixar ou retomar pacote parcial\nsem expor dados de consulta"]
    DL --> PKG["Conferir tamanho, SHA-256, ZIP seguro,\nmanifesto e payloads"]
    PKG --> STR{"Estratégia assinada"}

    STR -->|"replace_file"| RF["Validar GeoPackage/arquivo em estágio"]
    STR -->|"import_mma_mcr"| MMA["Copiar banco e importar MMA/MCR"]
    STR -->|"import_mte"| MTE["Copiar banco e importar MTE"]
    STR -->|"import_sicor"| SICOR["Copiar banco e importar Sicor\npor payload e escopo"]
    MMA --> QC["PRAGMA quick_check na cópia"]
    MTE --> QC
    SICOR --> QC
    RF --> BK["Criar histórico da versão ativa"]
    QC --> BK
    BK --> SWAP["Promover arquivo ou banco validado\npor troca atômica"]
    SWAP --> REG["Registrar versão, hash, data da fonte\ne pacote em estado.json"]
    REG --> DONE["Reinventariar e mostrar conclusão"]
    DL -->|"Falha"| SAFE
    PKG -->|"Falha"| SAFE
    RF -->|"Falha"| SAFE
    QC -->|"Falha"| SAFE

    INV --> REST{"Existe ponto de restauração?"}
    REST -->|"Sim"| CONF["Confirmar Restaurar versão anterior"]
    REST -->|"Não"| NOREST["Manter restauração indisponível"]
    CONF --> RV["Validar metadados, alvo e cópia anterior\nem área temporária"]
    RV -->|"Inválida"| SAFE
    RV -->|"Válida"| UNDO["Preservar a versão atual\ncomo novo ponto para desfazer"]
    UNDO --> RSWAP["Restaurar por troca segura"]
    RSWAP --> RREG["Restaurar registro e reinventariar"]
```

A busca de atualizações envia ao publicador somente requisições do catálogo
e do pacote selecionado. CPF/CNPJ, CAR, geometrias e resultados de consulta não
são enviados ao GitHub. A restauração é integralmente local.

## 5. Preparação e publicação de uma atualização

```mermaid
flowchart TD
    SRC["Fontes oficiais locais"] --> INV["Inventariar 11 bases e 36 pacotes previstos"]
    INV --> LIM{"Fontes presentes e abaixo\ndo limite por asset?"}
    LIM -->|"Não"| HOLD["Bloquear publicação e listar pendências"]
    LIM -->|"Sim"| STRUCT["Validar GeoPackages, cabeçalhos Sicor,\nMMA/MCR, MTE e integridade SQLite"]
    STRUCT --> ROUTE["Auditar exceções de UF do SICAR\ncom saída somente agregada"]
    ROUTE --> AUTHZ{"Fonte autorizada para publicação?"}
    AUTHZ -->|"Não"| HOLD
    AUTHZ -->|"Sim"| PKG["Gerar ZIP e package.json\ncom hashes e estratégia"]
    PKG --> TPL["Preencher candidato de catálogo v2"]
    TPL --> CAND["Preparar candidato e hash de aprovação"]
    CAND --> REVIEW["Segundo responsável revisa e aprova o hash"]
    REVIEW --> SIGN["Assinar externamente com chave privada RSA"]
    SIGN --> PUB["Publicar catalog.json, assinatura e assets"]
    PUB --> CLIENT["Cliente QGIS valida antes de oferecer a atualização"]
```

A chave privada permanece fora do Git, do OneDrive e do ZIP do plugin. O Sicor
possui uma barreira adicional de custódia: a existência técnica dos arquivos
não autoriza seu espelhamento.

## 6. Resultado automático e decisão humana

```mermaid
flowchart LR
    E["Evidência por regra"] --> C{"Classificação automática"}
    C --> PI["Possível impedimento"]
    C --> SI["Sem indício de impedimento"]
    C --> IC["Inconclusivo"]
    C --> VT["Requer validação técnica"]
    PI --> H["Revisão humana"]
    SI --> H
    IC --> H
    VT --> H
    H --> D["Decisão + justificativa + data + hash"]
    D --> R["PDF e JSON"]
```

A aplicação nunca converte a pré-análise em aprovação ou recusa de
crédito. Uma mudança nas evidências ou nas regras altera o hash e invalida a
decisão anterior para nova revisão.

## 7. Responsabilidade de cada componente

| Componente | Responsabilidade |
|---|---|
| QGIS e janelas do plugin | entrada, escolha, progresso, mapa e mensagens |
| SQLite Sicor/MMA/MTE | operações, vínculos e listas importadas |
| SICAR e bases ambientais locais | geometria e cruzamentos territoriais |
| Motor de pré-análise | organizar evidências e indicar conclusão preliminar |
| Técnico de crédito | conferir documentos, exceções, enquadramento e decidir |
| Publicador central | assinar e disponibilizar catálogo e pacotes autorizados |
| Atualizador local | validar, preservar a versão anterior e promover a nova base |

## 8. Saídas e estados finais

| Caminho | Saída normal | Saída segura em falha/cancelamento |
|---|---|---|
| Consulta individual | camadas QGIS, pré-análise, PDF e JSON | mensagem objetiva; nenhum resultado é inventado |
| Consulta em lote | PDF consolidado e JSON com hash da planilha | relatório parcial com falhas, duplicados e cancelados |
| Consulta CPF/CNPJ por CAR | documentos mascarados; revelação temporária confirmada | nenhum documento exportado ou registrado em log |
| Atualização | base promovida e versão registrada | base ativa preservada; estágio temporário removido |
| Restauração | versão anterior ativa e novo ponto para desfazer | versão atual preservada |
| Publicação | catálogo e pacotes assinados | publicação bloqueada diante de fonte, aprovação ou assinatura inválida |
