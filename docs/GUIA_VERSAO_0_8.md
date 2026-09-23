# CAR Microcrédito 0.8

Esta versão deve ser instalada somente depois da aprovação dos testes e da preparação de uma cópia do banco. O backup da versão anterior deve permanecer guardado. Reinicie o QGIS antes de trocar de versão.

## O que muda

- Listas sem carga validada ou com validade vencida produzem consulta inconclusiva.
- O relatório não declara o imóvel apto apenas por não constar na publicação MMA.
- A seleção do CAR é conferida antes de usar a gleba de uma operação.
- Geometria incompleta ou inválida produz aviso, sem considerar a área totalmente analisada.
- Geometrias ambientais reparáveis são corrigidas para o cruzamento, com aviso e identificador no relatório; geometrias que não podem ser reparadas mantêm a fonte inconclusiva.
- Cada relatório é guardado em uma pasta própria, com PDF, JSON e evidências disponíveis.
- A pasta do relatório inclui o mapa e a conferência dos arquivos. A geometria original permanece na pasta interna da execução, identificada por seu hash no JSON; seus atributos podem conter informações reservadas e não são copiados para a pasta compartilhável.
- Lotes registram falhas e cancelamentos. A planilha é lida novamente ao iniciar.

## Preparação administrativa do banco

O banco da versão 0.7 não deve ser aberto para gravação pela nova consulta. O comando `migrar-copia` cria uma cópia independente e migra apenas essa cópia. Cargas antigas ficam inativas até receberem competência e abrangência explícitas; nenhum histórico é apagado.

Com o Python do projeto e `src` no PYTHONPATH:

```text
python -m car_microcredito migrar-copia --origem BANCO_ANTERIOR.db --destino BANCO_NOVO.db
python -m car_microcredito --db BANCO_NOVO.db status
python -m car_microcredito --db BANCO_NOVO.db ativar-importacao ID --escopo COMPETENCIA_ABRANGENCIA
```

O escopo identifica os dados que uma atualização substitui. Arquivos complementares de períodos distintos devem ter escopos distintos. Duas edições do mesmo conjunto devem ter o mesmo escopo. Não escolher automaticamente o último arquivo quando houver dúvida sobre sua abrangência.

Para a publicação MMA, o escopo é `nacional` e é necessário informar `--validade-ate AAAA-MM-DD`. O prazo é definido pelo responsável pela atualização da fonte; não é uma garantia de validade jurídica. Registros antigos com rejeições exigem nova importação válida antes de serem ativados.

O cadastro MTE deve ser reimportado com o script `importar_trabalho_escravo.py`, indicando `--db` e `--validade-ate`. Arquivo vazio, incompatível ou com duplicações não substitui a lista anterior.

Novas importações Sicor exigem `--escopo`. Os arquivos fornecidos na mesma chamada são confirmados em conjunto; se um falhar, a chamada é revertida. Para uma atualização completa, fornecer todos os arquivos correspondentes à edição. A publicação MMA pode ser importada com `import-mma-mcr --arquivo ARQUIVO --validade-ate AAAA-MM-DD`.

## Conferência antes de instalar

Os testes automatizados usam dados sintéticos e o QGIS 3.40.10 com Python 3.12.11. Conferir também casos reais escolhidos pelo responsável, usando a cópia preparada do banco. A atualização das bases nacionais e a determinação dos prazos de revisão não são feitas automaticamente.

As janelas continuam sendo de triagem para revisão humana. A ausência de uma ocorrência em uma fonte não representa aprovação integral de crédito.

## Pacotes

`build_release.py` monta as versões individual e Supremo diretamente dos fontes, com hashes e verificação das entradas. `build_portable_package.py` exige uma pasta de dados já migrada e homologada, valida as 27 UFs e usa cópias consistentes dos bancos. Não utilizar a pasta de estágio de uma compilação antiga.

## Retorno à versão anterior

Fechar o QGIS. Preservar relatórios novos. Restaurar código e banco compatíveis a partir do backup, sem misturar arquivos auxiliares antigos dos bancos com a cópia restaurada. A instalação em uso só deve ser substituída após essa conferência.
