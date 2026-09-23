# Decisões necessárias para ativar as bases

A cópia migrada está íntegra, mas as cargas antigas ficaram inativas por segurança. A ativação deve ocorrer somente depois que o responsável pelos dados confirmar a abrangência e o prazo de revisão.

## Informações já verificadas

| Base | Informação encontrada | Decisão necessária |
|---|---|---|
| Sicor, mutuários | Há uma carga menor de 1.416.657 registros e outra de 18.497.604 registros. A maior foi importada em 10/09/2026. | Confirmar se a carga maior representa o histórico nacional completo e qual competência deve constar no sistema. |
| Sicor, propriedades | Há uma carga menor de 2.248.071 registros e outra de 27.707.382 registros. A maior foi importada em 10/09/2026. | Confirmar se a carga maior representa o histórico nacional completo e se pertence à mesma edição dos mutuários. |
| Sicor, operações e complementos | As cargas disponíveis foram importadas em 09/09/2026. | Confirmar a abrangência e se elas podem ser combinadas com as cargas maiores de mutuários e propriedades. |
| Sicor, glebas atuais | A carga `SICOR_GLEBAS_CONTRAT.gz` tem 4.327.646 registros sem rejeições. | Confirmar a competência e abrangência. |
| Sicor, glebas WKT de 2020 | Foram aceitos 885.547 registros e rejeitados 3.166. | Não ativar enquanto as rejeições não forem explicadas ou a fonte não for reimportada sem erro. |
| MMA/MCR | A publicação tem 130.832 registros e data interna máxima de 17/08/2026. | Definir até qual data essa publicação pode ser usada antes de exigir atualização. |
| MTE | O cadastro tem 579 empregadores, foi importado em 11/09/2026 e contém datas de inclusão até 04/09/2026. | Confirmar a edição oficial e definir até qual data ela pode ser usada antes de exigir atualização. |

## Valores que o sistema precisa receber

1. Nome da competência e abrangência da edição Sicor escolhida, por exemplo `2026-09-nacional`, somente se essa descrição for confirmada pela origem dos arquivos.
2. Data limite de revisão da publicação MMA/MCR.
3. Data limite de revisão do cadastro MTE.
4. Confirmação de que operações, complementos e glebas pertencem ao conjunto compatível com mutuários e propriedades.

Enquanto essas informações não forem definidas, a versão 0.8 mantém as listas como inconclusivas e não mistura automaticamente cargas de períodos possivelmente diferentes.
