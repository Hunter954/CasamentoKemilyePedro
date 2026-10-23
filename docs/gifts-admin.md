# Catálogo de presentes no painel

O painel `/admin/presentes` reúne resumo de visibilidade, busca por nome sem
distinção de acentos, filtros combináveis de status, tipo de compra e valor.
Os filtros ficam na sessão do navegador e são restaurados após salvar um cadastro.

A ordenação de visualização (posição, nome ou valor) é local ao painel e não
modifica o site público. A posição é editada pelo número na própria linha e usa
o total do catálogo, mesmo com filtros aplicados. Após salvar, os indicadores
são atualizados sem mover as linhas ou a rolagem. Veja [gift-order.md](gift-order.md).

O botão Editar abre o mesmo formulário de cadastro em uma janela, preenchida
com os dados do presente. Criar e salvar continuam usando as rotas autenticadas
com CSRF e upload existentes. Ocultar e excluir ficam no menu de mais ações.

O layout é responsivo. A consulta carrega as compras em lote para calcular
recebimentos e disponibilidade sem uma consulta adicional para cada presente.
