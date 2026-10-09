const e=s=>String(s??'').replace(/[&<>"']/g,c=>'&#'+c.charCodeAt(0)+';'),$=s=>document.querySelector(s);
const ST={active:'Активен',inactive:'Деактивирован',blocked:'Заблокирована'};
const ROLE={superadmin:'Суперадминистратор',center_admin:'Администратор центра',ohs_engineer:'Инженер по ОТ',org_admin:'Администратор организации',employee:'Сотрудник'};
const fd=f=>Object.fromEntries([...new FormData(f)].filter(([,v])=>v!==''));
const dt=x=>new Date(x).toLocaleString('ru-RU');
let me=null,tok=JSON.parse(localStorage.getItem('tok')||'null');
const save=t=>{tok=t;t?localStorage.setItem('tok',JSON.stringify(t)):localStorage.removeItem('tok')};
const wide=()=>me.role==='superadmin'||me.role==='center_admin'||(me.role==='ohs_engineer'&&!me.org_id);
const center=()=>me.role==='superadmin'||me.role==='center_admin';
const canEdit=()=>['superadmin','center_admin','org_admin'].includes(me.role);

function toast(m,bad){const d=document.createElement('div');d.className='t'+(bad?' bad':'');d.textContent=m;$('#toast').append(d);setTimeout(()=>d.remove(),4500)}

async function api(p,o={}){
  const r=await fetch('/api/v1'+p,{method:o.method||'GET',headers:{'Content-Type':'application/json',...(tok&&!o.anon?{Authorization:'Bearer '+tok.access_token}:{})},body:o.body?JSON.stringify(o.body):undefined});
  if(r.status===401&&!o.anon&&!o.again&&tok){
    const rr=await fetch('/api/v1/auth/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({refresh_token:tok.refresh_token})});
    if(rr.ok){save(await rr.json());return api(p,{...o,again:1})}
    save(null);me=null;renderLogin();throw new Error('Сессия истекла, войдите заново');
  }
  if(r.status===204)return null;
  const d=await r.json().catch(()=>({})),x=d.detail;
  if(!r.ok){
    if(x&&x.code==='password_change_required'){renderChange(true);throw new Error(x.message)}
    throw new Error(typeof x==='string'?x:Array.isArray(x)?'Проверьте поле «'+x[0].loc.slice(-1)[0]+'»: '+String(x[0].msg).replace(/^Value error, /,''):(x&&x.message)||'Ошибка '+r.status);
  }
  return d;
}

function modal(title,body,ok,onOk){
  const m=document.createElement('div');m.className='ov';
  m.innerHTML=`<form class="card md"><h2>${title}</h2>${body}<div class="act"><button type="button" class="g" id="c">${ok?'Отмена':'Закрыть'}</button>${ok?`<button class="b">${ok}</button>`:''}</div></form>`;
  document.body.append(m);const f=m.firstChild;m.querySelector('#c').onclick=()=>m.remove();
  f.onsubmit=async ev=>{ev.preventDefault();if(!ok)return;try{await onOk(fd(f));m.remove()}catch(x){toast(x.message,1)}};
  return m;
}
function creds(r){
  const m=modal('Доступ выдан',`<p>Телефон для входа: <b>${e(r.phone)}</b></p><p>Временный пароль — он виден только сейчас:</p><div class="pw"><code>${e(r.temporary_password)}</code><button type="button" class="g" id="cp">Копировать</button></div><p class="m">Передайте его сотруднику. При первом входе система попросит придумать свой пароль.</p>`);
  m.querySelector('#cp').onclick=()=>navigator.clipboard.writeText(r.temporary_password).then(()=>toast('Пароль скопирован'));
}

function renderLogin(){
  $('#app').innerHTML=`<div class="auth"><form id="f" class="card"><h1>🦺 Охрана труда</h1><p class="m">Войдите по номеру телефона</p><label>Телефон<input name="phone" type="tel" placeholder="+7 900 000-00-00" required autofocus></label><label>Пароль<input name="password" type="password" required></label><button class="b">Войти</button></form></div>`;
  $('#f').onsubmit=async ev=>{ev.preventDefault();try{save(await api('/auth/login',{method:'POST',anon:1,body:fd(ev.target)}));start()}catch(x){toast(x.message,1)}};
}
function renderChange(forced){
  $('#app').innerHTML=`<div class="auth"><form id="f" class="card"><h1>Смена пароля</h1><p class="m">${forced?'Вы вошли с временным паролем. Придумайте свой: не короче 8 символов, буквы и цифры.':'Новый пароль: не короче 8 символов, буквы и цифры.'}</p><label>Текущий пароль<input name="current_password" type="password" required></label><label>Новый пароль<input name="new_password" type="password" minlength="8" required></label><label>Повторите новый пароль<input name="again" type="password" required></label><button class="b">Сохранить</button>${forced?'':'<a class="l" href="#" id="x">Отмена</a>'}</form></div>`;
  if(!forced)$('#x').onclick=ev=>{ev.preventDefault();start()};
  $('#f').onsubmit=async ev=>{ev.preventDefault();const v=fd(ev.target);
    if(v.new_password!==v.again)return toast('Пароли не совпадают',1);delete v.again;
    try{save(await api('/auth/change-password',{method:'POST',body:v}));toast('Пароль изменён');start()}catch(x){toast(x.message,1)}};
}

function shell(){
  const staff=me.role!=='employee',nav=[['#/','Главная','🏠']];
  if(staff)nav.push(['#/employees','Сотрудники','👥'],['#/orgs','Организации','🏢']);
  if(center())nav.push(['#/audit','Журнал действий','📜']);
  $('#app').innerHTML=`<aside><div class="logo">🦺 Охрана труда</div><nav>${nav.map(n=>`<a href="${n[0]}">${n[2]} ${n[1]}</a>`).join('')}</nav><div class="me"><b>${e(me.full_name)}</b><small>${ROLE[me.role]}</small><a href="#" id="pw">Сменить пароль</a><a href="#" id="out">Выйти</a></div></aside><main id="v"></main>`;
  $('#pw').onclick=ev=>{ev.preventDefault();renderChange(false)};
  $('#out').onclick=async ev=>{ev.preventDefault();try{await api('/auth/logout',{method:'POST',body:{refresh_token:tok.refresh_token}})}catch{}save(null);me=null;renderLogin()};
}

const R={'/':home,'/employees':employees,'/orgs':orgs,'/audit':audit};
async function route(){
  if(!me)return;if(!$('aside'))shell();
  const p=location.hash.slice(1)||'/',v=$('#v');
  document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('on',a.getAttribute('href')==='#'+p));
  v.innerHTML='<p class="m">Загрузка…</p>';
  try{await(R[p]||home)(v)}catch(x){v.innerHTML='';toast(x.message,1)}
}
addEventListener('hashchange',route);
async function start(){
  if(!tok)return renderLogin();
  try{me=await api('/auth/me')}catch{return renderLogin()}
  if(me.must_change_password)return renderChange(true);
  shell();route();
}

async function home(v){
  let h=`<h1>Здравствуйте, ${e(me.full_name)}!</h1><p class="m">${ROLE[me.role]}</p>`;
  if(me.role==='employee')h+=`<div class="card" style="margin-top:18px"><h2>Ваш личный кабинет</h2><p>Здесь появятся назначенные вам курсы, тесты и результаты обучения. Раздел обучения находится в разработке.</p></div>`;
  else{
    const n=q=>api('/employees?limit=1'+q).then(d=>d.total);
    const [all,act,off,org]=await Promise.all([n(''),n('&status=active'),n('&status=inactive'),center()?api('/organizations?limit=1').then(d=>d.total):null]);
    const st=(b,t)=>`<div class="card stat"><b>${b}</b><span>${t}</span></div>`;
    h+=`<div class="grid">${org!==null?st(org,'Организаций'):''}${st(all,'Сотрудников всего')}${st(act,'Активных')}${st(off,'Деактивированных')}</div>`;
    if(canEdit())h+=`<div class="card"><h2>С чего начать</h2><ol>${center()?'<li>Добавьте организацию в разделе «Организации».</li>':''}<li>Добавьте сотрудников в разделе «Сотрудники».</li><li>Нажмите «Выдать доступ» — система создаст кабинет и временный пароль.</li></ol><p class="m">Курсы, тесты, сроки обучения и отчёты — в разработке.</p></div>`;
  }
  v.innerHTML=h;
}

async function orgs(v){
  v.innerHTML=`<div class="bar"><h1>Организации</h1>${center()?'<button class="b" id="add">+ Добавить организацию</button>':''}</div><div class="filters"><input id="q" placeholder="Поиск по названию или ИНН…"></div><div id="tb"></div>`;
  const load=async()=>{
    const d=await api('/organizations?limit=200&q='+encodeURIComponent($('#q').value));
    $('#tb').innerHTML=d.items.length?`<div class="tw"><table><tr><th>Название</th><th>ИНН</th><th>Ответственный</th><th>Статус</th></tr>${d.items.map(o=>`<tr><td><b>${e(o.name)}</b><small>${e(o.legal_address||'')}</small></td><td>${e(o.inn||'—')}</td><td>${e(o.responsible_name||'—')}</td><td><span class="s ${o.status}">${ST[o.status]}</span></td></tr>`).join('')}</table></div>`:'<div class="card empty">Организаций пока нет. Нажмите «Добавить организацию».</div>';
  };
  let t;$('#q').oninput=()=>{clearTimeout(t);t=setTimeout(()=>load().catch(x=>toast(x.message,1)),300)};
  if(center())$('#add').onclick=()=>modal('Новая организация',`<label>Название*<input name="name" required></label><label>ИНН<input name="inn" pattern="[0-9]{10}([0-9]{2})?" title="10 или 12 цифр"></label><label>КПП<input name="kpp" pattern="[0-9]{9}" title="9 цифр"></label><label>Юридический адрес<input name="legal_address"></label><label>Ответственный<input name="responsible_name"></label>`,'Создать',async b=>{await api('/organizations',{method:'POST',body:b});toast('Организация создана');load()});
  await load();
}

async function employees(v){
  const w=wide(),os=w?(await api('/organizations?limit=200')).items:[];
  const opts=os.map(o=>`<option value="${o.id}">${e(o.name)}</option>`).join('');
  v.innerHTML=`<div class="bar"><h1>Сотрудники</h1>${canEdit()?'<button class="b" id="add">+ Добавить сотрудника</button>':''}</div><div class="filters"><input id="q" placeholder="Поиск по ФИО…">${w?`<select id="o"><option value="">Все организации</option>${opts}</select>`:''}<select id="s"><option value="">Любой статус</option><option value="active">Активные</option><option value="inactive">Деактивированные</option></select></div><div id="tb"></div>`;
  const btn=(a,id,t,c='g')=>`<button class="${c} sm" data-a="${a}" data-id="${id}">${t}</button>`;
  const acts=x=>(x.status==='active'&&!x.has_access?btn('grant',x.id,'Выдать доступ','b'):'')+(x.has_access?btn('reset',x.id,'Сбросить пароль'):'')+btn(x.status==='active'?'off':'on',x.id,x.status==='active'?'Деактивировать':'Восстановить');
  const load=async()=>{
    const p=new URLSearchParams({limit:200,q:$('#q').value,status:$('#s').value});if(w&&$('#o').value)p.set('org_id',$('#o').value);
    const d=await api('/employees?'+p);
    $('#tb').innerHTML=d.items.length?`<div class="tw"><table><tr><th>Сотрудник</th><th>Подразделение</th><th>Телефон</th><th>Статус</th>${canEdit()?'<th></th>':''}</tr>${d.items.map(x=>`<tr><td><b>${e(x.full_name)}</b><small>${e(x.position_name||'')}</small></td><td>${e(x.department_name||'—')}</td><td>${e(x.phone||'—')}</td><td><span class="s ${x.status}">${ST[x.status]}</span> ${x.has_access?'<span class="s ok">Есть доступ</span>':''}</td>${canEdit()?`<td class="ra">${acts(x)}</td>`:''}</tr>`).join('')}</table></div>`:'<div class="card empty">Сотрудников не найдено.</div>';
  };
  let t;const lazy=()=>{clearTimeout(t);t=setTimeout(()=>load().catch(x=>toast(x.message,1)),300)};
  $('#q').oninput=lazy;$('#s').onchange=lazy;if(w)$('#o').onchange=lazy;
  if(canEdit())$('#add').onclick=()=>modal('Новый сотрудник',`${w?`<label>Организация*<select name="org_id" required><option value="">Выберите…</option>${opts}</select></label>`:''}<label>ФИО*<input name="full_name" required></label><label>Телефон<input name="phone" type="tel" placeholder="+7 900 000-00-00"></label><p class="m" style="margin-top:-6px;font-size:13px">Телефон нужен, чтобы выдать сотруднику доступ в систему.</p><label>Дата приёма на работу<input name="hired_at" type="date"></label>`,'Добавить',async b=>{await api('/employees',{method:'POST',body:b});toast('Сотрудник добавлен');load()});
  $('#tb').onclick=async ev=>{
    const b=ev.target.closest('button[data-a]');if(!b)return;const id=b.dataset.id,a=b.dataset.a;
    try{
      if(a==='grant'||a==='reset'){
        if(a==='reset'&&!confirm('Сбросить пароль? Сотруднику придётся войти с новым временным паролем.'))return;
        creds(await api(`/employees/${id}/${a==='grant'?'grant-access':'reset-password'}`,{method:'POST'}));
      }else{
        if(a==='off'&&!confirm('Деактивировать сотрудника? Его доступ в систему будет закрыт.'))return;
        await api(`/employees/${id}/${a==='off'?'deactivate':'restore'}`,{method:'POST'});toast(a==='off'?'Сотрудник деактивирован':'Сотрудник восстановлен. Доступ нужно выдать заново.');
      }
      load();
    }catch(x){toast(x.message,1)}
  };
  await load();
}

async function audit(v){
  const d=await api('/audit?limit=100');
  v.innerHTML=`<div class="bar"><h1>Журнал действий</h1></div>${d.items.length?`<div class="tw"><table><tr><th>Время</th><th>Действие</th></tr>${d.items.map(a=>`<tr><td style="white-space:nowrap">${dt(a.at)}</td><td>${e(a.description)}</td></tr>`).join('')}</table></div>`:'<div class="card empty">Записей пока нет.</div>'}`;
}
start();
