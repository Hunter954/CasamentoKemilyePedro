# Seleção de pessoas e prévia de convidados

Atualização de 22/10/2026. Substitui a regra inicial de confirmação obrigatória
do grupo inteiro descrita em `smart-rsvp.md`.

Todos os nomes do convite começam selecionados. O convidado pode desmarcar
quem não vai, mas não pode adicionar nomes nem ultrapassar o cadastro. Os
checkboxes enviam posições; o servidor valida cada posição e recupera o nome
oficial. Aceitar sem selecionar ninguém mostra uma orientação para selecionar
alguém ou recusar o convite. Recusar significa ausência do convite inteiro.

`rsvp.attendee_names` é uma coluna TEXT adicionada de forma compatível. Ela
guarda em JSON os nomes selecionados e `guests_count` guarda a quantidade que
vai. Respostas antigas conservam os campos anteriores e a seleção vazia mantém
a interpretação histórica do convite inteiro. Não há atualização em massa.

Os relatórios somam os presentes selecionados e os demais como ausentes.
Confirmações mostra presença parcial, os nomes e ambas as quantidades; a
correção administrativa também permite selecionar integrantes. Após uma
resposta nova, repetir o envio não altera a seleção nem cria outro registro.

Depois de um novo aceite, a confirmação fica visível por 1,8 segundo. Em
seguida aparece a mensagem animada sobre os presentes e a página de presentes
abre em 4,8 segundos. É possível abrir imediatamente ou continuar na página.
Escape cancela a transição. A preferência de movimento reduzido desliga os
efeitos. Recusas, recargas e consultas de respostas anteriores não iniciam a
animação. Sem JavaScript, permanece o link para os presentes.

Contatos diferencia convites cadastrados de pessoas convidadas. O total de
pessoas soma os segmentos não vazios separados por `&` em todos os contatos,
independentemente de filtro ou paginação. A edição rápida do nome atualiza a
prévia imediatamente. A consulta periódica também considera novas importações
e evita sobrescrever a soma com uma resposta que começou antes da edição.

Validação: suíte Python (95 testes), seleção de 1/3 e 2/3 pessoas, dados
adulterados, posições inválidas/repetidas, seleção vazia, recusa, repetição,
migração aditiva e preservação de respostas antigas. Navegador desktop e móvel
com identificação de WhatsApp: seleção, totais, animação, navegação, cancelamento,
Escape, movimento reduzido e atualização da prévia de contatos.
