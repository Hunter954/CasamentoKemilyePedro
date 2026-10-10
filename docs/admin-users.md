# Usuários do painel

Em **Acessos → Usuários**, um administrador pode criar contas com nome, e-mail, senha e perfil:

- **Administrador:** gerencia todas as páginas e também as contas de usuários.
- **Gerente:** gerencia convidados, presentes, campanhas e configurações. Não acessa nem altera a seção de usuários, inclusive por requisições diretas.

O novo usuário entra pela mesma página `/admin/login`. Senhas são armazenadas como hashes; nunca são exibidas ao editar. No cadastro, a senha deve ter de 8 a 128 caracteres e ser confirmada. Ao editar, deixar a senha vazia mantém a atual. Não é enviado e-mail de convite automaticamente.

É possível buscar por nome/e-mail, filtrar acessos ativos/desativados, editar, desativar, reativar e excluir contas. Desativação, exclusão, troca de senha, e-mail ou perfil revogam sessões anteriores. Quem altera sua própria conta mantém a sessão atual; ao mudar seu perfil para Gerente, volta à página inicial do painel.

Não se pode excluir/desativar a própria conta nem remover o último administrador ativo. A conta principal configurada com `ADMIN_EMAIL` e `ADMIN_PASSWORD` mantém seu e-mail, senha e acesso sob controle dessas variáveis; no painel, apenas seu nome pode ser alterado. Reinicializações preservam as demais contas, senhas e estados.

## Migração e segurança

`_sync_schema` adiciona `role`, `enabled`, `session_version` e `is_primary` à tabela `admin_user`. Contas antigas continuam ativas como administradores. Sessões assinadas antigas permanecem válidas enquanto a versão de credenciais for 1. Novos logins incluem a versão no identificador da sessão, e o carregador rejeita contas desativadas ou sessões revogadas. Essa implementação usa a interface de identificação/carregamento de usuários do [Flask-Login](https://flask-login.readthedocs.io/en/0.6.3/#alternative-tokens).

Todas as alterações de usuários exigem autenticação, perfil Administrador e token CSRF. Um bloqueio transacional do PostgreSQL coordena operações simultâneas e a proteção do último administrador. E-mails são normalizados para minúsculas e conferidos contra contas existentes, com a restrição única do banco como proteção adicional.

## Verificação

```sh
python -m unittest discover -s tests -p 'test_*.py'
```

Os testes cobrem cadastro/login, permissões, tentativas de promoção indevida, CSRF, duplicados, validação, senha preservada/alterada, revogação de sessões, desativação, reativação, exclusão, conta principal, último administrador, migração do banco antigo e persistência após reinicialização.
