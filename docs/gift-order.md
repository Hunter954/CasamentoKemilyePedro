# Ordem de presentes no painel

Em Presentes, cada card tem “Editar ordem”. A posição é editada e salva no
próprio card, sem recarregar ou reorganizar a tela durante a edição. Enter salva
e Escape cancela. Os indicadores dos outros cards são atualizados na resposta.

A primeira alteração ativa uma sequência manual baseada na lista do painel.
Mover um presente desloca os demais e salva posições consecutivas de 1 ao
total de presentes. O site público segue essa sequência, preservando a ordem
relativa quando existem presentes inativos. Novos presentes sem posição ficam
ao final; a próxima edição os incorpora à sequência. Sem posição configurada,
o catálogo público mantém o comportamento aleatório anterior.

A coluna nullable `gift_item.display_order` é adicionada pela migração aditiva
existente. Instalar a versão não define posições nem altera o catálogo.
Preços, imagens, disponibilidade e compras não são modificados ao ordenar.
O endpoint requer login e CSRF. Um lock transacional PostgreSQL e locks de
linhas serializam edições simultâneas, evitando sequências duplicadas.
