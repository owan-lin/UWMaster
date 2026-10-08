let S,filter='week',course='all',view='week',cursor=new Date(),search='',completedOpen=false,stateNotice=null;
const pendingStates=new Set();
const $=x=>document.querySelector(x),esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),TZ='America/Los_Angeles';
const C=id=>S.courses.find(x=>x.id===id)||{},D=x=>x.due?new Date(x.due.length===10?x.due+'T12:00:00Z':x.due):null,A=x=>x.is_class||((x.kind==='exam'||x.kind==='quiz')&&x.end),stamp=d=>new Intl.DateTimeFormat('en-CA',{timeZone:TZ,year:'numeric',month:'2-digit',day:'2-digit'}).format(d),taskKey=x=>x.due?.length===10?x.due:stamp(D(x));
// Course identity stays consistent across the sidebar, agenda and calendar.
const courseHues={math126:212,cse123:356,cse190:166,cse391:32};
const taskKinds={class:['到课',97,59],participation:['参与',94,50],preparation:['课前材料',90,44],homework:['作业',86,39],extra_credit:['额外加分',82,36],project:['项目',77,32],quiz:['测验',72,28],exam:['考试',66,24]};
function courseHue(id){if(Object.hasOwn(courseHues,id))return courseHues[id];let hash=0;for(let c of String(id))hash=(hash*31+c.charCodeAt(0))>>>0;return hash%360}
function taskKind(x){return taskKinds[x.kind]||['其他',94,44]}
function courseStyle(id){let h=courseHue(id);return `--course-ink:hsl(${h} 55% 27%);--course-accent:hsl(${h} 54% 40%);--course-soft:hsl(${h} 48% 94%)`}
const taskTints={class:.045,participation:.07,preparation:.09,homework:.11,extra_credit:.08,project:.13,quiz:.145,exam:.16};
function taskStyle(x){let h=courseHue(x.course_id),[,,accent]=taskKind(x),tint=taskTints[x.kind]||.065;return `${courseStyle(x.course_id)};--task-bg:hsl(${h} 48% 48% / ${tint});--task-accent:hsl(${h} 54% ${accent}%);--task-hover:hsl(${h} 48% 48% / ${tint+.035})`}
function taskSource(x){try{let url=new URL(x.source_url);return ['https:','http:'].includes(url.protocol)?url.href:null}catch{return null}}
function render(){let xs=list(),pending=xs.filter(x=>!x.user_completed),completed=completedList();$('#app').innerHTML=`<aside class=sidebar><h2>我的课程</h2><button data-course=all>全部课程</button>${S.courses.map(c=>`<div class="course-group" style="${courseStyle(c.id)}"><button data-course="${esc(c.id)}"><b>${esc(c.code)}</b><small>${esc(c.title)}</small></button></div>`).join('')}</aside><section class=workspace><div class=hero><div><h2>${esc(S.term.name)}</h2><p>上次核查：${esc(S.checked_at||'未提供')} · 下次：${esc(S.automation?.next_run||'按周更新')}</p></div></div><div class=filters><select id=f aria-label="筛选任务范围"><option value=week>未来 7 天</option><option value=all>全部学期</option><option value=confirm>待确认</option><option value=done>已完成</option></select><label class="search-field"><input id=q aria-label="搜索任务、课程或要求" placeholder="搜索任务、课程或要求" value="${esc(search)}"></label></div><div class=two-panels><section class=todo-panel><div class="panel-heading"><h3>待办</h3><span>${pending.length} 项未完成</span></div><div class=completion-tools><button id=showCompleted>查看全部已完成</button></div>${noticeMarkup()}<div class=pending-tasks>${filter==='done'?'':pending.map(card).join('')||'<p class=empty>没有符合条件的未完成项目。<br><span>已勾选任务可在下方“已完成”中查看。</span></p>'}</div><details id=completedTasks class=completed-section ${completedOpen||filter==='done'?'open':''}><summary>已完成 <span>${completed.length} 项</span></summary><div class=completed-body><p class=completed-context>按当前课程和搜索筛选 · 不限截止日期 · 取消勾选可恢复</p>${completed.map(card).join('')||'<p class=empty>没有符合当前课程或搜索的已完成任务。</p>'}</div></details></section><section class=calendar-panel><div class="panel-heading"><h3>课程日历</h3><span>西雅图时间</span></div>${calendar(xs)}</section></div></section>`;$('#f').value=filter;$('#f').onchange=e=>{filter=e.target.value;if(filter==='done')completedOpen=true;render()};$('#q').oninput=e=>{search=e.target.value;render()};document.querySelectorAll('[data-course]').forEach(b=>b.onclick=()=>{course=b.dataset.course;render()});document.querySelectorAll('[data-detail]').forEach(b=>b.onclick=()=>detail(b.dataset.detail));document.querySelectorAll('[data-check]').forEach(b=>b.onchange=()=>state(b.dataset.check,b.checked));$('#completedTasks').ontoggle=e=>{if(e.target.isConnected&&e.target===$('#completedTasks'))completedOpen=e.target.open};$('#showCompleted').onclick=()=>{course='all';search='';completedOpen=true;render();$('#completedTasks summary').focus({preventScroll:true})};document.querySelectorAll('[data-task-detail]').forEach(row=>{row.onclick=e=>{if(e.target.closest('a,button,input,label'))return;detail(row.dataset.taskDetail)};row.onkeydown=e=>{if(e.target!==row||!['Enter',' '].includes(e.key))return;e.preventDefault();detail(row.dataset.taskDetail)}});}
function noticeMarkup(){return stateNotice?.error?`<div class="completion-notice save-error"><span role=alert>${esc(stateNotice.text)}</span></div>`:''}
// State saves replace the UI without scrolling the document or its nested panels.
function renderKeepingPosition(){
  let page={x:window.scrollX,y:window.scrollY},active=document.activeElement,focusId=active?.dataset?.check;
  let scrolls=['.todo-scroll','.calendar-scroll','.day-events','.popover-tasks'].map(selector=>({selector,positions:[...document.querySelectorAll(selector)].map(node=>({top:node.scrollTop,left:node.scrollLeft}))}));
  render();
  for(let group of scrolls)document.querySelectorAll(group.selector).forEach((node,i)=>{let pos=group.positions[i];if(pos){node.scrollTop=pos.top;node.scrollLeft=pos.left}});
  if(focusId){let control=[...document.querySelectorAll('[data-check]')].find(node=>node.dataset.check===focusId);if(control?.getClientRects().length)control.focus({preventScroll:true})}
  window.scrollTo({left:page.x,top:page.y,behavior:'instant'});
}
async function state(id,done){
  if(pendingStates.has(id))return false;
  let x=S.tasks.find(x=>x.id===id),changed=Boolean(x.user_completed)!==done;
  pendingStates.add(id);
  document.querySelectorAll('[data-check]').forEach(b=>{if(b.dataset.check===id)b.disabled=true});
  try{
    let r=await fetch('/api/task-state',{method:'POST',headers:{'Content-Type':'application/json','X-UW-Course-Panel':'local-ui'},body:JSON.stringify({id,completed:done,note:x.user_note||''})});
    if(!r.ok)throw Error((await r.json()).error||'保存失败');
    x.user_completed=done;
    if(changed)completedOpen=true;
    stateNotice=null;
    pendingStates.delete(id);renderKeepingPosition();
    return true;
  }catch(err){
    stateNotice={text:'未保存：'+err.message+'。原完成状态已保留。',error:true};
    pendingStates.delete(id);renderKeepingPosition();return false;
  }finally{pendingStates.delete(id)}
}


