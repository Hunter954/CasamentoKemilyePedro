# Casamento Kemily & Pedro

Site de casamento em Flask com painel administrativo, RSVP, mural, lista de presentes, Mercado Pago e campanhas de WhatsApp.

## WhatsApp — motor Baileys (mesma lógica do Reivilo)

A integração antiga por Z-API foi substituída por um processo Node/Baileys executado no mesmo serviço do site. A sessão do WhatsApp é persistida no PostgreSQL na tabela `whatsapp_auth`, evitando perder o pareamento a cada redeploy.

Fluxo no painel:
1. Acesse **Conexão WhatsApp** e leia o QR Code.
2. Cadastre/organize os contatos e tags.
3. Crie a campanha com mensagem e imagem opcional.
4. Ajuste o intervalo (padrão: 15 segundos) e inicie o envio aos pendentes.
5. Acompanhe a fila, pause ou retome os envios. Revise conversas com falha antes de reenviar.

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

A frequência das campanhas é configurada no painel e persistida no banco, entre 15 e 600 segundos. A antiga variável `WHATSAPP_SEND_DELAY` não controla mais campanhas. Veja [a operação da fila](docs/campaign-queue.md).

A integração antiga da Z-API pode permanecer com colunas/rotas legadas no banco por compatibilidade, mas não é usada pelo painel nem pelo disparo atual.

## Lista de presentes

Cards responsivos com fotos quadradas, preço em destaque e contador de presentes cadastrados. Fotografias locais em `app/static/images/gifts`; uploads e URLs do painel continuam funcionando. Falhas de imagem exibem uma composição alternativa. Cadastro e edição no admin usam modal com prévia de foto, título e valor.

O catálogo de `app/gift_catalog.py` mantém seis opções iniciais para bancos vazios e acrescenta 12 presentes (R$ 49,90 a R$ 899,90) uma única vez. A tabela `gift_catalog_release` registra a aplicação. Presentes existentes, preços, disponibilidade e compras são preservados. Presentes excluídos ou desativados depois da atualização não são recriados nos próximos reinícios. Revise nomes, valores e imagens pelo painel administrativo.

Validação: `python -m unittest discover -s tests -v` (SQLite em memória, sem pagamentos ou envio de mensagens).

Interações JavaScript: `node tests/test_gift_filters.mjs`.

## Pagamentos e mural

O retorno do checkout e as notificações consultam o pagamento no Mercado Pago pelo token do servidor. A aprovação exige referência da compra, valor e moeda correspondentes; parâmetros da URL não aprovam compras. Boletos pendentes mostram **Aguardando pagamento** e permitem atualizar o status. Falhas temporárias nas notificações retornam 503 para permitir nova tentativa.

O checkout permite escolher Pix ou outros meios, sem excluir cartão ou boleto. Para o Pix aparecer no Checkout Pro, cadastre uma chave Pix **na conta Mercado Pago que recebe os presentes**: Área Pix → Minhas chaves → Cadastrar chave. A seleção no site não substitui essa configuração da conta. [Documentação do Mercado Pago](https://www.mercadopago.com.br/developers/pt/docs/woocommerce/payments-configuration/checkout-pro).

O mural público permite somente leitura. Novos recados vêm de respostas ao RSVP com código válido ou de presentes com pagamento aprovado e verificado. A configuração de moderação do admin continua sendo respeitada. A origem de cada recado impede duplicação por notificações repetidas e evita restaurar recados excluídos pelo admin. Na atualização, respostas antigas confirmadas são importadas uma única vez; presentes antigos precisam de confirmação verificada do pagamento.

Os testes de pagamento usam respostas simuladas do provedor, sem cobranças reais. Validação completa: `python -m unittest discover -s tests -v`.

## Cerimônias e perguntas frequentes

As áreas **Cerimônias e locais** e **Perguntas frequentes** no admin controlam a localização e as respostas na home. Os dois momentos têm data, horário, foto, endereço e rota independentes. O horário da recepção começa em branco, com “Horário a definir”, até ser informado pelos noivos. A cerimônia religiosa preserva dados existentes das configurações e atualiza os campos usados nos convites e na contagem regressiva. As perguntas podem ser criadas, editadas, ordenadas, ocultadas e excluídas; o cadastro inicial acontece uma única vez.
