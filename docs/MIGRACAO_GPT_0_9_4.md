# Migração das funcionalidades 0.9.x

Este documento registra a incorporação das funcionalidades que existiam no
projeto descontinuado `GPT/repos/Qgis_plugin-microcredito` ao projeto atual.
O código foi acomodado na arquitetura vigente, sem preservar o pacote legado
`car_microcredito` nem seus caminhos internos.

## Mapa da transição

| Funcionalidade de origem | Implementação atual | Garantia principal |
| --- | --- | --- |
| Catálogo HTTPS assinado e pacotes locais | `infrastructure/updates.py` | RSA/SHA-256, limites de download e ZIP, redirecionamento seguro e promoção atômica |
| Atualização de Sicor, MMA/MCR, MTE e GeoPackage | serviços atuais de importação + `LocalUpdater` | preparação em cópia, integridade SQLite/GeoPackage e restauração da versão anterior |
| Histórico e desfazer restauração | `.atualizacoes/.h` e registro `estado.json` | ponto de restauração auditável e recuperação do estado anterior |
| Inventário das bases | `domain/base_catalog.py` | nomes regulatórios separados dos componentes técnicos |
| Auditoria das fontes de produção | `tools/inventory_production_sources.py`, `tools/validate_production_sources.py` e `tools/audit_sicar_state_routing.py` | barreira técnica de publicação e relatórios agregados sem expor identificadores CAR |
| Consulta CPF/CNPJ por CAR | `plugin/car_document_window.py` | máscara por padrão, confirmação antes da revelação, ocultação automática em 30 segundos e nenhuma exportação |
| Fonte de recursos por UF e linhas Pronaf B | `domain/financing.py` | sugestão automática identificada como sugestão e seleção manual preservada |
| Pré-análise individual e em lote | `application/pre_analysis.py` | regras determinísticas e explicáveis, sem aprovação ou recusa automática |
| Decisão técnica | interface e relatório | justificativa humana, data, hash da pré-análise e invalidação quando os resultados mudam |
| Planilha de lote | `modelo_consulta_lote.xlsx` | campos obrigatórios, listas de seleção e validação no importador |

O fluxo consolidado está em `FLUXOGRAMA_APLICACAO_0_9_4.md`, e a matriz
regulatória ampliada foi mantida em `matriz_conformidade_mcr_fno_fco.md`.
Manuais de teste 0.9.2/0.9.3, URLs de homologação e DOCX gerados não foram
copiados: estavam vinculados ao repositório descontinuado e foram substituídos
por estas fontes canônicas da versão atual.

## Publicação segura de bases

1. Execute `tools/inventory_production_sources.py` e
   `tools/validate_production_sources.py` nas fontes locais. Quando necessário,
   use `tools/audit_sicar_state_routing.py`; seu resultado contém somente
   contagens e prefixos, nunca os identificadores CAR.
2. Gere o pacote com `car-microcredito-installer update-package`.
3. Preencha um catálogo baseado em `updates/producao/catalog.template.example.json`.
4. Execute `tools/build_signed_catalog.ps1 -PrepareOnly` para gerar o candidato
   e seu hash; um segundo responsável registra a aprovação com base em
   `approval.example.json`.
5. Execute novamente o mesmo utilitário com `-ApprovalPath` e
   `-PrivateKeyPath`. A chave privada não pode ficar no Git, no OneDrive ou no
   pacote QGIS.
6. Publique `catalog.json`, `catalog.json.sig` e os assets no repositório atual.
7. Valide a aplicação e a restauração em uma cópia antes de liberar o catálogo.

O cliente envia somente requisições do catálogo e dos pacotes. CPF/CNPJ, CAR,
geometrias e resultados de análise permanecem locais.

## Critérios de aceite

- suíte Python, lint e tipagem estrita aprovados;
- ZIPs normal e supremo contêm os módulos e o modelo de lote atuais;
- versão única `0.9.4` no pacote e nos metadados;
- catálogo inválido, pacote truncado, ZIP inseguro ou base inconsistente não
  substituem dados ativos;
- relatório distingue pré-análise automática da decisão técnica humana;
- o diretório legado só pode ser removido depois destas verificações.
