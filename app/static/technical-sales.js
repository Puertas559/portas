(() => {
  const cfg = window.TS_CONFIG || {};
  const $ = (s, root=document) => root.querySelector(s);
  const $$ = (s, root=document) => [...root.querySelectorAll(s)];
  const currency = String(cfg.countryCode || 'BR').toUpperCase()==='PY' ? 'PYG' : 'BRL';
  const locale = currency==='PYG' ? 'es-PY' : 'pt-BR';
  const money = new Intl.NumberFormat(locale,{style:'currency',currency,maximumFractionDigits:currency==='PYG'?0:2});
  const COURSE_STORE='hgTechnicalCourseProgressV1';
  const ACTIVE_STORE='hgTechnicalSalesActiveServerV2';
  let currentSection=0;
  let activeLesson=0;
  let surveys=[];
  let activeSurvey=null;
  let activeDraftId=localStorage.getItem(ACTIVE_STORE) || '';
  let courseProgress=new Set(loadJson(COURSE_STORE,[]) || []);
  let saveTimer=null;
  let saveInFlight=null;
  let companyTimer=null;
  let companyOptions=new Map();
  let signatureDrawing=false;
  let signatureDirty=false;

  const lessons = [
    {title:'Começando do zero',icon:'bi-door-open',summary:'O que é uma porta seccionada, como funciona e quais são os componentes básicos.',why:'Antes de medir ou vender, você precisa visualizar o conjunto: painéis articulados, trilhos, ferragens, molas, cabos, vedações e automação.',learn:['O que diferencia uma porta seccionada de outros tipos de fechamento.','Vocabulário básico usado no levantamento e no orçamento.','Como a porta se desloca e por que precisa de espaço ao redor do vão.'],practice:'Ao chegar à obra, identifique o vão, teto, laterais e trajeto provável da porta antes de retirar a trena.',alert:'Nunca prometa uma configuração antes de verificar espaço superior, laterais, profundidade e estrutura.'},
    {title:'Cliente e obra',icon:'bi-person-vcard',summary:'Entenda quem compra, onde será instalada e em que estágio a obra se encontra.',why:'Obra nova, reforma e substituição geram necessidades, riscos e custos diferentes.',learn:['Identificar o decisor e o responsável técnico.','Confirmar se a residência está pronta ou em construção.','Registrar prazo desejado e condições de acesso.'],practice:'Preencha os dados do cliente antes das medidas. Isso evita fotos e medições sem identificação.'},
    {title:'O vão da porta',icon:'bi-bounding-box',summary:'Aprenda largura, altura, vão livre, vão acabado e referência de medição.',why:'A medida errada do vão compromete dimensionamento, custo e instalação.',learn:['Largura deve ser medida em cima, no centro e embaixo.','Altura deve ser medida à esquerda, no centro e à direita.','A menor medida encontrada é a referência do levantamento.'],practice:'Meça sempre de acabamento a acabamento e registre as três leituras, não apenas uma.',alert:'A medida do vão não é necessariamente a medida final de fabricação.'},
    {title:'Matemática prática',icon:'bi-calculator',summary:'Milímetros, centímetros, metros, conversões e cálculos simples para o vendedor.',why:'A maioria dos erros de orçamento começa em unidade de medida ou anotação incorreta.',learn:['1 metro = 100 centímetros = 1.000 milímetros.','Use milímetros como padrão técnico para evitar ambiguidade.','Área aproximada: largura × altura, com as duas medidas na mesma unidade.'],practice:'3,00 m = 300 cm = 3.000 mm. Registre 3000 mm no levantamento.'},
    {title:'Nível, prumo, esquadro e diagonais',icon:'bi-triangle',summary:'Conceitos básicos para verificar se o vão está geometricamente adequado.',why:'Um vão fora de nível ou esquadro pode exigir compensações, reforços e ajustes.',learn:['Nível: referência horizontal.','Prumo: referência vertical.','Esquadro: relação correta entre lados; as diagonais ajudam a identificar distorções.'],practice:'Meça as duas diagonais. Diferenças relevantes devem ser registradas e fotografadas.',alert:'Não tente “corrigir” a medida no papel; registre a condição real da obra.'},
    {title:'Espaços ao redor do vão',icon:'bi-arrows-fullscreen',summary:'Verga, ombreiras e profundidade interna.',why:'Esses espaços determinam se guias, curvas, trilhos e automação podem ser instalados.',learn:['Verga: espaço acima do topo do vão até o teto ou primeira interferência.','Ombreiras: espaços laterais disponíveis para fixação das guias.','Profundidade: espaço interno necessário para o deslocamento horizontal do conjunto.'],practice:'Meça e fotografe verga, lateral esquerda, lateral direita e profundidade.'},
    {title:'Interferências',icon:'bi-exclamation-diamond',summary:'Vigas, luminárias, tubulações, forro, ar-condicionado, portas e outros obstáculos.',why:'Uma interferência pode mudar o tipo de elevação, posição de trilho, motor ou custo de instalação.',learn:['Verifique teto e laterais em todo o trajeto da porta.','Registre a primeira interferência e sua distância.','Fotografe o contexto, não apenas o obstáculo.'],practice:'Faça uma foto ampla interna apontando para o teto e outra lateral.'},
    {title:'Estrutura e fixação',icon:'bi-bricks',summary:'Concreto, alvenaria, estrutura metálica, madeira e blocos.',why:'A porta precisa de base resistente para fixar guias e componentes.',learn:['Identificar o material da estrutura.','Verificar pilares laterais e viga superior.','Sinalizar necessidade de reforço metálico ou requadro.'],practice:'Quando houver dúvida sobre resistência, marque “validar tecnicamente” e fotografe de perto e de longe.',alert:'Reforço estrutural deve aparecer separado no orçamento quando necessário.'},
    {title:'Sistemas de elevação',icon:'bi-arrow-up-square',summary:'Padrão, baixa, alta, vertical e acompanhando a inclinação do teto.',why:'O espaço disponível determina a geometria dos trilhos e a solução aplicável.',learn:['Residencial normalmente usa elevação padrão ou baixa.','Maior verga pode permitir outras soluções.','Teto inclinado pode exigir trilho acompanhando inclinação.'],practice:'Não escolha o sistema apenas pela preferência; relacione-o às medidas e interferências.'},
    {title:'Painéis e acabamento',icon:'bi-grid-3x3-gap',summary:'Painel simples ou térmico, espessura, desenho, cor e acabamento.',why:'Painel impacta estética, isolamento, peso e preço.',learn:['Isolamento em poliuretano melhora desempenho térmico.','Textura e desenho alteram aparência da fachada.','Cor especial e amadeirado podem alterar prazo e custo.'],practice:'Confirme acabamento desejado e compatibilidade com fachada/esquadrias.'},
    {title:'Vedação',icon:'bi-wind',summary:'Borracha inferior, vedações laterais e superior.',why:'Vedação influencia chuva, vento, poeira, insetos e diferença de temperatura.',learn:['A vedação depende também da qualidade do piso e das laterais.','Desníveis podem impedir fechamento uniforme da borracha inferior.'],practice:'Registre desnível de piso e exposição à chuva/vento.'},
    {title:'Molas, cabos, trilhos e ferragens',icon:'bi-gear-wide-connected',summary:'Entenda a função dos principais componentes mecânicos.',why:'O vendedor precisa saber que o motor não “carrega” sozinho uma porta mal balanceada.',learn:['Molas auxiliam o balanceamento do peso.','Cabos e ferragens trabalham junto ao sistema de elevação.','Trilhos orientam o deslocamento dos painéis.'],practice:'Nunca dimensione componentes apenas por aparência ou por uma medida isolada.'},
    {title:'Funcionamento e ciclos',icon:'bi-arrow-repeat',summary:'Manual, automatizada e frequência diária de uso.',why:'Quantidade de ciclos influencia motor, molas e componentes.',learn:['Uso eventual, moderado e intenso devem ser diferenciados.','Condomínio compartilhado exige análise diferente de garagem unifamiliar.'],practice:'Pergunte quantos veículos usam a garagem e estime aberturas/fechamentos por dia.'},
    {title:'Motores e automação',icon:'bi-cpu',summary:'Peso, potência, tensão, controles e recursos inteligentes.',why:'O motor deve ser compatível com peso, balanceamento e frequência de uso.',learn:['Confirmar 110/127 V, 220 V ou outra tensão.','Registrar posição e distância da tomada.','Definir controles, botoeira, Wi‑Fi, app, tag e fechamento automático.'],practice:'Fotografe tomada/quadro quando relevante.',alert:'Motor não deve ser definido somente pela dimensão da porta.'},
    {title:'Elétrica básica para o vendedor',icon:'bi-lightning-charge',summary:'O mínimo necessário para levantar alimentação e prever instalação.',why:'Sem alimentação adequada, a automação pode exigir serviço elétrico adicional.',learn:['Identificar tensão disponível.','Localizar tomada e distância até o motor.','Não executar diagnóstico elétrico sem competência técnica.'],practice:'Registre a informação da instalação e sinalize quando precisar de eletricista.'},
    {title:'Segurança',icon:'bi-shield-check',summary:'Fotocélula, antiesmagamento, ruptura de molas/cabos e emergência.',why:'Segurança não deve ser tratada como acessório estético.',learn:['Fotocélula e sistemas antiesmagamento reduzem riscos durante fechamento.','Abertura de emergência é crítica quando não existe outro acesso à garagem.','Proteções devem ser compatíveis com o produto e aplicação.'],practice:'Pergunte sobre crianças, animais, acesso alternativo e falta de energia.'},
    {title:'Acessórios e personalização',icon:'bi-sliders',summary:'Janelas, porta social, puxador, fechadura, ventilação e controles.',why:'Personalizações alteram peso, fabricação, complexidade e preço.',learn:['Porta social incorporada aumenta peso e complexidade.','Visores exigem definição de quantidade, material e posição.'],practice:'Não deixe “acessórios” genérico; registre exatamente o que o cliente deseja.'},
    {title:'Condições de instalação',icon:'bi-tools',summary:'Acesso, altura de trabalho, energia, área de montagem e regras locais.',why:'Uma porta tecnicamente correta ainda pode ter custo de instalação diferente conforme o local.',learn:['Verifique escadas, rampas, corredores, estacionamento e restrições de horário.','Identifique necessidade de andaime ou plataforma.','Confirme autorizações de condomínio.'],practice:'Fotografe o acesso quando ele puder afetar transporte e montagem.'},
    {title:'Porta existente e reforma',icon:'bi-arrow-left-right',summary:'Desmontagem, descarte e possível reaproveitamento.',why:'Substituições podem gerar mão de obra e riscos adicionais.',learn:['Registrar tipo, dimensão e estado da porta atual.','Separar desmontagem, retirada e descarte.','Reaproveitamento exige aprovação técnica.'],practice:'Fotografe a porta existente por dentro e por fora.',alert:'Nunca prometa reaproveitamento de motor, trilhos ou componentes sem inspeção técnica.'},
    {title:'Como fotografar uma obra',icon:'bi-camera',summary:'Fotos úteis para engenharia, orçamento e registro comercial.',why:'Uma foto sem contexto pode não permitir validação técnica posterior.',learn:['Faça foto externa frontal do vão.','Faça foto interna ampla mostrando teto, laterais e interferências.','Aproxime-se para detalhes somente depois da foto contextual.'],practice:'Use os botões de câmera do levantamento; cada imagem ficará ligada à etapa correta.'},
    {title:'Levantamento completo',icon:'bi-clipboard2-check',summary:'Sequência prática para não esquecer nenhuma informação.',why:'O sistema deve guiar o vendedor, reduzindo dependência de memória.',learn:['Dados → vão → espaços → estrutura → produto → uso → automação → segurança → instalação → comercial.','Revise campos essenciais antes de sair da obra.'],practice:'Use o indicador de progresso e finalize somente quando os campos essenciais estiverem completos.'},
    {title:'Do levantamento ao orçamento',icon:'bi-receipt-cutoff',summary:'Transforme dados técnicos em composição comercial preliminar.',why:'A proposta precisa separar produto, automação, acessórios, transporte, instalação e adicionais.',learn:['Diferencie estimativa de orçamento definitivo.','Liste itens incluídos e não incluídos.','Defina validade, prazo, pagamento e garantias.'],practice:'Use a aba Orçamento preliminar após concluir o levantamento.'},
    {title:'Apresentar e defender a proposta',icon:'bi-chat-square-text',summary:'Conecte solução, segurança, estética, prazo e valor.',why:'O vendedor técnico-comercial não vende apenas preço; explica a solução e seus condicionantes.',learn:['Explique o que foi considerado no levantamento.','Mostre claramente adicionais e itens fora do escopo.','Nunca esconda condição que dependa de validação técnica.'],practice:'Apresente o orçamento preliminar como solução condicionada à validação final das medidas.'}
  ];

  const micro = {
    'vao':{title:'O que é o vão?',icon:'bi-bounding-box',lead:'É a abertura livre onde a porta será instalada.',what:'Meça a abertura já considerando se a obra está acabada ou se ainda faltam reboco, piso e acabamento.',how:'Largura: superior, centro e inferior. Altura: esquerda, centro e direita. Use a menor medida como referência.',impact:'Erros aqui podem alterar dimensionamento, fabricação e instalação.'},
    'verga':{title:'O que é verga superior?',icon:'bi-arrows-collapse-vertical',lead:'É o espaço entre o topo do vão e o teto ou a primeira interferência.',what:'Pode haver viga, tubulação, luminária, forro ou equipamento acima do vão.',how:'Meça verticalmente do topo acabado do vão até o primeiro obstáculo.',impact:'Determina o tipo de trilho e o sistema de elevação.'},
    'ombreira':{title:'O que são ombreiras?',icon:'bi-arrows-collapse',lead:'São os espaços disponíveis à esquerda e à direita do vão.',what:'É onde normalmente ficam as guias verticais e seus pontos de fixação.',how:'Meça cada lado separadamente e identifique o material da estrutura.',impact:'Pouco espaço lateral pode exigir solução especial ou inviabilizar a configuração prevista.'},
    'profundidade':{title:'O que é profundidade interna?',icon:'bi-arrows-angle-expand',lead:'É a distância livre para dentro da garagem a partir do vão.',what:'O trilho e a porta precisam de trajeto sem interferências.',how:'Meça até o fundo útil e registre vigas, luminárias, portas, armários, forro e veículos altos.',impact:'Pode alterar trilhos, elevação e posição do motor.'},
    'estrutura':{title:'Estrutura para fixação',icon:'bi-bricks',lead:'A porta precisa ser fixada em base resistente e adequada.',what:'Pode ser concreto, alvenaria, estrutura metálica, madeira ou blocos.',how:'Identifique material, pilares e viga superior; fotografe quando houver dúvida.',impact:'Reforço metálico ou requadro deve ser tratado separadamente no orçamento.'},
    'automacao':{title:'Automação: como levantar',icon:'bi-cpu',lead:'O motor depende de mais do que largura e altura.',what:'Peso, balanceamento, frequência de uso, tensão e acessórios precisam ser considerados.',how:'Registre ciclos, tensão, posição da tomada, controles e recursos desejados.',impact:'Dimensionamento incorreto pode comprometer funcionamento e vida útil.'},
    'seguranca':{title:'Segurança da porta',icon:'bi-shield-check',lead:'Mapeie dispositivos e condições de emergência antes de fechar a solução.',what:'Fotocélula, antiesmagamento, ruptura de molas/cabos, travas, sinalização e abertura de emergência.',how:'Pergunte sobre crianças, animais e se existe outro acesso à garagem.',impact:'Se não houver outra entrada, destravamento externo de emergência é especialmente importante.'},
    'esquadro':{title:'Esquadro, piso e diagonais',icon:'bi-triangle',lead:'O formato real do vão precisa ser conferido, não presumido.',what:'Duas diagonais ajudam a verificar distorção; piso deve ser avaliado quanto a nível e inclinação.',how:'Meça diagonal a diagonal e registre desníveis.',impact:'Pode afetar vedação, fixação e acabamento final.'},
    'fotos':{title:'Fotos técnicas úteis',icon:'bi-camera',lead:'Fotografe para que outra pessoa consiga entender a obra sem estar no local.',what:'Faça imagens externas e internas amplas, depois detalhes.',how:'Inclua teto, laterais, piso, estrutura, interferências e alimentação elétrica.',impact:'Reduz retorno à obra e melhora validação do orçamento.'}
  };

  const sections = [
    {title:'Dados do cliente e da obra',icon:'bi-person-vcard',desc:'Identifique cliente, local, estágio da obra, prazo e decisor.',fields:[
      f('client_name','Nome do cliente','text',true),f('phone','Telefone / WhatsApp','tel',true),f('email','E-mail','email'),f('address','Endereço completo da instalação','text',true),f('city_country','Cidade / país','text',true),
      f('work_type','Tipo de obra','select',true,['Obra nova','Reforma','Substituição de porta existente']),f('work_status','Situação da residência','select',true,['Pronta','Em construção']),f('desired_deadline','Prazo desejado para instalação'),f('approval_person','Pessoa responsável pela aprovação do orçamento'),f('survey_date','Data do levantamento','date'),f('sales_responsible','Responsável técnico-comercial','text',true)
    ]},
    {title:'Medidas do vão',icon:'bi-rulers',desc:'Faça três leituras de largura e três de altura. A menor medida é a referência.',learn:'vao',fields:[
      f('width_top','Largura superior (mm)','number',true,null,'Medir a largura livre na parte superior.'),f('width_middle','Largura central (mm)','number',true),f('width_bottom','Largura inferior (mm)','number',true),
      f('height_left','Altura esquerda (mm)','number',true),f('height_middle','Altura central (mm)','number',true),f('height_right','Altura direita (mm)','number',true),
      f('diagonal_1','Diagonal 1 (mm)','number'),f('diagonal_2','Diagonal 2 (mm)','number'),f('squared','Vão está no esquadro?','select',false,['Sim','Não','Não confirmado']),f('floor_level','Piso está nivelado?','select',false,['Sim','Não','Não confirmado']),f('finish_state','Medidas são de obra acabada?','select',true,['Sim, obra acabada','Não, falta reboco','Não, falta piso','Não, faltam outros acabamentos']),f('level_notes','Desníveis / inclinações / observações','textarea')
    ],photos:{id:'opening_photos',title:'Fotos do vão',desc:'Tire foto externa frontal, interna ampla, piso e detalhes de esquadro/interferências.'}},
    {title:'Espaços ao redor do vão',icon:'bi-arrows-fullscreen',desc:'Verga, ombreiras e profundidade determinam trilhos e elevação.',learn:'verga',fields:[
      f('headroom','Verga / espaço superior livre (mm)','number',true,null,'Do topo do vão até o teto ou primeira interferência.','verga'),f('left_side','Ombreira esquerda (mm)','number',true,null,'Espaço disponível para guia vertical.','ombreira'),f('right_side','Ombreira direita (mm)','number',true,null,'Espaço disponível para guia vertical.','ombreira'),f('depth','Profundidade interna livre (mm)','number',true,null,'Do vão para dentro da garagem.','profundidade'),
      f('upper_interferences','Interferências superiores','textarea',false,null,'Vigas, tubulações, luminárias, forro, motores ou equipamentos próximos.'),f('depth_interferences','Interferências na profundidade','textarea',false,null,'Vigas, colunas, portas, janelas, luminárias, tubulações, ar-condicionado, armários, forro ou veículos altos.')
    ],photos:{id:'space_photos',title:'Fotos dos espaços e interferências',desc:'Registre teto, verga, lado esquerdo, lado direito e profundidade.'}},
    {title:'Estrutura para fixação',icon:'bi-bricks',desc:'Confirme material, resistência e necessidade de reforço.',learn:'estrutura',fields:[
      f('structure_material','Material da estrutura','select',true,['Concreto','Alvenaria','Estrutura metálica','Madeira','Bloco cerâmico','Bloco de concreto','Outro']),f('structure_condition','Condição aparente da estrutura','select',true,['Adequada','Requer validação técnica','Aparenta necessitar reforço']),f('side_columns','Existem pilares laterais?','select',false,['Sim','Não','Não confirmado']),f('upper_beam','Existe viga superior?','select',false,['Sim','Não','Não confirmado']),f('metal_reinforcement','Necessidade de reforço metálico?','select',false,['Não','Sim','A validar']),f('frame_required','Necessidade de requadro?','select',false,['Não','Sim','A validar']),f('installation_position','Posição prevista de instalação','select',false,['Por dentro','Dentro do vão','Lado externo','A definir']),f('structure_notes','Observações sobre fixação','textarea')
    ],photos:{id:'structure_photos',title:'Fotos da estrutura',desc:'Inclua pilares, viga, material de fixação e qualquer ponto duvidoso.'}},
    {title:'Tipo de instalação e elevação',icon:'bi-arrow-up-square',desc:'A escolha depende do espaço disponível e das interferências.',fields:[
      f('lift_type','Sistema de elevação previsto','select',false,['Elevação padrão','Elevação baixa','Elevação alta','Elevação vertical','Trilhos acompanhando inclinação do teto','A definir tecnicamente']),f('ceiling_slope','Teto inclinado?','select',false,['Não','Sim','Não confirmado']),f('lift_notes','Observações sobre trilhos / elevação','textarea')
    ]},
    {title:'Características da porta',icon:'bi-grid-3x3-gap',desc:'Defina painel, desenho, acabamento e necessidades de vedação.',fields:[
      f('panel_type','Tipo de painel','select',true,['Painel simples','Painel térmico','Com isolamento em poliuretano','A definir']),f('panel_thickness','Espessura do painel'),f('panel_design','Modelo / desenho externo','select',false,['Liso','Frisado','Almofadado','Texturizado','Imitação de madeira','Outro']),f('color_finish','Cor / acabamento desejado','text',true),f('inside_finish','Acabamento interno'),f('facade_match','Compatibilidade desejada com fachada / esquadrias','textarea'),
      f('sealing_needs','Necessidades de vedação','checks',false,['Borracha inferior','Vedações laterais','Vedação superior','Proteção contra chuva','Entrada de vento','Poeira','Insetos','Diferença de temperatura'])
    ]},
    {title:'Funcionamento da porta',icon:'bi-arrow-repeat',desc:'Uso e ciclos ajudam no dimensionamento dos componentes.',fields:[
      f('operation_mode','Acionamento desejado','select',true,['Manual','Automatizado','Manual com preparação para futura automação']),f('cycles_day','Quantidade aproximada de ciclos por dia','number',true,null,'Considere abertura + fechamento como um ciclo.'),f('vehicles','Quantidade de veículos que utilizam a garagem','number'),f('usage_context','Tipo de uso','select',true,['Residencial individual','Compartilhado / condomínio']),f('usage_intensity','Intensidade estimada','select',true,['Eventual','Moderado','Intenso'])
    ]},
    {title:'Automação',icon:'bi-cpu',desc:'Motor, alimentação, controles e integração.',learn:'automacao',fields:[
      f('voltage','Tensão disponível','select',true,['110/127 V','220 V','Outra','Não confirmado']),f('outlet_location','Local da tomada / alimentação'),f('outlet_distance','Distância tomada → motor (mm)','number'),f('remote_qty','Quantidade de controles remotos','number'),f('automation_options','Recursos desejados','checks',false,['Botoeira','Aplicativo','Wi‑Fi','Teclado de senha','Leitor de tag','Integração residencial','Fechamento automático','Luz de cortesia','Destravamento manual','Bateria / nobreak']),f('automation_notes','Observações de automação','textarea')
    ],photos:{id:'electrical_photos',title:'Fotos da alimentação elétrica',desc:'Fotografe tomada, quadro ou local previsto para o motor quando aplicável.'}},
    {title:'Segurança',icon:'bi-shield-check',desc:'Mapeie dispositivos, emergência, crianças e animais.',learn:'seguranca',fields:[
      f('safety_items','Itens de segurança previstos / desejados','checks',false,['Fotocélula / sensor de presença','Sistema antiesmagamento','Proteção contra ruptura de molas','Proteção contra ruptura de cabos','Trava mecânica','Trava elétrica','Alarme','Sinalizador luminoso','Bateria / nobreak','Abertura de emergência','Borracha inferior sensível']),f('children_pets','Há crianças ou animais no ambiente?','select',false,['Não','Sim','Não informado']),f('other_access','Garagem possui outra entrada?','select',true,['Sim','Não','Não confirmado']),f('safety_notes','Observações de segurança','textarea')
    ]},
    {title:'Acessórios e personalizações',icon:'bi-sliders',desc:'Registre exatamente o que o cliente deseja.',fields:[
      f('accessories','Acessórios desejados','checks',false,['Janelas / visores','Porta social incorporada','Puxador','Fechadura','Grelhas de ventilação','Acabamentos laterais','Perfis de arremate','Controle adicional','Acionamento inteligente','Pintura / acabamento personalizado']),f('windows_qty','Quantidade de janelas / visores','number'),f('window_material','Tipo de vidro / acrílico'),f('window_position','Posição dos visores'),f('accessory_notes','Detalhes / observações','textarea')
    ]},
    {title:'Condições do local',icon:'bi-geo-alt',desc:'Acesso e logística podem alterar o custo de instalação.',fields:[
      f('site_access','Condição de acesso ao imóvel','textarea'),f('material_entry','Altura / largura disponível para entrada dos materiais'),f('stairs_ramps','Escadas, rampas ou corredores estreitos?','select',false,['Não','Sim']),f('parking','É possível estacionar o veículo da equipe?','select',false,['Sim','Não','Com restrição']),f('lift_equipment','Necessidade de andaime ou plataforma?','select',false,['Não','Sim','A validar']),f('working_height','Altura de trabalho'),f('power_available','Há energia elétrica no local?','select',true,['Sim','Não','Não confirmado']),f('assembly_area','Área disponível para montagem','textarea'),f('time_restrictions','Restrições de horário / condomínio','textarea'),f('entry_authorization','Necessidade de autorização de entrada?','select',false,['Não','Sim']),f('rain_risk','Risco de chuva afetar instalação?','select',false,['Baixo','Moderado','Alto','Não avaliado'])
    ],photos:{id:'access_photos',title:'Fotos do acesso e área de montagem',desc:'Use quando entrada, estacionamento, corredores ou montagem puderem afetar o serviço.'}},
    {title:'Porta existente',icon:'bi-arrow-left-right',desc:'Preencha em reforma ou substituição; reaproveitamento só após inspeção.',fields:[
      f('existing_type','Tipo da porta atual'),f('existing_dimensions','Dimensões da porta atual'),f('existing_material','Material'),f('existing_condition','Estado da estrutura','textarea'),f('existing_fixing','Forma de fixação'),f('dismantle','Necessita desmontagem?','select',false,['Não','Sim']),f('disposal','Necessita retirada / descarte?','select',false,['Não','Sim']),f('reuse_motor','Pretende reaproveitar motor?','select',false,['Não','Sim','A validar']),f('reuse_components','Possibilidade de reaproveitar trilhos / componentes','select',false,['Não','Sim, sujeito a inspeção','A validar'])
    ],photos:{id:'existing_photos',title:'Fotos da porta existente',desc:'Frente, verso, motor, trilhos, fixações e estado geral.'}},
    {title:'Serviços incluídos',icon:'bi-tools',desc:'Marque o escopo considerado para a proposta.',fields:[
      f('included_services','Serviços / itens incluídos','checks',false,['Projeto / dimensionamento','Fabricação','Painéis','Trilhos','Molas','Ferragens','Motor','Controles','Sensores','Transporte','Instalação','Materiais de fixação','Reforço estrutural','Instalação elétrica','Desmontagem da porta antiga','Retirada de entulho','Regulagem','Testes','Treinamento do cliente','Manutenção inicial']),f('service_notes','Observações de escopo','textarea')
    ]},
    {title:'Informações comerciais e validação',icon:'bi-clipboard2-check',desc:'Finalize prazo, garantias e observações para o orçamento preliminar.',fields:[
      f('payment_terms','Forma de pagamento'),f('entry_value','Valor da entrada'),f('installments','Número de parcelas','number'),f('manufacturing_deadline','Prazo de fabricação'),f('installation_deadline','Prazo de instalação'),f('proposal_validity','Validade da proposta'),f('panel_warranty','Garantia dos painéis'),f('motor_warranty','Garantia do motor'),f('installation_warranty','Garantia da instalação'),f('technical_assistance','Condições de assistência técnica','textarea'),f('not_included','Itens não incluídos','textarea'),f('measure_change_terms','Condições para alteração de medidas','textarea'),f('final_notes','Observações finais','textarea')
    ]}
  ];


  function f(id,label,type='text',required=false,options=null,helper='',learn=''){return {id,label,type,required,options,helper,learn};}
  function loadJson(key,fallback){try{return JSON.parse(localStorage.getItem(key)) ?? fallback}catch{return fallback}}
  function saveJson(key,value){localStorage.setItem(key,JSON.stringify(value))}
  function escapeHtml(v){return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
  function escapeAttr(v){return escapeHtml(v)}
  function formatDate(v){if(!v)return '—';try{return new Intl.DateTimeFormat('pt-BR',{dateStyle:'short',timeStyle:'short'}).format(new Date(v))}catch{return String(v)}}
  function draft(){return activeSurvey || {fields:{},budget:{},commercial:{},attachments:[],events:[],permissions:{}}}
  function draftLabel(d){const n=d.clientName || d.fields?.client_name?.trim();const c=d.cityCountry || d.fields?.city_country?.trim();return n ? `${n}${c?' · '+c:''}` : `${d.reference || 'Nova ficha'} · ${formatDate(d.createdAt).split(' ')[0]}`}

  async function api(url, options={}){
    const opts={credentials:'same-origin',...options};
    opts.headers={...(options.headers||{})};
    if(options.body && !(options.body instanceof FormData) && typeof options.body!=='string'){
      opts.headers['Content-Type']='application/json';
      opts.body=JSON.stringify(options.body);
    }
    const response=await fetch(url,opts);
    let data=null;
    const type=response.headers.get('content-type')||'';
    if(type.includes('application/json')) data=await response.json();
    else data=await response.text();
    if(!response.ok){const err=new Error(data?.error || `Erro ${response.status}`);err.status=response.status;err.data=data;throw err}
    return data;
  }

  function setServerState(state,text){
    const el=$('#serverState'); if(!el)return;
    const icons={saved:'bi-cloud-check',saving:'bi-cloud-arrow-up',error:'bi-cloud-slash',loading:'bi-arrow-repeat'};
    el.className=`ts-server-state ${state}`;
    el.innerHTML=`<i class="bi ${icons[state]||icons.saved}"></i><span>${escapeHtml(text||'Servidor')}</span>`;
  }

  function mergeSurveySummary(detail){
    const idx=surveys.findIndex(x=>String(x.id)===String(detail.id));
    const summary={...detail};
    delete summary.attachments; delete summary.events; delete summary.signatureData; delete summary.fields; delete summary.budget; delete summary.commercial;
    if(idx>=0) surveys[idx]={...surveys[idx],...summary}; else surveys.unshift(summary);
    surveys.sort((a,b)=>new Date(b.updatedAt||0)-new Date(a.updatedAt||0));
  }

  async function loadSurveys(){
    setServerState('loading','Carregando');
    const data=await api('/api/technical-surveys');
    surveys=data.items||[];
    if(!surveys.length){
      const created=await api('/api/technical-surveys',{method:'POST',body:{fields:{sales_responsible:cfg.userName||''}}});
      surveys=[created];
      activeDraftId=String(created.id);
    } else if(!activeDraftId || !surveys.some(x=>String(x.id)===String(activeDraftId))){
      activeDraftId=String(surveys[0].id);
    }
    localStorage.setItem(ACTIVE_STORE,activeDraftId);
    renderDraftSelect();
    await selectSurvey(activeDraftId,false);
    setServerState('saved','Sincronizado');
  }

  async function createSurvey(){
    await flushSave();
    setServerState('saving','Criando');
    const created=await api('/api/technical-surveys',{method:'POST',body:{fields:{sales_responsible:cfg.userName||''}}});
    surveys.unshift(created); activeDraftId=String(created.id); activeSurvey=created;
    localStorage.setItem(ACTIVE_STORE,activeDraftId);
    currentSection=0; renderDraftSelect(); renderAllActive(); openView('survey');
    setServerState('saved','Sincronizado');
  }

  async function selectSurvey(id, flush=true){
    if(flush) await flushSave();
    setServerState('loading','Carregando');
    const detail=await api(`/api/technical-surveys/${id}`);
    activeDraftId=String(detail.id); activeSurvey=detail;
    localStorage.setItem(ACTIVE_STORE,activeDraftId);
    mergeSurveySummary(detail); renderDraftSelect(); renderAllActive();
    setServerState('saved','Sincronizado');
  }

  function payloadFromDraft(){
    const d=draft();
    return {fields:d.fields||{},budget:d.budget||{},commercial:d.commercial||{},budgetTotal:Number(d.budgetTotal||0),companyId:d.companyId||null,validationNotes:d.validationNotes||''};
  }

  function queueSave(delay=650){
    if(!activeSurvey)return;
    activeSurvey.updatedAt=new Date().toISOString();
    mergeSurveySummary(activeSurvey); renderDraftSelect();
    setServerState('saving','Salvando');
    $('#autosaveStatus').innerHTML='<i class="bi bi-cloud-arrow-up"></i> Salvando no servidor…';
    clearTimeout(saveTimer);
    saveTimer=setTimeout(()=>{saveTimer=null;saveNow().catch(showError)},delay);
  }

  async function saveNow(){
    if(!activeSurvey)return;
    const id=activeSurvey.id;
    const work=api(`/api/technical-surveys/${id}`,{method:'PATCH',body:payloadFromDraft()});
    saveInFlight=work;
    try{
      const saved=await work;
      if(String(activeDraftId)===String(id)) activeSurvey={...activeSurvey,...saved};
      mergeSurveySummary(saved); renderDraftSelect(); renderWorkflow(); renderHistory();
      setServerState('saved','Sincronizado');
      $('#autosaveStatus').innerHTML='<i class="bi bi-cloud-check"></i> Salvo no servidor';
      return saved;
    } finally { if(saveInFlight===work) saveInFlight=null; }
  }

  async function flushSave(){
    if(saveTimer){clearTimeout(saveTimer);saveTimer=null;await saveNow();}
    else if(saveInFlight){await saveInFlight;}
  }

  function showError(err){
    console.error(err); setServerState('error','Erro ao salvar');
    const msg=err?.message || 'Não foi possível concluir a operação.';
    alert(msg);
  }

  function renderDraftSelect(){
    const sel=$('#draftSelect'); if(!sel)return;
    sel.innerHTML=surveys.map(d=>`<option value="${d.id}" ${String(d.id)===String(activeDraftId)?'selected':''}>${escapeHtml(draftLabel(d))} · ${escapeHtml(d.statusLabel||'')}</option>`).join('');
  }

  function renderCourse(filter=''){
    const q=filter.trim().toLowerCase();
    $('#courseModules').innerHTML=lessons.map((l,i)=>({l,i})).filter(({l})=>!q || `${l.title} ${l.summary} ${l.learn.join(' ')}`.toLowerCase().includes(q)).map(({l,i})=>`<button class="ts-module-card ${i===activeLesson?'active':''}" data-lesson="${i}"><span class="ts-module-number">${i}</span><span><b>${escapeHtml(l.title)}</b><small>${escapeHtml(l.summary)}</small></span>${courseProgress.has(i)?'<i class="bi bi-check-circle-fill"></i>':'<i class="bi bi-chevron-right"></i>'}</button>`).join('');
    $$('.ts-module-card').forEach(b=>b.addEventListener('click',()=>openLesson(Number(b.dataset.lesson)))); updateCourseProgress();
  }
  function openLesson(i){activeLesson=i;const l=lessons[i];$('#lessonPanel').innerHTML=`<div class="ts-lesson-head"><span><i class="bi ${l.icon}"></i></span><div><p class="ts-eyebrow">MÓDULO ${i}</p><h2>${escapeHtml(l.title)}</h2><p>${escapeHtml(l.summary)}</p></div></div><div class="ts-lesson-block"><h3>Por que você precisa saber isso?</h3><p>${escapeHtml(l.why)}</p></div><div class="ts-lesson-block"><h3>O que você vai dominar</h3><ul>${l.learn.map(x=>`<li>${escapeHtml(x)}</li>`).join('')}</ul></div><div class="ts-lesson-block"><h3>Aplicação prática</h3><p>${escapeHtml(l.practice)}</p></div>${l.alert?`<div class="ts-warning"><i class="bi bi-exclamation-triangle"></i><p><b>Alerta técnico</b><span>${escapeHtml(l.alert)}</span></p></div>`:''}<div class="ts-lesson-actions"><button class="ts-btn secondary" data-lesson-survey><i class="bi bi-rulers"></i> Aplicar no levantamento</button><button class="ts-btn primary" data-complete-lesson><i class="bi bi-check2-circle"></i> ${courseProgress.has(i)?'Concluído':'Marcar como concluído'}</button></div>`;
    $('[data-complete-lesson]').addEventListener('click',()=>{courseProgress.add(i);saveJson(COURSE_STORE,[...courseProgress]);renderCourse($('#courseSearch').value);openLesson(i)});
    $('[data-lesson-survey]').addEventListener('click',()=>openView('survey')); renderCourse($('#courseSearch').value);
  }
  function updateCourseProgress(){const pct=Math.round((courseProgress.size/lessons.length)*100);$('#coursePct').textContent=`${pct}%`;$('#courseRing').style.setProperty('--pct',`${pct}%`);$('#courseCompleted').textContent=`${courseProgress.size} de ${lessons.length} módulos concluídos`}

  function technicalEditable(){return ['DRAFT','PENDING_VALIDATION'].includes(draft().status)}
  function commercialEditable(){return ['DRAFT','PENDING_VALIDATION','VALIDATED'].includes(draft().status)}

  function renderSurvey(){
    if(!activeSurvey)return;
    $('#surveyStepper').innerHTML=sections.map((s,i)=>`<button type="button" class="ts-step-btn ${i===currentSection?'active':''}" data-step="${i}" title="${escapeHtml(s.title)}">${i+1}</button>`).join('');
    $('#surveySections').innerHTML=sections.map((s,i)=>`<section class="ts-form-section ${i===currentSection?'active':''}" data-section="${i}"><div class="ts-form-section-head"><div><p class="ts-eyebrow">ETAPA ${i+1} DE ${sections.length}</p><h2>${escapeHtml(s.title)}</h2><p>${escapeHtml(s.desc)}</p>${s.learn?`<button type="button" class="ts-learn-btn" data-learn="${s.learn}"><i class="bi bi-mortarboard"></i> Aprender este conceito</button>`:''}</div><span class="ts-section-icon"><i class="bi ${s.icon}"></i></span></div><div class="ts-form-grid">${s.fields.map(renderField).join('')}${i===1?'<div class="ts-measure-result wide" id="measureReference"></div>':''}${s.photos?renderPhotoZone(s.photos):''}</div></section>`).join('');
    bindForm(); bindLearn(); bindPhotoInputs(); updateSurveyProgress(); applyLocks(); renderWorkflow(); hydrateCrm();
  }

  function renderField(x){
    const req=x.required?'<em class="ts-required">*</em>':''; let control=''; const value=draft().fields?.[x.id] ?? '';
    if(x.type==='select') control=`<select data-field="${x.id}" ${x.required?'data-required="1"':''}><option value="">Selecione…</option>${x.options.map(o=>`<option ${value===o?'selected':''}>${escapeHtml(o)}</option>`).join('')}</select>`;
    else if(x.type==='textarea') control=`<textarea rows="3" data-field="${x.id}" ${x.required?'data-required="1"':''}>${escapeHtml(value)}</textarea>`;
    else if(x.type==='checks'){const current=Array.isArray(value)?value:[];control=`<div class="ts-option-grid">${x.options.map(o=>`<label class="ts-option"><input type="checkbox" data-field-check="${x.id}" value="${escapeAttr(o)}" ${current.includes(o)?'checked':''}> ${escapeHtml(o)}</label>`).join('')}</div>`;}
    else control=`<input type="${x.type}" data-field="${x.id}" ${x.required?'data-required="1"':''} value="${escapeAttr(value)}" ${x.type==='number'?'min="0" step="1" inputmode="numeric"':''}>`;
    return `<div class="ts-field ${x.type==='textarea'||x.type==='checks'?'wide':''}"><span>${escapeHtml(x.label)} ${req}</span>${control}${x.helper?`<small class="ts-helper"><i class="bi bi-info-circle"></i>${escapeHtml(x.helper)}</small>`:''}${x.learn?`<button type="button" class="ts-learn-btn" data-learn="${x.learn}"><i class="bi bi-question-circle"></i> O que é isso?</button>`:''}</div>`;
  }

  function renderPhotoZone(p){return `<div class="ts-photo-zone"><div class="ts-photo-zone-head"><div><h4><i class="bi bi-camera"></i> ${escapeHtml(p.title)}</h4><p>${escapeHtml(p.desc)} Fotos e vídeos ficam salvos no servidor.</p></div><label class="ts-btn secondary ts-camera-btn"><i class="bi bi-camera-fill"></i> Câmera / arquivo<input type="file" accept="image/*,video/mp4,video/webm,video/quicktime" capture="environment" multiple data-photo-input="${p.id}"></label></div><div class="ts-photo-previews" data-photo-list="${p.id}"></div></div>`}

  function bindForm(){
    $$('[data-field]').forEach(el=>el.addEventListener('input',()=>{draft().fields[el.dataset.field]=el.value;touchDraft();updateSurveyProgress()}));
    $$('[data-field-check]').forEach(el=>el.addEventListener('change',()=>{const id=el.dataset.fieldCheck;draft().fields[id]=$$(`[data-field-check="${id}"]:checked`).map(c=>c.value);touchDraft();updateSurveyProgress()}));
  }
  function touchDraft(){queueSave();updateBudgetSummary();}

  function updateSurveyProgress(){
    const required=$$('[data-required="1"]'); const done=required.filter(x=>String(x.value||'').trim()).length; const pct=required.length?Math.round(done/required.length*100):0;
    draft().progress=pct; $('#surveyPct').textContent=`${pct}%`; $('#surveyProgress').style.width=`${pct}%`; $('#surveyMissing').textContent=pct===100?'Campos essenciais preenchidos. Envie para validação técnica.':`${required.length-done} campo(s) essencial(is) ainda não preenchido(s).`;
    $('#surveyStepper').querySelectorAll('button').forEach((b,i)=>{const sec=$(`[data-section="${i}"]`);const req=$$('[data-required="1"]',sec);b.classList.toggle('done',req.length>0 && req.every(x=>String(x.value||'').trim()))});
    const mr=$('#measureReference'); if(mr){const r=refs();const d=draft().fields;const diag=(Number(d.diagonal_1)&&Number(d.diagonal_2))?Math.abs(Number(d.diagonal_1)-Number(d.diagonal_2)):null;mr.innerHTML=`<i class="bi bi-bounding-box"></i><div><small>REFERÊNCIA AUTOMÁTICA DO LEVANTAMENTO</small><b>${r.w&&r.h?`${r.w} × ${r.h} mm`:'Preencha as 3 larguras e 3 alturas'}</b>${diag!==null?`<span>Diferença registrada entre diagonais: ${diag} mm · validar condição do esquadro.</span>`:''}</div>`;}
    renderWorkflow(); updateBudgetSummary();
  }

  function goSection(i){currentSection=Math.max(0,Math.min(sections.length-1,i));$$('.ts-form-section').forEach((s,n)=>s.classList.toggle('active',n===currentSection));$$('.ts-step-btn').forEach((b,n)=>b.classList.toggle('active',n===currentSection));$('#prevSection').disabled=currentSection===0;$('#nextSection').innerHTML=currentSection===sections.length-1?'Ir para orçamento <i class="bi bi-arrow-right"></i>':'Próxima etapa <i class="bi bi-arrow-right"></i>';window.scrollTo({top:0,behavior:'smooth'});loadSectionAttachments()}
  function bindLearn(){$$('[data-learn]').forEach(b=>b.addEventListener('click',()=>showMicro(b.dataset.learn)))}
  function showMicro(key){const m=micro[key];if(!m)return;$('#learnDialogContent').innerHTML=`<div class="ts-dialog-content"><i class="bi ${m.icon}"></i><h2>${escapeHtml(m.title)}</h2><p class="lead">${escapeHtml(m.lead)}</p><div class="ts-learn-grid"><article><h3>O que observar</h3><p>${escapeHtml(m.what)}</p></article><article><h3>Como fazer</h3><p>${escapeHtml(m.how)}</p></article><article><h3>Impacto técnico/comercial</h3><p>${escapeHtml(m.impact)}</p></article><article><h3>Regra do sistema</h3><p>Se houver dúvida, registre a condição real, fotografe e marque para validação técnica. Não presuma.</p></article></div></div>`;$('#learnDialog').showModal()}

  async function uploadAttachments(group, files){
    if(!files.length)return;
    setServerState('saving','Enviando anexos');
    const form=new FormData(); form.append('group',group); [...files].forEach(file=>form.append('file',file));
    const data=await api(`/api/technical-surveys/${draft().id}/attachments`,{method:'POST',body:form});
    draft().attachments=[...(draft().attachments||[]),...(data.items||[])];
    await refreshDetail(false); renderPhotoGroup(group); renderHistory(); setServerState('saved','Sincronizado');
  }
  function bindPhotoInputs(){$$('[data-photo-input]').forEach(inp=>inp.addEventListener('change',async()=>{try{await uploadAttachments(inp.dataset.photoInput,inp.files)}catch(e){showError(e)}finally{inp.value=''}}));loadSectionAttachments()}
  function loadSectionAttachments(){const s=sections[currentSection];if(s?.photos)renderPhotoGroup(s.photos.id)}
  function renderPhotoGroup(group){
    const list=$(`[data-photo-list="${group}"]`); if(!list)return;
    const rows=(draft().attachments||[]).filter(x=>x.group===group);
    list.innerHTML=rows.map(x=>`<div class="ts-photo-item">${x.mimeType?.startsWith('video/')?`<video src="${escapeAttr(x.url)}" controls preload="metadata"></video>`:`<img src="${escapeAttr(x.url)}" alt="${escapeAttr(x.name)}">`}<small>${escapeHtml(x.name)}</small>${technicalEditable()?`<button type="button" data-delete-attachment="${x.id}" title="Excluir"><i class="bi bi-x-lg"></i></button>`:''}</div>`).join('') || '<div class="ts-photo-empty"><i class="bi bi-cloud"></i><span>Nenhum anexo nesta etapa.</span></div>';
    $$('[data-delete-attachment]',list).forEach(b=>b.addEventListener('click',async()=>{if(!confirm('Excluir este anexo do servidor?'))return;try{await api(`/api/technical-surveys/attachments/${b.dataset.deleteAttachment}`,{method:'DELETE'});draft().attachments=draft().attachments.filter(x=>String(x.id)!==String(b.dataset.deleteAttachment));renderPhotoGroup(group);await refreshDetail(false);renderHistory()}catch(e){showError(e)}}));
  }

  async function loadCompanies(q=''){
    try{
      const data=await api(`/api/companies?perPage=100${q?`&q=${encodeURIComponent(q)}`:''}`);
      companyOptions=new Map((data.items||[]).map(x=>[`${x.name}${x.city?` · ${x.city}`:''}`,x]));
      $('#companyOptions').innerHTML=[...companyOptions].map(([label,x])=>`<option value="${escapeAttr(label)}" data-id="${x.id}"></option>`).join('');
    }catch(e){console.warn('CRM search',e)}
  }
  function hydrateCrm(){
    const input=$('#companySearch'); if(!input||!activeSurvey)return;
    if(activeSurvey.company){input.value=`${activeSurvey.company.name}${activeSurvey.company.city?` · ${activeSurvey.company.city}`:''}`;$('#companyLinkHelp').textContent=`Vinculado ao CRM · ID ${activeSurvey.company.id}`;}
    else {input.value='';$('#companyLinkHelp').textContent='A ficha pode existir sem vínculo e ser vinculada depois.';}
  }
  async function linkCompanyByLabel(label){
    const hit=companyOptions.get(label); if(!hit)return;
    try{await flushSave();const saved=await api(`/api/technical-surveys/${draft().id}`,{method:'PATCH',body:{companyId:hit.id}});activeSurvey=saved;mergeSurveySummary(saved);hydrateCrm();renderWorkflow();renderHistory();renderDraftSelect()}catch(e){showError(e)}
  }
  async function unlinkCompany(){
    if(!draft().companyId)return;
    try{await flushSave();const saved=await api(`/api/technical-surveys/${draft().id}`,{method:'PATCH',body:{companyId:null}});activeSurvey=saved;mergeSurveySummary(saved);hydrateCrm();renderHistory();renderDraftSelect()}catch(e){showError(e)}
  }

  const STATUS_FLOW=[
    ['DRAFT','Rascunho','bi-pencil-square'],['PENDING_VALIDATION','Validação técnica','bi-clipboard2-pulse'],['VALIDATED','Validado','bi-patch-check'],['QUOTE_GENERATED','Orçamento gerado','bi-file-earmark-check'],['APPROVED','Aprovado','bi-check2-circle']
  ];
  function renderWorkflow(){
    if(!activeSurvey)return; const d=draft();
    const badge=$('#statusBadge'); badge.textContent=d.statusLabel||STATUS_FLOW.find(x=>x[0]===d.status)?.[1]||d.status; badge.className=`ts-status-badge status-${d.status}`;
    const current=STATUS_FLOW.findIndex(x=>x[0]===d.status);
    $('#statusTrack').innerHTML=STATUS_FLOW.map((x,i)=>`<div class="ts-status-node ${i<current?'done':i===current?'active':''}"><i class="bi ${x[2]}"></i><span>${escapeHtml(x[1])}</span></div>`).join('');
    const actions=[];
    if(d.status==='DRAFT') actions.push(`<button class="ts-btn primary" data-status="PENDING_VALIDATION"><i class="bi bi-send-check"></i> Enviar para validação</button>`);
    if(d.status==='PENDING_VALIDATION'){
      if(d.permissions?.canValidate) actions.push(`<button class="ts-btn primary" data-status="VALIDATED"><i class="bi bi-patch-check"></i> Validar tecnicamente</button>`);
      actions.push(`<button class="ts-btn secondary" data-status="DRAFT"><i class="bi bi-arrow-counterclockwise"></i> Voltar a rascunho</button>`);
    }
    if(d.status==='VALIDATED') actions.push(`<button class="ts-btn secondary" data-status="PENDING_VALIDATION"><i class="bi bi-pencil-square"></i> Reabrir para revisão</button>`,`<button class="ts-btn primary" data-open-view="budget"><i class="bi bi-receipt"></i> Compor orçamento</button>`);
    if(d.status==='QUOTE_GENERATED') actions.push(`<button class="ts-btn secondary" data-status="VALIDATED"><i class="bi bi-arrow-counterclockwise"></i> Voltar para validado</button>`,`<button class="ts-btn primary" data-open-view="budget"><i class="bi bi-pen"></i> Assinatura / aprovação</button>`);
    if(d.status==='APPROVED') actions.push(`<button class="ts-btn secondary" data-status="QUOTE_GENERATED"><i class="bi bi-arrow-counterclockwise"></i> Reabrir orçamento</button>`);
    $('#workflowActions').innerHTML=actions.join('');
    $$('[data-status]','#workflowActions').forEach(b=>b.addEventListener('click',()=>changeStatus(b.dataset.status)));
    $$('[data-open-view]','#workflowActions').forEach(b=>b.addEventListener('click',()=>openView(b.dataset.openView)));
    $('#validationNotes').value=d.validationNotes||'';
    $('#validationNotes').disabled=d.status==='APPROVED';
    applyLocks(); renderSignatureState(); updateBudgetActionState();
  }

  async function changeStatus(target){
    try{
      await flushSave();
      const body={status:target,notes:$('#validationNotes')?.value||''};
      setServerState('saving','Atualizando status');
      const saved=await api(`/api/technical-surveys/${draft().id}/status`,{method:'POST',body});
      activeSurvey=saved;mergeSurveySummary(saved);renderAllActive();setServerState('saved','Sincronizado');
      if(target==='VALIDATED') openView('budget');
    }catch(e){if(e.data?.missingRequired){openView('survey');alert(`${e.message}\n\nFaltam ${e.data.missingRequired.length} campos essenciais.`)}else showError(e)}
  }

  function applyLocks(){
    const tech=technicalEditable(); const commercial=commercialEditable();
    $$('[data-field], [data-field-check], [data-photo-input]').forEach(el=>el.disabled=!tech);
    $$('.ts-camera-btn').forEach(el=>el.classList.toggle('disabled',!tech));
    $$('[data-budget], [data-commercial]').forEach(el=>el.disabled=!commercial);
    $('#deleteDraft').disabled=!(draft().permissions?.canDelete ?? draft().status==='DRAFT');
  }

  function parseMoney(v){
    const raw=String(v||'').trim(); if(!raw)return 0;
    if(currency==='PYG') return Number(raw.replace(/[^0-9-]/g,''))||0;
    const s=raw.replace(/\./g,'').replace(',','.').replace(/[^0-9.-]/g,''); return Number(s)||0;
  }
  function hydrateBudget(){$$('[data-budget]').forEach(i=>i.value=draft().budget?.[i.dataset.budget]??'');$$('[data-commercial]').forEach(i=>i.value=draft().commercial?.[i.dataset.commercial]??'');calcBudget(false);renderSignatureState();applyLocks();}
  function calcBudget(save=true){let total=0;$$('[data-budget]').forEach(i=>total+=parseMoney(i.value));$('#budgetTotal').textContent=money.format(total);draft().budgetTotal=total;if(save)queueSave();updateBudgetSummary()}
  function refs(){const d=draft().fields||{};const widths=['width_top','width_middle','width_bottom'].map(k=>Number(d[k])).filter(Boolean);const heights=['height_left','height_middle','height_right'].map(k=>Number(d[k])).filter(Boolean);return {w:widths.length?Math.min(...widths):null,h:heights.length?Math.min(...heights):null}}
  function updateBudgetSummary(){const d=draft().fields||{},r=refs();const rows=[['Ficha',draft().reference||'—'],['Status',draft().statusLabel||'—'],['Cliente',d.client_name||'—'],['CRM',draft().company?.name||'Sem vínculo'],['Local',d.city_country||'—'],['Vão de referência',r.w&&r.h?`${r.w} × ${r.h} mm`:'—'],['Verga',d.headroom?`${d.headroom} mm`:'—'],['Laterais',d.left_side&&d.right_side?`${d.left_side} / ${d.right_side} mm`:'—'],['Painel',d.panel_type||'—'],['Acionamento',d.operation_mode||'—'],['Tensão',d.voltage||'—'],['Total preliminar',money.format(draft().budgetTotal||0)]];$('#budgetSummary').innerHTML=rows.map(x=>`<div class="ts-summary-row"><span>${escapeHtml(x[0])}</span><b>${escapeHtml(String(x[1]))}</b></div>`).join('')}

  async function generatePdf(){
    try{
      await flushSave(); setServerState('saving','Gerando orçamento');
      const data=await api(`/api/technical-surveys/${draft().id}/generate-quote`,{method:'POST'});
      activeSurvey=data.survey;mergeSurveySummary(activeSurvey);renderAllActive();setServerState('saved','Sincronizado');
      window.open(data.pdfUrl,'_blank','noopener');
    }catch(e){showError(e)}
  }
  function updateBudgetActionState(){
    const canPdf=['VALIDATED','QUOTE_GENERATED','APPROVED'].includes(draft().status);
    $('#generatePdf').disabled=!canPdf;
    $('#generatePdf').title=canPdf?'Gerar PDF definitivo do orçamento':'A ficha precisa ser validada tecnicamente antes do PDF.';
    $('#approveSurvey').style.display=['QUOTE_GENERATED','APPROVED'].includes(draft().status)?'inline-flex':'none';
    $('#approveSurvey').disabled=draft().status==='APPROVED';
  }

  function setupSignaturePad(){
    const canvas=$('#signaturePad'); if(!canvas)return; const ctx=canvas.getContext('2d'); ctx.lineWidth=4;ctx.lineCap='round';ctx.lineJoin='round';ctx.strokeStyle='#17231f';
    const point=e=>{const r=canvas.getBoundingClientRect();return {x:(e.clientX-r.left)*(canvas.width/r.width),y:(e.clientY-r.top)*(canvas.height/r.height)}};
    canvas.addEventListener('pointerdown',e=>{if(!signatureEnabled())return;signatureDrawing=true;signatureDirty=true;canvas.setPointerCapture(e.pointerId);const p=point(e);ctx.beginPath();ctx.moveTo(p.x,p.y)});
    canvas.addEventListener('pointermove',e=>{if(!signatureDrawing)return;const p=point(e);ctx.lineTo(p.x,p.y);ctx.stroke()});
    const stop=()=>{signatureDrawing=false}; canvas.addEventListener('pointerup',stop);canvas.addEventListener('pointercancel',stop);canvas.addEventListener('pointerleave',stop);
  }
  function signatureEnabled(){return ['QUOTE_GENERATED','APPROVED'].includes(draft().status)}
  function clearSignatureCanvas(){const canvas=$('#signaturePad');if(!canvas)return;canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);signatureDirty=true;}
  function drawStoredSignature(){
    const canvas=$('#signaturePad');if(!canvas)return;const ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);signatureDirty=false;
    if(!draft().signatureData)return;const img=new Image();img.onload=()=>{ctx.drawImage(img,0,0,canvas.width,canvas.height)};img.src=draft().signatureData;
  }
  function renderSignatureState(){
    const enabled=signatureEnabled(); const canvas=$('#signaturePad'); if(!canvas)return;
    canvas.classList.toggle('disabled',!enabled); $('#signatureName').disabled=!enabled;$('#clearSignature').disabled=!enabled;$('#saveSignature').disabled=!enabled;
    $('#signatureName').value=draft().signatureName||'';
    $('#signatureHelp').textContent=enabled?'Assine no quadro e registre. A assinatura ficará vinculada à ficha no servidor.':'A assinatura é habilitada depois que a ficha for validada e o orçamento gerado.';
    $('#signedState').innerHTML=draft().hasSignature?`<i class="bi bi-patch-check-fill"></i><div><b>Assinatura registrada</b><span>${escapeHtml(draft().signatureName||'')} · ${formatDate(draft().signedAt)}</span></div>`:'';
    drawStoredSignature();
  }
  async function saveSignature(){
    if(!signatureEnabled())return; const name=$('#signatureName').value.trim(); const canvas=$('#signaturePad');
    if(!name){alert('Informe o nome completo do assinante.');return}
    if(!signatureDirty && !draft().signatureData){alert('Registre a assinatura no quadro.');return}
    const signatureData=signatureDirty?canvas.toDataURL('image/png'):draft().signatureData;
    try{const saved=await api(`/api/technical-surveys/${draft().id}/signature`,{method:'POST',body:{name,signatureData}});activeSurvey=saved;mergeSurveySummary(saved);renderSignatureState();renderHistory();renderWorkflow()}catch(e){showError(e)}
  }
  async function approveSurvey(){if(draft().status==='APPROVED')return;await changeStatus('APPROVED')}

  function eventIcon(action){return ({CREATED:'bi-plus-circle',CRM_LINK_CHANGED:'bi-building-check',STATUS_CHANGED:'bi-arrow-left-right',SIGNED:'bi-pen',ATTACHMENT_ADDED:'bi-paperclip',ATTACHMENT_REMOVED:'bi-trash3',QUOTE_GENERATED:'bi-file-earmark-check'}[action]||'bi-clock-history')}
  function renderHistory(){
    if(!activeSurvey)return; $('#historyReference').textContent=draft().reference||'—';
    const events=draft().events||[];
    $('#historyTimeline').innerHTML=events.length?events.map(e=>`<article class="ts-history-event"><span><i class="bi ${eventIcon(e.action)}"></i></span><div><div><b>${escapeHtml(e.summary||e.action)}</b><time>${formatDate(e.createdAt)}</time></div><p>${escapeHtml(e.user||'Sistema')}${e.fromStatus||e.toStatus?` · ${escapeHtml(e.fromStatus||'')} ${e.toStatus?'→ '+escapeHtml(e.toStatus):''}`:''}</p></div></article>`).join(''):'<div class="ts-history-empty"><i class="bi bi-clock-history"></i><p>Nenhum evento registrado ainda.</p></div>';
    const d=draft();$('#historySummary').innerHTML=`<div class="ts-card-title"><span><i class="bi bi-card-checklist"></i></span><div><p class="ts-eyebrow">FICHA 360</p><h2>${escapeHtml(d.reference||'')}</h2></div></div><div class="ts-history-facts"><div><span>Status</span><b>${escapeHtml(d.statusLabel||'—')}</b></div><div><span>Cliente</span><b>${escapeHtml(d.fields?.client_name||'—')}</b></div><div><span>CRM</span><b>${escapeHtml(d.company?.name||'Sem vínculo')}</b></div><div><span>Criada por</span><b>${escapeHtml(d.createdBy||'—')}</b></div><div><span>Validação</span><b>${d.validatedAt?`${escapeHtml(d.validatedBy||'')} · ${formatDate(d.validatedAt)}`:'—'}</b></div><div><span>Assinatura</span><b>${d.signedAt?`${escapeHtml(d.signatureName||'')} · ${formatDate(d.signedAt)}`:'—'}</b></div><div><span>Aprovação</span><b>${formatDate(d.approvedAt)}</b></div><div><span>Anexos</span><b>${(d.attachments||[]).length}</b></div></div>`;
  }

  function openView(view){
    $$('.ts-view').forEach(v=>v.classList.toggle('active',v.dataset.viewPanel===view));$$('.ts-nav').forEach(b=>b.classList.toggle('active',b.dataset.view===view));
    const titles={academy:'Academia técnica',survey:'Levantamento técnico-comercial',budget:'Orçamento preliminar',history:'Histórico da ficha'};$('#viewTitle').textContent=titles[view]||'Academia técnica';
    if(view==='survey'){renderSurvey();goSection(currentSection)} if(view==='budget'){hydrateBudget();updateBudgetSummary();renderWorkflow()} if(view==='history')renderHistory();window.scrollTo({top:0,behavior:'smooth'});
  }

  async function refreshDetail(render=true){
    if(!activeSurvey)return; const detail=await api(`/api/technical-surveys/${draft().id}`);activeSurvey=detail;mergeSurveySummary(detail);if(render)renderAllActive();return detail;
  }
  function renderAllActive(){renderDraftSelect();renderSurvey();hydrateBudget();hydrateCrm();renderWorkflow();renderHistory();updateBudgetSummary();}

  function bindGlobal(){
    $$('.ts-nav').forEach(b=>b.addEventListener('click',()=>openView(b.dataset.view)));$$('[data-open-view]').forEach(b=>b.addEventListener('click',()=>openView(b.dataset.openView)));
    $('#courseSearch').addEventListener('input',e=>renderCourse(e.target.value));$('[data-start-course]').addEventListener('click',()=>openLesson(0));
    $('#draftSelect').addEventListener('change',e=>selectSurvey(e.target.value).catch(showError));
    $('#newDraft').addEventListener('click',()=>createSurvey().catch(showError));
    $('#deleteDraft').addEventListener('click',async()=>{if(!draft().permissions?.canDelete){alert('Somente fichas em rascunho podem ser excluídas.');return}if(!confirm('Excluir definitivamente esta ficha em rascunho?'))return;try{await api(`/api/technical-surveys/${draft().id}`,{method:'DELETE'});surveys=surveys.filter(x=>String(x.id)!==String(draft().id));activeSurvey=null;if(!surveys.length){await createSurvey()}else{await selectSurvey(surveys[0].id,false)}}catch(e){showError(e)}});
    $('#prevSection').addEventListener('click',e=>{e.preventDefault();goSection(currentSection-1)});$('#nextSection').addEventListener('click',e=>{e.preventDefault();if(currentSection===sections.length-1)openView('budget');else goSection(currentSection+1)});
    $('#surveyStepper').addEventListener('click',e=>{const b=e.target.closest('[data-step]');if(b)goSection(Number(b.dataset.step))});$('[data-close-dialog]').addEventListener('click',()=>$('#learnDialog').close());
    $$('[data-budget]').forEach(i=>i.addEventListener('input',()=>{draft().budget[i.dataset.budget]=i.value;calcBudget(true)}));$$('[data-commercial]').forEach(i=>i.addEventListener('input',()=>{draft().commercial[i.dataset.commercial]=i.value;queueSave()}));
    $('#generatePdf').addEventListener('click',generatePdf);$('#approveSurvey').addEventListener('click',approveSurvey);
    $('#validationNotes').addEventListener('input',()=>{draft().validationNotes=$('#validationNotes').value;queueSave(900)});
    $('#companySearch').addEventListener('input',e=>{clearTimeout(companyTimer);companyTimer=setTimeout(()=>loadCompanies(e.target.value.trim()),250)});$('#companySearch').addEventListener('change',e=>linkCompanyByLabel(e.target.value));$('#unlinkCompany').addEventListener('click',unlinkCompany);
    $('#clearSignature').addEventListener('click',clearSignatureCanvas);$('#saveSignature').addEventListener('click',saveSignature);
    window.addEventListener('beforeunload',()=>{if(saveTimer&&draft().id){clearTimeout(saveTimer);saveTimer=null;try{fetch(`/api/technical-surveys/${draft().id}`,{method:'PATCH',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(payloadFromDraft()),keepalive:true})}catch(_){}}});
  }

  async function init(){
    try{
      renderCourse();openLesson(0);bindGlobal();setupSignaturePad();await loadCompanies();await loadSurveys();openView('academy');
    }catch(e){showError(e)}
  }
  init();
})();
