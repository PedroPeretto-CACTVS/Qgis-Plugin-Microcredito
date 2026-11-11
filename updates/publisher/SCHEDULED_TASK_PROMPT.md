# Prompt da tarefa quinzenal do Bases Plugin

Execute a revisão quinzenal das bases do CAR Microcrédito no projeto local
`C:\Projetos\QGIS-Plugin-Microcredito-Pedro-pilot-quilombolas`.

Regras obrigatórias:

1. Trabalhe em estágio isolado. Nunca modifique
   `C:\Projetos\QGIS-Microcredito-Dados` nem uma instalação ativa do QGIS.
2. Inicie o ciclo com `tools/publisher_cycle.py start` e consulte todas as 11
   fontes de `updates/publisher/sources.json`, mesmo quando nenhuma atualização
   for encontrada.
3. Use somente fontes oficiais. Registre URL, data/hora com fuso, data ou edição
   publicada e evidência verificável. Não exponha CPF, CNPJ, CAR ou geometrias de
   usuários.
4. Não contorne CAPTCHA ou autenticação. Marque a fonte como `revisao_manual` e
   solicite a intervenção do líder do projeto.
5. Quando houver nova edição, baixe em estágio, calcule SHA-256, valide estrutura
   e cobertura e gere somente um pacote candidato. Quando não houver mudança,
   registre `sem_nova_edicao` e preserve a versão já aprovada.
6. Valide o relatório completo. Não assine, publique, faça push, abra PR ou
   distribua o **Bases Plugin** (`.carbases`) sem aprovação humana explícita do
   relatório e do hash do catálogo candidato.
7. Execute os testes do publicador e produza um resumo com: 11 fontes
   consultadas, novas edições, fontes sem mudança, bloqueios, pacotes candidatos,
   hashes e ações exigidas. Notifique também quando não houver nova edição, pois
   a conclusão do ciclo é uma evidência operacional.

A tarefa deve rodar a cada 14 dias, segunda-feira às 08:00, no fuso
`America/Sao_Paulo`, no projeto local (não em worktree descartável), porque os
artefatos de estágio são grandes e precisam permanecer disponíveis para revisão.
