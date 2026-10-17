'use strict';
(() => {
  const anchor = $('load-overview');
  if (!anchor) return;
  const panel = document.createElement('section');
  panel.id = 'footprints-panel'; panel.className = 'footprints-panel';
  panel.setAttribute('aria-labelledby', 'footprints-title');
  panel.innerHTML = `
    <div class="footprints-heading"><div><h2 id="footprints-title">每日足迹</h2></div><div class="footprints-heading-actions"><button id="footprints-toggle" class="secondary" type="button" aria-expanded="false" aria-controls="footprints-expanded-content" disabled>展开足迹</button><button id="footprints-year-open" class="secondary" type="button" disabled>查看全年 ↗</button></div></div>
    <p id="footprints-summary" class="footprints-summary">正在读取最近 12 周的足迹…</p>
    <div id="footprints-recent-calendar" class="footprints-calendar"><div class="footprints-weekdays" aria-hidden="true"><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span><span>日</span></div><div id="footprints-grid" class="footprints-grid" role="group" aria-label="最近 12 周，按星期排列的每日足迹"></div></div>
    <div class="footprints-footer"><div class="footprints-legend" aria-label="日历图例"><span><i class="footprints-swatch"></i>未记录</span><span><i class="footprints-swatch is-checkin"></i>已签到</span><span><i class="footprints-swatch is-rest"></i>休息日</span><span><i class="footprints-swatch has-activity"></i>有任务进展</span></div><span id="footprints-range" class="footprints-muted"></span></div>
    <p class="footprints-caption">点击日期看看那天。签到和休息不占用预算，也不计入耗时。</p>
    <div class="footprints-message"><p id="footprints-status" role="status" aria-live="polite" hidden></p><div class="footprints-actions"><button id="footprints-retry" class="secondary" type="button" hidden>核实并重试同一次标记</button><button id="footprints-reload" class="text-button" type="button" hidden>重新载入足迹</button></div></div>`;
  anchor.before(panel);
  addTodayGlance();
  const expandedContent = document.createElement('div');
  expandedContent.id = 'footprints-expanded-content'; expandedContent.hidden = true;
  panel.querySelector('.footprints-body').before(expandedContent);
  ['.footprints-body', '.footprints-footer', '.footprints-caption'].forEach((selector) => expandedContent.append(panel.querySelector(selector)));
  function addTodayGlance() {
    const body = document.createElement('div'); body.className = 'footprints-body';
    const calendar = $('footprints-recent-calendar'); calendar.before(body); body.append(calendar);
    const glimpse = document.createElement('aside'); glimpse.className = 'footprints-glimpse'; glimpse.setAttribute('aria-label', '今天的足迹概览');
    glimpse.innerHTML = `<span class="section-kicker">TODAY, AT YOUR OWN PACE</span><strong id="footprints-glimpse-title">今天，按自己的节奏</strong><p id="footprints-glimpse-time">实际投入尚未记录</p><p id="footprints-glimpse-completed">每一小步，都值得留下。</p><button id="footprints-glimpse-open" class="text-button" type="button">看看今天的足迹 ↗</button>`;
    body.append(glimpse);
  }
  const yearDialog = document.createElement('dialog');
  yearDialog.id = 'footprints-year-dialog'; yearDialog.className = 'footprints-dialog footprints-year-dialog';
  yearDialog.setAttribute('aria-labelledby', 'footprints-year-title');
  yearDialog.innerHTML = `<div class="footprints-heading"><div><span class="section-kicker">DAYS YOU HAVE LIVED</span><h2 id="footprints-year-title">这一年的足迹</h2></div><button id="footprints-year-close" type="button" class="icon-button" aria-label="关闭全年足迹">×</button></div><div class="footprints-year-toolbar"><label for="footprints-year-select">选择年份</label><select id="footprints-year-select"></select><span class="footprints-muted">只记下发生过的日子，不必填满每一个格子。</span></div><p id="footprints-year-summary" class="footprints-summary"></p><p id="footprints-year-error" class="error" role="alert" hidden></p><button id="footprints-year-retry" class="text-button" type="button" hidden>重新读取这一年</button><div class="footprints-year-scroll" tabindex="0" role="region" aria-label="全年日历，可左右滚动"><div class="footprints-calendar"><div class="footprints-weekdays" aria-hidden="true"><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span><span>日</span></div><div id="footprints-year-grid" class="footprints-grid" role="group" aria-label="全年每日足迹"></div></div></div><div id="footprints-year-legend" class="footprints-legend"></div><p class="footprints-caption">颜色表示签到或休息，格子上的小点表示当天有真实耗时或完成进展。</p>`;
  const dayDialog = document.createElement('dialog');
  dayDialog.id = 'footprints-day-dialog'; dayDialog.className = 'footprints-dialog footprints-day-dialog';
  dayDialog.setAttribute('aria-labelledby', 'footprints-day-title');
  dayDialog.innerHTML = `<div class="footprints-heading"><div><span class="section-kicker">YOUR DAILY FOOTPRINT</span><h2 id="footprints-day-title">这一天的足迹</h2></div><button id="footprints-day-close" type="button" class="icon-button" aria-label="关闭当天足迹">×</button></div><div id="footprints-day-content"></div><p id="footprints-day-error" class="error" role="alert" hidden></p><button id="footprints-day-retry" class="text-button" type="button" hidden>重新读取这一天</button><div id="footprints-day-actions" class="footprints-day-actions" hidden><button id="footprints-day-checkin" class="primary" type="button">今日签到</button><button id="footprints-day-rest" class="secondary" type="button">今天休息</button><button id="footprints-day-clear" class="text-button" type="button">撤销今日标记</button><p>签到和休息可以切换；你记录的真实进展会一直保留。</p></div><div id="footprints-day-message" class="footprints-message"><p id="footprints-day-status" role="status" hidden></p><div class="footprints-actions"><button id="footprints-day-write-retry" class="secondary" type="button" hidden>核实并重试同一次标记</button><button id="footprints-day-reload" class="text-button" type="button" hidden>重新载入足迹</button></div></div>`;
  document.body.append(yearDialog, dayDialog);
  $('footprints-year-legend').replaceChildren(panel.querySelector('.footprints-legend').cloneNode(true));

  const model = {expanded:false, owner:null, epoch:0, generation:0, recent:null, year:null, day:null, selectedDate:null, selectedYear:null, pending:null, busy:false, readError:false, request:0, yearRequest:0, dayRequest:0, timer:null, refreshTimer:null};
  const node = (tag, value = '', className = '') => text(tag, value, className);
  const context = () => ({owner:model.owner, epoch:model.epoch, generation:model.generation});
  const current = (ctx) => Boolean(state.user) && ctx.owner === state.user.id && ctx.owner === model.owner && ctx.epoch === state.epoch && ctx.generation === model.generation;
  const weekday = (date) => (new Date(`${date}T00:00:00Z`).getUTCDay() + 6) % 7;
  const markName = (mark) => ({checkin:'已签到', rest:'休息日'}[mark] || '未签到');
  const formatDate = (date) => new Intl.DateTimeFormat('zh-CN', {month:'long', day:'numeric', weekday:'long', timeZone:'UTC'}).format(new Date(`${date}T00:00:00Z`));
  const summaryText = (data, scope) => `${scope} · 签到 ${data.summary.checkin_days} 天 · 休息 ${data.summary.rest_days} 天 · 有进展 ${data.summary.active_days} 天`;
  function checkedCalendar(data) {
    if (!data || !/^\d{4}-\d{2}-\d{2}$/.test(data.today) || !Array.isArray(data.days) || !data.today_mark || !data.summary) throw new Error('足迹数据暂时无法读取，请重新载入。');
    return data;
  }
  function status(message = '', kind = '') {
    ['footprints-status', 'footprints-day-status'].forEach((id) => { $(id).textContent = message; $(id).hidden = !message; $(id).classList.toggle('error', kind === 'error'); });
  }
  function setExpanded(expanded, persist = false) {
    model.expanded = expanded;
    expandedContent.hidden = !expanded;
    panel.dataset.expanded = String(expanded);
    $('footprints-toggle').setAttribute('aria-expanded', String(expanded));
    $('footprints-toggle').textContent = expanded ? '收起足迹' : '展开足迹';
    if (persist && current(context())) {
      try { localStorage.setItem(`liubai.phase5.footprints.expanded.${model.owner}`, String(expanded)); }
      catch { /* Folding still works for this visit when local storage is blocked. */ }
    }
  }
  function syncControls() {
    $('footprints-toggle').disabled = !current(context());
    const mark = model.recent?.today_mark?.mark;
    const blocked = !state.user || !model.recent || model.busy || Boolean(model.pending);
    $('footprints-checkin').disabled = blocked || mark === 'checkin';
    $('footprints-checkin').textContent = model.busy ? '正在确认…' : mark === 'checkin' ? '今日已签到 ✓' : mark === 'rest' ? '改为今日签到' : '今日签到';
    $('footprints-checkin').dataset.mark = mark || '';
    $('footprints-checkin').dataset.date = model.recent?.today || '';
    $('footprints-today-label').textContent = mark === 'checkin' ? '今天也为自己留下了足迹。' : mark === 'rest' ? '今天，给自己留一点空白。' : '给今天留一个小记号';
    $('footprints-today-detail').disabled = !state.user || !model.recent;
    $('footprints-year-open').disabled = !state.user || !model.recent;
    ['checkin', 'rest', 'clear'].forEach((kind) => { $(`footprints-day-${kind}`).disabled = blocked || model.selectedDate !== model.recent?.today || (kind === 'clear' ? !mark : mark === kind); });
    const retry = Boolean(model.pending && !model.pending.conflict);
    ['footprints-retry', 'footprints-day-write-retry'].forEach((id) => { $(id).hidden = !retry; $(id).disabled = model.busy; });
    ['footprints-reload', 'footprints-day-reload'].forEach((id) => { $(id).hidden = !model.pending?.conflict && Boolean(model.recent); $(id).disabled = model.busy; });
  }
  function dayLabel(day, today) {
    const details = [day.date, formatDate(day.date)];
    if (day.date === today) details.push('今天');
    if (day.date > today) return [...details, '尚未到来'].join('，');
    details.push(day.mark ? markName(day.mark) : '未签到');
    if (day.minutes) details.push(`实际投入 ${window.Duration.format(day.minutes)}`);
    if (day.completed_steps) details.push(`完成 ${day.completed_steps} 个步骤`);
    if (day.completed_tasks) details.push(`完成 ${day.completed_tasks} 个任务`);
    if (!day.mark && !day.has_activity) details.push('未记录');
    return details.join('，');
  }
  function renderGrid(id, data) {
    const grid = $(id), focused = grid.contains(document.activeElement) ? document.activeElement.dataset.date : null;
    const fragment = document.createDocumentFragment();
    for (let offset = 0; offset < weekday(data.start); offset += 1) fragment.append(node('span', '', 'footprints-cell-gap'));
    data.days.forEach((day) => {
      const button = node('button', '', 'footprints-cell');
      button.type = 'button'; button.dataset.date = day.date; button.dataset.mark = day.mark || ''; button.dataset.activity = String(day.has_activity);
      button.dataset.minutes = day.minutes; button.dataset.completedSteps = day.completed_steps; button.dataset.completedTasks = day.completed_tasks;
      if (day.mark) button.classList.add(`is-${day.mark}`);
      if (day.has_activity) button.classList.add('has-activity');
      if (day.date === data.today) { button.classList.add('is-today'); button.setAttribute('aria-current', 'date'); }
      button.disabled = day.date > data.today; button.tabIndex = -1;
      button.title = dayLabel(day, data.today); button.setAttribute('aria-label', button.title);
      button.addEventListener('click', () => openDay(day.date));
      fragment.append(button);
    });
    grid.replaceChildren(fragment);
    const cells = [...grid.querySelectorAll('button:not(:disabled)')];
    const target = cells.find((cell) => cell.dataset.date === focused) || cells.find((cell) => cell.dataset.date === data.today) || cells[cells.length - 1];
    if (target) { target.tabIndex = 0; if (focused) target.focus({preventScroll:true}); }
  }
  function keyboardGrid(event) {
    if (!event.target.matches('button[data-date]')) return;
    const buttons = [...event.currentTarget.querySelectorAll('button')], index = buttons.indexOf(event.target), dayOfWeek = weekday(event.target.dataset.date);
    const movement = {ArrowUp:-1, ArrowDown:1, ArrowLeft:-7, ArrowRight:7, Home:-dayOfWeek, End:6-dayOfWeek}[event.key];
    if (movement === undefined) return;
    event.preventDefault();
    const next = buttons[index + movement];
    if (!next || next.disabled) return;
    event.target.tabIndex = -1; next.tabIndex = 0; next.focus();
  }
  ['footprints-grid', 'footprints-year-grid'].forEach((id) => $(id).addEventListener('keydown', keyboardGrid));
  function renderRecent() {
    const data = model.recent;
    if (!data) return;
    panel.dataset.today = data.today; panel.dataset.timezone = data.timezone;
    $('footprints-summary').textContent = summaryText(data, '最近 12 周');
    const today = data.days.find((day) => day.date === data.today);
    $('footprints-glimpse-title').textContent = today?.mark === 'rest' ? '今天，留一点空白' : today?.mark === 'checkin' ? '今天，也留下了足迹' : '今天，按自己的节奏';
    $('footprints-glimpse-time').textContent = today?.minutes ? `已记录投入 ${window.Duration.format(today.minutes)}` : '实际投入尚未记录';
    $('footprints-glimpse-completed').textContent = today?.completed_steps || today?.completed_tasks ? `完成 ${today.completed_steps} 个步骤 · ${today.completed_tasks} 个任务` : '每一小步，都值得留下。';
    $('footprints-range').textContent = `${data.start.replaceAll('-', '.')} — ${data.end.replaceAll('-', '.')} · 北京时间`;
    renderGrid('footprints-grid', data); syncControls();
  }
  async function refresh({clearConflict = false} = {}) {
    if (!state.user || model.owner !== state.user.id || model.busy) return false;
    const ctx = context(), request = ++model.request;
    panel.setAttribute('aria-busy', 'true');
    try {
      const data = checkedCalendar(await api('/api/footprints/calendar?view=recent'));
      if (!current(ctx) || request !== model.request) return false;
      model.recent = data;
      if (model.readError && !model.pending) status();
      model.readError = false;
      if (clearConflict && model.pending?.conflict) { model.pending = null; status('已重新载入最新足迹，请核对后再选择今天的标记。'); }
      renderRecent();
      return true;
    } catch (error) {
      if (current(ctx) && request === model.request && ![401, -1].includes(error.status) && !model.pending) {
        model.readError = true;
        status(`足迹暂时未能读取：${error.message}`, 'error');
        $('footprints-reload').hidden = false; $('footprints-day-reload').hidden = false;
      }
      return false;
    } finally { if (current(ctx) && request === model.request) panel.setAttribute('aria-busy', 'false'); }
  }
  async function refreshOpenDetails() {
    const work = [];
    if (yearDialog.open) work.push(fetchYear());
    if (dayDialog.open && model.selectedDate) work.push(fetchDay(model.selectedDate));
    await Promise.all(work);
  }
  async function reload() {
    if (model.busy) return;
    if (await refresh({clearConflict:true})) await refreshOpenDetails();
  }
  function invalidate() {
    if (!state.user || model.owner !== state.user.id) return;
    clearTimeout(model.refreshTimer);
    const ctx = context();
    model.refreshTimer = setTimeout(async () => { if (!current(ctx)) return; await refresh(); if (current(ctx)) await refreshOpenDetails(); }, 80);
  }
  function start(kind) {
    if (!state.user || !model.recent || model.busy || model.pending) return;
    const today = model.recent.today, mark = model.recent.today_mark;
    if (kind === mark.mark || (kind === 'clear' && !mark.mark)) return;
    model.pending = {...context(), key:crypto.randomUUID(), body:{date:today, kind, version:mark.version}, conflict:false};
    transmit();
  }
  async function transmit() {
    const packet = model.pending;
    if (!packet || model.busy || packet.conflict || !current(packet)) return;
    model.busy = true; model.request += 1; status('正在确认今天的标记…'); syncControls();
    try {
      const receipt = await api('/api/footprints/mark', {method:'POST', body:packet.body, headers:{'Idempotency-Key':packet.key}});
      if (!current(packet) || model.pending !== packet) return;
      if (!receipt?.day || receipt.day.date !== packet.body.date) throw new Error('未能核对这一次标记的回执。');
      // A saved receipt can predate another tab's edit; only the current calendar sets the UI.
      const canonical = checkedCalendar(await api('/api/footprints/calendar?view=recent'));
      if (!current(packet) || model.pending !== packet) return;
      model.request += 1; model.recent = canonical; model.pending = null; renderRecent();
      const now = canonical.today_mark.mark;
      if (packet.body.date !== canonical.today) status('已确认前一天的操作。日期已更新，可以为今天留下新足迹。');
      else if ((packet.body.kind === 'clear' ? null : packet.body.kind) !== now) status('已确认这次操作；今日标记已在其他页面更新，现已显示最新状态。');
      else status(now === 'checkin' ? '今天也留下了自己的足迹。慢慢来，按你的节奏。' : now === 'rest' ? '休息也值得被认真对待，今天给自己一点空白。' : '已撤销今日标记，真实耗时和任务进展仍然保留。');
      await refreshOpenDetails();
    } catch (error) {
      if (!current(packet) || [401, -1].includes(error.status) || model.pending !== packet) return;
      if (error.status >= 400 && error.status < 500) {
        packet.conflict = true;
        status(`标记没有覆盖最新记录：${error.message} 请重新载入足迹后再操作。`, 'error');
      } else status(`这次标记的结果尚未确认：${error.message} 可核实并重试同一次操作。`, 'error');
    } finally { if (current(packet)) { model.busy = false; syncControls(); } }
  }
  function linkTask(item, section) {
    const button = node('button', item.deleted ? '前往回收站' : '查看任务', 'text-button'); button.type = 'button';
    button.dataset.taskId = item.task_id; button.dataset.deleted = String(Boolean(item.deleted));
    button.addEventListener('click', () => { dayDialog.close(); yearDialog.close(); if (item.deleted) window.LoadWorkspace?.navigate('tasks/trash'); else window.LoadWorkspace?.openTask(item.task_id, section); });
    return button;
  }
  function factList(title, items, kind) {
    const section = node('section', '', 'footprints-facts'); section.append(node('h3', title));
    if (!items.length) { section.append(node('p', kind === 'time' ? '这一天还没有记录实际耗时。' : '这一天还没有有效的完成记录。', 'footprints-muted')); return section; }
    const list = node('ul');
    items.forEach((item) => {
      const row = node('li'), top = node('div', '', 'footprints-fact-title');
      top.append(node('strong', item.step_title ? `${item.task_title} / ${item.step_title}` : item.task_title));
      top.append(node('span', kind === 'time' ? window.Duration.format(item.minutes) : item.kind === 'step' ? '完成步骤' : '完成任务', 'footprints-fact-value'));
      row.append(top);
      if (item.note) row.append(node('p', item.note, 'footprints-fact-note'));
      if (item.deleted) row.append(node('span', '任务已在回收站 · 记录保留', 'footprints-muted'));
      row.append(linkTask(item, kind === 'time' ? 'ledger' : 'steps')); list.append(row);
    });
    section.append(list); return section;
  }
  function renderDay() {
    const data = model.day, day = data.day, box = $('footprints-day-content'); box.replaceChildren();
    $('footprints-day-title').textContent = `${day.date} · ${formatDate(day.date)}`;
    const summary = node('div', '', 'footprints-day-summary');
    summary.append(node('strong', day.mark ? markName(day.mark) : day.has_activity ? '有任务进展' : '这一天还没有记录'));
    summary.append(node('p', `实际投入 ${window.Duration.format(day.minutes)} · 完成 ${day.completed_steps} 个步骤 / ${day.completed_tasks} 个任务`));
    if (day.mark === 'rest') summary.append(node('p', '休息与真实进展可以同时存在，不需要抹去已经做过的事。', 'footprints-muted'));
    if (day.date < data.today) summary.append(node('p', '过去的日子只读查看；今天可以留下一枚新的记号。', 'footprints-muted'));
    box.append(summary, factList('实际投入', data.entries, 'time'), factList('完成的事', data.completions, 'completion'));
    $('footprints-day-actions').hidden = day.date !== data.today; syncControls();
  }
  async function fetchDay(date) {
    const ctx = context(), request = ++model.dayRequest;
    $('footprints-day-content').setAttribute('aria-busy', 'true');
    $('footprints-day-error').hidden = true; $('footprints-day-retry').hidden = true;
    try {
      const data = await api(`/api/footprints/day?${new URLSearchParams({date})}`);
      if (!current(ctx) || request !== model.dayRequest || model.selectedDate !== date) return;
      if (!data?.day || !Array.isArray(data.entries) || !Array.isArray(data.completions)) throw new Error('当天记录暂时无法读取。');
      model.day = data; renderDay();
      if (model.recent?.today !== data.today) invalidate();
    } catch (error) {
      if (current(ctx) && request === model.dayRequest && ![401, -1].includes(error.status)) {
        $('footprints-day-error').textContent = `当天足迹读取失败：${error.message}`;
        $('footprints-day-error').hidden = false; $('footprints-day-retry').hidden = false;
      }
    } finally { if (current(ctx) && request === model.dayRequest) $('footprints-day-content').setAttribute('aria-busy', 'false'); }
  }
  function openDay(date) {
    if (!state.user || !model.recent || date > model.recent.today) return;
    model.selectedDate = date; model.day = null;
    $('footprints-day-title').textContent = `${date} 的足迹`;
    $('footprints-day-content').replaceChildren(node('p', '正在读取这一天…', 'footprints-muted'));
    $('footprints-day-actions').hidden = true;
    if (!dayDialog.open) dayDialog.showModal();
    void fetchDay(date);
  }
  async function fetchYear() {
    if (!state.user || !model.selectedYear) return;
    const ctx = context(), request = ++model.yearRequest, year = model.selectedYear;
    $('footprints-year-grid').setAttribute('aria-busy', 'true');
    $('footprints-year-error').hidden = true; $('footprints-year-retry').hidden = true;
    try {
      const data = checkedCalendar(await api(`/api/footprints/calendar?${new URLSearchParams({view:'year', year})}`));
      if (!current(ctx) || request !== model.yearRequest || model.selectedYear !== year) return;
      model.year = data; $('footprints-year-summary').textContent = summaryText(data, `${year} 年`);
      renderGrid('footprints-year-grid', data);
      if (model.recent?.today !== data.today) invalidate();
    } catch (error) {
      if (current(ctx) && request === model.yearRequest && ![401, -1].includes(error.status)) {
        $('footprints-year-error').textContent = `全年足迹读取失败：${error.message}`;
        $('footprints-year-error').hidden = false; $('footprints-year-retry').hidden = false;
      }
    } finally { if (current(ctx) && request === model.yearRequest) $('footprints-year-grid').setAttribute('aria-busy', 'false'); }
  }
  function openYear() {
    if (!model.recent || !state.user) return;
    const currentYear = Number(model.recent.today.slice(0, 4)), select = $('footprints-year-select'); select.replaceChildren();
    for (let year = currentYear; year >= 1900; year -= 1) { const option = node('option', `${year} 年`); option.value = year; select.append(option); }
    model.selectedYear = currentYear; select.value = currentYear; $('footprints-year-summary').textContent = '正在读取这一年…';
    $('footprints-year-grid').replaceChildren(); yearDialog.showModal(); void fetchYear();
  }
  function routeChanged(route) { if (route !== 'overview') { dayDialog.close(); yearDialog.close(); } }
  function lock() {
    model.generation += 1; model.request += 1; model.dayRequest += 1; model.yearRequest += 1;
    clearTimeout(model.timer); clearTimeout(model.refreshTimer);
    model.owner = null; model.recent = null; model.year = null; model.day = null; model.pending = null; model.busy = false; model.readError = false; model.selectedDate = null; model.selectedYear = null;
    dayDialog.close(); yearDialog.close();
    ['footprints-grid', 'footprints-year-grid', 'footprints-day-content', 'footprints-year-select'].forEach((id) => $(id).replaceChildren());
    ['footprints-range', 'footprints-year-summary', 'footprints-year-error', 'footprints-day-error'].forEach((id) => { $(id).textContent = ''; });
    ['footprints-year-error', 'footprints-day-error', 'footprints-year-retry', 'footprints-day-retry', 'footprints-day-actions'].forEach((id) => { $(id).hidden = true; });
    $('footprints-summary').textContent = '正在读取最近 12 周的足迹…'; $('footprints-day-title').textContent = '这一天的足迹';
    $('footprints-glimpse-title').textContent = '今天，按自己的节奏'; $('footprints-glimpse-time').textContent = '实际投入尚未记录'; $('footprints-glimpse-completed').textContent = '每一小步，都值得留下。';
    delete panel.dataset.today; delete panel.dataset.timezone; panel.setAttribute('aria-busy', 'false');
    setExpanded(false); status(); syncControls();
  }
  function schedule() {
    clearTimeout(model.timer);
    // Poll near the Shanghai midnight; the response, not the browser clock, chooses today.
    const now = Date.now(), shifted = now + 8 * 60 * 60 * 1000;
    const untilMidnight = 86400000 - (shifted % 86400000) + 300;
    model.timer = setTimeout(() => { if (!document.hidden && state.user) invalidate(); if (state.user) schedule(); }, Math.min(untilMidnight, 60000));
  }
  function enter(user) {
    lock(); model.owner = user.id; model.epoch = state.epoch;
    let expanded = false;
    try { expanded = window.OverviewFocusRules.parseExpanded(localStorage.getItem(`liubai.phase5.footprints.expanded.${user.id}`)); }
    catch { /* A missing or unreadable preference starts with the compact view. */ }
    setExpanded(expanded); syncControls(); void refresh(); schedule();
  }
  function resume() { if (state.user && model.owner === state.user.id && !document.hidden) { invalidate(); schedule(); } }
  $('footprints-toggle').addEventListener('click', () => { if (current(context())) setExpanded(!model.expanded, true); });
  $('footprints-checkin').addEventListener('click', () => start('checkin'));
  $('footprints-today-detail').addEventListener('click', () => openDay(model.recent.today));
  $('footprints-glimpse-open').addEventListener('click', () => { if (model.recent) openDay(model.recent.today); });
  $('footprints-year-open').addEventListener('click', openYear);
  $('footprints-year-close').addEventListener('click', () => yearDialog.close());
  $('footprints-day-close').addEventListener('click', () => dayDialog.close());
  ['checkin', 'rest', 'clear'].forEach((kind) => $(`footprints-day-${kind}`).addEventListener('click', () => start(kind)));
  ['footprints-retry', 'footprints-day-write-retry'].forEach((id) => $(id).addEventListener('click', transmit));
  ['footprints-reload', 'footprints-day-reload'].forEach((id) => $(id).addEventListener('click', reload));
  $('footprints-day-retry').addEventListener('click', () => fetchDay(model.selectedDate));
  $('footprints-year-retry').addEventListener('click', fetchYear);
  $('footprints-year-select').addEventListener('change', () => { model.selectedYear = Number($('footprints-year-select').value); $('footprints-year-grid').replaceChildren(); $('footprints-year-summary').textContent = '正在读取这一年…'; void fetchYear(); });
  dayDialog.addEventListener('close', () => { model.dayRequest += 1; });
  yearDialog.addEventListener('close', () => { model.yearRequest += 1; });
  window.addEventListener('focus', resume); window.addEventListener('pageshow', resume);
  window.addEventListener('pagehide', () => { clearTimeout(model.timer); clearTimeout(model.refreshTimer); });
  document.addEventListener('visibilitychange', resume);
  window.addEventListener('beforeunload', (event) => { if (model.pending) { event.preventDefault(); event.returnValue = ''; } });
  window.Footprints = Object.freeze({enter, lock, invalidate, refresh, openDay, routeChanged});
  syncControls();
})();
