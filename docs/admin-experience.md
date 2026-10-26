# Melhorias de experiência — 26/10/2026

Publicada em 26/10/2026 em https://kemilyepedro.com.br/. A base `e08168d` foi comparada com a aplicação em execução antes da publicação. Imagem: `kemily-e-pedro-web-jekf2r:admin-ux-20261026`.

- Confirmações: busca imediata por nome, telefone, código e recado; filtros de resposta e grupo; datas; ordenação alfabética e cronológica; exportação CSV da seleção. Confirmações parciais têm filtro próprio e também aparecem em confirmados.
- Campanhas: filtros, segmentação por resposta combinada com grupo, revisão nominal de destinatários e criação de um novo lembrete a partir de uma campanha existente. A ação de criar/salvar um lembrete não inicia o envio. No dia desejado, revisar o público e confirmar a entrada na fila. Não há agendamento automático por data nesta entrega.
- Lembretes para quem ainda não respondeu excluem confirmações e recusas, usam o público atualizado no início do envio e cancelam mensagens ainda na fila quando o contato responde. A frequência e as proteções existentes da fila são preservadas.
- Compras: resumo de recebidos e pagamentos em aberto, status em português, busca, datas, ordenação por valor e nome, CSV e detalhes recolhíveis. A exclusão de registro não executa cancelamento/reembolso; compras aprovadas não apresentam essa ação na interface.
- Perguntas frequentes: busca, visibilidade, editor, publicar/ocultar e setas para reorganizar a sequência.
- Mural admin: cartões de moderação, busca por autor e conteúdo, status e período. A publicação passa a usar POST protegido por CSRF.
- Mural público: nova composição responsiva, cartões de recados, identificação de autores e chamada para confirmar presença. Os recados aprovados e a paginação são mantidos.
- Monogramas públicos: `K ♥ P` em cabeçalhos, menus e rodapés.

## Validação

`python -m unittest discover -s tests -v`

`python tests/browser_admin_experience.py` usa Playwright/Chrome em modo headless, banco SQLite em memória e dados sintéticos. Confere busca sem acentos, resposta parcial, combinação de filtros, estado vazio, ordenação, exportação, segmentação de lembrete e seis telas em 1440px/390px sem rolagem horizontal da página. Capturas em `.preview/admin-experience/`.

Não foram iniciadas campanhas nem enviados WhatsApps durante a preparação e a publicação. As comparações de registros antes e depois não apontaram alterações nos dados existentes. As telas autenticadas e os recursos estáticos responderam HTTP 200; a home e o mural público também foram conferidos no navegador. O WhatsApp está sem pareamento salvo e o início automático já estava desativado na configuração; conecte pelo painel antes de disparar campanhas.

## Histórico da publicação

Conferir o código atual do VPS e preservar mudanças posteriores a `e08168d`. Fazer backup do banco e da imagem existente. A inicialização adiciona somente `whatsapp_campaign.target_rsvp VARCHAR(20) NOT NULL DEFAULT 'all'` quando a coluna não existe; campanhas existentes mantêm seu público anterior. Publicar pelo fluxo existente do Dokploy e verificar as telas autenticadas, o mural público, a home e a saúde da fila sem iniciar campanhas reais.

Backups e registros privados da publicação estão em `/root/kemilyepedro-admin-ux-20261026/`, no VPS. Validação: 109 testes Python aprovados, verificações de sintaxe JavaScript e testes Node da fila e dos contatos aprovados. O banco, os uploads e a imagem anterior foram preservados.
