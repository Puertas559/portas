(()=>{
  const $=id=>document.getElementById(id);
  const esc=(v="")=>String(v??"").replace(/[&<>'"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
  const roleLabel={ADMIN:"Administrador",MANAGER:"Gerente",SALES:"Comercial",VIEWER:"Solo consulta"};
  async function loadUsers(){
    const box=$("adminUserList"); if(!box)return;
    const r=await fetch('/api/admin/users'); const rows=await r.json();
    if(!r.ok){box.innerHTML='<p>No se pudieron cargar los usuarios.</p>';return;}
    $("adminActiveUsers").textContent=rows.filter(x=>x.status==='ACTIVE').length;
    $("adminAdmins").textContent=rows.filter(x=>x.role==='ADMIN'&&x.status==='ACTIVE').length;
    const last=rows.filter(x=>x.lastLoginAt).sort((a,b)=>new Date(b.lastLoginAt)-new Date(a.lastLoginAt))[0];
    $("adminLastLogin").textContent=last?new Date(last.lastLoginAt).toLocaleDateString('es-PY'):'Sin datos';
    box.innerHTML=rows.map(u=>`<article class="admin-user-row" data-user-id="${u.id}"><div class="admin-user-avatar">${esc(u.name.split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase())}</div><div class="admin-user-main"><strong>${esc(u.name)}</strong><span>${esc(u.email)}</span></div><label>Rol<select class="admin-role"><option value="ADMIN" ${u.role==='ADMIN'?'selected':''}>Administrador</option><option value="MANAGER" ${u.role==='MANAGER'?'selected':''}>Gerente</option><option value="SALES" ${u.role==='SALES'?'selected':''}>Comercial</option><option value="VIEWER" ${u.role==='VIEWER'?'selected':''}>Solo consulta</option></select></label><div class="admin-user-status ${u.status==='ACTIVE'?'active':'disabled'}"><i></i>${u.status==='ACTIVE'?'Activo':'Desactivado'}</div><small>${u.lastLoginAt?'Último acceso '+new Date(u.lastLoginAt).toLocaleString('es-PY'):'Nunca ingresó'}</small><button class="admin-toggle">${u.status==='ACTIVE'?'Desactivar':'Activar'}</button></article>`).join('');
  }
  async function patchUser(id,payload){const r=await fetch(`/api/admin/users/${id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const d=await r.json();if(!r.ok){alert(d.error||'No se pudo actualizar el usuario.');return false;}await loadUsers();return true;}
  document.addEventListener('change',e=>{const select=e.target.closest('.admin-role');if(!select)return;const row=select.closest('.admin-user-row');patchUser(row.dataset.userId,{role:select.value});});
  document.addEventListener('click',e=>{
    const open=e.target.closest('#openCreateUser'); if(open){$("createUserDialog")?.showModal();return;}
    const close=e.target.closest('#closeCreateUser'); if(close){$("createUserDialog")?.close();return;}
    const toggle=e.target.closest('.admin-toggle'); if(toggle){const row=toggle.closest('.admin-user-row');const disabled=row.querySelector('.admin-user-status').classList.contains('disabled');patchUser(row.dataset.userId,{status:disabled?'ACTIVE':'DISABLED'});return;}
    const adminOpen=e.target.closest('[data-module-open="admin"]'); if(adminOpen){document.querySelector('[data-module-target="admin"]')?.click();document.querySelector('.user-menu')?.removeAttribute('open');}
  });
  $("createUserForm")?.addEventListener('submit',async e=>{e.preventDefault();const msg=$("createUserMessage");const payload=Object.fromEntries(new FormData(e.target));const r=await fetch('/api/admin/users',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const d=await r.json();if(!r.ok){msg.textContent=d.error||'No se pudo crear el usuario.';return;}e.target.reset();$("createUserDialog").close();await loadUsers();});
  loadUsers();
})();
