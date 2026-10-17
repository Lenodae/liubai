'use strict';
(() => {
  const el = (id) => document.getElementById(id);
  const ex = { generation:0, id: null, owner: null, data: null, tab: 'plan', busy: false, pending: null, timer: null, draft: null, draftBaseline: '', entry: null, stash: null, dirty: false, dirtyForms: new Set(), completionMode: null };
  const dialog = el('execution-dialog');
  const minute = (n) => n === null ? '未记录' : `${n} 分钟${n >= 60 ? `（${Number((n / 60).toFixed(2))} 小时）` : ''}`;
  const optional = (id) => el(id).value === '' ? null : Number(el(id).value);
  const target = (id) => el(id).value || null;
  const today = () => { const d = new Date(); return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };
  const button = (name, fn, kind = 'secondary') => { const b = text('button', name, kind); b.type = 'button'; b.addEventListener('click', fn); return b; };
  const notice = (s = '') => { el('ex-notice').textContent = s; };
  function tab(name) {
    ex.tab = name;
    if(dialog.open && ex.id)window.LoadWorkspace?.dialogOpened(ex.id,name);
    document.querySelectorAll('[data-ex-tab]').forEach((b) => { b.classList.toggle('active', b.dataset.exTab === name); b.setAttribute('aria-current', b.dataset.exTab === name ? 'page' : 'false'); });
    document.querySelectorAll('[data-ex-panel]').forEach((p) => { p.hidden = p.dataset.exPanel !== name; });
  }
  document.querySelectorAll('[data-ex-tab]').forEach((b) => b.addEventListener('click', () => tab(b.dataset.exTab)));
  function freeze(value) {
    ex.busy = value;
    dialog.querySelectorAll('input,textarea,select,button').forEach((item) => { item.disabled = value; });
    el('ex-retry').disabled = false;
  }
  function setOptions(id, includeParent = true) {
    const select = el(id); const old = select.value;
    select.replaceChildren();
    if (includeParent) select.append(new Option(id === 'ex-time-target' ? '任务本身（不属于子步骤的额外投入）' : '整个任务', ''));
    ex.data.steps.forEach((s, i) => select.append(new Option(`${i + 1}. ${s.title}`, s.id)));
    if ([...select.options].some((o) => o.value === old)) select.value = old;
  }
  function standard() {
    if (!ex.data) return;
    const s = ex.data.steps.find((item) => item.id === target('ex-complete-target'));
    const total = s ? s.actual_minutes : ex.data.summary.actual_minutes;
    el('ex-completion-standard').textContent = `完成标准：${s ? s.criterion : ex.data.profile.criterion || ex.data.task.description || '请核对整个任务是否已达到你的目标。'}\n已记录：${minute(total)}。${(s || ex.data.task).status === 'completed' ? '修改耗时请前往账本。' : '只补漏记的部分。'}`;
  }
  function syncCompletionMode(force = false) {
    if (!ex.data) return;
    const stepId = target('ex-complete-target');
    const step = ex.data.steps.find((s) => s.id === stepId);
    const edit = (step || ex.data.task).status === 'completed';
    const record = step ? step.completion : ex.data.completion;
    if (!force && ex.completionMode?.stepId === stepId && ex.completionMode.edit === edit) return;
    ex.completionMode = {stepId, edit, eventId:record?.event_id ?? null};
    el('ex-complete-heading').textContent = edit ? '编辑完成记录' : '登记完成';
    el('ex-complete-submit').textContent = edit ? '保存修改' : '确认完成';
    el('ex-complete-new-fields').hidden = edit;
    el('ex-complete-edit-help').hidden = !edit;
    el('ex-complete-record-meta').textContent = edit ? (record?.completed_at ? `原完成时间：${new Date(record.completed_at).toLocaleString('zh-CN', {hour12:false})}` : '这是一条旧完成记录，未记录原完成时间。') : '';
    el('ex-complete-note').value = edit ? record?.note || '' : '';
    el('ex-complete-link').value = edit ? record?.link || '' : '';
    el('ex-extra').value = '';el('ex-complete-verified').checked = false;el('ex-allow-unfinished').checked = false;
  }
  function chooseCompletion(stepId) {
    if (ex.dirtyForms.has('ex-complete-form') && !confirm('完成说明有未保存修改，确认放弃并切换记录？')) {
      el('ex-complete-target').value = ex.completionMode?.stepId || '';return;
    }
    ex.dirtyForms.delete('ex-complete-form');ex.dirty = ex.dirtyForms.size > 0;
    el('ex-complete-target').value = stepId || '';syncCompletionMode(true);standard();
    el('ex-complete-note').focus();
  }
  function renderSummary() {
    const d = ex.data;
    el('ex-title').textContent = d.task.title;
    el('ex-subtitle').textContent = `${labels[d.task.status]} · 完成由你确认，投入由记录累积`;
    el('ex-summary').replaceChildren();
    const rows = [ ['每周计划投入', d.task.weekly_minutes === null ? '未估计' : `${d.task.weekly_minutes} 分钟 / 周`, '计划与实际分开'], ['剩余预计耗时', d.analysis.remaining_low === null ? '待估计' : `${d.analysis.remaining_low}–${d.analysis.remaining_high} 分钟`, '未知步骤不会当作零'], ['已记录实际投入', minute(d.summary.actual_minutes), d.summary.time_verified ? '你已确认记录完整' : '记录完整性待确认'] ];
    rows.forEach(([title, value, note]) => { const card = text('div', '', 'ex-stat'); card.append(text('small', title), text('strong', value), text('small', note)); el('ex-summary').append(card); });
    el('ex-analysis').replaceChildren(text('p', d.analysis.explanation, 'ex-callout'));
    d.analysis.warnings.forEach((s) => el('ex-analysis').append(text('p', s, 'ex-muted')));
    el('ex-provider').textContent = d.provider.configured ? `${d.provider.name} · ${d.provider.model} · 已配置` : '尚未配置密钥。点击“设置 / 验证 API Key”即可配置，手工拆分可直接使用。';
    const p = d.profile;
    el('ex-ai-preview').textContent = JSON.stringify({任务名称:d.task.title,说明:d.task.description,每周计划分钟:d.task.weekly_minutes,完成标准:p.criterion,已有基础:p.foundation,约束:p.constraints,目标日期:p.deadline,可用总分钟:p.available_minutes,已有步骤:d.steps.map((s) => ({名称:s.title,完成标准:s.criterion,状态:labels[s.status]}))}, null, 2);
  }
  function renderSteps() {
    const box = el('ex-steps'); box.replaceChildren();
    if (!ex.data) return;
    const query = el('ex-step-search').value.trim().toLocaleLowerCase();
    const visible = ex.data.steps.map((s, i) => ({s, i}))
      .filter(({s}) => !query || `${s.title}\n${s.criterion}`.toLocaleLowerCase().includes(query))
      .sort((a, b) => Number(a.s.status === 'completed') - Number(b.s.status === 'completed') || a.i - b.i);
    el('ex-step-count').textContent = `显示 ${visible.length} / ${ex.data.steps.length} 个步骤 · 已完成的自动排在末尾`;
    el('ex-step-hint').textContent = ex.data.summary.all_steps_completed ? '步骤已全部完成。请核对右侧标准，再确认整个任务完成。' : '完成必要的前置步骤后，再开始下一步。父任务暂停时，步骤随任务暂停。';
    if (!ex.data.steps.length) box.append(text('p', '还没有步骤。去“分析与拆分”保存并采纳一份草稿。', 'ex-muted'));
    if (ex.data.steps.length && !visible.length) box.append(text('p', '没有找到匹配的步骤，试试其他关键词或清空搜索。', 'ex-muted'));
    visible.forEach(({s, i}) => {
      const item = text('article', '', 'ex-step'); item.dataset.stepId = s.id;
      item.append(text('span', s.effective_status === 'paused' && s.status !== 'paused' ? '随任务暂停' : labels[s.effective_status], 'ex-status'), text('h4', `${i + 1}. ${s.title}`), text('p', `完成标准：${s.criterion}`), text('p', `预计 ${s.low === null ? '未知' : `${s.low}–${s.high} 分钟`} · 实际 ${minute(s.actual_minutes)}${s.time_verified ? ' · 已核对' : ''}`));
      if (s.depends.length) item.append(text('p', `前置步骤：${s.depends.map((id) => ex.data.steps.find((v) => v.id === id)?.title || '未知').join('、')}`));
      const actions = text('div', '', 'ex-actions');
      if (s.status === 'completed') {
        if (s.completion?.note) item.append(text('p', `完成说明：${s.completion.note}`));
        actions.append(button('编辑完成记录', () => chooseCompletion(s.id)), button('撤销完成', () => { if (confirm('撤销完成并保留已登记的时间？')) send('undo', { step_id: s.id }); }));
      }
      else {
        actions.append(button('开始', () => send('step_status', { step_id: s.id, status: 'in_progress' })), button('暂停', () => send('step_status', { step_id: s.id, status: 'paused' })), button('登记完成', () => chooseCompletion(s.id)));
        actions.append(button('放弃', () => { if (confirm('放弃此步骤可能影响任务目标，仍然保留它的耗时记录。确认放弃？')) send('step_status', { step_id: s.id, status: 'abandoned' }); }));
      }
      actions.append(button('记一次时间', () => { tab('time'); clearEntry(); el('ex-time-target').value = s.id; el('ex-time-minutes').focus(); })); item.append(actions); box.append(item);
    });
    const actions = text('div', '', 'ex-actions');
    if (ex.data.task.status === 'completed') actions.append(button('编辑整个任务完成记录', () => chooseCompletion(null)), button('撤销整个任务完成', () => send('undo', { step_id: null })));
    else if (ex.data.task.status !== 'in_progress') actions.append(button('开始 / 恢复父任务', async () => {
      try { await api(`/api/tasks/${ex.id}`, { method:'PATCH', body:{version:ex.data.task.version,status:'in_progress'} }); await refresh(); await loadTasks(); }
      catch (error) { showError('ex-error', error.message); }
    }));
    box.append(actions);
  }
  el('ex-step-search').addEventListener('input', renderSteps);
  el('ex-step-search-clear').addEventListener('click', () => { el('ex-step-search').value = ''; renderSteps(); el('ex-step-search').focus(); });
  function clearEntry() {
    ex.entry = null; el('ex-time-form').reset(); el('ex-time-date').value = today(); el('ex-time-heading').textContent = '记录一次实际投入';
  }
  function renderEntries() {
    const box = el('ex-entries'); box.replaceChildren();
    if (!ex.data.entries.length) box.append(text('p', '还没有记录实际投入。未记录不等于花了 0 分钟。', 'ex-muted'));
    ex.data.entries.forEach((entry) => {
      const row = text('article', '', 'ex-entry'); row.dataset.entryId = entry.id;
      const name = ex.data.steps.find((s) => s.id === entry.step_id)?.title || '任务本身';
      row.append(text('strong', `${entry.minutes} 分钟`), text('p', `${entry.date} · ${name}`), text('p', entry.note));
      const actions = text('div', '', 'ex-actions');
      actions.append(button('修改', () => { ex.entry = entry; el('ex-time-target').value = entry.step_id || ''; el('ex-time-date').value = entry.date; el('ex-time-minutes').value = entry.minutes; el('ex-time-note').value = entry.note; el('ex-time-heading').textContent = '修改这一次投入'; el('ex-time-minutes').focus(); }), button('删除', () => { if (confirm('删除这条时间记录？合计会重新计算，变更历史仍保留。')) send('time_delete', {entry_id:entry.id,entry_version:entry.version}); }));
      row.append(actions);box.append(row);
    });
  }
  function renderHistory() {
    const box = el('ex-history');box.replaceChildren();
    const kinds = {complete:'确认完成',completion_edit:'修改完成记录',undo:'撤销完成',time_add:'新增耗时',time_edit:'修改耗时',time_delete:'删除耗时',step_status:'步骤状态变化',verify_time:'核对耗时完整性',task_trash:'移入回收站',task_restore:'从回收站恢复'};
    if (!ex.data.history.length) box.append(text('p', '开始执行后，这里会留下你的足迹。', 'ex-muted'));
    ex.data.history.forEach((event) => {
      const row = text('article', '', 'ex-history-item'); const d = event.data;
      row.append(text('strong', `${kinds[event.kind] || event.kind} · ${ex.data.steps.find((s) => s.id === event.step_id)?.title || '整个任务'}`), text('time', new Date(event.at).toLocaleString('zh-CN')));
      if (d.note) row.append(text('p', d.note));
      if (d.link) { const a = text('a', '查看成果'); a.href = d.link; a.target = '_blank'; a.rel = 'noopener noreferrer'; row.append(a); }
      if (d.minutes) row.append(text('p', `${d.date} · ${d.minutes} 分钟`));
      if (event.kind === 'completion_edit') {
        row.append(text('p', `完成说明：${d.before.note || '未填写'} → ${d.after.note || '未填写'}`), text('p', `成果链接：${d.before.link || '未填写'} → ${d.after.link || '未填写'}`));
      } else if (d.before) row.append(text('p', `${d.before.minutes} 分钟 → ${d.after ? d.after.minutes + ' 分钟' : '已删除'}；${d.before.note || '无备注'} → ${d.after?.note || '无备注'}`));
      if (d.from) row.append(text('p', `${labels[d.from]} → ${labels[d.to] || '完成'}`));
      if (event.kind === 'verify_time') row.append(text('p', d.verified ? '已确认记录完整' : '恢复待确认'));
      box.append(row);
    });
  }
  function renderDrafts() {
    const box = el('ex-draft-list');box.replaceChildren();
    ex.data.drafts.forEach((d, i) => box.append(button(`${d.source}草稿 ${ex.data.drafts.length-i}${d.applied ? ' · 已采纳' : d.stale ? ' · 待复核' : ''}`, () => {
      if (ex.draftBaseline !== JSON.stringify(readNodes()) && !confirm('当前草稿有未保存修改，确认载入另一份草稿？')) return;
      loadDraft(d);
    }, 'secondary ex-draft-chip')));
  }
  function renderRuns() {
    const box = el('ex-runs');box.replaceChildren();
    const names = {queued:'等待生成',running:'正在生成',succeeded:'草稿已就绪',cancelled:'已取消',failed:'生成失败',interrupted:'上次生成中断'};
    ex.data.runs.forEach((r) => {
      const row = text('div', `${names[r.status]}${r.error ? '：'+r.error : ''}`, 'ex-run');
      if (['queued','running'].includes(r.status)) row.append(button('取消生成', () => send('cancel_analysis', {run_id:r.id})));
      box.append(row);
    });
    clearTimeout(ex.timer);
    if (dialog.open && ex.data.runs.some((r) => ['queued','running'].includes(r.status))) ex.timer = setTimeout(poll, 2000);
  }
  async function poll() {
    if (!dialog.open || ex.busy || ex.pending) { if (dialog.open) ex.timer=setTimeout(poll,2000); return; }
    try {
      const id=ex.id, generation=ex.generation;
      const result = await api(`/api/tasks/${id}/workspace`);
      if(id!==ex.id || generation!==ex.generation || !ex.data)return;
      ex.data.runs = result.runs; ex.data.drafts = result.drafts;
      renderRuns();renderDrafts();
    } catch (error) { if (![401,-1].includes(error.status)) { showError('ex-error','分析状态读取失败，可点击载入最新数据重试。'); } }
  }
  function render() {
    renderSummary(); renderSteps(); renderEntries(); renderHistory(); renderDrafts(); renderRuns();
    ['ex-time-target','ex-complete-target'].forEach((id) => setOptions(id));setOptions('ex-estimate-target',false);standard();syncCompletionMode();
  }
  async function refresh() {
    const id=ex.id,generation=ex.generation;
    const data = await api(`/api/tasks/${id}/workspace`);
    if(id!==ex.id || generation!==ex.generation)throw new RequestError('请求已取消。',-1);
    ex.data=data;render();
  }
  async function send(action, data, after) {
    if (ex.busy || ex.pending) return;
    ex.pending = {action,body:{action,version:ex.data.task.version,...data},key:crypto.randomUUID(),after};
    return transmit();
  }
  async function transmit() {
    if (!ex.pending || ex.busy) return;
    const completionContext = {owner:state.user?.id, taskId:ex.id, generation:ex.generation, feedback:window.Encouragement?.context()};
    const packet=ex.pending;freeze(true);showError('ex-error','');notice('');
    try {
      const result=await api(`/api/tasks/${ex.id}/workspace`,{method:'POST',body:packet.body,headers:{'Idempotency-Key':packet.key}});
      ex.data=result;ex.pending=null;render();
      if (packet.after) packet.after(result);
      if (packet.action === 'complete' && completionContext.owner === state.user?.id && completionContext.owner === ex.owner && completionContext.taskId === ex.id && completionContext.generation === ex.generation && dialog.open) {
        try { window.Encouragement?.completed({owner:completionContext.owner, taskId:completionContext.taskId, result, stepId:packet.body.step_id ?? null, host:dialog, context:completionContext.feedback}); } catch { /* Saving remains successful if optional feedback fails. */ }
      }
      notice('已保存。');const savedForm = {profile:'ex-profile-form',draft:'ex-draft-form',time_add:'ex-time-form',time_edit:'ex-time-form',complete:'ex-complete-form',completion_edit:'ex-complete-form',step_status:'ex-estimate-form'}[packet.action];if(savedForm)ex.dirtyForms.delete(savedForm);ex.dirty=ex.dirtyForms.size>0;await loadTasks();
    } catch(error) {
      if (![401,-1].includes(error.status)) showError('ex-error',error.message);
      if (error.status && error.status !== 0 && error.status < 500) ex.pending=null;
    } finally {
      freeze(false);el('ex-retry').hidden=!ex.pending;
      if (ex.pending) { dialog.querySelectorAll('input,textarea,select,button').forEach((item) => { item.disabled=true; });el('ex-retry').disabled=false;el('ex-close').disabled=false; }
    }
  }
  el('ex-retry').addEventListener('click',transmit);
  el('ex-refresh').addEventListener('click',async()=>{try{await refresh();showError('ex-error','');notice('已载入最新版本，表单保留。请核对后再提交。');}catch(e){showError('ex-error',e.message);}});
  function addNode(n={title:'',criterion:'',low:null,high:null,depends:[]}, selected=true) {
    const count=el('ex-draft-nodes').children.length;if(count>=12)return;
    const row=text('div','','ex-node');
    const head=text('div','','ex-node-head');const label=text('label','','ex-check');const check=document.createElement('input');check.type='checkbox';check.checked=selected;check.dataset.field='selected';label.append(check,text('span',`采纳步骤 ${count+1}`));head.append(label);row.append(head);
    const parts=[['title','步骤名称','text',n.title],['criterion','完成标准','text',n.criterion],['low','预计下限（分钟）','number',n.low??''],['high','预计上限（分钟）','number',n.high??''],['depends','前置序号（逗号分隔）','text',n.depends.map((i)=>i+1).join(',')]];
    const main=text('div','','ex-node-fields'),times=text('div','','ex-node-times');
    parts.forEach(([field,name,type,value],i)=>{const wrap=text('div');const id=`ex-node-${count}-${field}`;const label=text('label',name);label.htmlFor=id;const input=document.createElement('input');input.id=id;input.dataset.field=field;input.type=type;input.value=value;if(type==='number'){input.min=0;input.max=525600;input.step=1;}else input.maxLength=field==='title'?120:2000;wrap.append(label,input);(i<2?main:times).append(wrap);});
    row.append(main,times);el('ex-draft-nodes').append(row);
  }
  function readNodes() {
    return [...el('ex-draft-nodes').children].map((row)=>{const value=(key)=>row.querySelector(`[data-field="${key}"]`).value;return {title:value('title'),criterion:value('criterion'),low:value('low')===''?null:Number(value('low')),high:value('high')===''?null:Number(value('high')),depends:value('depends').trim()?value('depends').split(/[,，]/).map((n)=>Number(n.trim())-1):[]};});
  }
  function loadDraft(d=null) {
    ex.draft=d;el('ex-draft-nodes').replaceChildren();(d?d.nodes:[{title:'',criterion:'',low:null,high:null,depends:[]}]).forEach((n)=>addNode(n));ex.draftBaseline=JSON.stringify(readNodes());
    el('ex-draft-label').textContent=d?`${d.source}草稿 · 第 ${d.revision} 版${d.applied?' · 已采纳，若要补充请新建草稿':d.stale?' · 任务有变化，请复核并保存后再采纳':''}${d.rationale?'\n'+d.rationale:''}`:'正在编辑一份新的手工草稿';
  }
  el('ex-add-node').addEventListener('click',()=>{addNode();ex.dirtyForms.add('ex-draft-form');ex.dirty=true;});
  el('ex-new-draft').addEventListener('click',()=>{if(confirm('新建空白草稿？当前未保存的草稿输入将清空。'))loadDraft();});
  el('ex-draft-form').addEventListener('submit',(e)=>{e.preventDefault();send('draft',{nodes:readNodes(),...(ex.draft?{draft_id:ex.draft.id,revision:ex.draft.revision}:{})},(r)=>loadDraft(ex.draft?r.drafts.find((d)=>d.id===ex.draft.id):r.drafts[0]));});
  el('ex-apply').addEventListener('click',()=>{
    if(!ex.draft || JSON.stringify(readNodes())!==ex.draftBaseline){showError('ex-error','请先保存当前草稿，再采纳。');return;}
    const selected=[...el('ex-draft-nodes').children].flatMap((row,i)=>row.querySelector('[data-field="selected"]').checked?[i]:[]);
    if(confirm(`采纳 ${selected.length} 个步骤？将追加到当前任务，保留原有步骤。`))send('apply',{draft_id:ex.draft.id,revision:ex.draft.revision,selected},()=>tab('steps'));
  });
  el('ex-profile-form').addEventListener('submit',(e)=>{e.preventDefault();send('profile',{criterion:el('ex-criterion').value,foundation:el('ex-foundation').value,constraints:el('ex-constraints').value,deadline:el('ex-deadline').value,available_minutes:optional('ex-available')});});
  el('ex-time-form').addEventListener('submit',(e)=>{e.preventDefault();send(ex.entry?'time_edit':'time_add',{step_id:target('ex-time-target'),minutes:Number(el('ex-time-minutes').value),date:el('ex-time-date').value,note:el('ex-time-note').value,...(ex.entry?{entry_id:ex.entry.id,entry_version:ex.entry.version}:{})},clearEntry);});
  el('ex-time-cancel').addEventListener('click',clearEntry);
  el('ex-verify').addEventListener('click',()=>send('verify_time',{step_id:null,verified:true}));
  el('ex-complete-target').addEventListener('change',()=>chooseCompletion(target('ex-complete-target')));
  el('ex-complete-form').addEventListener('submit',(e)=>{
    e.preventDefault();const data={step_id:target('ex-complete-target'),note:el('ex-complete-note').value,link:el('ex-complete-link').value};
    if(ex.completionMode?.edit) send('completion_edit',{...data,event_id:ex.completionMode.eventId});
    else send('complete',{...data,extra_minutes:optional('ex-extra'),date:el('ex-complete-date').value,verified:el('ex-complete-verified').checked,allow_unfinished:el('ex-allow-unfinished').checked});
  });
  el('ex-complete-edit-time').addEventListener('click',()=>tab('time'));
  el('ex-estimate-target').addEventListener('change',()=>{const s=ex.data.steps.find((s)=>s.id===target('ex-estimate-target'));el('ex-estimate-low').value=s?.low??'';el('ex-estimate-high').value=s?.high??'';});
  el('ex-estimate-form').addEventListener('submit',(e)=>{e.preventDefault();send('step_status',{step_id:target('ex-estimate-target'),low:optional('ex-estimate-low'),high:optional('ex-estimate-high')});});
  el('ex-generate').addEventListener('click',()=>{if(!ex.data.provider.configured){showError('ex-error','请先点击“设置 / 验证 API Key”填写并验证密钥。');window.DeepSeekSettings.open();return;}if(!el('ex-ai-consent').checked){showError('ex-error','请先查看将发送的内容并勾选同意。');return;}send('analyze',{consent:true},()=>{el('ex-ai-consent').checked=false;});});
  dialog.addEventListener('input',(event)=>{if(event.target.id==='ex-complete-target')return;const form=event.target.closest('form');if(form){ex.dirtyForms.add(form.id);ex.dirty=true;}});
  function close() {
    if(ex.busy)return;
    if((ex.dirty||ex.pending)&&!confirm(ex.pending?'保存结果尚未确认。返回后请检查账本，避免重复登记。确认返回？':'有未保存的输入，确认返回清单？'))return;
    window.Encouragement?.dismiss();
    ex.generation+=1;clearTimeout(ex.timer);dialog.close();ex.id=null;ex.pending=null;ex.draft=null;ex.dirty=false;ex.stash=null;window.LoadWorkspace?.dialogClosed();
  }
  el('ex-close').addEventListener('click',close);dialog.addEventListener('cancel',(e)=>{e.preventDefault();close();});
  window.addEventListener('beforeunload',(e)=>{if(dialog.open&&(ex.dirty||ex.pending)){e.preventDefault();e.returnValue='';}});
  function snapshotForms() { return [...dialog.querySelectorAll('input,textarea,select')].filter((n)=>n.id).map((n)=>({id:n.id,value:n.value,checked:n.checked})); }
  async function open(id, section='plan') {
    if(state.busy || ex.busy)return;
    const focusContext={owner:state.user?.id,epoch:state.epoch};
    if(dialog.open && ex.id===id){tab(section);window.OverviewFocus?.remember(ex.data?.task,focusContext);return;}
    if(dialog.open && (ex.dirty||ex.pending) && !confirm('当前任务有未保存输入，确认放弃并打开其他任务？')){window.LoadWorkspace?.dialogOpened(ex.id,ex.tab);return;}
    ex.generation+=1;
    if(el('task-dialog').open && state.baseline!==JSON.stringify(readRaw()) && !confirm('任务基本信息有未保存修改，确认放弃并进入分析与执行？'))return;
    window.Encouragement?.dismiss();
    el('task-dialog').close();ex.id=id;ex.owner=state.user?.id;ex.pending=null;ex.entry=null;ex.dirty=false;ex.dirtyForms.clear();freeze(false);showError('ex-error','');notice('');el('ex-retry').hidden=true;el('ex-step-search').value='';
    try {
      await refresh();
      const p=ex.data.profile;['criterion','foundation','constraints','deadline'].forEach((key)=>{el(`ex-${key}`).value=p[key];});el('ex-available').value=p.available_minutes??'';
      el('ex-complete-form').reset();ex.completionMode=null;syncCompletionMode();el('ex-complete-date').value=today();el('ex-ai-consent').checked=false;clearEntry();loadDraft();standard();tab(section);dialog.showModal();renderRuns();window.LoadWorkspace?.dialogOpened(id,section);window.OverviewFocus?.remember(ex.data.task,focusContext);
    }catch(error){if(![401,-1].includes(error.status))toast(error.message,true);}
  }
  function lock() {
    window.Encouragement?.dismiss();
    ex.generation+=1;
    if(dialog.open && ex.owner) ex.stash={owner:ex.owner,id:ex.id,tab:ex.tab,forms:snapshotForms(),nodes:readNodes(),draft:ex.draft,baseline:ex.draftBaseline,entry:ex.entry,pending:ex.pending,dirty:ex.dirty,dirtyForms:[...ex.dirtyForms],completionMode:ex.completionMode};
    ex.completionMode=null;el('ex-complete-record-meta').textContent='';
    clearTimeout(ex.timer);dialog.close();dialog.querySelectorAll('form').forEach((f)=>f.reset());el('ex-step-search').value='';el('ex-step-count').textContent='';['ex-summary','ex-steps','ex-entries','ex-history','ex-draft-list','ex-runs','ex-draft-nodes','ex-ai-preview','ex-draft-label','ex-title','ex-subtitle','ex-completion-standard','ex-analysis','ex-time-target','ex-complete-target','ex-estimate-target'].forEach((id)=>el(id).replaceChildren());ex.data=null;ex.id=null;ex.pending=null;
  }
  async function resume(user) {
    const saved=ex.stash;ex.stash=null;if(!saved || saved.owner!==user.id)return;
    await open(saved.id,saved.tab);if(!ex.data)return;
    ex.draft=saved.draft;ex.draftBaseline=saved.baseline;ex.entry=saved.entry;ex.pending=saved.pending;ex.dirty=saved.dirty;ex.dirtyForms=new Set(saved.dirtyForms);el('ex-draft-nodes').replaceChildren();saved.nodes.forEach((n)=>addNode(n));
    const completionTarget=saved.forms.find((n)=>n.id==='ex-complete-target');if(completionTarget)el('ex-complete-target').value=completionTarget.value;
    syncCompletionMode(true);
    if(saved.completionMode?.stepId===ex.completionMode.stepId && saved.completionMode.edit===ex.completionMode.edit)ex.completionMode.eventId=saved.completionMode.eventId;
    saved.forms.forEach((n)=>{if(el(n.id)){el(n.id).value=n.value;el(n.id).checked=n.checked;}});standard();renderSteps();notice('已恢复本账号未保存的输入，请核对后再提交。');el('ex-retry').hidden=!ex.pending;
  }
  function updateProvider(data) { if(ex.data) { ex.data.provider={name:'DeepSeek',model:data.model,configured:data.configured}; renderSummary(); } }
  window.Execution={open,lock,resume,updateProvider,hasDraft:(user)=>{if(ex.stash && ex.stash.owner!==user.id)ex.stash=null;return Boolean(ex.stash);},isDirty:()=>ex.dirty||Boolean(ex.pending),close};
})();
