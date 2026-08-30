# Correções de segurança e estabilidade

Revisão aplicada em 26–27/08/2026 sobre a cópia `portas-main (27)`.

## Alterações

- Removida a promoção automática de administradores locais para `GROUP_ADMIN`.
- Sessões de usuários ou operações desativadas são invalidadas imediatamente.
- Rotas de análise de sites e criação de tarefas agora exigem `WRITE_CRM`.
- Corrigida a referência indefinida a `tenant` na inclusão por busca empresarial.
- Dados recebidos pelas telas do HUB são escapados antes de entrar em HTML.
- Análise de sites valida credenciais, portas, IPs e cada redirecionamento HTTP.
- Importação e varredura do HUB usam a mesma proteção de URLs públicas.
- Coletor automático pode receber o tenant explicitamente.
- Agendador calcula execução e atividade por tenant e mantém o advisory lock na mesma conexão PostgreSQL.
- `.env.example` passou a exigir autenticação por padrão.
- Adicionado `.dockerignore` para não publicar cópias antigas, caches, arquivos locais e ZIPs internos na imagem.
- Testes atualizados para a interface atual do scoring e do analisador de sites.
- Adicionados testes de regressão para privilégios, sessões desativadas e permissões de usuário somente leitura.
- Adicionado validador que bloqueia inicialização com banco, chave, cookies ou autenticação inseguros.
- Fechado o cadastro inicial público em produção; o bootstrap por variáveis cria o primeiro `GROUP_ADMIN`.
- Sessões passam a expirar em 12 horas e tentativas de login recebem limite por IP e identidade.
- Adicionados CSP com nonce, HSTS, proteção de contexto, cache privado e cabeçalhos contra indexação e isolamento de origem.
- Fotos de visitas agora têm validação de assinatura e autorização por tenant no download.
- Senhas novas exigem no mínimo 12 caracteres.
- Migrações deixam de colocar a senha do banco na URL de log/configuração.
- Docker executa compilação e testes durante o build, inclui healthcheck e inicia Gunicorn com rotação de workers e logs.
- Criados `.env.production.example`, `DEPLOY_PRODUCAO.md` e testes específicos do preflight.

## Validações realizadas

- Compilação de todos os arquivos Python com `compileall`.
- Validação sintática de `app/static/hub-events.js` com Node.js.
- Comparação da árvore final com o ZIP original para confirmar o escopo das mudanças.
- Cadeia linear das 12 migrações validada, com um único head.
- Validador de produção testado com configurações seguras e inseguras.
- Shell de inicialização e scripts do service worker validados sintaticamente.

O ambiente local da revisão não possui Flask/SQLAlchemy e bloqueia download de pacotes, por isso a suíte Flask completa não pôde ser executada aqui. O Dockerfile agora a executa obrigatoriamente durante o build, depois de instalar `requirements.txt`:

```bash
python -m pip install -r requirements.txt
python -m unittest -q
```
