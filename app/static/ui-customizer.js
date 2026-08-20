(() => {
  const user = window.RADAR_USER || null;
  const canEdit = user && ["ADMIN","GROUP_ADMIN"].includes(user.role);
  const lang = (window.RADAR_BRAND || {}).language === "pt-BR" ? "pt" : "es";
  const defaults = {
    triage:{label:lang==="pt"?"Qualificar por site":"Calificar por sitio",group:"qualify",order:10},
    research:{label:lang==="pt"?"Fila de pesquisa":"Cola de investigación",group:"qualify",order:20},
    salesready:{label:lang==="pt"?"Pronto para vendas":"Listo para ventas",group:"qualify",order:30},
    hoy:{label:lang==="pt"?"Meu dia":"Mi día",group:"execute",order:10},
    crm:{label:"CRM",group:"execute",order:20},
    reportes:{label:lang==="pt"?"Relatórios":"Reportes",group:"execute",order:30},
    pipeline:{label:lang==="pt"?"Funil comercial":"Embudo comercial",group:"execute",order:40},
    visitas:{label:"Visitas",group:"execute",order:50},
    radar:{label:"Radar",group:"intel",order:10},
    captacion:{label:lang==="pt"?"Captação":"Captación",group:"intel",order:20},
    oportunidades:{label:lang==="pt"?"Oportunidades":"Oportunidades",group:"intel",order:30},
    smartlists:{label:lang==="pt"?"Listas inteligentes":"Listas inteligentes",group:"intel",order:40},
    metrics:{label:lang==="pt"?"Desempenho":"Rendimiento",group:"intel",order:50},
    admin:{label:lang==="pt"?"Usuários e acesso":"Usuarios y acceso",group:"admin",order:10}
  };
  let cfg = {};
  const get = key => ({...defaults[key], ...(cfg[key]||{})});

  function navLink(key){ return document.querySelector(`[data-module-target="${key}"]`); }
  function section(key){ return document.querySelector(`.app-module[data-module="${key}"]`); }
  function apply(){
    Object.keys(defaults).forEach(key=>{
      const row=get(key), link=navLink(key), sec=section(key);
      if(link){ const label=link.querySelector("span"); if(label) label.textContent=row.label; link.style.display=row.visible===false?"none":""; }
      if(sec) sec.dataset.customLabel=row.label;
    });
    const groups={}; Object.entries(defaults).forEach(([k,v])=>(groups[v.group]??=[]).push(k));
    Object.values(groups).forEach(keys=>{
      const present=keys.map(navLink).filter(Boolean); if(!present.length)return;
      const parent=present[0].parentElement;
      const anchor=present[0];
      const sorted=[...keys].sort((a,b)=>(get(a).order??defaults[a].order)-(get(b).order??defaults[b].order));
      sorted.forEach(k=>{ const el=navLink(k); if(el) parent.insertBefore(el, anchor); });
    });
    const active=document.querySelector('[data-module-target].active');
    if(active){ const k=active.dataset.moduleTarget; const title=document.getElementById('workspaceModuleTitle'); if(title&&defaults[k]) title.textContent=get(k).label; }
  }

  function ensureIcons(){
    if(!canEdit)return;
    Object.keys(defaults).forEach(key=>{
      const link=navLink(key); if(link && !link.querySelector('.module-edit-inline')){
        const i=document.createElement('i'); i.className='bi bi-pencil-square module-edit-inline'; i.title=lang==='pt'?'Editar módulo':'Editar módulo'; i.dataset.editModule=key; link.appendChild(i);
      }
      const sec=section(key); if(sec && !sec.querySelector(':scope > .module-head-edit')){
        const head=sec.querySelector('.section-head,.crm-head,.today-head,.capture-head,.reports-head,.visit-copy');
        if(head && !head.querySelector('.module-head-edit')){
          const b=document.createElement('button'); b.type='button'; b.className='module-head-edit'; b.dataset.editModule=key; b.title=lang==='pt'?'Editar este módulo':'Editar este módulo'; b.innerHTML='<i class="bi bi-pencil-square"></i>';
          head.appendChild(b);
        }
      }
    });
  }

  function overlay(){
    let o=document.getElementById('uiModuleEditor'); if(o)return o;
    o=document.createElement('div'); o.id='uiModuleEditor'; o.className='ui-editor-overlay';
    o.innerHTML=`<div class="ui-editor-card"><header><div><h3>${lang==='pt'?'Editar módulo':'Editar módulo'}</h3><p>${lang==='pt'?'Altere nome, posição ou visibilidade sem apagar o código.':'Cambie nombre, posición o visibilidad sin borrar el código.'}</p></div><button class="ui-editor-close" type="button"><i class="bi bi-x-lg"></i></button></header><form class="ui-editor-form"><input type="hidden" name="key"><label>${lang==='pt'?'Nome exibido':'Nombre visible'}<input name="label" type="text" maxlength="70"></label><label><span><input name="visible" type="checkbox"> ${lang==='pt'?'Módulo visível':'Módulo visible'}</span></label><div class="ui-editor-actions"><button type="button" data-move="up"><i class="bi bi-arrow-up"></i> ${lang==='pt'?'Mover para cima':'Mover arriba'}</button><button type="button" data-move="down"><i class="bi bi-arrow-down"></i> ${lang==='pt'?'Mover para baixo':'Mover abajo'}</button><button type="button" class="danger" data-hide><i class="bi bi-eye-slash"></i> ${lang==='pt'?'Ocultar':'Ocultar'}</button><button type="button" class="restore" data-reset><i class="bi bi-arrow-counterclockwise"></i> ${lang==='pt'?'Restaurar':'Restaurar'}</button><button class="save" type="submit"><i class="bi bi-check2"></i> ${lang==='pt'?'Salvar':'Guardar'}</button></div><div class="ui-editor-status"></div></form></div>`;
    document.body.appendChild(o);
    o.querySelector('.ui-editor-close').onclick=()=>o.classList.remove('open');
    o.addEventListener('click',e=>{if(e.target===o)o.classList.remove('open')});
    o.querySelector('[data-hide]').onclick=()=>{o.querySelector('[name=visible]').checked=false};
    o.querySelector('[data-reset]').onclick=()=>{const k=o.querySelector('[name=key]').value; delete cfg[k]; fill(k)};
    o.querySelectorAll('[data-move]').forEach(b=>b.onclick=()=>move(o.querySelector('[name=key]').value,b.dataset.move));
    o.querySelector('form').onsubmit=async e=>{e.preventDefault();const k=o.querySelector('[name=key]').value; const row=get(k); cfg[k]={...row,label:o.querySelector('[name=label]').value.trim()||defaults[k].label,visible:o.querySelector('[name=visible]').checked}; await save(); apply(); ensureIcons(); o.classList.remove('open')};
    return o;
  }
  function fill(key){const o=overlay(), row=get(key);o.querySelector('[name=key]').value=key;o.querySelector('[name=label]').value=row.label;o.querySelector('[name=visible]').checked=row.visible!==false;o.querySelector('.ui-editor-status').textContent='';}
  function open(key){if(!canEdit||!defaults[key])return;fill(key);overlay().classList.add('open')}
  function move(key,dir){const group=defaults[key].group;const keys=Object.keys(defaults).filter(k=>defaults[k].group===group).sort((a,b)=>(get(a).order??0)-(get(b).order??0));const i=keys.indexOf(key),j=dir==='up'?i-1:i+1;if(j<0||j>=keys.length)return;const a=get(key),b=get(keys[j]);cfg[key]={...a,order:b.order};cfg[keys[j]]={...b,order:a.order};apply();fill(key)}
  async function save(){const o=overlay();o.querySelector('.ui-editor-status').textContent=lang==='pt'?'Salvando...':'Guardando...';const r=await fetch('/api/ui-config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({modules:cfg})});const d=await r.json();if(!r.ok)throw new Error(d.error||'Erro');cfg=d.modules||cfg;}
  async function load(){try{const r=await fetch('/api/ui-config');if(r.ok){const d=await r.json();cfg=d.modules||{}}}catch(_){cfg={}}apply();ensureIcons()}

  document.addEventListener('click',e=>{const t=e.target.closest('[data-edit-module]');if(t){e.preventDefault();e.stopPropagation();open(t.dataset.editModule)}},true);
  // Keep custom label when workspace.js activates a module.
  document.addEventListener('click',e=>{const link=e.target.closest('[data-module-target]');if(link&&defaults[link.dataset.moduleTarget])setTimeout(()=>{const title=document.getElementById('workspaceModuleTitle');if(title)title.textContent=get(link.dataset.moduleTarget).label},0)},true);
  load();
})();
