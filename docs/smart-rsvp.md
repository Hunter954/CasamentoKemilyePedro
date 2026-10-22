# Confirmação por convite — 22/10/2026

O link `https://kemilyepedro.com.br/?codigo=%codigo%` usa o mesmo substituidor
de campanhas e legendas já existente. O parâmetro é validado no servidor. Um
redirecionamento 303 abre `/rsvp` e remove o código da URL. A credencial fica
na sessão assinada; o código deve continuar sendo tratado como confidencial.
A regeneração administrativa do código invalida a credencial anterior.

Abrir o link, inclusive por prévias do WhatsApp, não grava RSVP. O formulário
manual identifica o convite antes de exibir as duas opções. A resposta exige
POST, sessão do convite e token CSRF. Nomes e quantidades do navegador são
ignorados. Respostas repetidas, inclusive concorrentes, são serializadas pelo
mesmo lock transacional PostgreSQL usado nas alterações de contatos.

Os nomes são separados exclusivamente por `&`; segmentos vazios são ignorados
e espaços extras são removidos para apresentação. O total é o número de
segmentos restantes. O nome original do cadastro não é alterado.

Não há migração destrutiva nem atualização em massa. Um novo aceite grava o
total oficial em `rsvp.guests_count`. Uma recusa mantém `guests_count = 0`
(pessoas presentes), e o relatório soma como ausentes todos os integrantes do
convite recusado. Os relatórios dos convites vinculados usam o cadastro atual,
inclusive após uma correção de nome. Snapshots e mensagens históricos ficam
intactos; divergências de aceites antigos aparecem na tabela administrativa.
Registros manuais sem contato continuam na seção de histórico e conservam a
quantidade aceita que estava gravada. Não havia exportador de RSVP no projeto.

Após responder, o convidado consulta a situação pelo mesmo link; outra resposta
pública não substitui uma já registrada. Para corrigir os nomes, o casal usa a
edição existente em Contatos. A edição rápida recalcula a quantidade na linha.
Para corrigir uma resposta, há uma ação autenticada e protegida por CSRF em
Confirmações → Corrigir resposta. Ela atualiza a mesma resposta do convite,
conserva o recado e aplica a quantidade oficial, sem criar uma segunda linha.

A prévia de campanhas permite selecionar um destinatário de teste e chama o
mesmo renderizador usado no envio. Visualizar não cria campanha, fila ou envio.
Nenhum disparo real de WhatsApp faz parte da validação.

## Validação

- `python -m unittest discover -s tests -v`: 87 testes, incluindo código válido
  com 1/2/3 pessoas, inválido/inexistente/ambíguo, resposta anterior, recusa,
  repetição, sessão/CSRF, cadastro oficial, contagens, relatórios e legenda.
- `check_smart_rsvp_browser.py` contra `preview_smart_rsvp.py`, ambos locais:
  Chrome desktop e viewport móvel com user agent WhatsApp; link, código manual,
  recarga, dois submits no mesmo instante, oito POSTs concorrentes, requisição
  manipulada, relatório e prévia real do destinatário de teste.
- As fixtures do navegador usam banco SQLite separado e nomes fictícios.
  Os dois scripts de prévia não são publicados na aplicação.
- PostgreSQL 18 descartável em rede isolada: doze POSTs concorrentes contra
  dois workers Gunicorn resultaram em uma única resposta, com três pessoas.
  Os containers, volumes de teste e a rede foram removidos ao concluir.
- Testes Node de worker de campanhas, importação de cartões e fallback de
  imagem passaram; sintaxe dos quatro scripts JavaScript alterados validada.
- A emulação cobre o comportamento web do navegador interno do WhatsApp; não
  substitui um teste em um aparelho físico. O envio de legenda é testado com
  transporte simulado para não enviar mensagens aos convidados.
