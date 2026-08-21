HG GRUPO RADAR COMERCIAL — V15.4 PATCH

ALTERAÇÕES
1. Um único motor de mensagens
- Mensagens do painel lateral agora usam /api/companies/<id>/message, o mesmo motor da Ficha 360°.
- Mensagem pós-classificação continua abrindo a aba Mensajes da Ficha 360°.
- Correo, WhatsApp e Llamada usam o mesmo contexto de empresa, contato, cargo e área.
- Painel lateral ganhou seletor de destinatário, contato exato e assunto de correo.

2. Atualização automática ao salvar dados
- Ao salvar dados empresariais (nome, correo geral, telefone, WhatsApp, setor etc.), o motor de mensagens é recalculado.
- A lateral aberta para a mesma empresa também se atualiza sem recarregar a página.
- Ao adicionar contato pelo Comitê de compra, o novo contato passa a ser selecionado e a mensagem é regenerada.

3. Edição de contatos na Ficha 360°
- Cada contato tem ícone de editar.
- Nome, cargo, correo e WhatsApp podem ser alterados inline.
- Ao salvar, o Radar abre Mensajes com o contato atualizado já selecionado.
- Foi incluído endpoint PATCH de contato com isolamento por tenant.

ARQUIVOS DO PATCH
app/routes/api.py
app/templates/index.html
app/static/app.js
app/static/dossier.js
app/static/v13.css