const baseRender=render;render=function(){
  baseRender();
  $('#termName').textContent=S.term.name; $('.hero p').textContent='上次核查：'+displayDate(S.checked_at)+' · 下次：'+displayDate(S.automation?.next_run);
  document.querySelectorAll('[data-course]').forEach(b=>{let active=b.dataset.course===course;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active))});
  let label={week:'未来 7 天',all:'全部学期',confirm:'待确认',done:'已完成'}[filter];
  $('.hero h2').textContent=course==='all'?'我的学期':C(course).code+' · '+C(course).title;
  $('.filters').insertAdjacentHTML('afterend',`<div class=course-legend aria-label=课程配色>${S.courses.map(c=>`<span style="${courseStyle(c.id)}"><i aria-hidden=true></i>${esc(c.code)}</span>`).join('')}</div>`);

  $('.hero p').innerHTML=`${esc(S.term.name.toUpperCase())} · UPDATED ${esc(quarterDate(S.checked_at,true))}`;
  $('.hero>div').insertAdjacentHTML('afterbegin','<span class=section-caption>MY QUARTER</span>');
  $('.hero').insertAdjacentHTML('beforeend',`<div class=quarter-stats aria-label="${S.courses.length}门课程，${list().length}项任务">${[[S.courses.length,'COURSES'],[list().length,'TASKS']].map(([n,label])=>`<div><strong>${n}</strong><span>${label}</span></div>`).join('')}</div>`);
  $('.sidebar h2').textContent='我的课程';
  $('.todo-panel h3').textContent='待办';
  $('.calendar-panel h3').textContent='课程日历';
  const intro=document.createElement('section');intro.className='quarter-intro';intro.setAttribute('aria-label','学期概览与筛选');
  $('#app').prepend(intro);
  for(const selector of ['.hero','.filters','.course-legend']){const node=$(selector);if(node)intro.append(node)}
};
document.addEventListener('input',event=>{if(event.target.id!=='q')return;let input=event.target,start=input.selectionStart,end=input.selectionEnd;event.stopImmediatePropagation();search=input.value;render();let next=$('#q');next.focus({preventScroll:true});next.setSelectionRange(start,end)},true);
$('#fileInput').onchange=async e=>{try{let r=await fetch('/api/import',{method:'POST',headers:{'Content-Type':'application/json','X-UW-Course-Panel':'local-ui'},body:JSON.stringify({snapshot:JSON.parse(await e.target.files[0].text())})});if(!r.ok)throw Error((await r.json()).error||'导入失败');location.reload()}catch(x){alert('导入失败：'+x.message)}};function download(n,t,type){let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([t],{type}));a.download=n;a.click()}
fetch('/api/data').then(r=>{if(!r.ok)throw Error('读取失败');return r.json()}).then(x=>{S=x;render()}).catch(()=>{$('#app').innerHTML='<div class=loading role=alert>无法读取课程快照，请确认本地服务已启动后刷新页面。</div>'});
// Calendar uses UTC noon purely as a date carrier. Its displayed calendar date is Seattle's date.
function seattleToday(){let parts=new Intl.DateTimeFormat('en-CA',{timeZone:TZ,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()),v={};parts.forEach(p=>v[p.type]=p.value);return new Date(Date.UTC(+v.year,+v.month-1,+v.day,12))}
cursor=seattleToday();
function utcMonday(d){let r=new Date(d);r.setUTCHours(12,0,0,0);r.setUTCDate(r.getUTCDate()-((r.getUTCDay()+6)%7));return r}
function calendarLabel(x){let title=x.title.replace(/^Week\s+(\d+)\s+/i,'W$1 ').replace(/\s*[·—]\s*(?:Quiz Section|BG|CC)\b.*$/i,'').replace(/^(Section\s+\d+):\s*([^;]+);.*$/i,'$1 · $2').replace(/^HW(\d+)\s*[—·]\s*/i,'HW$1 · ');return title.length>30?title.slice(0,29)+'…':title}
function calendarEvent(x,compact=false){return `<button data-detail="${esc(x.id)}" style="${taskStyle(x)}" class="event ${A(x)?'event-class':'event-deadline'} ${compact?'event-expanded':''} ${x.user_completed?'done':''}" title="${esc(x.title)}"><span class=event-time>${x.due.length>10?D(x).toLocaleTimeString('zh-CN',{timeZone:TZ,hour:'2-digit',minute:'2-digit'}):'全天'}</span><strong>${esc(C(x.course_id).code)}</strong><span class=event-title lang="en">${esc(compact?x.title:calendarLabel(x))}</span><span class=event-kind>${esc(taskKind(x)[0])}</span></button>`}
function calendar(xs){
 let first;if(view==='week')first=utcMonday(cursor);else{let m=new Date(cursor);m.setUTCDate(1);first=utcMonday(m)}
 let count=view==='week'?7:42,days=[...Array(count)].map((_,i)=>new Date(first.getTime()+i*86400000));
 let label=view==='week'?`${first.toLocaleDateString('zh-CN',{timeZone:'UTC',month:'short',day:'numeric'})} — ${days.at(-1).toLocaleDateString('zh-CN',{timeZone:'UTC',month:'short',day:'numeric'})}`:cursor.toLocaleDateString('zh-CN',{timeZone:'UTC',year:'numeric',month:'long'});
 return `<div class=calendar-toolbar><span><button id=prev aria-label="上一页日历">‹</button><button id=today aria-label="今天">今</button><button id=next aria-label="下一页日历">›</button></span><b>${label}</b><span class=view-tabs role=group aria-label="日历视图"><button data-view=week aria-label="周视图" aria-pressed="${view==='week'}">周</button><button data-view=month aria-label="月视图" aria-pressed="${view==='month'}">月</button></span></div><div class="calendar-scroll"><div class="calendar-grid ${view}">${['一','二','三','四','五','六','日'].map(x=>`<b>${x}</b>`).join('')}${days.map((day,i)=>{
 let date=day.toISOString().slice(0,10),items=xs.filter(x=>D(x)&&taskKey(x)===date),dateLabel=day.toLocaleDateString('zh-CN',{timeZone:'UTC',month:'long',day:'numeric'});
 let content=view==='week'?`<div class=day-events>${items.map(x=>calendarEvent(x)).join('')}</div>`:`<div class=day-markers style="--marker-columns:${items.length<=2?items.length:Math.ceil(items.length/2)}" aria-hidden=true>${items.map((x,j)=>{let top=items.length<=2?items.length:Math.floor(items.length/2);return `<span class="day-marker ${x.user_completed?'done':''}" style="${taskStyle(x)};grid-row:${j<top?1:2};grid-column:${j<top?j+1:j-top+1}"></span>`}).join('')}</div>${items.length?`<div class=date-popover role=group aria-label="${dateLabel}的任务"><header><strong>${dateLabel}</strong><span>${items.length} 项</span></header><div class=popover-tasks>${items.map(x=>calendarEvent(x,true)).join('')}</div></div>`:''}`;
 return `<div style="--day-column:${i%7}" class="day ${[0,6].includes(day.getUTCDay())?'weekend':''} ${date===seattleToday().toISOString().slice(0,10)?'today':''} ${view==='month'&&day.getUTCMonth()!==cursor.getUTCMonth()?'other-month':''} ${i%7>=3?'popover-left':'popover-right'} ${i>=21?'popover-up':''}" ${view==='month'&&items.length?`tabindex="0" aria-label="${dateLabel}，${items.length}项任务，聚焦查看"`:''}><em><span class=mobile-date>${day.getUTCMonth()+1}月</span>${day.getUTCDate()}<span class=mobile-date>日 · ${['周日','周一','周二','周三','周四','周五','周六'][day.getUTCDay()]}</span></em>${content}</div>`
 }).join('')}</div></div><p class=calendar-context>日历使用当前范围、课程和搜索筛选 · “全部学期”包含已完成任务</p>`
}
document.addEventListener('click',event=>{if(event.target.dataset.view){event.stopImmediatePropagation();view=event.target.dataset.view;render();return}let id=event.target.id;if(!['prev','next','today','switch'].includes(id))return;event.stopImmediatePropagation();if(id==='today')cursor=seattleToday();else if(id==='switch')view=view==='week'?'month':'week';else if(view==='week')cursor.setUTCDate(cursor.getUTCDate()+(id==='next'?7:-7));else{cursor.setUTCDate(1);cursor.setUTCMonth(cursor.getUTCMonth()+(id==='next'?1:-1))}render()},true);
function card(x){let d=D(x),cn={verified:'已核实',tentative:'暂定',needs_confirmation:'待确认'}[x.certainty]||x.certainty,status=x.source_status==='completed'?'Ed 已完成':x.source_status==='not_started'?'Ed 未开始':x.source_status==='scored'?'已评分':x.source_status==='not_submitted'?'未提交':'',badges=[x.certainty!=='verified'?`<i class="uncertain">${esc(cn)}</i>`:'',x.grade_impact?`<span class=grade-label>${esc(x.grade_impact)}</span>`:'',status?`<i class="source-status">${esc(status)}</i>`:''].filter(Boolean).join('');let date=d?d.toLocaleDateString('en-US',{timeZone:TZ,month:'short',day:'2-digit'}).toUpperCase():'待确认',clock=d?(x.due.length>10?d.toLocaleTimeString('zh-CN',{timeZone:TZ,hour:'2-digit',minute:'2-digit'}):'全天'): '无确定日期';let url=taskSource(x),title=`<b>${A(x)?'到课 · ':''}${esc(x.title)}</b>`;return `<article data-task-detail="${esc(x.id)}" tabindex="0" aria-label="${esc(x.title)}，查看详情" style="${taskStyle(x)}" class="task ${x.user_completed?'done':''}"><input data-check="${esc(x.id)}" aria-label="完成：${esc(x.title)}" type=checkbox ${pendingStates.has(x.id)?'disabled':''} ${x.user_completed?'checked':''}><div class=task-content>${url?`<a class=task-title href="${esc(url)}" target=_blank rel="noopener noreferrer" title="打开任务来源（新标签页）">${title}<span class=source-arrow aria-hidden=true> ↗</span></a>`:`<button class=task-title data-detail="${esc(x.id)}">${title}</button>`}<small><span class=course-code>${esc(C(x.course_id).code)}</span><span class=kind-label>${esc(taskKind(x)[0])}</span> ${badges}</small></div><time datetime="${esc(x.due||'')}" title="${esc(x.due||'无确定日期')}" class="${x.certainty!=='verified'?'date-uncertain':''}"><span>${date}</span><strong>${clock}</strong>${x.kind==='preparation'?'<small>课前目标</small>':''}</time></article>`}
function matchesTask(x){let txt=`${x.title} ${C(x.course_id).code||''} ${x.description||''}`.toLowerCase();return (course==='all'||x.course_id===course)&&(!search||txt.includes(search.toLowerCase()))}
function sortTasks(xs){return xs.sort((a,b)=>(D(a)?.valueOf()??Infinity)-(D(b)?.valueOf()??Infinity))}
function completedList(){return sortTasks(S.tasks.filter(x=>x.user_completed&&matchesTask(x)))}
function list(){let now=new Date(),later=new Date(now);later.setDate(later.getDate()+7);return sortTasks(S.tasks.filter(x=>{
  if(!matchesTask(x))return false;
  if(filter==='week'){let d=D(x),available=x.available_from?new Date(x.available_from+'T12:00:00Z'):null,shown=d&&d<=later&&(!A(x)||d>=now)||(!d&&available&&available<=later)||(!d&&x.manual);return shown&&!x.user_completed&&x.source_status!=='completed'}
  if(filter==='all')return true;
  if(filter==='confirm')return ['tentative','needs_confirmation'].includes(x.certainty);
  if(filter==='done')return x.user_completed;
  return true;
}))}

function quarterDate(value,withTime){if(!value)return 'PENDING';return new Intl.DateTimeFormat('en-US',{timeZone:TZ,month:'short',day:'2-digit',...(withTime?{hour:'2-digit',minute:'2-digit',hourCycle:'h23'}:{})}).format(new Date(value.length===10?value+'T12:00:00Z':value)).toUpperCase()}
function displayDate(value){if(!value)return '无确定日期';return new Date(value.length===10?value+'T12:00:00Z':value).toLocaleString('zh-CN',{timeZone:TZ,year:'numeric',month:'long',day:'numeric',weekday:'short',...(value.length>10?{hour:'2-digit',minute:'2-digit'}:{})})}
function detail(id){let x=S.tasks.find(v=>v.id===id),m=$('#detail'),label=x.kind==='preparation'?'课前完成目标（按个人上课时间）':A(x)?'到课时间':'截止时间';m.querySelector('article').innerHTML=`<button class=dialog-close aria-label="关闭任务详情">×</button><p class=detail-course>${esc(C(x.course_id).code)} · 西雅图时间</p><h2>${esc(x.title)}</h2><div class=detail-date><b>${label}</b><p>${esc(displayDate(x.due))}${x.end?' — '+esc(displayDate(x.end)):''}</p>${x.platform_due_label?`<p class=platform-label>平台截止标签：${esc(x.platform_due_label)}</p>`:''}</div><p class=detail-description>${esc(x.description||'')}</p><div class=grade-info>分值：${esc(x.points??'未提供')}　权重：${esc(x.weight??'未提供')}</div><p class=source-note>${esc(x.source_note||'')} ${x.source_url?`<a href="${esc(x.source_url)}" target=_blank rel="noopener noreferrer">查看原始来源 ↗</a>`:''}</p><label class=note-label for=note>个人备注</label><textarea id=note aria-label="个人备注" placeholder="记录你的计划、疑问或提醒…">${esc(x.user_note||'')}</textarea><button id=save>保存备注</button><span id=saveStatus role=status aria-live=polite></span>`;m.querySelector('.dialog-close').onclick=()=>m.close();$('#save').onclick=async()=>{let previous=x.user_note;x.user_note=$('#note').value;$('#save').disabled=true;$('#save').textContent='正在保存…';let saved=await state(id,x.user_completed);if(saved){$('#saveStatus').textContent='已保存';$('#save').textContent='保存备注'}else{x.user_note=previous;$('#saveStatus').textContent='保存失败，备注仍在输入框中';$('#save').textContent='重新保存'}$('#save').disabled=false};if(!m.open)m.showModal()}

// Keep task actions in the heading without changing existing filter/save behavior.
const taskActionsRender=render;
render=function(){
  taskActionsRender();
  let heading=$('.todo-panel .panel-heading'),actions=document.createElement('div');actions.className='task-heading-actions';
  let count=heading.querySelector('span'),completed=$('#showCompleted');completed.textContent='已完成';
  let title=document.createElement('div');title.className='task-heading-title';title.append(heading.querySelector('h3'),count);heading.prepend(title);
  actions.append(completed);$('.completion-tools').remove();
  let add=document.createElement('button');add.className='add-task-button';add.textContent='+';add.setAttribute('aria-label','手动添加任务');add.title='手动添加任务';add.onclick=openAddTask;actions.append(add);heading.append(actions);
  const scroll=document.createElement('div');scroll.className='todo-scroll';
  const panel=heading.parentElement;while(heading.nextSibling)scroll.append(heading.nextSibling);panel.append(scroll);
};
async function localTask(body){let response=await fetch('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json','X-UW-Course-Panel':'local-ui'},body:JSON.stringify(body)}),result=await response.json();if(!response.ok)throw Error(result.error||'保存失败');return result}
async function reloadTasks(){let response=await fetch('/api/data');if(!response.ok)throw Error('无法读取任务，请刷新页面');S=await response.json();renderKeepingPosition()}
function seattleTaskDate(date,time){
  if(!date)return null;if(!time)return date;
  let wanted=Date.parse(date+'T'+time+':00Z'),instant=wanted;
  for(let i=0;i<3;i++){let parts=new Intl.DateTimeFormat('en-CA',{timeZone:TZ,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(new Date(instant)),v={};parts.forEach(p=>v[p.type]=p.value);let wall=Date.parse(`${v.year}-${v.month}-${v.day}T${v.hour}:${v.minute}:${v.second}Z`);if(wall===wanted)return new Date(instant).toISOString();instant+=wanted-wall}
  throw Error('该时间位于夏令时切换的跳过时段，请选择其他时间');
}
function openAddTask(){
  let modal=$('#addTask'),form=$('#addTaskForm');form.reset();$('#taskCourse').innerHTML=S.courses.map(c=>`<option value="${esc(c.id)}">${esc(c.code)}</option>`).join('');$('#taskCourse').value=course==='all'?S.courses[0].id:course;$('#addTaskStatus').textContent='';
  modal.querySelector('.dialog-close').onclick=()=>modal.close();$('#cancelAddTask').onclick=()=>modal.close();
  form.onsubmit=async event=>{event.preventDefault();let button=$('#submitAddTask');if(button.disabled)return;button.disabled=true;$('#addTaskStatus').textContent='正在添加…';try{if($('#taskTime').value&&!$('#taskDate').value)throw Error('填写时间时请同时选择日期');await localTask({action:'add',title:$('#taskTitle').value,course_id:$('#taskCourse').value,kind:$('#taskKind').value,due:seattleTaskDate($('#taskDate').value,$('#taskTime').value),description:$('#taskDescription').value,source_url:$('#taskSource').value.trim()});modal.close();await reloadTasks()}catch(error){$('#addTaskStatus').textContent=error.message}finally{button.disabled=false}};
  modal.showModal();$('#taskTitle').focus();
}
function deletionNotice(id){
  $('.task-delete-notice')?.remove();let box=document.createElement('div');box.className='task-delete-notice';box.setAttribute('role','status');box.innerHTML='<span>任务已删除</span><button>撤销</button><button aria-label="关闭删除提示">×</button>';document.body.append(box);let buttons=box.querySelectorAll('button');buttons[1].onclick=()=>box.remove();buttons[0].onclick=async()=>{buttons[0].disabled=true;try{await localTask({action:'restore',id});await reloadTasks();box.remove()}catch(error){box.querySelector('span').textContent=error.message;buttons[0].disabled=false}};
}
const taskDetail=detail;
detail=function(id){
  taskDetail(id);let article=$('#detail article'),button=document.createElement('button');button.className='delete-task-button';button.textContent='删除任务';article.append(button);
  button.onclick=async()=>{if(button.disabled||pendingStates.has(id))return;button.disabled=true;try{await localTask({action:'delete',id});$('#detail').close();await reloadTasks();deletionNotice(id)}catch(error){button.textContent=error.message+' · 重试';button.disabled=false}};
};

// Motion preserves the page and nested scroll positions through every render.
const motionRender=render;
const reduceMotion=()=>Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
function keepViewportRoom(y){let app=$('#app');if(!app||!document.documentElement)return;let room=y+window.innerHeight-document.documentElement.scrollHeight;if(room>0)app.style.minHeight=(app.getBoundingClientRect().height+room)+'px'}
render=function(){
 const page={x:window.scrollX,y:window.scrollY},active=document.activeElement;
 const focus=active?.id?{id:active.id}:active?.dataset?.course?{attr:'data-course',value:active.dataset.course}:active?.dataset?.view?{attr:'data-view',value:active.dataset.view}:null;
 const selectors=['.todo-scroll','.calendar-scroll','.day-events','.popover-tasks'];
 const offsets=selectors.map(selector=>({selector,positions:[...document.querySelectorAll(selector)].map(node=>[node.scrollTop,node.scrollLeft])}));
 const old={pending:$('.pending-tasks')?.innerHTML,calendar:$('.calendar-grid')?.innerHTML};
 motionRender();
 keepViewportRoom(page.y);
 offsets.forEach(group=>document.querySelectorAll(group.selector).forEach((node,i)=>{let p=group.positions[i];if(p){node.scrollTop=p[0];node.scrollLeft=p[1]}}));
 if(focus){let node=focus.id?document.getElementById(focus.id):[...document.querySelectorAll('['+focus.attr+']')].find(n=>n.getAttribute(focus.attr)===focus.value);node?.focus({preventScroll:true})}
 window.scrollTo({left:page.x,top:page.y,behavior:'instant'});
 if(!reduceMotion())for(let [selector,previous] of [['.pending-tasks',old.pending],['.calendar-grid',old.calendar]]){let node=$(selector);if(previous!==undefined&&node?.innerHTML!==previous)node.animate([{opacity:.35},{opacity:1}],{duration:180,easing:'ease-out'})}
 document.querySelectorAll('#completedTasks').forEach(bindDisclosureMotion);
 $('#showCompleted').onclick=()=>{
  let needsRender=course!=='all'||search!=='';course='all';search='';
  if(needsRender)render();
  let section=$('#completedTasks'),animation=animateDisclosure(section,true);section.querySelector('summary').focus({preventScroll:true});
  const reveal=()=>{let panel=$('.todo-scroll');if(!section.isConnected||getComputedStyle(panel).overflowY!=='auto')return;let top=section.getBoundingClientRect().top-panel.getBoundingClientRect().top+panel.scrollTop;panel.scrollTo({top:Math.max(0,top-60),behavior:reduceMotion()?'instant':'smooth'})};
  if(animation)animation.finished.then(reveal).catch(()=>{});else reveal();
 };
};
const disclosureAnimations=new WeakMap();
function bindDisclosureMotion(section){section.querySelector('summary').onclick=event=>{event.preventDefault();animateDisclosure(section,section.dataset.motionOpen?section.dataset.motionOpen!=='true':!section.open)}}
function animateDisclosure(section,open){
 if(!section)return;
 const oldAnimation=disclosureAnimations.get(section),start=section.getBoundingClientRect().height;
 oldAnimation?.cancel();
 section.dataset.motionOpen=String(open);if(section.id==='completedTasks')completedOpen=open;
 if(reduceMotion()){section.open=open;keepViewportRoom(window.scrollY);return}
 section.style.height='';section.style.overflow='hidden';section.open=true;
 const end=open?section.getBoundingClientRect().height:section.querySelector('summary').getBoundingClientRect().height+parseFloat(getComputedStyle(section).paddingTop)+parseFloat(getComputedStyle(section).borderTopWidth);
 const animation=section.animate([{height:start+'px'},{height:end+'px'}],{duration:260,easing:'cubic-bezier(.22,1,.36,1)'});disclosureAnimations.set(section,animation);
 animation.onfinish=()=>{let page={x:window.scrollX,y:window.scrollY};section.open=open;section.style.height='';section.style.overflow='';disclosureAnimations.delete(section);delete section.dataset.motionOpen;keepViewportRoom(page.y);window.scrollTo({left:page.x,top:page.y,behavior:'instant'})};
 animation.oncancel=()=>{section.style.height='';section.style.overflow=''};return animation;
}
// Only the initial downward page scroll snaps to the white workspace.
if(document.documentElement){
 let initialScrollUsed=false,scrollFrame=0,touchStartY=null;
 const cancelScroll=()=>{cancelAnimationFrame(scrollFrame);scrollFrame=0};
 function enterWorkspace(){let app=$('#app');if(!app?.querySelector('.quarter-intro'))return false;let target=app.getBoundingClientRect().top+window.scrollY;if(window.scrollY>=target-1){initialScrollUsed=true;return false}initialScrollUsed=true;if(reduceMotion()){window.scrollTo({top:target,behavior:'instant'});return true}let from=window.scrollY,start=performance.now();function step(now){let t=Math.min(1,(now-start)/580),ease=t<.5?4*t*t*t:1-Math.pow(-2*t+2,3)/2;window.scrollTo({top:from+(target-from)*ease,behavior:'instant'});if(t<1)scrollFrame=requestAnimationFrame(step);else scrollFrame=0}scrollFrame=requestAnimationFrame(step);return true}
 const nestedScroll=target=>{let node=target.closest?.('.todo-scroll,.day-events,.popover-tasks,dialog');return node&&(node.tagName==='DIALOG'||node.scrollHeight>node.clientHeight)};
 window.addEventListener('wheel',event=>{if(event.ctrlKey||event.deltaY===0||nestedScroll(event.target)||document.querySelector('dialog[open]'))return;if(event.deltaY<0){cancelScroll();return}if(scrollFrame){event.preventDefault();return}if(!initialScrollUsed&&enterWorkspace())event.preventDefault()},{passive:false});
 window.addEventListener('touchstart',event=>{touchStartY=event.touches[0]?.clientY;cancelScroll()},{passive:true});
 window.addEventListener('touchmove',event=>{if(scrollFrame){event.preventDefault();return}if(touchStartY!==null&&touchStartY-event.touches[0]?.clientY>12&&!initialScrollUsed&&!nestedScroll(event.target)&&!document.querySelector('dialog[open]')&&enterWorkspace())event.preventDefault()},{passive:false});
 window.addEventListener('keydown',event=>{if(['ArrowUp','Escape','PageUp','Home'].includes(event.key))cancelScroll();if(!initialScrollUsed&&['PageDown','ArrowDown',' '].includes(event.key)&&!event.target.closest?.('input,textarea,select,button,summary,a,[tabindex]')&&enterWorkspace())event.preventDefault()});
 window.addEventListener('pointerdown',cancelScroll,{passive:true});
}
