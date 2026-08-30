# Implantação em produção — Railway

## 1. Serviços

- Um serviço Railway construído pelo `Dockerfile` deste projeto.
- Um PostgreSQL Railway vinculado ao serviço.
- Um volume persistente montado em `/data` para propostas, fotos e chave local de desenvolvimento.

## 2. Variáveis obrigatórias

Copie `.env.production.example` para o painel de variáveis do Railway e substitua todos os valores de exemplo.

Gere uma chave de sessão:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Na primeira implantação, mantenha:

```env
AUTH_REQUIRED=true
ALLOW_WEB_SETUP=false
SESSION_COOKIE_SECURE=true
TRUST_PROXY=true
BOOTSTRAP_ADMIN_COMPLETE=false
```

Informe `ADMIN_EMAIL`, `ADMIN_NAME` e uma `ADMIN_PASSWORD` exclusiva com pelo menos 12 caracteres. O primeiro usuário será criado como `GROUP_ADMIN`.

## 3. Processo automático

O contêiner executa, nesta ordem:

1. validação das variáveis de produção;
2. migrações do banco com `flask db upgrade`;
3. bootstrap idempotente das operações e do administrador;
4. Gunicorn com logs em stdout/stderr;
5. healthcheck periódico em `/health`.

O build também compila o código e executa a suíte de testes. Se uma dessas etapas falhar, a versão não deve ser promovida.

## 4. Conferência após o deploy

1. Confirme que `/health` retorna `{"status":"ok","database":"connected"}`.
2. Entre com `ADMIN_EMAIL` e confirme o perfil `GROUP_ADMIN`.
3. Verifique as operações Puertas Brasil PY e Tech Doors BR separadamente.
4. Crie um usuário `VIEWER` e confirme que ele não consegue alterar o CRM.
5. Faça uma análise de um site público conhecido e valide o resultado antes de inserir no CRM.
6. Execute o coletor manual uma vez e confira o histórico da execução.
7. Defina `BOOTSTRAP_ADMIN_COMPLETE=true` e remova `ADMIN_PASSWORD` das variáveis.

## 5. Operação segura

- O sistema não envia e-mails ou WhatsApp automaticamente; ele prepara mensagens para revisão humana.
- E-mails encontrados em páginas públicas não são garantia de entregabilidade.
- Faça backup periódico do PostgreSQL e do volume `/data`.
- Nunca publique `.env`, backup de banco ou credenciais no repositório.
- Antes de uma atualização, preserve a versão anterior do contêiner e confirme o backup do banco.

## 6. Rollback

Se a nova versão falhar após a migração, não apague o banco. Reimplante a imagem anterior pelo histórico do Railway e revise primeiro o log da etapa que falhou. Migrações destrutivas devem sempre ter um procedimento específico de reversão e backup validado.
