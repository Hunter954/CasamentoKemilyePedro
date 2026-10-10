# Campanhas com frequência configurável

## Operação

1. Salvar uma campanha não envia mensagens. Use **Iniciar envio aos pendentes** para cadastrar os destinatários na fila.
2. O padrão é 15 segundos entre mensagens. **Salvar frequência** aceita de 15 a 600 segundos e vale para todas as campanhas. Não é uma configuração por destinatário nem por lote.
3. Imagem com até 1.024 caracteres de legenda é uma mensagem. Imagem e texto maior viram duas mensagens com o mesmo intervalo entre elas.
4. A fila continua com a página fechada e é persistida no PostgreSQL. Sem conexão, os pendentes aguardam. Use **Pausar fila** para impedir que continuem ao reconectar; uma mensagem já em andamento pode terminar.
5. Um erro pausa a campanha. Confira a conversa antes de **Revisei: reenviar erros**: uma falha de rede pode ocorrer após a entrega. Partes já enviadas (por exemplo, a imagem) não são reenviadas. Um processo interrompido durante o envio fica com entrega incerta, sem repetição automática.
6. Campanhas com mensagens pendentes ou com falha não podem ter o conteúdo editado. Crie outra campanha para um novo convite. A exclusão cancela os pendentes e remove o histórico; é recusada durante uma mensagem em andamento. Contatos com mensagens na fila não podem ser excluídos antes da campanha.

Os destinatários, números e mensagens personalizados são fotografados no início do envio. Novos contatos podem ser adicionados depois pelo botão dos pendentes, sem repetir quem já tem registro naquela campanha. Alterar a tag de um contato não impede a revisão de um envio com falha já registrado.

O intervalo não garante proteção contra bloqueios do WhatsApp. Use o envio para convidados que esperam o contato.

## Implementação

- `campaign_delivery`: configuração global e instante mínimo do próximo envio.
- `campaign_job`: uma linha por mensagem física, com conteúdo, estado e identificador de envio.
- `whatsapp_campaign.queue_paused`: pausa persistente da campanha; migração aditiva para bancos existentes.
- `whatsapp-bridge/campaign-worker.js`: consulta o endpoint interno a cada 2 segundos, sem chamadas sobrepostas. O endpoint exige `WA_INTERNAL_TOKEN`, gerado no `start.sh`; não exponha o token ao navegador.
- `app/services/campaign_queue.py`: bloqueio de sessão exclusivo no PostgreSQL, no mesmo banco da fila, coordenando réplicas e requisições. O bloqueio permanece durante a chamada ao provedor. O estado `sending` é confirmado antes da chamada externa; após 120 segundos sem conclusão, exige revisão. SQLite usa bloqueio em memória somente para testes locais.
- O intervalo começa após a conclusão de cada mensagem e também após uma falha. Não há laço de disparo nem espera de vários minutos dentro da requisição do administrador.
- Não existe garantia de entrega exatamente uma vez em caso de interrupção entre a chamada externa e o commit. Por isso o sistema não repete automaticamente envios incertos.

## Validação

`python -m unittest discover -s tests -p 'test_*.py'`

`node --test tests/test_contact_cards.cjs tests/test_gift_filters.mjs tests/test_campaign_worker.cjs`

Os testes usam banco local e provedores simulados; nenhum convidado recebe mensagens.
