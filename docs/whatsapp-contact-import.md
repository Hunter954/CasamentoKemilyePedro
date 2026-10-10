# Convidados pelo WhatsApp

## Uso no painel

1. Criem um grupo reservado para cadastrar os convidados. Incluam os dois noivos e o número conectado em **Conexão WhatsApp** (esse número pode ser o de um dos noivos).
2. Em **Contatos**, cliquem em **Buscar meus grupos**, selecionem o grupo correto e ativem a importação.
3. No grupo, compartilhem os cartões usando **Anexar → Contato** ou encaminhem cartões recebidos em outras conversas. É possível enviar vários de uma vez.

O cadastro usa nome, telefone e categoria `convidado`, com um código de confirmação novo. Não envia mensagens ao convidado nem ao grupo. Mensagens de texto, contatos da agenda e cartões anteriores à ativação não são importados. Todos os participantes do grupo selecionado podem compartilhar cartões; por isso, usem um grupo reservado para esse cadastro.

Telefones formatados e números brasileiros com/sem o nono dígito móvel são comparados com a base existente. Duplicados preservam nome, categoria, código, confirmações e histórico de envios. Um cartão com vários telefones usa primeiro o `waid` do WhatsApp, depois o celular e, por último, o primeiro telefone disponível. Telefones internacionais precisam incluir o código do país.

O painel mostra importações, duplicados e cartões inválidos; atualiza os indicadores a cada 15 segundos e oferece atualizar a lista sem interromper um formulário aberto. Corrijam um cartão inválido no WhatsApp e encaminhem novamente. É possível pausar ou mudar o grupo; reativar começa uma nova janela de recebimento, sem importar cartões enviados enquanto estava pausado.

## Implementação e operação

- `messages.upsert` processa `notify` e `append` (incluindo entregas recebidas após reconexão), usando `normalizeMessageContent` para cartões encapsulados. O histórico completo não é importado. Referência: [eventos Baileys](https://github.com/WhiskeySockets/baileys.wiki-site/blob/main/docs/socket/receiving-updates.md).
- A configuração usa o identificador real do grupo retornado por `groupFetchAllParticipating`, validado novamente ao salvar. Nome repetido de grupo não funciona como chave.
- `whatsapp_contact_inbox` guarda lotes no PostgreSQL antes de entregá-los ao Flask. A fila tenta a cada 10 segundos, com recuo progressivo até 5 minutos em caso de falha, e só remove um lote após confirmação do processamento. O painel informa lotes pendentes.
- `start.sh` gera `WA_INTERNAL_TOKEN` privado por container e o compartilha com os dois processos. O endpoint interno exige esse token. Não é necessário configurar outro segredo no Railway; usar sempre `./start.sh` para iniciar a aplicação.
- `contact_import_settings` e `contact_import_event` são tabelas aditivas criadas por `db.create_all()`. Dados existentes e a autenticação do Baileys não são migrados ou apagados. A fila é criada pelo bridge.
- Um bloqueio transacional do PostgreSQL coordena importações, cadastro manual, edição e exclusão. Cada lote tem um identificador determinístico; reprocessamentos não refazem o cadastro nem duplicam os totais.
- As datas de ativação são UTC, convertidas explicitamente para epoch no bridge. Trocar o grupo/reativar descarta entregas anteriores à nova ativação; salvar o mesmo grupo ativo preserva a janela atual.
- Os testes usam contatos fictícios, banco SQLite e transporte isolado. O teste final de recebimento real requer ativar o grupo no painel e compartilhar um cartão pelo WhatsApp.

## Verificação

```sh
python -m unittest discover -s tests -p 'test_*.py'
node --test tests/test_contact_cards.cjs tests/test_gift_filters.mjs
```
