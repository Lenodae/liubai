'use strict';
(() => {
  const root = $('load-root');
  const currentMonday = () => { const d = new Date(); d.setHours(12, 0, 0, 0); d.setDate(d.getDate() - (d.getDay() + 6) % 7); return localDate(d); };
  const localDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const monday = (value) => { const d = new Date(`${value}T12:00:00`); if (!Number.isFinite(+d)) throw new Error('请选择有效的日期。'); d.setDate(d.getDate() - (d.getDay() + 6) % 7); return localDate(d); };
  const addDays = (date, count) => { const d = new Date(`${date}T12:00:00`); d.setDate(d.getDate() + count); return localDate(d); };
  const model = { week: currentMonday(), mode: 'week', route: 'overview', base: 'overview', generation: 0, request: 0, data: null, deadlines: null, history: null, preview: null, pending: null, busy: false, refreshQueued: false, dirty: new Set(), planId: null, stash: null, owner: null, timer: null, deadlineRequest: 0, historyRequest: 0 };
  const titles = { overview: ['预算与任务总览', '先看时间和承诺，再决定下一步。'], load: ['负载与建议', '让承诺和可用时间对得上，给变化留出余量。'], deadlines: ['期限检查', '按你实际可用的时间，检查共同截止日期。'], review: ['每周回顾', '看已记录的投入，也看当时的计划。'] };
  const verdicts = { unknown: '信息待补全', conflict: '当前安排有冲突', conditional: '需要留意上界', fits: '当前安排可容纳' };
  const fieldNames = { progress_low: '推进下限', progress_high: '推进上限', maintenance_low: '维护下限', maintenance_high: '维护上限', remaining_low: '目标剩余下限', remaining_high: '目标剩余上限', budget_minutes: '可用预算', buffer_minutes: '留白缓冲', scope_confirmed: '推进与维护口径', plan_confirmed: '计划待重新确认', remaining_confirmed: '目标剩余工作待确认', reservation_minutes: '进行中投入估时', maintenance_active: '是否有独立维护', confirmed: '窗口预算待确认', status: '任务状态', budget: '可用预算', buffer: '留白缓冲', capacity: '预算确认', progress: '推进估时', maintenance: '维护估时', stale: '输入已经过期' };
  const min = window.Duration.format;
  const range = window.Duration.range;
  const btn = (label, fn, style = 'secondary') => { const b = text('button', label, style); b.type = 'button'; b.addEventListener('click', fn); return b; };
  const node = (tag, value = '', className = '') => text(tag, value, className);
  const value = (id) => $(id).value.trim() === '' ? null : Number($(id).value);
  const sameContext = (generation, epoch) => generation === model.generation && epoch === state.epoch && Boolean(state.user);
  const params = () => new URLSearchParams({ week: model.week, mode: model.mode });
  const packet = () => ({ week: model.week, mode: model.mode, fingerprint: model.data?.fingerprint });
  const durationFields = (id, title) => `<fieldset class="duration-field"><legend>${title}</legend><div class="duration-inputs"><label><input id="${id}-hours" type="number" min="0" step="1" inputmode="numeric" placeholder="未知可留空" aria-label="${title}（小时）"><span>小时</span></label><label><input id="${id}-minutes" type="number" min="0" max="59" step="1" inputmode="numeric" placeholder="0–59" aria-label="${title}（分钟）"><span>分钟</span></label></div></fieldset>`;

  root.innerHTML = `
    <section class="load-window" aria-label="分析时间窗口">
      <div><label for="load-week">所在周</label><input id="load-week" type="date" required></div>
      <div><label for="load-mode">计划口径</label><select id="load-mode"><option value="week">整周计划 · 进行中投入</option><option value="remaining">本周剩余时间 · 单独确认</option></select></div>
      <button id="load-refresh" class="secondary" type="button">刷新分析</button>
      <p id="load-window-help" class="load-muted"></p>
    </section>
    <div id="load-status" class="load-notice" role="status" hidden></div>
    <div id="load-problem" class="error" role="alert" hidden></div>
    <div id="load-retry-wrap" class="load-notice" hidden><span>保存结果尚未确认；输入已保留，重试会核对同一次操作。</span><button id="load-retry" type="button" class="secondary">重试同一次保存</button></div>
    <section id="load-summary" class="load-summary" aria-label="预算和负载摘要" aria-live="polite"></section>
    <section id="load-budget-editor" class="budget-inline-editor" aria-labelledby="load-budget-editor-title" hidden>
      <h3 id="load-budget-editor-title">直接调整预算</h3>
      <form id="load-capacity-form" class="load-form"><p id="load-budget-editor-help" class="load-muted">填写这一周真正可支配的时间。留白包含在总预算内，保存后圆盘一起更新。</p>
        <div class="load-grid">${durationFields('load-budget', '可用总预算')}${durationFields('load-buffer', '其中留白缓冲')}</div>
        <p class="duration-help">两格都留空表示未知；不留缓冲填 0。</p>
        <button type="submit" class="primary">保存并更新圆盘</button><span id="load-budget-source" class="load-muted"></span>
      </form>
    </section>
    <section id="load-overview" data-load-panel="overview" class="load-overview-actions"><div><h2>先记下想法，再决定投入</h2><p>想法池只记录可能性。开始投入后，预计时间才进入上面的预算圆盘；暂停或完成后释放占用。下方是正在投入的事情。</p></div><button id="load-open-analysis" type="button" class="secondary">查看负载与建议 ↗</button></section>
    <section data-load-panel="load" hidden>
      <div class="load-card"><div class="load-heading"><div><h2>负载明细</h2><p>仅汇总父任务的未来推进与独立维护；步骤估时不会再次相加。</p></div><button id="load-save-snapshot" type="button" class="secondary">保存这次分析</button></div><div id="load-breakdown"></div><div id="load-unknowns"></div></div>
      <div class="load-card"><h2>调整建议</h2><p class="load-muted">以下建议供你选择，确认采纳之前不会改变任务。</p><div id="load-recommendations"></div></div>
      <div class="load-card"><h2>比较一份调整方案</h2><p class="load-muted">勾选需要调整的任务，再填写这一个窗口的投入。持续暂停会改变任务状态；只将本窗口推进归零不会改变长期状态。</p>
        <form id="load-scenario-form"><label class="load-check"><input id="load-scenario-capacity" type="checkbox">同时调整这个窗口的预算</label><div class="load-grid">${durationFields('load-scenario-budget', '方案总预算')}${durationFields('load-scenario-buffer', '方案缓冲')}</div><div id="load-scenario-rows"></div><button type="submit" class="primary">预览这份方案</button></form>
        <section id="load-preview" class="load-preview" aria-live="polite" hidden></section>
      </div>
      <div class="load-card"><h2>本窗口的调整记录</h2><div id="load-events"></div></div>
    </section>
    <section data-load-panel="deadlines" hidden>
      <div class="load-card"><div class="load-heading"><div><h2>目标剩余工作与共享容量</h2><p>所有目标共用一份时间。目标剩余工作与本周推进不会重复相加。</p></div><button id="load-deadline-refresh" type="button" class="secondary">刷新期限检查</button></div><div id="load-deadline-result" aria-live="polite"></div></div>
      <div class="load-card"><h2>按实际安排填写分段容量</h2><p class="load-muted">每段从上一段结束后的次日开始，末段须到本周日。各段预算与缓冲之和须分别等于本窗口预算与缓冲。其他占用指待检查目标以外的推进和维护，每段只计一次；没有分段时不会按每天平均估算。</p><form id="load-slices-form"><div id="load-slices"></div><div class="load-actions"><button id="load-add-slice" type="button" class="secondary">＋ 增加时间段</button><button type="submit" class="primary">保存分段并检查</button></div></form></div>
    </section>
    <section data-load-panel="review" hidden><div class="load-card"><div class="load-heading"><div><h2>这一周，时间去了哪里</h2><p>按账本实际发生日期归集。修改历史日期后，对应两周的实际投入会更新，已保存计划保留原样。</p></div><button id="load-review-refresh" type="button" class="secondary">刷新回顾</button></div><div id="load-review-content" aria-live="polite"></div></div></section>
  `;
  // Keep this form node across chart refreshes so unsaved inputs and listeners survive.
  const budgetEditor = $('load-budget-editor');
  const planDialog = document.createElement('dialog');
  planDialog.id = 'load-plan-dialog'; planDialog.className = 'load-dialog'; planDialog.setAttribute('aria-labelledby', 'load-plan-title');
  planDialog.innerHTML = `<div class="load-heading"><div><span class="section-kicker">PLAN THIS WINDOW</span><h2 id="load-plan-title">确认任务投入</h2></div><button id="load-plan-close" type="button" class="icon-button" aria-label="关闭投入计划">×</button></div><form id="load-plan-form"><p id="load-plan-context" class="load-muted"></p><p id="load-plan-reference" class="load-notice"></p><fieldset><legend>本窗口的未来推进（分钟）</legend><div class="load-grid"><div><label for="load-progress-low">下限</label><input id="load-progress-low" type="number" min="0" step="1" placeholder="未知留空"></div><div><label for="load-progress-high">上限</label><input id="load-progress-high" type="number" min="0" step="1" placeholder="精确估时填相同值"></div></div></fieldset><fieldset><legend>独立维护（分钟）</legend><label class="load-check"><input id="load-maintenance-active" type="checkbox">这项任务有独立维护投入（暂停或完成后仍保留）</label><div class="load-grid"><div><label for="load-maintenance-low">下限</label><input id="load-maintenance-low" type="number" min="0" step="1" placeholder="无维护填 0"></div><div><label for="load-maintenance-high">上限</label><input id="load-maintenance-high" type="number" min="0" step="1" placeholder="无维护填 0"></div></div></fieldset><label class="load-check"><input id="load-scope-confirmed" type="checkbox">我确认推进与维护已经分开填写，没有重复计入</label><fieldset><legend>整个目标的剩余工作（可选，分钟）</legend><p class="load-muted">用于期限检查：从现在到完成目标还需要多少工作。它不等同于本窗口推进，也不加入周负载求和。</p><div class="load-grid"><div><label for="load-remaining-low">剩余下限</label><input id="load-remaining-low" type="number" min="0" step="1" placeholder="未知留空"></div><div><label for="load-remaining-high">剩余上限</label><input id="load-remaining-high" type="number" min="0" step="1" placeholder="未知留空"></div></div></fieldset><p id="load-plan-error" class="error" role="alert" hidden></p><div class="load-actions"><button id="load-plan-task" type="button" class="secondary">查看任务 / 设置目标日期</button><button type="submit" class="primary">保存并确认投入</button></div></form>`;
  document.body.append(planDialog);

  function message(content = '', bad = false) {
    const id = bad ? 'load-problem' : 'load-status'; $(id).textContent = content; $(id).hidden = !content;
    if (bad && planDialog.open) showError('load-plan-error', content);
  }
  function clearMessages() { message(); message('', true); showError('load-plan-error', ''); }
  function setBusy(busy) {
    model.busy = busy;
    [...root.querySelectorAll('input,select,button'), ...planDialog.querySelectorAll('input,button')].forEach((el) => { el.disabled = busy || Boolean(model.pending); });
    $('load-retry').disabled = busy; $('load-refresh').disabled = busy;
    $('load-plan-close').disabled = busy;
    $('load-retry-wrap').hidden = !model.pending;
    if (!busy && model.refreshQueued && state.user) {
      model.refreshQueued = false;
      const generation = model.generation, epoch = state.epoch;
      queueMicrotask(() => { if (sameContext(generation, epoch)) refresh({canonical:true}); });
    }
  }
  function invalidatePreview() { model.preview = null; $('load-preview').replaceChildren(); $('load-preview').hidden = true; }
  function contextReset() {
    model.generation += 1; model.request += 1; model.deadlineRequest += 1; model.historyRequest += 1;
    model.refreshQueued = false;
    root.insertBefore(budgetEditor, $('load-summary').nextSibling);
    budgetEditor.hidden = true;
    $('load-capacity-form').reset(); $('load-budget-source').textContent = '';
    model.data = null; model.deadlines = null; model.history = null; model.dirty.clear(); model.planId = null;
    invalidatePreview(); planDialog.close(); clearMessages();
    $('load-summary').replaceChildren(node('p', '正在读取这个窗口…', 'load-muted'));
    ['load-breakdown', 'load-unknowns', 'load-recommendations', 'load-scenario-rows', 'load-events', 'load-deadline-result', 'load-slices', 'load-review-content'].forEach((id) => $(id).replaceChildren());
  }
  function dirtyInput(event) {
    const form = event.target.closest('form'); if (!form) return;
    model.dirty.add(form.id);
    if (form.id === 'load-capacity-form') $('load-budget-source').textContent = '输入尚未保存 · 保存后更新圆盘';
    if (form.id === 'load-scenario-form') invalidatePreview();
  }
  root.addEventListener('input', dirtyInput); planDialog.addEventListener('input', dirtyInput);
  function hasUnsaved() { return model.dirty.size > 0 || Boolean(model.pending); }
  function routeUrl(route) { return `#${route}?${params()}`; }
  function navigate(route) {
    if (window.TaskTrash?.deferNavigation(() => navigate(route))) return;
    if (location.hash === routeUrl(route)) { handleRoute(); return; }
    location.hash = routeUrl(route);
  }
  function setRouteHash(route) { history.replaceState(null, '', routeUrl(route)); }
  function dialogOpened(id, section = 'details') { setRouteHash(`task/${encodeURIComponent(id)}/${section}`); }
  function dialogClosed() { setRouteHash(model.base); }
  function openTask(id, section = 'details') { navigate(`task/${encodeURIComponent(id)}/${section}`); }
  function updateHeading(route) {
    if (titles[route]) {
      const [title, description] = titles[route];
      $('page-title').replaceChildren(node('span', title), node('span', '.', 'title-dot'));
      $('page-description').textContent = description; $('breadcrumb-current').textContent = title;
    }
    document.querySelectorAll('[data-route]').forEach((b) => { b.classList.toggle('active', b.dataset.route === route); b.setAttribute('aria-current', b.dataset.route === route ? 'page' : 'false'); });
    if (!route.startsWith('tasks/')) document.querySelectorAll('[data-tab]').forEach((b) => { b.classList.remove('active'); b.setAttribute('aria-current', 'false'); });
    root.querySelectorAll('[data-load-panel]').forEach((p) => { p.hidden = p.dataset.loadPanel !== route; });
    const showTasks = route === 'overview' || route.startsWith('tasks/');
    $('task-section').hidden = !showTasks; $('task-counters').hidden = !route.startsWith('tasks/');
    $('workspace').dataset.page = route;
    $('load-summary').hidden = !['overview', 'load'].includes(route);
    budgetEditor.hidden = !model.data || !['overview', 'load'].includes(route);
  }
  async function handleRoute() {
    if (!state.user) return;
    if (window.TaskTrash?.busy()) {
      const destination = location.hash;
      window.TaskTrash.deferNavigation(() => { location.hash = destination; });
      history.replaceState(null, '', window.TaskTrash.route()); return;
    }
    const parsed = new URL(location.hash.slice(1) || 'overview', 'http://local/');
    let route = decodeURIComponent(parsed.pathname.slice(1));
    const selectedWeek = parsed.searchParams.get('week'), selectedMode = parsed.searchParams.get('mode');
    try {
      const week = selectedWeek ? monday(selectedWeek) : model.week;
      const requestedMode = ['week', 'remaining'].includes(selectedMode) ? selectedMode : model.mode;
      const mode = week === currentMonday() ? requestedMode : 'week';
      if (week !== model.week || mode !== model.mode) {
        if (model.pending || (hasUnsaved() && !confirm('切换时间窗口会放弃当前未保存输入，确定切换吗？'))) { setRouteHash(model.route); return; }
        model.week = week; model.mode = mode; contextReset();
      }
    } catch (error) { message(error.message, true); setRouteHash(model.base); return; }
    $('load-week').value = model.week; $('load-mode').value = model.mode;
    $('load-mode').querySelector('[value=remaining]').disabled = model.week !== currentMonday();
    if (route === 'new' || route.startsWith('task/')) {
      if (!model.data) { setTab('in_progress', false); updateHeading('overview'); await Promise.all([refresh(), loadTasks(false)]); }
      if (!state.user) return;
      if ($('task-dialog').open && (route === 'new' || route.split('/')[1] !== state.editing?.id)) { closeEditor(); if ($('task-dialog').open) { if(state.editing)dialogOpened(state.editing.id); return; } }
      if (route === 'new') { openEditor(); setRouteHash('new'); }
      else {
        const [, id, section = 'details'] = route.split('/');
        if (section === 'details') await fetchEditor(id);
        else await window.Execution.open(id, { analysis: 'plan', ledger: 'time' }[section] || (['plan', 'steps', 'time', 'history'].includes(section) ? section : 'plan'));
      }
      return;
    }
    if (!titles[route] && !/^tasks\/(in_progress|planned|paused|history|trash)$/.test(route)) route = 'overview';
    if ($('task-dialog').open) { closeEditor(); if ($('task-dialog').open) { dialogOpened(state.editing?.id || '', 'details'); return; } }
    if ($('execution-dialog').open) { window.Execution.close(); if ($('execution-dialog').open) return; }
    model.route = model.base = route; setRouteHash(route);
    if (route === 'overview' || route.startsWith('tasks/')) { setTab(route === 'overview' ? 'in_progress' : route.split('/')[1], false); loadTasks(false); }
    updateHeading(route);
    if (!model.data) await refresh();
    else if (route === 'deadlines') await fetchDeadlines();
    else if (route === 'review') await fetchHistory();
  }
  async function enter(user) {
    model.owner = user.id;
    if (model.stash && model.stash.owner !== user.id) model.stash = null;
    model.week = currentMonday(); model.mode = 'week'; contextReset();
    await handleRoute();
  }
  function formSnapshot() { return [...root.querySelectorAll('input,select'), ...planDialog.querySelectorAll('input')].filter((el) => el.id).map((el) => ({ id: el.id, value: el.value, checked: el.checked })); }
  function lock() {
    if (hasUnsaved() && model.owner) model.stash = { owner: model.owner, week: model.week, mode: model.mode, route: model.base, forms: formSnapshot(), dirty: [...model.dirty], pending: model.pending, planId: model.planId, slices: readSlices() };
    clearTimeout(model.timer); model.owner = null; model.pending = null; contextReset(); setBusy(false);
    root.querySelectorAll('form').forEach((f) => f.reset()); planDialog.querySelector('form').reset();
    $('load-window-help').textContent = ''; $('load-budget-source').textContent = ''; $('load-plan-title').textContent = '确认任务投入'; $('load-plan-context').textContent = ''; $('load-plan-reference').textContent = '';
    setRouteHash('overview');
  }
  async function restoreDraft(user) {
    const saved = model.stash; if (!saved || saved.owner !== user.id) return;
    model.stash = null; model.week = saved.week; model.mode = saved.mode; contextReset();
    setRouteHash(saved.route); await handleRoute();
    if (!state.user || state.user.id !== user.id) return;
    if (saved.planId && model.data?.tasks.some((t) => t.id === saved.planId)) openPlan(saved.planId);
    $('load-slices').replaceChildren(); saved.slices.forEach(addSlice);
    saved.forms.forEach((item) => { if ($(item.id)) { $(item.id).value = item.value; $(item.id).checked = item.checked; } });
    model.dirty = new Set(saved.dirty); model.pending = saved.pending;
    if (model.dirty.has('load-capacity-form')) $('load-budget-source').textContent = '输入尚未保存 · 保存后更新圆盘';
    if (model.pending) model.pending.generation = model.generation;
    setBusy(false); message('已恢复本账号的输入。请核对当前窗口；尚未确认的保存可用原请求重试。');
  }
  function invalidate() { invalidatePreview(); model.deadlines = null; model.history = null; if (state.user) refresh({canonical:true}); }
  async function refresh({canonical = false} = {}) {
    if (!state.user || (model.pending && !canonical)) return;
    if (model.busy) { if (canonical) model.refreshQueued = true; return; }
    const request = ++model.request, generation = model.generation, epoch = state.epoch;
    root.setAttribute('aria-busy', 'true');
    try {
      const result = await api(`/api/load/workspace?${params()}`);
      if (!sameContext(generation, epoch) || request !== model.request) return;
      const changed = model.data && model.data.fingerprint !== result.fingerprint;
      model.data = result;
      if (changed) invalidatePreview();
      render(); setBusy(false);
      // A read updates server facts, never the pending mutation or its error/draft.
      if (!canonical && !model.pending) message('', true);
      if (model.route === 'deadlines') await fetchDeadlines();
      if (model.route === 'review') await fetchHistory();
    } catch (error) { if (sameContext(generation, epoch) && ![401, -1].includes(error.status)) message(`分析读取失败：${error.message}`, true); }
    finally { if (request === model.request) root.setAttribute('aria-busy', 'false'); }
  }
  function metric(label, main, detail = '') { const card = node('div', '', 'load-metric'); card.append(node('span', label), node('strong', main)); if (detail) card.append(node('small', detail)); return card; }
  function renderAnalysis(analysis, target, heading) {
    target.replaceChildren(); const status = node('div', '', `load-verdict verdict-${analysis.verdict || 'unknown'}`);
    const feeling = window.LoadFeeling.describe(analysis); status.dataset.loadFeeling = feeling.level;
    const title = node('div', '', 'load-feeling-heading'); title.append(node('span', heading || '当前负载'));
    if (feeling.percent) title.append(node('span', `${feeling.rangeText ? '按上界 ' : ''}${feeling.percent}`, 'load-feeling-percent'));
    status.append(title, node('strong', feeling.label, 'load-feeling-label'), node('p', feeling.message, 'load-feeling-message'));
    if (feeling.rangeText) status.append(node('p', `预计负载 ${feeling.rangeText}，按投入上界提示。`));
    if (analysis.unknown_count) status.append(node('p', `${analysis.unknown_count} 项信息待补全；未知量没有按 0 计算。`));
    if (analysis.deficit_low > 0) status.append(node('p', `保留缓冲至少缺 ${min(analysis.deficit_low)}。`));
    else if (analysis.deficit_high > 0) status.append(node('p', `需求达到上界时，保留缓冲将缺 ${min(analysis.deficit_high)}。`));
    if (analysis.total_budget_deficit > 0) status.append(node('p', `即使用完总预算，仍至少缺 ${min(analysis.total_budget_deficit)}。`));
    status.append(node('p', '时间负载 = 进行中预计投入 ÷ 可安排容量（总预算 − 留白）。', 'load-feeling-basis'));
    target.append(status);
  }
  function render() {
    const data = model.data; if (!data) return;
    const w = data.window, a = data.analysis;
    $('load-window-help').textContent = `${model.week} 至 ${addDays(model.week, 6)} · ${model.mode === 'remaining' ? `从 ${w.as_of ? new Date(w.as_of).toLocaleString('zh-CN', {hour12:false}) : '当前确认时点'} 起的未来剩余安排；整周投入请切换整周查看，不会自动复制到这里。跨日后需重新确认。` : '只有进行中的事情占用本周预算；想法、暂停和结束的事情不占用。长期事项进行期间每周计入，实际耗时单独记录。' }`;
    const focusedBudgetField = budgetEditor.contains(document.activeElement) ? document.activeElement : null;
    const status = node('div'); renderAnalysis(a, status);
    const metrics = node('div', '', 'load-metrics');
    metrics.append(metric('可安排容量', min(a.capacity), `总预算 ${min(w.budget_minutes)} − 留白 ${min(w.buffer_minutes)}`), metric(model.mode === 'week' ? '进行中整周投入' : '进行中剩余投入', range(a.low, a.high), a.unknown_count ? `已知下限 ${min(a.known_low)}，仍有未知项` : model.mode === 'week' ? '进行中的估时 / 已确认窗口计划' : '进行中的推进 + 独立维护'), metric('这周已记录', data.actual?.minutes == null ? '未记录' : min(data.actual.minutes), `${data.actual?.entry_count || 0} 条账本 · ${data.actual?.verified ? '已核对完整性' : '完整性待核对'}`));
    if (!model.dirty.has('load-capacity-form') && model.pending?.formId !== 'load-capacity-form') { window.Duration.fill('load-budget', w.budget_minutes); window.Duration.fill('load-buffer', w.buffer_minutes); }
    $('load-budget-editor-title').textContent = model.mode === 'remaining' ? '调整未来剩余预算' : '直接调整这一周的预算';
    $('load-budget-editor-help').textContent = model.mode === 'remaining' ? '只填当前确认时点之后真正可用的时间。剩余口径单独保存，留白包含在总预算内。' : '填写这一周真正可支配的时间。留白包含在总预算内，保存后圆盘一起更新。';
    $('load-budget-source').textContent = model.dirty.has('load-capacity-form') ? '输入尚未保存 · 保存后更新圆盘' : w.version ? `第 ${w.version} 版 · ${w.confirmed && !w.stale ? '已确认' : w.stale ? '已过期，请重新确认' : '待确认'}` : '这个窗口尚未设置';
    const chart = window.BudgetReservation.render(data, { compact: true, editor: budgetEditor, onEditTask: (task) => task.deleted_at ? navigate('tasks/trash') : task.allocation_source === 'auto' ? openTask(task.id) : openPlan(task.id) });
    $('load-summary').replaceChildren(status, metrics, chart);
    budgetEditor.hidden = !['overview', 'load'].includes(model.base);
    if (focusedBudgetField?.isConnected && !focusedBudgetField.disabled) focusedBudgetField.focus({ preventScroll: true });
    renderBreakdown(); renderRecommendations(); renderEvents();
    if (!model.dirty.has('load-scenario-form') && model.pending?.formId !== 'load-scenario-form') renderScenario();
    clearTimeout(model.timer);
    const expiry = Date.parse(data.valid_until);
    if (Number.isFinite(expiry)) model.timer = setTimeout(() => { invalidatePreview(); message('时间窗口已变化，请刷新并重新确认剩余安排。'); refresh(); }, Math.min(Math.max(expiry - Date.now() + 100, 1000), 2147483647));
  }
  function renderBreakdown() {
    const container = $('load-breakdown'); container.replaceChildren();
    if (!model.data.tasks.length) container.append(node('p', '还没有任务。先记下一个想法，无需先填完预算。', 'load-muted'), btn('记录一个想法', () => navigate('new')));
    model.data.tasks.forEach((task) => {
      const card = node('article', '', 'load-task-plan'); card.dataset.loadTask = task.id;
      const auto = task.allocation_source === 'auto';
      const active = (task.load_status || task.status) === 'in_progress';
      const head = node('div', '', 'load-heading'); const title = node('div'); title.append(node('h3', task.title), node('span', `${labels[task.status]} · ${!active ? '不占用当前预算' : auto ? '进行中估时 · 自动计入整周' : task.allocation_source === 'manual' ? '采用手工窗口计划' : '本窗口待确认'}`, 'load-muted'));
      head.append(title, btn(task.deleted_at ? '前往回收站' : '确认 / 修改投入', () => openPlan(task.id))); card.append(head);
      const rows = node('dl', '', 'load-values');
      const loadStatus = task.load_status || task.status;
      const countedProgress = loadStatus === 'in_progress';
      const progress = countedProgress ? range(task.progress_low, task.progress_high) : `${min(0)}（当前${labels[task.status]}，不计入）`;
      if (model.mode === 'week' && loadStatus !== task.status) card.append(node('p', `历史计划确认时为${labels[loadStatus]}；当前状态为${labels[task.status]}。`, 'load-muted'));
      const entries = auto ? [['进行中整周投入', min(task.reservation_minutes)], ['时间安排', task.budget_schedule === 'recurring' ? `长期每周 · 从 ${task.budget_week}` : `所选周 · ${task.budget_week}`], ['投入口径', '整个任务的总投入，已纳入本周；步骤与维护不再叠加']] : [['本窗口推进', progress], ['独立维护', !active ? '0 分钟（当前状态不计入）' : task.maintenance_active == null ? '是否维护待确认' : task.maintenance_active ? range(task.maintenance_low, task.maintenance_high) : '未启用']];
      entries.push(['整个目标剩余', range(task.remaining_low, task.remaining_high)], ['本周实际记录', task.actual_minutes == null ? '未记录' : min(task.actual_minutes)]);
      entries.forEach(([label, val]) => rows.append(node('dt', label), node('dd', val)));
      card.append(rows, btn(task.deleted_at ? '前往回收站' : '进入步骤与完成', () => task.deleted_at ? navigate('tasks/trash') : openTask(task.id, 'steps'), 'text-button')); container.append(card);
    });
    const unknown = $('load-unknowns'); unknown.replaceChildren();
    if (model.data.analysis.unknowns?.length) {
      unknown.append(node('h3', '需要补全或确认的信息'));
      model.data.analysis.unknowns.forEach((item) => { const row = node('p', `${item.title || '窗口预算'}：${(item.fields || []).map((f) => fieldNames[f] || f).join('、')}`, 'load-muted'); if (item.task_id) { const task = model.data.tasks.find((task) => task.id === item.task_id); const auto = task?.allocation_source === 'auto'; row.append(btn(task?.deleted_at ? '前往回收站' : auto ? '补充投入估时' : '去确认', () => task?.deleted_at ? navigate('tasks/trash') : auto ? openTask(item.task_id) : openPlan(item.task_id), 'text-button')); } unknown.append(row); });
    }
  }
  function renderRecommendations() {
    const box = $('load-recommendations'); box.replaceChildren();
    const suggestions = model.data.analysis.recommendations || [];
    if (!suggestions.length) box.append(node('p', '目前没有额外调整建议。你仍可以保留缓冲，随实际情况重新确认。', 'load-muted'));
    suggestions.forEach((item) => { const card = node('article', '', 'load-suggestion'); card.append(node('h3', item.title || '核对安排'), node('p', window.Duration.prose(item.reason || '请结合实际情况判断。'))); if (item.task_id) card.append(btn('查看这项投入', () => openPlan(item.task_id), 'text-button')); box.append(card); });
  }
  function openPlan(id) {
    const task = model.data?.tasks.find((t) => t.id === id); if (!task) return;
    if (task.deleted_at) { navigate('tasks/trash'); return; }
    if (model.pending || model.busy) return;
    model.planId = id; model.dirty.delete('load-plan-form');
    $('load-plan-title').textContent = task.title;
    $('load-plan-context').textContent = `${model.week} 这一周 · ${model.mode === 'week' ? '整周' : '剩余'}计划。${task.status !== 'in_progress' ? `当前${labels[task.status]}，保存估时也不占用预算；开始投入后才计入。` : '只有进行中的投入参与当前预算。'}`;
    $('load-plan-reference').textContent = `${task.allocation_source === 'auto' ? `进行中整周投入 ${min(task.reservation_minutes)} 已自动计入；下面保存的手工计划会优先覆盖本窗口，其他周仍按进行中的估时。` : model.mode === 'remaining' ? `预计整周投入 ${min(task.weekly_minutes)}；请只确认当前时点之后的未来投入，整周值不会自动复制。` : `预计每周投入 ${min(task.weekly_minutes)}；进行中且这个窗口已有手工计划时采用手工值。`}${task.deadline ? `目标日期：${task.deadline}。` : '尚未设置目标日期。'}`;
    ['progress-low', 'progress-high', 'maintenance-low', 'maintenance-high', 'remaining-low', 'remaining-high'].forEach((field) => { $(`load-${field}`).value = task[field.replaceAll('-', '_')] ?? ''; });
    $('load-maintenance-active').checked = Boolean(task.maintenance_active); $('load-scope-confirmed').checked = Boolean(task.scope_confirmed && task.plan_confirmed);
    showError('load-plan-error', ''); planDialog.showModal(); $('load-progress-low').focus();
  }
  function closePlan() {
    if (model.busy) return;
    if (model.dirty.has('load-plan-form') && !confirm('投入计划尚未保存，确定关闭吗？')) return;
    model.dirty.delete('load-plan-form'); planDialog.close();
  }
  $('load-plan-close').addEventListener('click', closePlan); planDialog.addEventListener('cancel', (event) => { event.preventDefault(); closePlan(); });
  $('load-plan-task').addEventListener('click', () => { const id = model.planId; closePlan(); if (!planDialog.open) openTask(id, 'plan'); });
  async function save(path, body, formId = null, after = null) {
    if (model.busy || model.pending || !model.data) return;
    model.pending = { path, body: { ...packet(), ...body }, key: crypto.randomUUID(), formId, after, generation: model.generation };
    await transmit();
  }
  async function transmit() {
    const pending = model.pending; if (!pending || model.busy) return;
    const generation = model.generation, epoch = state.epoch; clearMessages(); setBusy(true); model.request += 1; model.deadlineRequest += 1; model.historyRequest += 1;
    // Also replace any read invalidated by this write, even if the reply is lost.
    model.refreshQueued = true;
    try {
      const result = await api(pending.path, { method: 'POST', body: pending.body, headers: { 'Idempotency-Key': pending.key } });
      if (!sameContext(generation, epoch) || model.pending !== pending) return;
      model.pending = null; if (pending.formId) model.dirty.delete(pending.formId); invalidatePreview();
      if (pending.path === '/api/load/deadlines') { model.deadlines = result; model.data.fingerprint = result.fingerprint; renderDeadlines(); }
      else { model.data = result; render(); }
      if (pending.after === 'close-plan') planDialog.close();
      if (pending.after === 'scenario') { model.dirty.delete('load-scenario-form'); renderScenario(); await loadTasks(false); }
      message('已保存。分析已按当前输入更新。');
    } catch (error) {
      if (!sameContext(generation, epoch) || [401, -1].includes(error.status)) return;
      if (error.status > 0 && error.status < 500) model.pending = null;
      message(error.status === 409 ? `${error.message} 当前输入已保留，请先刷新分析，核对后重新提交。` : error.message, true);
    } finally { if (sameContext(generation, epoch)) setBusy(false); }
  }
  $('load-retry').addEventListener('click', transmit);
  $('load-capacity-form').addEventListener('submit', (event) => { event.preventDefault(); save('/api/load/settings', { action: 'capacity', budget_minutes: window.Duration.read('load-budget'), buffer_minutes: window.Duration.read('load-buffer') }, 'load-capacity-form'); });
  $('load-plan-form').addEventListener('submit', (event) => { event.preventDefault(); save('/api/load/settings', { action: 'plan', task_id: model.planId, progress_low: value('load-progress-low'), progress_high: value('load-progress-high'), maintenance_low: value('load-maintenance-low'), maintenance_high: value('load-maintenance-high'), maintenance_active: $('load-maintenance-active').checked, scope_confirmed: $('load-scope-confirmed').checked, remaining_low: value('load-remaining-low'), remaining_high: value('load-remaining-high') }, 'load-plan-form', 'close-plan'); });
  $('load-save-snapshot').addEventListener('click', () => save('/api/load/settings', { action: 'save_snapshot' }));

  function numberField(id, label, initial, parent) { const wrap = node('div'); const l = node('label', label); l.htmlFor = id; const input = document.createElement('input'); input.id = id; input.type = 'number'; input.min = '0'; input.step = '1'; input.value = initial ?? ''; input.placeholder = '未知留空'; wrap.append(l, input); parent.append(wrap); return input; }
  function renderScenario() {
    window.Duration.fill('load-scenario-budget', model.data.window.budget_minutes); window.Duration.fill('load-scenario-buffer', model.data.window.buffer_minutes); $('load-scenario-capacity').checked = false;
    const box = $('load-scenario-rows'); box.replaceChildren();
    model.data.tasks.forEach((task, index) => {
      const row = node('fieldset', '', 'load-scenario-row'); row.dataset.taskId = task.id;
      const legend = node('legend'); const label = node('label', '', 'load-check'); const check = document.createElement('input'); check.type = 'checkbox'; check.id = `load-change-${index}`; check.dataset.change = 'selected'; label.append(check, node('span', task.title)); legend.append(label); row.append(legend);
      const fields = node('div', '', 'load-grid load-grid-four');
      ['progress_low', 'progress_high', 'maintenance_low', 'maintenance_high'].forEach((key) => { const input = numberField(`load-change-${index}-${key}`, fieldNames[key], task[key], fields); input.dataset.change = key; });
      row.append(fields);
      const wrap = node('div'); const stateLabel = node('label', '持续状态变更'); stateLabel.htmlFor = `load-change-${index}-status`; const select = document.createElement('select'); select.id = stateLabel.htmlFor; select.dataset.change = 'status'; select.append(new Option('保持当前状态，只调整这个窗口', ''), new Option('持续暂停这项任务', 'paused'), new Option('持续恢复 / 开始进行', 'in_progress')); wrap.append(stateLabel, select); row.append(wrap);
      const maintenanceWrap = node('div'); const maintenanceLabel = node('label', '独立维护'); maintenanceLabel.htmlFor = `load-change-${index}-maintenance-active`;
      const maintenance = document.createElement('select'); maintenance.id = maintenanceLabel.htmlFor; maintenance.dataset.change = 'maintenance_active'; maintenance.append(new Option('是否有维护：尚未确认', 'unknown'), new Option('有独立维护投入', 'true'), new Option('无独立维护投入', 'false')); maintenance.value = task.maintenance_active == null ? 'unknown' : String(task.maintenance_active); maintenanceWrap.append(maintenanceLabel, maintenance); row.append(maintenanceWrap);
      const scope = node('label', '', 'load-check'); const scopeCheck = document.createElement('input'); scopeCheck.type = 'checkbox'; scopeCheck.id = `load-change-${index}-scope`; scopeCheck.dataset.change = 'scope_confirmed'; scopeCheck.checked = Boolean(task.scope_confirmed && task.plan_confirmed); scope.append(scopeCheck, node('span', '确认这项任务的推进与维护已经分开，没有重复计入')); row.append(scope);
      row.append(btn('仅将本窗口推进归零', () => { check.checked = true; row.querySelector('[data-change="progress_low"]').value = '0'; row.querySelector('[data-change="progress_high"]').value = '0'; model.dirty.add('load-scenario-form'); invalidatePreview(); }, 'text-button'));
      box.append(row);
    });
  }
  function scenarioChanges() {
    const changes = [];
    if ($('load-scenario-capacity').checked) changes.push({ budget_minutes: window.Duration.read('load-scenario-budget'), buffer_minutes: window.Duration.read('load-scenario-buffer') });
    $('load-scenario-rows').querySelectorAll('[data-task-id]').forEach((row) => {
      if (!row.querySelector('[data-change="selected"]').checked) return;
      const change = { task_id: row.dataset.taskId }; const original = model.data.tasks.find((task) => task.id === row.dataset.taskId);
      ['progress_low', 'progress_high', 'maintenance_low', 'maintenance_high'].forEach((key) => { const input = row.querySelector(`[data-change="${key}"]`); const next = input.value === '' ? null : Number(input.value); if (next !== (original?.[key] ?? null)) change[key] = next; });
      const maintenance = row.querySelector('[data-change="maintenance_active"]').value; change.maintenance_active = maintenance === 'unknown' ? null : maintenance === 'true';
      change.scope_confirmed = row.querySelector('[data-change="scope_confirmed"]').checked;
      const status = row.querySelector('[data-change="status"]').value; if (status) change.status = status; changes.push(change);
    });
    return changes;
  }
  $('load-scenario-form').addEventListener('submit', async (event) => {
    event.preventDefault(); if (model.busy || model.pending || !model.data) return;
    const changes = scenarioChanges(); if (!changes.length) { message('先勾选至少一项任务调整或预算调整。', true); return; }
    const body = { ...packet(), changes }, generation = model.generation, epoch = state.epoch; clearMessages(); setBusy(true);
    try {
      const result = await api('/api/load/preview', { method: 'POST', body });
      if (!sameContext(generation, epoch)) return;
      model.preview = { result, body: { ...body, changes: result.changes || body.changes }, original: structuredClone(model.data), generation }; renderPreview();
    } catch (error) { if (sameContext(generation, epoch) && ![401, -1].includes(error.status)) message(error.message, true); }
    finally { if (sameContext(generation, epoch)) setBusy(false); }
  });
  function renderPreview() {
    const preview = model.preview; if (!preview) return;
    const box = $('load-preview'); box.replaceChildren(node('h3', '采纳前，请核对这些变化')); box.hidden = false;
    const compare = node('div', '', 'load-grid'); const before = node('div'), after = node('div'); renderAnalysis(preview.result.before, before, '当前安排'); renderAnalysis(preview.result.after, after, '方案安排'); compare.append(before, after); box.append(compare);
    const list = node('ul', '', 'load-diff');
    preview.body.changes.forEach((change) => {
      const old = change.task_id ? preview.original.tasks.find((t) => t.id === change.task_id) : preview.original.window;
      const row = node('li'); row.append(node('strong', old?.title || '窗口预算'));
      Object.keys(change).filter((key) => key !== 'task_id').forEach((key) => { const format = (v) => key === 'status' ? labels[v] : key === 'maintenance_active' ? v == null ? '未知' : v ? '启用维护' : '无维护' : key === 'scope_confirmed' ? v ? '已确认分开' : '未确认' : min(v); const a = format(old?.[key]), b = format(change[key]); row.append(node('p', `${fieldNames[key] || key}：${a} → ${b}${key === 'status' ? '（持续改变任务状态）' : ''}`)); });
      list.append(row);
    });
    box.append(list, node('p', '只采纳上面列出的差异。页面数据或日期发生变化后，需要重新预览。', 'load-muted'));
    box.append(btn('确认采纳这份方案', () => {
      if (!model.preview || model.preview.generation !== model.generation || model.preview.body.fingerprint !== model.data.fingerprint) { message('分析来源已变化，请重新预览。', true); invalidatePreview(); return; }
      save('/api/load/apply', { changes: model.preview.body.changes }, 'load-scenario-form', 'scenario');
    }, 'primary'));
  }
  function renderEvents() {
    const box = $('load-events'); box.replaceChildren();
    if (!model.data.history?.length) box.append(node('p', '这个窗口还没有调整记录。', 'load-muted'));
    (model.data.history || []).forEach((event) => {
      const row = node('article', '', 'load-event'); row.append(node('strong', event.summary || event.kind), node('time', new Date(event.created_at).toLocaleString('zh-CN')));
      if (event.can_undo) row.append(btn('撤回这次方案', () => { if (confirm('撤回会恢复这次方案采纳前的值。仅当来源和时间仍有效时可撤回，确认继续？')) save('/api/load/undo', { event_id: event.id }, null, 'scenario'); }));
      box.append(row);
    });
  }

  async function fetchDeadlines() {
    if (!state.user || model.pending || model.busy) return;
    const generation = model.generation, epoch = state.epoch, request = ++model.deadlineRequest;
    try {
      const result = await api(`/api/load/deadlines?${params()}`);
      if (!sameContext(generation, epoch) || request !== model.deadlineRequest) return;
      model.deadlines = result; renderDeadlines();
    } catch (error) { if (sameContext(generation, epoch) && ![401, -1].includes(error.status)) message(`期限检查读取失败：${error.message}`, true); }
  }
  function humanValue(val) { if (val === null || val === undefined) return '未知'; if (Array.isArray(val)) return val.map(humanValue).join('；'); if (typeof val === 'object') return Object.entries(val).map(([key, item]) => `${fieldNames[key] || ({ deadline: '截止日期', title: '任务', low: '下限', high: '上限', capacity: '容量', verdict: '判断', reason: '说明', status: '状态', known_low: '已知下限', unknowns: '待补全', unknown_count: '未知项数', deficit_low: '至少缺少', deficit_high: '上界缺少', budget: '预算', buffer: '缓冲', end: '截至', other_minutes: '其他占用', task_id: '任务标识', remaining: '剩余工作' }[key]) || key}：${humanValue(item)}`).join(' · '); return verdicts[val] || ({ overdue: '已逾期', out_of_window: '在当前窗口外', outside: '尚未评估', unavailable: '资料不足', missing: '未填写', true: '是', false: '否' }[String(val)]) || String(val); }
  function renderDeadlines() {
    const data = model.deadlines; if (!data) return;
    const box = $('load-deadline-result'); box.replaceChildren();
    box.append(node('p', `可安排容量 ${min(data.capacity)} · 留白 ${min(data.buffer)}`, 'load-notice'));
    const work = data.work || [];
    if (work.length) {
      box.append(node('h3', '待检查的目标'));
      work.forEach((item) => { const card = node('article', '', 'load-event'); card.append(node('strong', item.title || '任务目标'), node('p', `目标日期：${item.deadline || '未设置'} · 目标剩余：${range(item.remaining_low ?? item.low, item.remaining_high ?? item.high)}`)); if (item.reason) card.append(node('p', humanValue(item.reason))); if (item.task_id || item.id) card.append(btn('确认目标剩余量', () => openPlan(item.task_id || item.id), 'text-button')); box.append(card); });
    } else box.append(node('p', '当前没有可检查的目标。请在任务中设置目标日期，并确认整个目标的剩余工作。', 'load-muted'));
    const checks = data.checks || [];
    checks.forEach((check) => {
      const card = node('article', '', `load-suggestion verdict-${check.verdict || 'unknown'}`);
      card.append(node('h3', `截至 ${check.deadline || check.end || check.date || '目标日期'} · ${verdicts[check.verdict] || ({ expired: '已逾期', outside_window: '当前范围外，未评估' }[check.verdict]) || '待检查'}`));
      card.append(node('p', check.reason ? window.Duration.prose(check.reason) : humanValue(check)), node('p', `累计目标剩余 ${range(check.low, check.high)} · 截止日前共享净容量 ${min(check.capacity)}`));
      if (check.deficit_low > 0) card.append(node('p', `已知下限至少缺 ${min(check.deficit_low)}${check.unknown_count ? '，仍有未确认目标' : ''}。`));
      else if (check.deficit_high > 0) card.append(node('p', `按上界安排将缺 ${min(check.deficit_high)}。`));
      if (check.titles?.length) card.append(node('p', `共同计入：${check.titles.join('、')}`));
      box.append(card);
    });
    if (!model.dirty.has('load-slices-form')) { $('load-slices').replaceChildren(); (data.slices?.length ? data.slices : [{ end: addDays(model.week, 6), budget_minutes: model.data?.window.budget_minutes, buffer_minutes: model.data?.window.buffer_minutes, other_minutes: null }]).forEach(addSlice); }
  }
  let sliceIndex = 0;
  function addSlice(initial = {}) {
    const index = ++sliceIndex; const row = node('fieldset', '', 'load-slice'); row.dataset.slice = String(index); row.append(node('legend', '时间段'));
    const fields = node('div', '', 'load-grid load-grid-four'); const wrap = node('div'); const label = node('label', '截至日期（含当天）'); label.htmlFor = `load-slice-${index}-end`; const input = document.createElement('input'); input.type = 'date'; input.id = label.htmlFor; input.required = true; input.value = initial.end || addDays(model.week, 6); input.dataset.sliceField = 'end'; wrap.append(label, input); fields.append(wrap);
    [['budget_minutes', '该段总预算'], ['buffer_minutes', '该段留白'], ['other_minutes', '其他推进与维护占用']].forEach(([key, title]) => { const n = numberField(`load-slice-${index}-${key}`, title, initial[key], fields); n.dataset.sliceField = key; });
    row.append(fields, btn('移除这一段', () => { row.remove(); model.dirty.add('load-slices-form'); }, 'text-button')); $('load-slices').append(row);
  }
  function readSlices() { return [...$('load-slices').querySelectorAll('[data-slice]')].map((row) => Object.fromEntries([...row.querySelectorAll('[data-slice-field]')].map((el) => [el.dataset.sliceField, el.dataset.sliceField === 'end' ? el.value : el.value === '' ? null : Number(el.value)]))); }
  $('load-add-slice').addEventListener('click', () => { addSlice(); model.dirty.add('load-slices-form'); });
  $('load-slices-form').addEventListener('submit', (event) => { event.preventDefault(); save('/api/load/deadlines', { slices: readSlices() }, 'load-slices-form'); });
  async function fetchHistory() {
    if (!state.user || model.pending || model.busy) return;
    const generation = model.generation, epoch = state.epoch, request = ++model.historyRequest;
    try {
      const result = await api(`/api/load/history?${params()}`);
      if (!sameContext(generation, epoch) || request !== model.historyRequest) return;
      model.history = result; renderHistory();
    } catch (error) { if (sameContext(generation, epoch) && ![401, -1].includes(error.status)) message(`回顾读取失败：${error.message}`, true); }
  }
  function renderHistory() {
    const data = model.history; if (!data) return;
    const box = $('load-review-content'); box.replaceChildren();
    box.append(node('p', `本周实际记录 ${data.actual?.minutes == null ? '未记录' : min(data.actual.minutes)} · ${data.actual?.entry_count || 0} 条 · ${data.actual?.verified ? '已核对记录完整性' : '记录完整性待核对'}`, 'load-notice'));
    const list = node('div', '', 'load-history-tasks');
    (data.tasks || []).forEach((task) => {
      const row = node('article', '', 'load-event');
      row.append(node('strong', task.title), node('p', `${min(task.minutes)} · ${task.entry_count || 0} 条记录`));
      if (task.deleted_at) row.append(node('p', '已移入回收站，恢复后可查看账本。'), btn('前往回收站', () => navigate('tasks/trash'), 'text-button'));
      else row.append(btn('查看账本', () => openTask(task.id, 'time'), 'text-button'));
      list.append(row);
    });
    if (!data.tasks?.length) list.append(node('p', '这一周没有实际耗时记录；没有记录不代表没有投入。', 'load-muted'));
    box.append(list, node('h3', '当时保存的计划与分析'));
    if (!data.snapshots?.length) box.append(node('p', '还没有保存的分析快照。可在「负载与建议」中保存当前分析，作为以后回顾的依据。', 'load-muted'));
    (data.snapshots || []).forEach((snapshot) => { const details = node('details', '', 'load-saved'); details.append(node('summary', `${new Date(snapshot.created_at).toLocaleString('zh-CN')} · ${snapshot.window?.mode === 'week' ? '整周计划' : '剩余安排'}`)); const result = node('div'); renderAnalysis(snapshot.analysis || {}, result); details.append(node('p', `当时总预算 ${min(snapshot.window?.budget_minutes)}，留白 ${min(snapshot.window?.buffer_minutes)}`, 'load-muted'), result); box.append(details); });
    box.append(node('h3', '调整足迹'));
    (data.events || []).forEach((event) => { const details = node('details', '', 'load-saved'); details.append(node('summary', `${event.summary || event.kind} · ${new Date(event.created_at).toLocaleString('zh-CN')}`)); if (event.before) details.append(node('p', `修改前：${humanValue(event.before)}`)); if (event.after) details.append(node('p', `修改后：${humanValue(event.after)}`)); box.append(details); });
  }
  $('load-open-analysis').addEventListener('click', () => navigate('load'));
  $('load-refresh').addEventListener('click', () => { if (model.pending) message('上一次保存结果尚未确认，请先重试同一次保存。', true); else refresh(); });
  $('load-deadline-refresh').addEventListener('click', fetchDeadlines); $('load-review-refresh').addEventListener('click', fetchHistory);
  document.querySelectorAll('[data-route]').forEach((b) => b.addEventListener('click', () => navigate(b.dataset.route)));
  function windowChanged() {
    if (model.pending) { $('load-week').value = model.week; $('load-mode').value = model.mode;
    $('load-mode').querySelector('[value=remaining]').disabled = model.week !== currentMonday(); return; }
    try { const selected = monday($('load-week').value); const next = new URLSearchParams({ week: selected, mode: selected === currentMonday() ? $('load-mode').value : 'week' }); location.hash = `#${model.base}?${next}`; } catch (error) { message(error.message, true); }
  }
  $('load-week').addEventListener('change', windowChanged); $('load-mode').addEventListener('change', windowChanged);
  window.addEventListener('hashchange', handleRoute);
  window.addEventListener('beforeunload', (event) => { if (hasUnsaved()) { event.preventDefault(); event.returnValue = ''; } });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible' && state.user) invalidate(); });
  function openWeek(week) { location.hash = `#overview?${new URLSearchParams({ week: monday(week), mode: 'week' })}`; }
  window.LoadWorkspace = { enter, lock, invalidate, navigate, openWeek, selectedWeek: () => model.week, openTask, dialogOpened, dialogClosed, restoreDraft, hasDraft: (user) => Boolean(model.stash && model.stash.owner === user.id) };
})();
