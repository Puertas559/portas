# Industrial Sales Radar PY — Flask

Radar de oportunidades comerciais da Puertas Brasil PY, reconstruído em Python Flask para Railway.

## Arquitetura

- Flask 3 + Jinja + JavaScript
- PostgreSQL com SQLAlchemy
- Migrações Alembic/Flask-Migrate
- Gunicorn em produção
- `/data` para arquivos persistentes
- Docker e Railway

## Variáveis do Railway

No serviço da aplicação:

```env
DATABASE_URL=${{Postgres.DATABASE_URL}}
SECRET_KEY=gere-uma-chave-longa-e-aleatoria
DATA_DIR=/data
RAILWAY_RUN_UID=0
```

O nome `Postgres` deve ser igual ao nome real do serviço de banco. `PORT` é fornecida automaticamente pelo Railway.

## Volume

Anexe um volume ao serviço Flask e monte em `/data`. O PostgreSQL deve continuar como serviço separado, com persistência própria.

## Deploy

1. Substitua todo o conteúdo do repositório pelo conteúdo deste pacote.
2. Faça commit e push na branch conectada ao Railway.
3. Configure as variáveis acima.
4. Confirme o volume em `/data`.
5. Use **Deploy Latest Commit**.

O container executa `flask db upgrade` antes de iniciar o Gunicorn.

## Rotas

- `/` — dashboard
- `/health` — saúde do banco
- `GET/POST /api/opportunities`
- `PATCH /api/opportunities/<id>`
- `GET /api/timeline/<id>`

## Desenvolvimento local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
flask --app wsgi.py db upgrade
flask --app wsgi.py run --debug
```

Sem PostgreSQL local, a aplicação usa SQLite apenas para desenvolvimento. Em produção, `start.sh` exige `DATABASE_URL`.

## Segurança

O MVP ainda não possui autenticação. Não cadastre dados confidenciais antes de implementar usuários e controle de acesso.
