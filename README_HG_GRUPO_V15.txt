HG GRUPO · RADAR COMERCIAL — V15

ARQUITETURA
- Sistema central: HG Grupo · Radar Comercial
- Operação ativa 1: Puertas Brasil PY (Paraguai / espanhol)
- Operação ativa 2: Tech Doors BR (Brasil / português)
- Empresa institucional: Premium Portas e Portões (Radar ainda não ativado)

ISOLAMENTO
- Puertas e Tech Doors usam o mesmo motor Flask/PostgreSQL.
- Os dados comerciais continuam separados por tenant_id.
- Usuários normais entram diretamente em sua própria operação.
- GROUP_ADMIN pode acessar a visão HG Grupo e alternar entre as operações.
- Clientes, contatos, atividades, oportunidades, relatórios e análises permanecem filtrados pelo tenant/operação ativa.

IDENTIDADE VISUAL
- Puertas Brasil: usa app/static/puertas-brasil-logo-oficial.jpg existente, sem redesenho.
- Tech Doors: usa app/static/techdoors-logo-oficial.jpg, copiado do arquivo oficial disponibilizado pelo usuário.
- Premium Portas: o painel institucional carrega diretamente a arte oficial publicada no site premiumportas.com.br/_imagens/banners/02.webp e recorta visualmente a área da marca via CSS, sem redesenhar pixels.
- HG Grupo: nova identidade própria em app/static/hg-group-logo.png.

TECH DOORS
- Tema laranja/preto.
- Operação Brasil / pt-BR.
- Mensagens CRM principais adaptadas para português.
- Assunto inicial padrão: Tech Doors | Primeiro Contato.
- Relatório PDF usa a logo/identidade da operação ativa.

PUERTAS BRASIL
- Mantém tema verde/amarelo.
- Operação Paraguai / es-PY.
- Mantém dados existentes da base atual.

PREMIUM PORTAS
- Empresa do HG Grupo.
- Sem interface operacional, CRM, usuários ou base comercial própria nesta versão.
- Exibe status: Radar ainda não ativado.
- Site oficial: https://premiumportas.com.br/

PRIMEIRO ADMINISTRADOR
- O administrador principal existente da Puertas Brasil é promovido para GROUP_ADMIN no primeiro login.
- Novos usuários criados dentro de Tech Doors pertencem ao tenant Tech Doors e não veem Puertas Brasil.
- Novos usuários Puertas pertencem ao tenant Puertas e não veem Tech Doors.

DEPLOY
1. Substitua o conteúdo do repositório pelo conteúdo deste ZIP.
2. Não misture com cópias antigas da raiz.
3. Faça commit/push no GitHub.
4. Railway executará flask db upgrade e depois Gunicorn como já fazia.
5. Não é necessária migration nova para a estrutura HG desta versão; Tech Doors é provisionada de forma idempotente ao abrir o painel HG.
