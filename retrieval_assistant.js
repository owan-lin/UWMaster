'use strict';
(() => {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const panel = document.createElement('aside');
  panel.className = 'retrieval-assistant';
  panel.setAttribute('aria-label', '检索助手');
  panel.innerHTML = '<button class="assistant-toggle" aria-expanded="false">检索助手 <span id="assistantBadge"></span></button><section class="assistant-panel" hidden><header><h2>检索助手</h2><button class="assistant-close" aria-label="关闭检索助手">×</button></header><p class="assistant-hint">根据本次证据解释结果；修改检索要求后请重新检索。</p><div class="assistant-content" aria-live="polite"></div><form class="assistant-form"><label for="assistantInput">询问本次检索</label><textarea id="assistantInput" maxlength="4000" rows="2" placeholder="为什么这项任务没有更新？"></textarea><button type="submit">发送</button></form><p class="assistant-error" role="status"></p></section>';
  document.body.append(panel);
  const toggle = panel.querySelector('.assistant-toggle'), section = panel.querySelector('section'), content = panel.querySelector('.assistant-content'), input = panel.querySelector('textarea'), send = panel.querySelector('form button');
  const historyLabel=document.createElement('label');historyLabel.textContent='检索记录';
  const historySelect=document.createElement('select');historySelect.setAttribute('aria-label','选择检索记录');
  historySelect.innerHTML='<option value="">最新检索</option>';historyLabel.append(historySelect);panel.querySelector('.assistant-hint').after(historyLabel);
  let selectedRecord='', job = null, lastRendered = '', lastFinished = '', refreshVersion = '', polling = false, refreshing = false, stateWrites = 0;
  historySelect.onchange=async()=>{selectedRecord=historySelect.value;try{renderJob(await request(selectedRecord?'runs/'+selectedRecord:'latest'))}catch(error){panel.querySelector('.assistant-error').textContent=error.message}};
  async function request(path, body) {
    const response = await fetch('/api/retrieval/' + path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-UW-Course-Panel':'local-ui'}, body:JSON.stringify(body)});
    const value = await response.json();
    if (!response.ok) throw Error(value.error || '操作失败');
    return value;
  }
  function open(value) { section.hidden = !value; toggle.setAttribute('aria-expanded', String(value)); }
  toggle.onclick = () => open(section.hidden);
  panel.querySelector('.assistant-close').onclick = () => open(false);
  const labels = {due:'截止时间',end:'结束时间',identity:'任务身份',rules:'课程规则',completion:'完成状态',requirements:'任务要求'};
  function groupedIssues(items, renderItem) {
    const groups = new Map();
    for (const item of items) { const key = item.task_id || item.id; if (!groups.has(key)) groups.set(key, []); groups.get(key).push(item); }
    return [...groups].map(([key, issues]) => `<section class="assistant-task-issues"><h3>${escape(job.task_titles?.[key] || '待核查事项')}</h3>${issues.map(renderItem).join('')}</section>`).join('');
  }
  function diagnostics(report) {
    const rejected = new Map();
    for (const item of report.rejected || []) { if (!rejected.has(item.message)) rejected.set(item.message, []); rejected.get(item.message).push(item); }
    const warnings = [...new Set(job.ai_result?.warnings || [])], failed = (job.sources || []).filter(source => source.status !== 'read'), platforms = new Map();
    for (const source of failed) { let host; try { host = new URL(source.url).hostname; } catch { host = '其他来源'; } if (!platforms.has(host)) platforms.set(host, []); platforms.get(host).push(source); }
    if (!rejected.size && !warnings.length && !failed.length) return '';
    return `<details class="assistant-diagnostics"><summary>核查详情 · ${failed.length} 个来源未读取 · ${(report.rejected || []).length} 项候选未应用</summary>${[...platforms].map(([host, sources]) => `<details><summary>${escape(host)} · ${sources.length} 个来源未读取</summary>${sources.map(source => `<p><a href="${escape(source.url)}" target="_blank" rel="noopener noreferrer">${escape(source.url)}</a><br>${escape(source.message)}</p>`).join('')}</details>`).join('')}${[...rejected].map(([message, items]) => `<details><summary>候选未应用 × ${items.length}：${escape(message)}</summary>${items.map(item=>`<p>${escape(job.task_titles?.[item.task_id] || item.task_id || '未识别事项')}${item.field ? ' · '+escape(item.field) : ''}</p>`).join('')}</details>`).join('')}${warnings.map(warning => `<p>${escape(warning)}</p>`).join('')}</details>`;
  }
  function renderJob(next) {
    job = next;
    if (!job) { content.textContent = '尚无 AI 检索记录。到课程检索页点击“更新检索”。'; send.disabled = true; return; }
    const report = job.report || {}, unresolved = (report.conflicts || []).filter(c => !c.resolved), signature = JSON.stringify(job);
    panel.querySelector('#assistantBadge').textContent = job.status === 'running' || job.chat_busy ? '进行中' : unresolved.length ? String(unresolved.length) : '';
    send.disabled = job.status === 'running' || job.chat_busy;
    if (signature === lastRendered) return;
    lastRendered = signature;
    const scroll = content.scrollTop, atBottom = content.scrollHeight - content.clientHeight - scroll < 30;
    content.innerHTML = `${job.instruction_versions ? `<p>本轮指示 · 总体 ${escape(job.instruction_versions.overall_plan_version.slice(0,12))} · 课程 ${escape(job.instruction_versions.course_requirements_version.slice(0,12))}</p>` : ''}<p class="assistant-progress">${escape(job.message)}<br>来源 ${job.completed} / ${job.total}</p>${job.status === 'running' ? '<button class="assistant-cancel">取消检索</button>' : ''}
      ${(report.changes || []).map(c => `<details><summary>${c.type === 'added' ? '新增' : '更新'} · ${escape(c.title)}</summary>${c.fields.map(f => `<p>${escape(labels[f] || f)}：${escape(JSON.stringify(c.before?.[f] ?? null))} → ${escape(JSON.stringify(c.after?.[f] ?? null))}</p>`).join('')}</details>`).join('')}
      ${groupedIssues(unresolved, c => `<article class="assistant-conflict"><strong>${escape(labels[c.field] || c.field || '待核查')}</strong><p>${escape(c.message)}</p>${c.source_url ? `<a target="_blank" rel="noopener noreferrer" href="${escape(c.source_url)}">查看来源 ↗</a>` : ''}${(c.offers || []).map((o, i) => `<div><p>${escape(JSON.stringify(o.value))}</p><a href="${escape(o.source_url)}" target="_blank" rel="noopener noreferrer">来源 ↗</a><blockquote>${escape(o.evidence)}</blockquote><button data-conflict="${escape(c.id)}" data-selection="${i}">采用此来源值</button></div>`).join('')}<button data-conflict="${escape(c.id)}" data-selection="keep">保留当前记录</button></article>`)}
      ${groupedIssues((report.notices || []).filter(n=>!n.resolved), n => `<article class="assistant-notice"><p>${escape(n.message)}</p>${n.source_url ? `<a href="${escape(n.source_url)}" target="_blank" rel="noopener noreferrer">检查平台 ↗</a>` : ''}<button data-conflict="${escape(n.id)}" data-selection="keep">已复核，保留个人状态</button></article>`)}
      ${[...(report.conflicts || []), ...(report.notices || [])].some(issue=>issue.resolved) ? `<details><summary>已处理提醒 · ${[...(report.conflicts || []), ...(report.notices || [])].filter(issue=>issue.resolved).length}</summary>${groupedIssues([...(report.conflicts || []), ...(report.notices || [])].filter(issue=>issue.resolved), issue=>`<p>${escape(issue.message)}${issue.resolution_carried ? '（沿用此前处理结果）' : ''}</p>`)}</details>` : ''}
      ${diagnostics(report)}
      ${(job.messages || []).map((m, index) => index === 0 && m.role === 'assistant' ? `<details><summary>检索反馈</summary><p>以下为检索结束时的反馈；当前处理状态以上方为准。</p><p>${escape(m.content)}</p></details>` : `<div class="assistant-message ${m.role === 'user' ? 'from-user' : ''}"><b>${m.role === 'user' ? '你' : '检索助手'}</b><p>${escape(m.content)}</p></div>`).join('')}${job.chat_busy ? '<p>AI 正在回复…</p>' : ''}`;
    content.querySelector('.assistant-cancel')?.addEventListener('click', () => act('cancel', {id:job.id}));
    content.querySelectorAll('[data-conflict]').forEach(button => button.onclick = () => act('resolve', {id:job.id, conflict_id:button.dataset.conflict, selection:button.dataset.selection === 'keep' ? 'keep' : Number(button.dataset.selection)}));
    content.scrollTop = atBottom ? content.scrollHeight : scroll;
    if (job.status !== 'running' && job.id !== lastFinished) {
      lastFinished = job.id;
      if (unresolved.length || report.notices?.length || job.status === 'failed') open(true);
    }
  }
  async function refreshData(){
    if(!job || job.status!=='finished' || refreshing || stateWrites || document.querySelector('dialog[open]') || (typeof pendingStates!=='undefined' && pendingStates.size))return;
    const version=JSON.stringify([job.id,job.report?.changes,job.report?.conflicts]);
    if(version===refreshVersion || typeof S==='undefined' || !S)return;
    refreshing=true;
    try{
      const response=await fetch('/api/data');if(!response.ok)throw Error('刷新失败');const next=await response.json();
      if(stateWrites || document.querySelector('dialog[open]') || (typeof pendingStates!=='undefined' && pendingStates.size))return;
      const x=window.scrollX,y=window.scrollY;S=next;
      if(typeof renderKeepingPosition==='function')renderKeepingPosition();else{render();window.scrollTo(x,y)}
      refreshVersion=version;
    }finally{refreshing=false}
  }
  async function act(path, body) {
    panel.querySelector('.assistant-error').textContent = '';
    try { renderJob(await request(path, body)); await refreshData(); }
    catch (error) { panel.querySelector('.assistant-error').textContent = error.message; }
  }
  panel.querySelector('form').onsubmit = async event => {
    event.preventDefault();
    if (!job || send.disabled || !input.value.trim()) return;
    const text = input.value;
    send.disabled = true;
    try { renderJob(await request('messages', {id:job.id, content:text})); input.value = ''; }
    catch (error) { panel.querySelector('.assistant-error').textContent = error.message; send.disabled = false; }
  };
  async function poll() {
    if (polling) return;
    polling = true;
    try {
      renderJob(await request(selectedRecord?'runs/'+selectedRecord:'latest'));
      await refreshData();
      const records=await request('recent');
      const signature=JSON.stringify(records);
      if(historySelect.dataset.records!==signature){historySelect.dataset.records=signature;historySelect.innerHTML='<option value="">最新检索</option>'+records.map(r=>`<option value="${escape(r.id)}">${escape(new Date(r.started_at).toLocaleString('zh-CN',{timeZone:'America/Los_Angeles'}))} · ${escape(r.course_ids.join(', '))}${r.unresolved?' · '+r.unresolved+' 项待处理':''}</option>`).join('');historySelect.value=selectedRecord}
    }
    catch (error) { panel.querySelector('.assistant-error').textContent = error.message + '；后端更新后请重启本地服务。'; }
    finally { polling = false; setTimeout(poll, job?.status === 'running' || job?.chat_busy ? 1500 : 5000); }
  }
  window.UWMasterAssistant = {show:next => { selectedRecord='';historySelect.value='';renderJob(next);open(true); }, request};
  if(typeof render==='function' && typeof list==='function'){
    const saveState=state;state=async function(...args){stateWrites++;try{return await saveState(...args)}finally{stateWrites--}};
    const panelRender=render,taskList=list;
    list=function(){return taskList().filter(t=>!['cancelled','excluded'].includes(t.lifecycle))};
    render=function(){panelRender();const reviews=S.tasks.filter(t=>t.needs_review && !['cancelled','excluded'].includes(t.lifecycle) && (course==='all'||t.course_id===course));if(!reviews.length)return;const banner=document.createElement('div');banner.className='review-banner';banner.innerHTML='<strong>需要复核 · '+reviews.length+' 项</strong><p>完成记录保留。请查看检索助手中的来源冲突或新增要求。</p>'+reviews.map(t=>'<button data-review-task="'+escape(t.id)+'">'+escape(t.title)+'</button>').join('');document.querySelector('.todo-scroll')?.prepend(banner);banner.querySelectorAll('[data-review-task]').forEach(b=>b.onclick=()=>detail(b.dataset.reviewTask));};
  }
  poll();
})();
