# Contrato de atualização das bases — catálogo v3

Este contrato separa a publicação das bases do funcionamento normal do plugin.
Nenhuma fonte oficial é consultada ou convertida pelo QGIS: o publicador prepara
os pacotes fora do plugin, registra a evidência oficial e assina o catálogo.

## Estado desta etapa

- a versão do plugin permanece `0.9.5`;
- catálogos legados v1 e v2 continuam legíveis;
- nenhum catálogo de produção é ativado por esta mudança;
- nenhum banco ou GeoPackage é alterado por esta mudança;
- novos catálogos devem usar `schema_version: 3`.

## Cadeia de confiança

1. O publicador consulta a fonte oficial e registra data, hora e URLs em
   `source_evidence`.
2. O pacote é gerado com `package.json` no esquema 1.
3. O SHA-256 e o tamanho do pacote entram no catálogo candidato.
4. Um segundo responsável aprova exatamente o SHA-256 do catálogo candidato.
5. O catálogo aprovado é assinado fora do Git e fora do QGIS.
6. O plugin verifica assinatura, compatibilidade, tamanho, SHA-256 e manifesto
   antes de preparar qualquer atualização.

## Evidência oficial obrigatória

Cada pacote do catálogo v3 declara:

```json
{
  "source_evidence": {
    "official_page_url": "https://fonte-oficial.example/pagina",
    "official_artifact_url": "https://fonte-oficial.example/arquivo",
    "checked_at": "2026-10-14T11:30:00-03:00"
  }
}
```

`official_page_url` e `checked_at` são obrigatórios. A URL do arquivo é
opcional quando a fonte usa CAPTCHA, sessão temporária ou outro mecanismo que
não produz um endereço permanente. Todas as URLs declaradas usam HTTPS e a
consulta não pode ocorrer depois da emissão do catálogo.

## Compatibilidade obrigatória

```json
{
  "compatibility": {
    "minimum_plugin_version": "0.9.5",
    "maximum_plugin_version": "0.9.5",
    "database_schema_version": 4,
    "package_manifest_schema_version": 1
  }
}
```

O plugin pode exibir o catálogo, mas marca o pacote como `inaplicavel` quando a
versão instalada ou o esquema do banco estiver fora do intervalo declarado. A
mesma validação é repetida imediatamente antes do download, impedindo que uma
chamada direta contorne a comparação da interface.

## Compatibilidade retroativa

Catálogos v1 e v2 continuam aceitos para não quebrar publicações já
homologadas. Somente o v3 exige os novos blocos. O pacote v3 exige
`schema_version: 1` no `package.json`; pacotes vinculados a catálogos anteriores
continuam seguindo as regras legadas.

## Critério para iniciar a base piloto

A primeira base somente pode ser publicada em homologação quando:

- a fonte oficial e sua frequência forem confirmadas;
- o pacote for reproduzível e passar nas validações específicas da base;
- o catálogo candidato for aprovado por responsável diferente do preparador;
- aplicação e restauração passarem em uma cópia do ambiente;
- consultas, mapa e relatórios permanecerem funcionais após a restauração.

O piloto não autoriza automaticamente a publicação das demais bases.
