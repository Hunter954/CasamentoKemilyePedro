# Casamento Kemily & Pedro

Site de casamento em Flask com painel administrativo, RSVP, mural, lista de presentes, Mercado Pago e campanhas de WhatsApp.

## WhatsApp — motor Baileys (mesma lógica do Reivilo)

A integração antiga por Z-API foi substituída por um processo Node/Baileys executado no mesmo serviço do site. A sessão do WhatsApp é persistida no PostgreSQL na tabela `whatsapp_auth`, evitando perder o pareamento a cada redeploy.

Fluxo no painel:
1. Acesse **Conexão WhatsApp** e leia o QR Code.
2. Cadastre/organize os contatos e tags.
3. Crie a campanha com mensagem e imagem opcional.
4. Revise o público e envie em lotes.
5. Acompanhe enviados e erros no histórico.

Placeholders das campanhas: `%contato%`, `%codigo%`, `%nome_noivos%`, `%site_url%`, `%data_casamento%`, `%horario_casamento%`, `%local_casamento%`, `%endereco_casamento%`, `%cidade_casamento%` e `%rota_url%`.

## Railway

O projeto usa `Dockerfile` para instalar Python + Node 20 no mesmo container. Mantenha o PostgreSQL ligado ao serviço e configure `DATABASE_URL`.

Variáveis principais:
- `DATABASE_URL` — PostgreSQL do Railway (obrigatória em produção e para persistência da sessão WhatsApp)
- `SECRET_KEY`
- `ADMIN_EMAIL`
- `ADMIN_PASSWORD`
- `UPLOAD_DIR` — opcional; use volume para uploads persistentes
- `WA_SESSION_ID` — opcional; padrão `kemily-pedro-casamento`
- `WA_DISABLE_AUTO_START=true` — opcional para impedir tentativa automática de reconexão no boot
- `WHATSAPP_SEND_DELAY` — intervalo entre disparos, padrão `1.2` segundo

A integração antiga da Z-API pode permanecer com colunas/rotas legadas no banco por compatibilidade, mas não é usada pelo painel nem pelo disparo atual.

## Lista de presentes

Cards responsivos com fotos quadradas, preço em destaque, busca, filtro por valor e ordenação. Fotografias locais em `app/static/images/gifts`; uploads e URLs do painel continuam funcionando. Falhas de imagem exibem uma composição alternativa.

O catálogo de `app/gift_catalog.py` mantém seis opções iniciais para bancos vazios e acrescenta 12 presentes (R$ 49,90 a R$ 899,90) uma única vez. A tabela `gift_catalog_release` registra a aplicação. Presentes existentes, preços, disponibilidade e compras são preservados. Presentes excluídos ou desativados depois da atualização não são recriados nos próximos reinícios. Revise nomes, valores e imagens pelo painel administrativo.

Validação: `python -m unittest discover -s tests -v` (SQLite em memória, sem pagamentos ou envio de mensagens).

Interações JavaScript: `node tests/test_gift_filters.mjs`.
