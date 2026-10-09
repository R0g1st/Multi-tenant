const e=s=>String(s??'').replace(/[&<>"']/g,c=>'&#'+c.charCodeAt(0)+';'),$=s=>document.querySelector(s);
const ST={active:'Активен',inactive:'Деактивирован',blocked:'Заблокирована'};
// 1 — главный администратор, 2 — директор, 3 — заказчик, 4 — подчинённый
const ROLE={superadmin:'Главный администратор',center_admin:'Директор',org_admin:'Заказчик',employee:'Подчинённый'};
const fd=f=>Object.fromEntries([...new FormData(f)].filter(([,v])=>v!==''));
const dt=x=>new Date(x).toLocaleString('ru-RU'),dd=x=>new Date(x).toLocaleDateString('ru-RU');
const sz=b=>b<1024?b+' Б':b<1048576?(b/1024).toFixed(0)+' КБ':b<1073741824?(b/1048576).toFixed(1)+' МБ':(b/1073741824).toFixed(2)+' ГБ';
let me=null,tok=JSON.parse(localStorage.getItem('tok')||'null');
const save=t=>{tok=t;t?localStorage.setItem('tok',JSON.stringify(t)):localStorage.removeItem('tok')};
const center=()=>me.role==='superadmin'||me.role==='center_admin';
const canEdit=()=>['superadmin','center_admin','org_admin'].includes(me.role);

function toast(m,bad){const d=document.createElement('div');d.className='t'+(bad?' bad':'');d.textContent=m;$('#toast').append(d);setTimeout(()=>d.remove(),4500)}
function errText(x,status){return typeof x==='string'?x:Array.isArray(x)?'Проверьте поле «'+x[0].loc.slice(-1)[0]+'»: '+String(x[0].msg).replace(/^Value error, /,''):(x&&x.message)||'Ошибка '+status}

async function refresh(){
  const r=await fetch('/api/v1/auth/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({refresh_token:tok.refresh_token})});
  if(r.ok){save(await r.json());return true}
  save(null);me=null;renderLogin();return false;
}
async function api(p,o={}){
  const r=await fetch('/api/v1'+p,{method:o.method||'GET',headers:{'Content-Type':'application/json',...(tok&&!o.anon?{Authorization:'Bearer '+tok.access_token}:{})},body:o.body?JSON.stringify(o.body):undefined});
  if(r.status===401&&!o.anon&&!o.again&&tok){
    if(await refresh())return api(p,{...o,again:1});
    throw new Error('Сессия истекла, войдите заново');
  }
  if(r.status===204)return null;
  const d=await r.json().catch(()=>({})),x=d.detail;
  if(!r.ok){
    if(x&&x.code==='password_change_required'){renderChange(true);throw new Error(x.message)}
    throw new Error(errText(x,r.status));
  }
  return d;
}

function modal(title,body,ok,onOk,wide){
  const m=document.createElement('div');m.className='ov';
  m.innerHTML=`<form class="card md${wide?' wide':''}"><h2>${title}</h2>${body}<div class="act"><button type="button" class="g" id="c">${ok?'Отмена':'Закрыть'}</button>${ok?`<button class="b" id="ok">${ok}</button>`:''}</div></form>`;
  document.body.append(m);const f=m.firstChild;m.querySelector('#c').onclick=()=>m.remove();
  m.onclick=ev=>{if(ev.target===m&&!ok)m.remove()};
  f.onsubmit=async ev=>{ev.preventDefault();if(!ok)return;const b=m.querySelector('#ok');b.disabled=true;
    try{await onOk(fd(f),f);m.remove()}catch(x){toast(x.message,1)}finally{b.disabled=false}};
  return m;
}
function confirmBox(text,ok,onOk){modal('Подтвердите действие',`<p>${text}</p>`,ok,onOk)}
function creds(r){
  const m=modal('Доступ выдан',`<p>Телефон для входа: <b>${e(r.phone)}</b></p><p>Временный пароль — он виден только сейчас:</p><div class="pw"><code>${e(r.temporary_password)}</code><button type="button" class="g" id="cp">Копировать</button></div><p class="m">Передайте его пользователю. При первом входе система попросит придумать свой пароль.</p>`);
  m.querySelector('#cp').onclick=()=>navigator.clipboard.writeText(r.temporary_password).then(()=>toast('Пароль скопирован'));
}

/* ---------- Вход ---------- */
function renderLogin(){
  $('#app').innerHTML=`<div class="auth"><div class="side"><h1>Обучение и <span>охрана труда</span></h1><p>Единая платформа для обучения персонала, учебных материалов и контроля результатов.</p><ul><li>Библиотека документов и видеоуроков</li><li>Обучение и проверка знаний сотрудников</li><li>Контроль прохождения для руководителей и заказчиков</li></ul></div>
  <form id="f" class="card"><h1>Вход в систему</h1><p class="m">Войдите по номеру телефона</p><label>Телефон<input name="phone" type="tel" placeholder="+7 900 000-00-00" required autofocus></label><label>Пароль<input name="password" type="password" required></label><button class="b">Войти</button></form></div>`;
  $('#f').onsubmit=async ev=>{ev.preventDefault();try{save(await api('/auth/login',{method:'POST',anon:1,body:fd(ev.target)}));start()}catch(x){toast(x.message,1)}};
}
function renderChange(forced){
  $('#app').innerHTML=`<div class="auth"><div class="side"><h1>Смена пароля</h1><p>${forced?'Вы вошли с временным паролем. Придумайте свой.':'Задайте новый пароль.'}</p></div><form id="f" class="card"><h1>Новый пароль</h1><p class="m">Не короче 8 символов, буквы и цифры.</p><label>Текущий пароль<input name="current_password" type="password" required></label><label>Новый пароль<input name="new_password" type="password" minlength="8" required></label><label>Повторите новый пароль<input name="again" type="password" required></label><button class="b">Сохранить</button>${forced?'':'<a class="l" href="#" id="x">Отмена</a>'}</form></div>`;
  if(!forced)$('#x').onclick=ev=>{ev.preventDefault();start()};
  $('#f').onsubmit=async ev=>{ev.preventDefault();const v=fd(ev.target);
    if(v.new_password!==v.again)return toast('Пароли не совпадают',1);delete v.again;
    try{save(await api('/auth/change-password',{method:'POST',body:v}));toast('Пароль изменён');start()}catch(x){toast(x.message,1)}};
}

/* ---------- Каркас ---------- */
function shell(){
  // у уровней 1–2 пунктов много — на главную ведёт логотип
  const nav=center()?[['#/library','Библиотека'],['#/courses','Курсы'],['#/training','Обучение'],['#/orgs','Заказчики'],['#/employees','Сотрудники'],['#/users','Пользователи'],['#/audit','Журнал']]
    :me.role==='org_admin'?[['#/','Главная'],['#/library','Библиотека'],['#/courses','Курсы'],['#/training','Обучение'],['#/employees','Мои сотрудники']]
    :[['#/','Главная'],['#/learn','Моё обучение'],['#/customer','Мой заказчик']];
  $('#app').innerHTML=`<header><div class="hd"><a class="logo" href="#/"><i>✚</i><span>Охрана труда<small>обучение персонала</small></span></a><nav>${nav.map(n=>`<a href="${n[0]}">${n[1]}</a>`).join('')}</nav><div class="me"><div><b>${e(me.full_name)}</b><small>${ROLE[me.role]}</small></div><button class="g" id="pw">Пароль</button><button class="b" id="out">Выйти</button></div></div></header><main id="v"></main><footer><div><span>© ${new Date().getFullYear()} Охрана труда · обучение персонала</span><span>${ROLE[me.role]}</span></div></footer>`;
  $('#pw').onclick=()=>renderChange(false);
  $('#out').onclick=async()=>{try{await api('/auth/logout',{method:'POST',body:{refresh_token:tok.refresh_token}})}catch{}save(null);me=null;renderLogin()};
}

const R={'':home,'library':library,'employees':employees,'orgs':orgs,'users':users,'audit':audit,'customer':customer,
  'courses':courses,'course':courseEdit,'training':training,'learn':learn};
async function route(){
  if(!me)return;if(!$('header'))shell();
  const [p,arg]=(location.hash.slice(2)||'').split('/'),v=$('#v');
  const sect={course:'courses'}[p]||p;
  document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('on',a.getAttribute('href')==='#/'+sect));
  v.onclick=null;v.innerHTML='<p class="m">Загрузка…</p>';
  try{await(R[p]||home)(v,arg)}catch(x){v.innerHTML='';toast(x.message,1)}
}
addEventListener('hashchange',route);
async function start(){
  if(!tok)return renderLogin();
  try{me=await api('/auth/me')}catch{return renderLogin()}
  if(me.must_change_password)return renderChange(true);
  shell();route();
}

/* ---------- Главная ---------- */
async function home(v){
  const st=(b,t)=>`<div class="card stat"><b>${b}</b><span>${t}</span></div>`;
  let h=`<div class="card hero"><h1>Здравствуйте, <span>${e(me.full_name)}</span>!</h1><p>${ROLE[me.role]}</p></div>`;
  if(me.role==='employee'){
    const my=await api('/my/assignments'),todo=my.filter(a=>!['passed'].includes(a.state));
    h+=`<div class="grid">${st(todo.length,'Нужно пройти')}${st(my.filter(a=>a.state==='overdue').length,'Просрочено')}${st(my.filter(a=>a.state==='passed').length,'Пройдено')}</div>
      <div class="card"><h2>Моё обучение</h2>${todo.length?`<p>У вас ${todo.length} незавершённых курсов.</p><a href="#/learn"><button class="b">Перейти к обучению</button></a>`:'<p class="m">Сейчас нет курсов, которые нужно пройти.</p>'}</div>`;
  }else{
    const n=q=>api('/employees?limit=1'+q).then(d=>d.total);
    const [act,org,asg,cs]=await Promise.all([n('&status=active'),
      center()?api('/organizations?limit=1').then(d=>d.total):null,api('/assignments'),
      center()?api('/courses'):null]);
    const c=s=>asg.filter(a=>a.state===s).length;
    h+=`<div class="grid">${org!==null?st(org,'Заказчиков'):''}${st(act,'Активных сотрудников')}${cs?st(cs.length,'Курсов'):''}${st(c('assigned')+c('in_progress'),'Проходят обучение')}${st(c('passed'),'Прошли')}${st(c('overdue')+c('expired'),'Просрочено')}</div>`;
    if(center())h+=`<div class="card"><h2>С чего начать</h2><ol><li>Наполните <a href="#/library">библиотеку</a>: создайте папки по темам и загрузите документы и видео.</li><li>Соберите <a href="#/courses">курс</a> из материалов библиотеки и добавьте тест.</li><li>Добавьте <a href="#/orgs">заказчика</a>, его <a href="#/employees">сотрудников</a> и выдайте им доступ.</li><li>Назначьте курс в разделе <a href="#/training">«Обучение»</a> — там же видно, кто прошёл.</li></ol></div>`;
    else h+=`<div class="card"><h2>Обучение ваших сотрудников</h2><ol><li>В <a href="#/library">библиотеке</a> есть общие материалы учебного центра, а во вкладке «Материалы нашей организации» можно загружать свои документы и видео.</li><li>В разделе <a href="#/courses">«Курсы»</a> назначайте общие курсы или собирайте свои — из общих и своих материалов, с тестом.</li><li>В разделе <a href="#/training">«Обучение»</a> видно, кто какой курс прошёл, с каким результатом и у кого просрочено.</li></ol></div>`;
  }
  v.innerHTML=h;
}

/* ---------- Библиотека ---------- */
const DOC_INLINE=/^(application\/pdf|image\/|text\/plain)/;
function upload(file,folder,owner,onp){
  return new Promise((res,rej)=>{
    const go=again=>{
      const x=new XMLHttpRequest();x.open('POST','/api/v1/library/items');x.setRequestHeader('Authorization','Bearer '+tok.access_token);
      x.upload.onprogress=ev=>ev.lengthComputable&&onp(ev.loaded/ev.total);
      x.onload=async()=>{
        if(x.status===401&&!again&&await refresh())return go(1);
        let d={};try{d=JSON.parse(x.responseText)}catch{}
        x.status<300?res(d):rej(new Error(errText(d.detail,x.status)));
      };
      x.onerror=()=>rej(new Error('Нет связи с сервером'));
      const f=new FormData();if(folder)f.append('folder_id',folder);else if(owner&&owner!=='shared')f.append('org_id',owner);
      f.append('file',file);x.send(f);
    };
    // токен обновляется перед каждым файлом: большое видео может грузиться долго
    refresh().then(ok=>ok?go(0):rej(new Error('Сессия истекла'))).catch(rej);
  });
}
async function uploadAll(files,folder,owner,box){
  let ok=0;
  for(const file of files){
    const row=document.createElement('div');row.innerHTML=`${e(file.name)} <span class="m">(${sz(file.size)})</span><progress max="1" value="0"></progress>`;box.append(row);
    try{await upload(file,folder,owner,p=>row.querySelector('progress').value=p);row.querySelector('progress').value=1;ok++}
    catch(x){row.innerHTML=`<span style="color:var(--bad)">✕ ${e(file.name)}: ${e(x.message)}</span>`}
  }
  return ok;
}
async function openItem(it,download){
  const w=!download&&it.kind==='document'&&DOC_INLINE.test(it.mime)?window.open('about:blank'):null;
  const {url}=await api(`/library/items/${it.id}/link`);
  if(download||(it.kind==='document'&&!w)){location.href=url+'&download=1';return}
  if(w){w.location=url;return}
  modal(e(it.title),`<video src="${url}" controls autoplay playsinline></video>${it.description?`<p>${e(it.description)}</p>`:''}`,null,null,true);
}

// Какая библиотека открыта: 'shared' — общая учебного центра, иначе id организации-заказчика
let libOwner=null;
try{libOwner=localStorage.getItem('libOwner')}catch{}
function setLibOwner(o){libOwner=o;try{localStorage.setItem('libOwner',o)}catch{}}

async function library(v,cur){
  const os=center()?(await api('/organizations?limit=200')).items:[];
  const valid=['shared',...(center()?os.map(o=>o.id):[me.org_id])];
  if(!valid.includes(libOwner))setLibOwner(center()?'shared':me.org_id);
  const owner=libOwner,mine=center()||owner===me.org_id;
  const ownerName=owner==='shared'?'Общая библиотека':center()?(os.find(o=>o.id===owner)||{}).name:'Материалы нашей организации';
  const folders=await api('/library/folders?owner='+owner);
  const by={};folders.forEach(f=>by[f.id]=f);if(cur&&!by[cur])cur=null;cur=cur||null;
  const kids=id=>folders.filter(f=>(f.parent_id||null)===id);
  const pathOf=id=>{const r=[];while(id){r.unshift(by[id]);id=by[id].parent_id}return r};
  const open=new Set(pathOf(cur).map(f=>f.id));
  const tree=id=>{const k=kids(id);return k.length?`<ul>${k.map(f=>`<li><a href="#/library/${f.id}" class="${f.id===cur?'on':''}">${kids(f.id).length?(open.has(f.id)?'▾':'▸'):'·'} 📁 ${e(f.name)}${f.items?`<em>${f.items}</em>`:''}</a>${open.has(f.id)?tree(f.id):''}</li>`).join('')}</ul>`:''};
  const opts=(sel,skip)=>{const out=[`<option value="">Корень библиотеки</option>`];const walk=(id,d)=>kids(id).forEach(f=>{if(f.id===skip)return;out.push(`<option value="${f.id}"${f.id===sel?' selected':''}>${'— '.repeat(d)}${e(f.name)}</option>`);walk(f.id,d+1)});walk(null,1);return out.join('')};
  const pathText=id=>id?pathOf(id).map(f=>f.name).join(' / '):'Корень библиотеки';
  const here=cur?by[cur]:null;
  const switcher=center()
    ?`<select id="own" class="own"><option value="shared">📚 Общая библиотека</option>${os.map(o=>`<option value="${o.id}"${o.id===owner?' selected':''}>🏢 ${e(o.name)}</option>`).join('')}</select>`
    :`<div class="tabs"><button class="${owner==='shared'?'on':''}" data-own="shared">📚 Общая библиотека</button><button class="${owner===me.org_id?'on':''}" data-own="${me.org_id}">🏢 Материалы нашей организации</button></div>`;

  v.innerHTML=`${switcher}<div class="lib"><div class="card tree"><a href="#/library" class="${cur?'':'on'}">${owner==='shared'?'📚':'🏢'} ${e(ownerName)}</a>${tree(null)}</div><div>
    <div class="crumbs"><a href="#/library">${e(ownerName)}</a>${pathOf(cur).map(f=>` / <a href="#/library/${f.id}">${e(f.name)}</a>`).join('')}</div>
    <div class="bar"><h1>${here?e(here.name):e(ownerName)}</h1>${mine?`<div><button class="b" id="up">⬆ Загрузить файлы</button> <button class="g" id="nf">+ Папка</button>${here?' <button class="g" id="ef">Изменить папку</button> <button class="d" id="df">Удалить папку</button>':''}</div>`:''}</div>
    ${mine?'':'<p class="m" style="margin-top:-6px">Материалы учебного центра. Их можно смотреть и добавлять в свои курсы, а изменять может только учебный центр.</p>'}
    <div class="filters"><input id="q" placeholder="Поиск по названию в этой библиотеке…"></div>
    ${mine?`<div class="drop" id="drop">Перетащите файлы сюда — они загрузятся в «${e(pathText(cur))}»</div><div class="up" id="upq"></div>`:''}
    <div id="body"></div></div></div>`;

  if(center())$('#own').value=owner;
  const sw=o=>{setLibOwner(o);location.hash==='#/library'?route():location.hash='#/library'};
  if(center())$('#own').onchange=ev=>sw(ev.target.value);
  else v.querySelectorAll('[data-own]').forEach(b=>b.onclick=()=>sw(b.dataset.own));

  const reload=()=>library(v,cur);
  const load=async()=>{
    const q=$('#q').value.trim();
    const items=await api('/library/items?'+new URLSearchParams(q?{q,owner}:cur?{folder_id:cur}:{owner}));
    const sub=q?[]:kids(cur);
    const tiles=sub.length?`<div class="tiles">${sub.map(f=>`<a class="card tile" href="#/library/${f.id}"><i>📁</i><span><b>${e(f.name)}</b><small>${f.items} матер. · ${kids(f.id).length} папок</small></span></a>`).join('')}</div>`:'';
    const rows=items.map(it=>`<tr><td class="ic">${it.kind==='video'?'🎬':'📄'}</td><td><b>${e(it.title)}</b><small>${e(it.description||it.file_name)}${q?' · 📁 '+e(pathText(it.folder_id)):''}</small></td><td class="nw">${it.kind==='video'?'Видео':'Документ'}<small>${sz(it.size)}</small></td><td class="nw">${dd(it.created_at)}</td><td class="ra"><button class="b sm" data-a="open" data-id="${it.id}">Открыть</button><button class="g sm" data-a="dl" data-id="${it.id}">Скачать</button>${mine?`<button class="g sm" data-a="edit" data-id="${it.id}">Изменить</button><button class="d sm" data-a="del" data-id="${it.id}">Удалить</button>`:''}</td></tr>`).join('');
    $('#body').innerHTML=tiles+(items.length?`<div class="tw"><table><tr><th></th><th>Материал</th><th>Тип</th><th>Добавлен</th><th></th></tr>${rows}</table></div>`:(sub.length?'':`<div class="card empty">${q?'Ничего не найдено.':mine?'Здесь пока пусто. Загрузите файлы или создайте папку.':'Здесь пока пусто.'}</div>`));
    const map={};items.forEach(i=>map[i.id]=i);
    $('#body').onclick=async ev=>{
      const b=ev.target.closest('button[data-a]');if(!b)return;const it=map[b.dataset.id];
      try{
        if(b.dataset.a==='open')await openItem(it);
        if(b.dataset.a==='dl')await openItem(it,true);
        if(b.dataset.a==='edit')modal('Материал',`<label>Название*<input name="title" required value="${e(it.title)}"></label><label>Описание<textarea name="description">${e(it.description||'')}</textarea></label><label>Папка<select name="folder_id">${opts(it.folder_id)}</select></label><p class="m">Файл: ${e(it.file_name)} (${sz(it.size)})</p>`,'Сохранить',async x=>{await api(`/library/items/${it.id}`,{method:'PATCH',body:{title:x.title,description:x.description||null,folder_id:x.folder_id||null}});toast('Сохранено');reload()});
        if(b.dataset.a==='del')confirmBox(`Удалить «${e(it.title)}»? Файл будет удалён с сервера.`,'Удалить',async()=>{await api(`/library/items/${it.id}`,{method:'DELETE'});toast('Материал удалён');reload()});
      }catch(x){toast(x.message,1)}
    };
  };

  if(mine){
    $('#up').onclick=()=>{
      const m=modal('Загрузка материалов',`<p class="m">Библиотека: <b>${e(ownerName)}</b></p><label>Куда загрузить<select name="folder">${opts(cur)}</select></label><label>Файлы (документы и видео, можно несколько)<input type="file" name="files" multiple required></label><div class="up" id="mq"></div>`,'Загрузить',async(x,f)=>{
        const files=[...f.querySelector('[name=files]').files];
        const ok=await uploadAll(files,x.folder||null,owner,m.querySelector('#mq'));
        toast(`Загружено: ${ok} из ${files.length}`,ok<files.length);
        if(ok<files.length)throw new Error('Часть файлов не загрузилась — см. список');
        if((x.folder||null)!==cur)location.hash='#/library'+(x.folder?'/'+x.folder:'');else reload();
      });
    };
    const drop=$('#drop');
    drop.ondragover=ev=>{ev.preventDefault();drop.classList.add('on')};drop.ondragleave=()=>drop.classList.remove('on');
    drop.ondrop=async ev=>{ev.preventDefault();drop.classList.remove('on');const files=[...ev.dataTransfer.files];if(!files.length)return;
      const ok=await uploadAll(files,cur,owner,$('#upq'));toast(`Загружено: ${ok} из ${files.length}`,ok<files.length);if(ok)setTimeout(reload,ok<files.length?3000:300)};
    $('#nf').onclick=()=>modal('Новая папка',`<label>Название*<input name="name" required autofocus></label><label>Внутри папки<select name="parent_id">${opts(cur)}</select></label>`,'Создать',async x=>{const f=await api('/library/folders',{method:'POST',body:{name:x.name,parent_id:x.parent_id||null,org_id:owner==='shared'?null:owner}});toast('Папка создана');location.hash='#/library/'+f.id});
    if(here){
      $('#ef').onclick=()=>modal('Папка',`<label>Название*<input name="name" required value="${e(here.name)}"></label><label>Расположена в<select name="parent_id">${opts(here.parent_id,here.id)}</select></label>`,'Сохранить',async x=>{await api(`/library/folders/${cur}`,{method:'PATCH',body:{name:x.name,parent_id:x.parent_id||null}});toast('Сохранено');reload()});
      $('#df').onclick=()=>confirmBox(`Удалить папку «${e(here.name)}»? Удалить можно только пустую папку.`,'Удалить',async()=>{await api(`/library/folders/${cur}`,{method:'DELETE'});toast('Папка удалена');location.hash='#/library'+(here.parent_id?'/'+here.parent_id:'')});
    }
  }
  let t;$('#q').oninput=()=>{clearTimeout(t);t=setTimeout(()=>load().catch(x=>toast(x.message,1)),300)};
  await load();
}

/* ---------- Заказчики (организации) ---------- */
async function orgs(v){
  v.innerHTML=`<div class="bar"><h1>Заказчики</h1>${center()?'<button class="b" id="add">+ Добавить заказчика</button>':''}</div><div class="filters"><input id="q" placeholder="Поиск по названию или ИНН…"></div><div id="tb"></div>`;
  const load=async()=>{
    const d=await api('/organizations?limit=200&q='+encodeURIComponent($('#q').value));
    $('#tb').innerHTML=d.items.length?`<div class="tw"><table><tr><th>Название</th><th>ИНН</th><th>Ответственный</th><th>Статус</th></tr>${d.items.map(o=>`<tr><td><b>${e(o.name)}</b><small>${e(o.legal_address||'')}</small></td><td>${e(o.inn||'—')}</td><td>${e(o.responsible_name||'—')}</td><td><span class="s ${o.status}">${ST[o.status]}</span></td></tr>`).join('')}</table></div>`:'<div class="card empty">Заказчиков пока нет. Нажмите «Добавить заказчика».</div>';
  };
  let t;$('#q').oninput=()=>{clearTimeout(t);t=setTimeout(()=>load().catch(x=>toast(x.message,1)),300)};
  if(center())$('#add').onclick=()=>modal('Новый заказчик',`<label>Название организации*<input name="name" required></label><label>ИНН<input name="inn" pattern="[0-9]{10}([0-9]{2})?" title="10 или 12 цифр"></label><label>КПП<input name="kpp" pattern="[0-9]{9}" title="9 цифр"></label><label>Юридический адрес<input name="legal_address"></label><label>Ответственный<input name="responsible_name"></label>`,'Создать',async b=>{await api('/organizations',{method:'POST',body:b});toast('Заказчик добавлен. Создайте ему вход в разделе «Пользователи».');load()});
  await load();
}

/* ---------- Сотрудники ---------- */
async function employees(v){
  const w=center(),os=w?(await api('/organizations?limit=200')).items:[];
  const opts=os.map(o=>`<option value="${o.id}">${e(o.name)}</option>`).join('');
  v.innerHTML=`<div class="bar"><h1>${w?'Сотрудники':'Мои сотрудники'}</h1>${canEdit()?'<button class="b" id="add">+ Добавить сотрудника</button>':''}</div><div class="filters"><input id="q" placeholder="Поиск по ФИО…">${w?`<select id="o"><option value="">Все заказчики</option>${opts}</select>`:''}<select id="s"><option value="">Любой статус</option><option value="active">Активные</option><option value="inactive">Деактивированные</option></select></div><div id="tb"></div>`;
  const btn=(a,id,t,c='g')=>`<button class="${c} sm" data-a="${a}" data-id="${id}">${t}</button>`;
  const acts=x=>(x.status==='active'&&!x.has_access?btn('grant',x.id,'Выдать доступ','b'):'')+(x.has_access?btn('reset',x.id,'Сбросить пароль'):'')+btn(x.status==='active'?'off':'on',x.id,x.status==='active'?'Деактивировать':'Восстановить',x.status==='active'?'d':'g');
  const load=async()=>{
    const p=new URLSearchParams({limit:200,q:$('#q').value,status:$('#s').value});if(w&&$('#o').value)p.set('org_id',$('#o').value);
    const d=await api('/employees?'+p);
    $('#tb').innerHTML=d.items.length?`<div class="tw"><table><tr><th>Сотрудник</th><th>Подразделение</th><th>Телефон</th><th>Последний вход</th><th>Статус</th>${canEdit()?'<th></th>':''}</tr>${d.items.map(x=>`<tr><td><b>${e(x.full_name)}</b><small>${e(x.position_name||'')}</small></td><td>${e(x.department_name||'—')}</td><td>${e(x.phone||'—')}</td><td class="nw">${x.last_login_at?dt(x.last_login_at):(x.has_access?'Ещё не входил':'—')}</td><td><span class="s ${x.status}">${ST[x.status]}</span> ${x.has_access?'<span class="s ok">Есть доступ</span>':''}</td>${canEdit()?`<td class="ra">${acts(x)}</td>`:''}</tr>`).join('')}</table></div>`:'<div class="card empty">Сотрудников не найдено.</div>';
  };
  let t;const lazy=()=>{clearTimeout(t);t=setTimeout(()=>load().catch(x=>toast(x.message,1)),300)};
  $('#q').oninput=lazy;$('#s').onchange=lazy;if(w)$('#o').onchange=lazy;
  if(canEdit())$('#add').onclick=()=>modal('Новый сотрудник',`${w?`<label>Заказчик*<select name="org_id" required><option value="">Выберите…</option>${opts}</select></label>`:''}<label>ФИО*<input name="full_name" required></label><label>Телефон<input name="phone" type="tel" placeholder="+7 900 000-00-00"></label><p class="m" style="margin-top:-6px;font-size:13px">Телефон нужен, чтобы выдать сотруднику доступ в систему.</p><label>Дата приёма на работу<input name="hired_at" type="date"></label>`,'Добавить',async b=>{await api('/employees',{method:'POST',body:b});toast('Сотрудник добавлен');load()});
  $('#tb').onclick=async ev=>{
    const b=ev.target.closest('button[data-a]');if(!b)return;const id=b.dataset.id,a=b.dataset.a;
    const run=async()=>{
      if(a==='grant'||a==='reset')creds(await api(`/employees/${id}/${a==='grant'?'grant-access':'reset-password'}`,{method:'POST'}));
      else{await api(`/employees/${id}/${a==='off'?'deactivate':'restore'}`,{method:'POST'});toast(a==='off'?'Сотрудник деактивирован':'Сотрудник восстановлен. Доступ нужно выдать заново.')}
      load();
    };
    try{
      if(a==='reset')return confirmBox('Сбросить пароль? Сотруднику придётся войти с новым временным паролем.','Сбросить',run);
      if(a==='off')return confirmBox('Деактивировать сотрудника? Его доступ в систему будет закрыт.','Деактивировать',run);
      await run();
    }catch(x){toast(x.message,1)}
  };
  await load();
}

/* ---------- Пользователи (директора, заказчики) ---------- */
async function users(v){
  const os=(await api('/organizations?limit=200')).items,on={};os.forEach(o=>on[o.id]=o.name);
  const can=me.role==='superadmin'?['superadmin','center_admin','org_admin']:['org_admin'];
  v.innerHTML=`<div class="bar"><h1>Пользователи</h1><button class="b" id="add">+ Добавить пользователя</button></div><div class="filters"><input id="q" placeholder="Поиск по ФИО или телефону…"><select id="r"><option value="">Все роли</option>${(me.role==="superadmin"?["superadmin","center_admin","org_admin"]:["center_admin","org_admin"]).map(r=>`<option value="${r}">${ROLE[r]}</option>`).join('')}</select></div><p class="m" style="margin-top:-6px">Подчинённые (сотрудники заказчиков) получают доступ в разделе «Сотрудники».</p><div id="tb"></div>`;
  const load=async()=>{
    const p=new URLSearchParams({limit:200,q:$('#q').value});if($('#r').value)p.set('role',$('#r').value);
    const d=await api('/users?'+p);
    $('#tb').innerHTML=d.items.length?`<div class="tw"><table><tr><th>Пользователь</th><th>Роль</th><th>Последний вход</th><th>Статус</th><th></th></tr>${d.items.map(u=>`<tr><td><b>${e(u.full_name)}</b><small>${e(u.phone)}</small></td><td>${ROLE[u.role]}${u.org_id?`<small>${e(on[u.org_id]||'')}</small>`:''}</td><td class="nw">${u.last_login_at?dt(u.last_login_at):'—'}</td><td><span class="s ${u.is_active?'active':'inactive'}">${u.is_active?'Активен':'Отключён'}</span></td><td class="ra">${can.includes(u.role)&&u.id!==me.id?`<button class="g sm" data-a="reset" data-id="${u.id}">Сбросить пароль</button><button class="${u.is_active?'d':'g'} sm" data-a="${u.is_active?'off':'on'}" data-id="${u.id}">${u.is_active?'Отключить':'Включить'}</button>`:''}</td></tr>`).join('')}</table></div>`:'<div class="card empty">Пользователей не найдено.</div>';
  };
  let t;$('#q').oninput=()=>{clearTimeout(t);t=setTimeout(()=>load().catch(x=>toast(x.message,1)),300)};$('#r').onchange=()=>load().catch(x=>toast(x.message,1));
  $('#add').onclick=()=>{
    const m=modal('Новый пользователь',`<label>Роль*<select name="role">${can.map(r=>`<option value="${r}"${r==='org_admin'?' selected':''}>${ROLE[r]}</option>`).join('')}</select></label><label id="ol">Заказчик*<select name="org_id"><option value="">Выберите…</option>${os.map(o=>`<option value="${o.id}">${e(o.name)}</option>`).join('')}</select></label><label>ФИО*<input name="full_name" required></label><label>Телефон*<input name="phone" type="tel" required placeholder="+7 900 000-00-00"></label>`,'Создать',async x=>{
      if(x.role!=='org_admin')delete x.org_id;else if(!x.org_id)throw new Error('Выберите заказчика');
      creds(await api('/users',{method:'POST',body:x}));load();
    });
    const role=m.querySelector('[name=role]'),sync=()=>m.querySelector('#ol').hidden=role.value!=='org_admin';role.onchange=sync;sync();
  };
  $('#tb').onclick=async ev=>{
    const b=ev.target.closest('button[data-a]');if(!b)return;const id=b.dataset.id,a=b.dataset.a;
    try{
      if(a==='reset')return confirmBox('Сбросить пароль? Пользователю придётся войти с новым временным паролем.','Сбросить',async()=>{creds(await api(`/users/${id}/reset-password`,{method:'POST'}));load()});
      await api(`/users/${id}`,{method:'PATCH',body:{is_active:a==='on'}});toast(a==='on'?'Пользователь включён':'Пользователь отключён');load();
    }catch(x){toast(x.message,1)}
  };
  await load();
}

/* ---------- Журнал ---------- */
async function audit(v){
  const d=await api('/audit?limit=100');
  v.innerHTML=`<div class="bar"><h1>Журнал действий</h1></div>${d.items.length?`<div class="tw"><table><tr><th>Время</th><th>Действие</th></tr>${d.items.map(a=>`<tr><td class="nw">${dt(a.at)}</td><td>${e(a.description)}</td></tr>`).join('')}</table></div>`:'<div class="card empty">Записей пока нет.</div>'}`;
}
start();

/* ---------- Мой заказчик (для работника) ---------- */
async function customer(v){
  const c=await api('/organizations/mine');
  const row=(k,val)=>val?`<tr><td class="m nw">${k}</td><td>${e(val)}</td></tr>`:'';
  v.innerHTML=`<div class="bar"><h1>Мой заказчик</h1></div>
    <div class="card hero"><h1><span>${e(c.name)}</span></h1><p>Организация, в которой вы работаете и проходите обучение</p></div>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr))">
      <div class="card"><h2>Реквизиты</h2>${[c.inn,c.kpp,c.legal_address].some(Boolean)?`<table>${row('ИНН',c.inn)}${row('КПП',c.kpp)}${row('Адрес',c.legal_address)}</table>`:'<p class="m">Реквизиты не указаны.</p>'}</div>
      <div class="card"><h2>Контакты</h2>${[c.responsible_name,c.contact_phone,c.contact_email].some(Boolean)?`<table>${row('Ответственный',c.responsible_name)}${row('Телефон',c.contact_phone)}${row('Эл. почта',c.contact_email)}</table>`:'<p class="m">Контакты не указаны.</p>'}</div>
    </div>
    <div class="card"><h2>Представители заказчика</h2>${c.contacts.length?`<table>${c.contacts.map(p=>`<tr><td><b>${e(p.full_name)}</b></td><td class="ra"><a href="tel:${e(p.phone)}">${e(p.phone)}</a></td></tr>`).join('')}</table>`:'<p class="m">Представители пока не назначены.</p>'}</div>`;
}

/* ---------- Обучение: общие части ---------- */
const STATE={assigned:'Назначен',in_progress:'В процессе',passed:'Пройден',overdue:'Просрочен',expired:'Истёк срок'};
const STATE_CLS={assigned:'',in_progress:'warn',passed:'ok',overdue:'bad',expired:'bad'};
const badge=s=>`<span class="s ${STATE_CLS[s]}">${STATE[s]}</span>`;
const validity=m=>!m?'бессрочно':m%12?m+' мес.':(m/12)+' г.';

// Назначение курса: выбор курса (если не задан), заказчика (для центра), сотрудников и срока
async function assignDialog(courseId,done){
  const [cs,os]=await Promise.all([api('/courses'),center()?api('/organizations?limit=200').then(d=>d.items):[]]);
  if(!cs.length)return toast('Сначала создайте курс',1);
  const byId={};cs.forEach(c=>byId[c.id]=c);
  const m=modal('Назначить обучение',`<label>Курс*<select name="course_id" required>${cs.map(c=>`<option value="${c.id}"${c.id===courseId?' selected':''}>${e(c.title)}${c.org_id?` (${center()?e(c.org_name||'заказчик'):'наш'})`:''}</option>`).join('')}</select></label>
    ${center()?`<label>Заказчик*<select id="ao"><option value="">Выберите…</option>${os.map(o=>`<option value="${o.id}">${e(o.name)}</option>`).join('')}</select></label>`:''}
    <label>Пройти до<input name="due_date" type="date" min="${new Date().toISOString().slice(0,10)}"></label>
    <div id="ae" class="pick"><p class="m">${center()?'Выберите заказчика, чтобы увидеть его сотрудников.':'Загрузка…'}</p></div>`,'Назначить',async(x,f)=>{
      const ids=[...f.querySelectorAll('[name=emp]:checked')].map(i=>i.value);
      if(!ids.length)throw new Error('Отметьте хотя бы одного сотрудника');
      const r=await api('/assignments',{method:'POST',body:{course_id:x.course_id,employee_ids:ids,due_date:x.due_date||null}});
      toast(`Назначено: ${r.created}`+(r.skipped.length?`. Пропущены: ${r.skipped.join(', ')}`:''),!r.created);done&&done();
    },true);
  const loadEmps=async org=>{
    const box=m.querySelector('#ae');
    if(center()&&!org){box.innerHTML='<p class="m">Выберите заказчика, чтобы увидеть его сотрудников.</p>';return}
    const d=await api('/employees?'+new URLSearchParams({limit:200,status:'active',...(org?{org_id:org}:{})}));
    box.innerHTML=d.items.length?`<label class="chk"><input type="checkbox" id="all"> <b>Выбрать всех (${d.items.length})</b></label>${d.items.map(x=>`<label class="chk"><input type="checkbox" name="emp" value="${x.id}"> ${e(x.full_name)} <span class="m">${e(x.position_name||x.department_name||'')}</span></label>`).join('')}`:'<p class="m">Нет активных сотрудников.</p>';
    const all=box.querySelector('#all');if(all)all.onchange=()=>box.querySelectorAll('[name=emp]').forEach(i=>i.checked=all.checked);
  };
  if(center()){
    // курс заказчика назначается только его сотрудникам
    const sel=m.querySelector('[name=course_id]'),org=m.querySelector('#ao');
    const fix=()=>{const c=byId[sel.value];if(c&&c.org_id){org.value=c.org_id;org.disabled=true;loadEmps(c.org_id).catch(x=>toast(x.message,1))}else org.disabled=false};
    sel.onchange=fix;org.onchange=ev=>loadEmps(ev.target.value).catch(x=>toast(x.message,1));fix();
  }else loadEmps().catch(x=>toast(x.message,1));
}

/* ---------- Курсы ---------- */
const courseOwner=c=>!c.org_id?'<span class="s">Общий</span>':center()?`<span class="s warn">${e(c.org_name||'Заказчик')}</span>`:'<span class="s ok">Наш</span>';
async function courses(v){
  const cs=await api('/courses');
  v.innerHTML=`<div class="bar"><h1>Курсы</h1><div><button class="g" id="as">Назначить обучение</button> <button class="b" id="add">+ Новый курс</button></div></div>
    ${center()?'':'<p class="m" style="margin-top:-6px">Общие курсы учебного центра можно назначать своим работникам. Свои курсы собирайте из общих материалов и материалов вашей организации.</p>'}
    ${cs.length?`<div class="tw"><table><tr><th>Курс</th><th>Чей</th><th>Материалы</th><th>Тест</th><th>Повторять</th><th></th></tr>${cs.map(c=>`<tr><td><a href="#/course/${c.id}"><b>${e(c.title)}</b></a><small>${e(c.description||'')}</small></td><td>${courseOwner(c)}</td><td>${c.materials}</td><td>${c.questions?c.questions+' вопр. · '+c.pass_score+'%':'—'}</td><td class="nw">${validity(c.validity_months)}</td><td class="ra"><a href="#/course/${c.id}"><button class="g sm">${c.editable?'Изменить':'Открыть'}</button></a><button class="b sm" data-as="${c.id}">Назначить</button></td></tr>`).join('')}</table></div>`
    :'<div class="card empty">Курсов пока нет. Нажмите «Новый курс» и соберите его из материалов библиотеки.</div>'}`;
  $('#add').onclick=()=>modal(center()?'Новый общий курс':'Новый курс',`<label>Название*<input name="title" required></label><label>Описание<textarea name="description"></textarea></label>${center()?'<p class="m">Общий курс увидят и смогут назначать все заказчики.</p>':''}`,'Создать',async x=>{const c=await api('/courses',{method:'POST',body:x});location.hash='#/course/'+c.id});
  $('#as').onclick=()=>assignDialog(null).catch(x=>toast(x.message,1));
  v.onclick=ev=>{const b=ev.target.closest('[data-as]');if(b)assignDialog(b.dataset.as).catch(x=>toast(x.message,1))};
}

async function courseEdit(v,id){
  const c=await api('/courses/'+id),ro=!c.editable;
  let mats=c.materials.map(m=>({...m})),qs=JSON.parse(JSON.stringify(c.test));
  const dis=ro?'disabled':'';
  v.innerHTML=`<div class="crumbs"><a href="#/courses">Курсы</a> / ${e(c.title)}</div>
    <div class="bar"><h1>${e(c.title)}</h1><div><button class="b" id="as">Назначить</button>${ro?'':' <button class="d" id="del">Удалить курс</button>'}</div></div>
    ${ro?'<p class="m" style="margin-top:-6px">Это общий курс учебного центра: его можно назначать своим работникам, но изменять может только учебный центр.</p>':''}
    <form class="card" id="pf"><h2>1. Параметры</h2><div class="row3"><label>Название*<input name="title" required value="${e(c.title)}" ${dis}></label>
      <label>Проходной балл теста, %<input name="pass_score" type="number" min="1" max="100" value="${c.pass_score}" ${dis}></label>
      <label>Проходить повторно через, мес.<input name="validity_months" type="number" min="1" max="120" value="${c.validity_months||''}" placeholder="не нужно" ${dis}></label></div>
      <label>Описание<textarea name="description" ${dis}>${e(c.description||'')}</textarea></label>${ro?'':'<button class="b">Сохранить параметры</button>'}</form>
    <div class="card" style="margin-top:16px"><div class="bar"><h2 style="margin:0">2. Материалы</h2>${ro?'':'<button class="g" id="am">+ Добавить из библиотеки</button>'}</div><div id="ml"></div></div>
    <div class="card" style="margin-top:16px"><div class="bar"><h2 style="margin:0">3. Тест</h2>${ro?'':'<div><button class="g" id="aq">+ Вопрос</button> <button class="b" id="sq">Сохранить тест</button></div>'}</div>
      ${ro?'':'<p class="m">Отметьте правильные ответы. Если вопросов нет, курс засчитывается, когда изучены все материалы.</p>'}<div id="ql"></div></div>`;

  $('#as').onclick=()=>assignDialog(id).catch(x=>toast(x.message,1));
  const drawMats=()=>{
    $('#ml').innerHTML=mats.length?`<table>${mats.map((m,i)=>`<tr><td class="ic">${m.kind==='video'?'🎬':'📄'}</td><td><b>${i+1}. ${e(m.title)}</b><small>${e(m.file_name)} · ${sz(m.size)}</small></td>${ro?'':`<td class="ra"><button class="g sm" data-up="${i}" ${i?'':'disabled'}>↑</button><button class="g sm" data-dn="${i}" ${i<mats.length-1?'':'disabled'}>↓</button><button class="d sm" data-rm="${i}">Убрать</button></td>`}</tr>`).join('')}</table>`:`<p class="m">Материалов пока нет.${ro?'':' Добавьте документы и видео из библиотеки.'}</p>`;
  };
  if(ro){
    $('#ql').innerHTML=qs.length?qs.map((q,i)=>`<div class="q"><b>${i+1}. ${e(q.text)}</b>${q.options.map(o=>`<div class="opt">${o.correct?'✅':'▫️'} ${e(o.text)}</div>`).join('')}</div>`).join(''):'<p class="m">Теста нет: курс засчитывается после изучения всех материалов.</p>';
    drawMats();return;
  }

  $('#pf').onsubmit=async ev=>{ev.preventDefault();const x=Object.fromEntries(new FormData(ev.target));
    try{await api('/courses/'+id,{method:'PATCH',body:{title:x.title,description:x.description||null,pass_score:+x.pass_score||80,validity_months:x.validity_months?+x.validity_months:null}});toast('Параметры сохранены');route()}catch(err){toast(err.message,1)}};
  $('#del').onclick=()=>confirmBox(`Удалить курс «${e(c.title)}»?`,'Удалить',async()=>{await api('/courses/'+id,{method:'DELETE'});toast('Курс удалён');location.hash='#/courses'});

  const saveMats=async()=>{const r=await api(`/courses/${id}/materials`,{method:'PUT',body:{item_ids:mats.map(m=>m.item_id)}});mats=r.materials;drawMats()};
  $('#ml').onclick=async ev=>{const b=ev.target.closest('button');if(!b)return;const d=b.dataset;
    if(d.up)[mats[+d.up-1],mats[+d.up]]=[mats[+d.up],mats[+d.up-1]];
    if(d.dn)[mats[+d.dn],mats[+d.dn+1]]=[mats[+d.dn+1],mats[+d.dn]];
    if(d.rm)mats.splice(+d.rm,1);
    try{await saveMats()}catch(x){toast(x.message,1)}};
  $('#am').onclick=()=>{
    // в общий курс — только общая библиотека; в курс заказчика — общая и его собственная
    const owners=[['shared','📚 Общая библиотека'],...(c.org_id?[[c.org_id,center()?'🏢 Материалы заказчика':'🏢 Наши материалы']]:[])];
    const have=new Set(mats.map(m=>m.item_id));
    const m=modal('Материалы из библиотеки',`<div class="filters">${owners.length>1?`<select id="pown">${owners.map(([k,t])=>`<option value="${k}">${t}</option>`).join('')}</select>`:''}<select id="pf2"></select><input id="pq" placeholder="или поиск по названию…"></div><div id="pl" class="pick"></div>`,'Добавить отмеченные',async(x,f)=>{
      const add=[...f.querySelectorAll('[name=it]:checked:not(:disabled)')].map(i=>i.value);
      if(!add.length)throw new Error('Отметьте материалы');
      mats.push(...add.map(item_id=>({item_id})));await saveMats();toast('Добавлено: '+add.length);
    },true);
    const owner=()=>m.querySelector('#pown')?m.querySelector('#pown').value:'shared';
    const loadFolders=async()=>{
      const fl=await api('/library/folders?owner='+owner()),kids=p=>fl.filter(f=>(f.parent_id||null)===p);
      const opts=[];const walk=(p,d)=>kids(p).forEach(f=>{opts.push(`<option value="${f.id}">${'— '.repeat(d)}${e(f.name)} (${f.items})</option>`);walk(f.id,d+1)});walk(null,1);
      m.querySelector('#pf2').innerHTML=`<option value="">Корень библиотеки</option>${opts.join('')}`;
    };
    const load=async()=>{const q=m.querySelector('#pq').value.trim(),fid=m.querySelector('#pf2').value;
      const items=await api('/library/items?'+new URLSearchParams(q?{q,owner:owner()}:fid?{folder_id:fid}:{owner:owner()}));
      m.querySelector('#pl').innerHTML=items.length?items.map(i=>`<label class="chk"><input type="checkbox" name="it" value="${i.id}" ${have.has(i.id)?'checked disabled':''}> ${i.kind==='video'?'🎬':'📄'} ${e(i.title)} <span class="m">${sz(i.size)}${have.has(i.id)?' · уже в курсе':''}</span></label>`).join(''):'<p class="m">Здесь нет материалов. Выберите другую папку.</p>'};
    const err=x=>toast(x.message,1);
    let t;m.querySelector('#pq').oninput=()=>{clearTimeout(t);t=setTimeout(()=>load().catch(err),300)};
    m.querySelector('#pf2').onchange=()=>load().catch(err);
    if(m.querySelector('#pown'))m.querySelector('#pown').onchange=()=>loadFolders().then(load).catch(err);
    loadFolders().then(load).catch(err);
  };

  // редактор теста работает с массивом qs; перед перерисовкой забираем введённый текст
  const grab=()=>$('#ql').querySelectorAll('.q').forEach((el,i)=>{qs[i].text=el.querySelector('[data-qt]').value;
    el.querySelectorAll('.opt').forEach((o,j)=>{qs[i].options[j].text=o.querySelector('[data-ot]').value;qs[i].options[j].correct=o.querySelector('[data-oc]').checked})});
  const drawQs=()=>{
    $('#ql').innerHTML=qs.length?qs.map((q,i)=>`<div class="q"><div class="bar" style="margin-bottom:8px"><b>Вопрос ${i+1}</b><div><label class="chk inl"><input type="checkbox" data-mul="${i}" ${q.multiple?'checked':''}> несколько правильных</label><button type="button" class="d sm" data-rq="${i}">Удалить вопрос</button></div></div>
      <textarea data-qt placeholder="Текст вопроса">${e(q.text)}</textarea>
      ${q.options.map((o,j)=>`<div class="opt"><input type="${q.multiple?'checkbox':'radio'}" name="c${i}" data-oc ${o.correct?'checked':''} title="Правильный ответ"><input type="text" data-ot value="${e(o.text)}" placeholder="Вариант ответа ${j+1}"><button type="button" class="g sm" data-ro="${i}:${j}" ${q.options.length>2?'':'disabled'}>✕</button></div>`).join('')}
      <button type="button" class="g sm" data-ao="${i}" ${q.options.length<10?'':'disabled'}>+ вариант</button></div>`).join(''):'<p class="m">Вопросов нет.</p>';
  };
  $('#ql').onclick=ev=>{const b=ev.target.closest('button');if(!b)return;grab();const d=b.dataset;
    if(d.rq)qs.splice(+d.rq,1);
    if(d.ao)qs[+d.ao].options.push({text:'',correct:false});
    if(d.ro){const [i,j]=d.ro.split(':').map(Number);qs[i].options.splice(j,1)}
    drawQs()};
  $('#ql').onchange=ev=>{const d=ev.target.dataset;if(d.mul===undefined)return;grab();const q=qs[+d.mul];q.multiple=ev.target.checked;
    if(!q.multiple){let seen=false;q.options.forEach(o=>{if(o.correct&&seen)o.correct=false;seen=seen||o.correct})}drawQs()};
  $('#aq').onclick=()=>{grab();qs.push({text:'',multiple:false,options:[{text:'',correct:true},{text:'',correct:false}]});drawQs()};
  $('#sq').onclick=async()=>{grab();
    for(const [i,q] of qs.entries()){if(!q.text.trim())return toast(`Вопрос ${i+1}: нет текста`,1);if(q.options.some(o=>!o.text.trim()))return toast(`Вопрос ${i+1}: заполните все варианты`,1);if(!q.options.some(o=>o.correct))return toast(`Вопрос ${i+1}: отметьте правильный ответ`,1)}
    try{const r=await api(`/courses/${id}/test`,{method:'PUT',body:{questions:qs}});qs=r.test;drawQs();toast('Тест сохранён: '+qs.length+' вопр.')}catch(x){toast(x.message,1)}};
  drawMats();drawQs();
}

/* ---------- Обучение: результаты (центр и заказчик) ---------- */
async function training(v){
  v.onclick=null;
  const [cs,os]=await Promise.all([api('/courses'),center()?api('/organizations?limit=200').then(d=>d.items):[]]);
  v.innerHTML=`<div class="bar"><h1>Обучение</h1><button class="b" id="as">+ Назначить обучение</button></div><div class="grid" id="sum"></div>
    <div class="filters"><input id="q" placeholder="Поиск по ФИО…">${center()?`<select id="o"><option value="">Все заказчики</option>${os.map(o=>`<option value="${o.id}">${e(o.name)}</option>`).join('')}</select>`:''}<select id="c"><option value="">Все курсы</option>${cs.map(c=>`<option value="${c.id}">${e(c.title)}</option>`).join('')}</select><select id="s"><option value="">Любой статус</option>${Object.entries(STATE).map(([k,t])=>`<option value="${k}">${t}</option>`).join('')}</select></div><div id="tb"></div>`;
  const val=s=>$(s)?$(s).value:'';
  const load=async()=>{
    const p=new URLSearchParams();
    if(val('#q'))p.set('q',val('#q'));if(val('#o'))p.set('org_id',val('#o'));if(val('#c'))p.set('course_id',val('#c'));
    const all=await api('/assignments?'+p),st=val('#s'),d=st?all.filter(a=>a.state===st):all;
    const n=s=>all.filter(a=>s.includes(a.state)).length,tile=(b,t)=>`<div class="card stat"><b>${b}</b><span>${t}</span></div>`;
    $('#sum').innerHTML=tile(n(['assigned','in_progress']),'Проходят')+tile(n(['passed']),'Прошли')+tile(n(['overdue']),'Просрочили')+tile(n(['expired']),'Нужна переаттестация');
    $('#tb').innerHTML=d.length?`<div class="tw"><table><tr><th>Сотрудник</th>${center()?'<th>Заказчик</th>':''}<th>Курс</th><th>Прогресс</th><th>Срок</th><th>Статус</th><th></th></tr>${d.map(a=>`<tr><td><b>${e(a.employee_name)}</b><small>${e(a.department_name||'')}</small></td>${center()?`<td>${e(a.org_name)}</td>`:''}<td>${e(a.course_title)}<small>назначен ${dd(a.assigned_at)}</small></td>
      <td class="nw">${a.materials?`материалы ${a.viewed}/${a.materials}`:''}${a.has_test?`<small>${a.score!==null?'тест: '+a.score+'%':'тест не сдавал'}${a.attempts?' · попыток: '+a.attempts:''}</small>`:''}</td>
      <td class="nw">${['passed','expired'].includes(a.state)?`пройден ${dd(a.completed_at)}<small>${a.expires_at?'действует до '+dd(a.expires_at):'бессрочно'}</small>`:a.due_date?'до '+dd(a.due_date):'—'}</td>
      <td>${badge(a.state)}</td><td class="ra">${a.state==='expired'?`<button class="b sm" data-re="${a.course_id}">Назначить снова</button>`:''}${['passed','expired'].includes(a.state)?'':`<button class="d sm" data-cancel="${a.id}">Отменить</button>`}</td></tr>`).join('')}</table></div>`:'<div class="card empty">Назначений не найдено.</div>';
  };
  let t;const lazy=()=>{clearTimeout(t);t=setTimeout(()=>load().catch(x=>toast(x.message,1)),300)};
  ['#q','#o','#c','#s'].forEach(s=>{const el=$(s);if(el){el.oninput=lazy;el.onchange=lazy}});
  $('#as').onclick=()=>assignDialog(null,load).catch(x=>toast(x.message,1));
  $('#tb').onclick=ev=>{const b=ev.target.closest('button');if(!b)return;
    if(b.dataset.re)assignDialog(b.dataset.re,load).catch(x=>toast(x.message,1));
    if(b.dataset.cancel)confirmBox('Отменить назначение? Оно пропадёт из списка.','Отменить назначение',async()=>{await api('/assignments/'+b.dataset.cancel,{method:'DELETE'});toast('Назначение отменено');load()})};
  await load();
}

/* ---------- Моё обучение (работник) ---------- */
async function learn(v,id){
  v.onclick=null;
  if(id)return learnCourse(v,id);
  const my=await api('/my/assignments'),order={overdue:0,in_progress:1,assigned:2,expired:3,passed:4};
  my.sort((a,b)=>order[a.state]-order[b.state]);
  v.innerHTML=`<div class="bar"><h1>Моё обучение</h1></div>${my.length?`<div class="tiles wide">${my.map(a=>{
    const fin=['passed','expired'].includes(a.state),steps=a.materials+(a.has_test?1:0),done=fin?steps:a.viewed;
    return `<a class="card course" href="#/learn/${a.id}"><div class="bar" style="margin:0 0 8px">${badge(a.state)}<span class="m nw">${a.due_date&&!fin?'до '+dd(a.due_date):''}</span></div><h3>${e(a.course_title)}</h3><progress max="${steps||1}" value="${done}"></progress><small>${a.materials?`Материалы: ${a.viewed} из ${a.materials}`:''}${a.has_test?` · Тест: ${a.score!==null?a.score+'%':'не сдан'}`:''}</small></a>`}).join('')}</div>`
    :'<div class="card empty">Вам пока не назначено обучение.</div>'}`;
}

async function learnCourse(v,id){
  const c=await api('/my/assignments/'+id),a=c.assignment,done=['passed','expired'].includes(a.state);
  v.innerHTML=`<div class="crumbs"><a href="#/learn">Моё обучение</a> / ${e(a.course_title)}</div>
    <div class="bar"><h1>${e(a.course_title)}</h1>${badge(a.state)}</div>${c.description?`<p>${e(c.description)}</p>`:''}
    ${done?`<div class="card hero" style="margin-bottom:16px"><h2>✓ Курс пройден ${dd(a.completed_at)}</h2><p>${a.score!==null?'Результат теста: '+a.score+'%. ':''}${a.expires_at?'Действует до '+dd(a.expires_at)+'.':''}</p></div>`:a.due_date?`<p class="m">Пройти до ${dd(a.due_date)}</p>`:''}
    ${c.materials.length?`<div class="card"><h2>Шаг 1. Изучите материалы</h2><table>${c.materials.map(m=>`<tr><td class="ic">${m.kind==='video'?'🎬':'📄'}</td><td><b>${e(m.title)}</b>${m.description?`<small>${e(m.description)}</small>`:''}</td><td class="nw">${m.viewed?'<span class="s ok">✓ Изучено</span>':'<span class="s">Не открыт</span>'}</td><td class="ra"><button class="b sm" data-open="${m.item_id}" data-kind="${m.kind}">${m.kind==='video'?'Смотреть':'Открыть'}</button></td></tr>`).join('')}</table></div>`:''}
    ${c.test.length?`<div class="card" style="margin-top:16px"><h2>Шаг ${c.materials.length?2:1}. Тест</h2><p class="m">Вопросов: ${c.test.length}. Для сдачи нужно не меньше ${c.pass_score}% правильных ответов.${a.attempts?` Попыток: ${a.attempts}, лучший результат ${a.score}%.`:''}</p>
      ${done?'':c.can_take_test?`<form id="tf">${c.test.map((q,i)=>`<div class="q"><b>${i+1}. ${e(q.text)}</b>${q.multiple?'<small>Выберите все правильные ответы</small>':''}${q.options.map((o,j)=>`<label class="chk"><input type="${q.multiple?'checkbox':'radio'}" name="q${i}" value="${j}"> ${e(o)}</label>`).join('')}</div>`).join('')}<button class="b">Отправить ответы</button></form>`:'<p><b>Тест откроется, когда вы изучите все материалы.</b></p>'}</div>`:''}`;
  v.onclick=async ev=>{const b=ev.target.closest('[data-open]');if(!b)return;
    const w=b.dataset.kind==='document'?window.open('about:blank'):null;
    try{const {url}=await api(`/my/assignments/${id}/materials/${b.dataset.open}`,{method:'POST'});
      if(w)w.location=url;else modal('Видеоурок',`<video src="${url}" controls autoplay playsinline></video>`,null,null,true);
      await learnCourse(v,id);
    }catch(x){if(w)w.close();toast(x.message,1)}};
  const f=$('#tf');if(f)f.onsubmit=async ev=>{ev.preventDefault();
    const answers=c.test.map((q,i)=>[...f.querySelectorAll(`[name=q${i}]:checked`)].map(x=>+x.value));
    const miss=answers.findIndex(x=>!x.length);if(miss>=0)return toast(`Ответьте на вопрос ${miss+1}`,1);
    try{const r=await api(`/my/assignments/${id}/test`,{method:'POST',body:{answers}});
      modal(r.passed?'✓ Тест сдан':'Тест не сдан',`<p style="font-size:20px">Результат: <b>${r.score}%</b> (${r.correct} из ${r.total})</p><p class="m">${r.passed?'Поздравляем! Курс пройден.':`Нужно не меньше ${r.pass_score}%. Повторите материалы и попробуйте ещё раз.`}</p>`);
      await learnCourse(v,id);
    }catch(x){toast(x.message,1)}};
}
