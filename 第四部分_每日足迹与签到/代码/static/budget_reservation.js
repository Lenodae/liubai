'use strict';
(() => {
  const localDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  function monday(value) {
    const d = new Date(`${value}T12:00:00`);
    if (!Number.isFinite(+d)) throw new Error('请选择有效的安排日期。');
    d.setDate(d.getDate() - (d.getDay() + 6) % 7);
    return localDate(d);
  }
  const currentMonday = () => monday(localDate(new Date()));
  const minutes = (n) => window.Duration.format(n, '待确认');
  const interval = window.Duration.range;
  const node = (tag, content = '', className = '') => text(tag, content, className);
  const svgNode = (tag, attrs = {}) => {
    const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, value));
    return element;
  };
  let generation = 0;
  const dialog = document.createElement('dialog');
  dialog.id = 'budget-reservation-dialog'; dialog.className = 'load-dialog budget-reservation-dialog';
  dialog.setAttribute('aria-labelledby', 'budget-reservation-title');
  dialog.innerHTML = `<div class="load-heading"><div><span class="section-kicker">MAKE ROOM FOR AN IDEA</span><h2 id="budget-reservation-title">已记录 · 看看本周预算</h2></div><button id="budget-reservation-close" class="icon-button" type="button" aria-label="关闭预算结果">×</button></div><p id="budget-reservation-task" class="load-muted"></p><div id="budget-reservation-result" role="status" aria-live="polite"></div><div class="load-actions"><button id="budget-reservation-done" type="button" class="secondary">继续记录</button><button id="budget-reservation-ideas" type="button" class="secondary" hidden>去想法池</button><button id="budget-reservation-overview" type="button" class="primary">查看这一周的预算</button></div>`;
  document.body.append(dialog);
  function close() { generation += 1; dialog.close(); }
  $('budget-reservation-close').addEventListener('click', close);
  $('budget-reservation-done').addEventListener('click', close);
  $('budget-reservation-ideas').addEventListener('click', () => { close(); window.LoadWorkspace?.navigate('tasks/planned'); });
  dialog.addEventListener('cancel', (event) => { event.preventDefault(); close(); });
  $('budget-reservation-overview').addEventListener('click', () => {
    const week = dialog.dataset.week; close(); window.LoadWorkspace?.openWeek(week);
  });
  function remaining(analysis) {
    const low = analysis.available_low, high = analysis.available_high;
    if (low == null || high == null) return '待确认';
    if (high < 0) return `缺 ${interval(-high, -low)}`;
    if (low < 0) return `缺 ${minutes(-low)} 至剩余 ${minutes(high)}`;
    return interval(low, high);
  }
  function renderTaskSources(data, onEditTask) {
    const historical = data.tasks?.some((task) => task.historical);
    const tasks = (data.tasks || []).filter((task) => (task.load_status || task.status) === 'in_progress' || (task.historical && (task.budget_committed || task.maintenance_active === true)));
    const section = node('section', '', 'budget-chart-tasks');
    section.setAttribute('aria-label', historical ? '本窗口的投入来源' : '圆盘中的进行中事项');
    section.append(node('h4', historical ? '本窗口的投入来源' : '圆盘中的进行中事项'));
    if (!tasks.length) section.append(node('p', '还没有进行中的事情。想法可以先记下来，开始投入后才进入圆盘。', 'budget-chart-note'));
    const list = node('ul', '', 'budget-task-sources');
    tasks.forEach((task) => {
      const row = node('li'); row.dataset.budgetTask = task.id;
      const main = node('div', '', 'budget-task-source-main');
      const title = node('span', task.title, 'budget-task-name');
      const unknown = (data.analysis.unknowns || []).some((item) => item.task_id === task.id);
      const auto = task.allocation_source === 'auto';
      const detail = node('div', '', 'budget-task-source-detail');
      let amount;
      if (auto) amount = task.reservation_minutes == null ? '估时待补充' : minutes(task.reservation_minutes);
      else if (task.allocation_source === 'manual') amount = unknown ? '窗口投入待确认' : '已采用窗口计划';
      else if (data.window.mode === 'remaining') amount = '剩余投入待确认';
      else if (task.historical && task.maintenance_active === true) amount = unknown ? '历史维护待确认' : '历史维护计划';
      else amount = '本窗口不占用';
      main.append(title, node('strong', amount, 'budget-task-time'));
      if (auto && task.reservation_minutes != null) detail.append(node('span', '整个任务的总投入'));
      else if (!auto && (task.allocation_source === 'manual' || (task.historical && task.maintenance_active === true))) {
        detail.append(node('span', `推进 ${interval(task.progress_low, task.progress_high)} · 维护 ${task.maintenance_active === true ? interval(task.maintenance_low, task.maintenance_high) : task.maintenance_active === false ? '未启用' : '待确认'}${unknown ? ' · 仍有信息待确认' : ''}`));
      }
      if (typeof onEditTask === 'function') {
        const edit = node('button', task.deleted_at ? '前往回收站' : auto ? '调整估时 ↗' : '查看投入 ↗', 'text-button budget-task-open');
        edit.type = 'button'; edit.setAttribute('aria-label', `${task.title}：${task.deleted_at ? '前往回收站' : auto ? '调整投入估时' : '查看窗口投入'}`);
        edit.addEventListener('click', () => onEditTask(task)); detail.append(edit);
      }
      row.append(main, detail); list.append(row);
    });
    section.append(list);
    section.append(node('p', historical ? '历史窗口采用当时确认的投入资料；当前状态与实际耗时单独显示。' : '上面的投入总量采用当前窗口分析结果；想法、暂停和结束的事情不占用当前预算。', 'budget-chart-note'));
    return section;
  }
  function render(data, { compact = false, editor = null, onEditTask = null } = {}) {
    const w = data.window || {}, a = data.analysis || {};
    const budgetKnown = w.confirmed && !w.stale && a.capacity != null && w.budget_minutes != null && w.buffer_minutes != null;
    const demandKnown = a.low != null && a.high != null;
    const knownConflict = budgetKnown && a.verdict === 'conflict' && a.deficit_low > 0;
    const verdict = knownConflict ? 'conflict' : ['fits', 'conditional', 'conflict'].includes(a.verdict) && budgetKnown && demandKnown ? a.verdict : 'unknown';
    const card = node('section', '', `budget-chart budget-chart-${verdict}${compact ? ' budget-chart-compact' : ''}${editor ? ' budget-chart-editable' : ''}`);
    const feeling = window.LoadFeeling.describe(a, w); card.dataset.loadFeeling = feeling.level;
    card.dataset.budgetVerdict = verdict;
    card.dataset.budgetMinutes = w.budget_minutes ?? '';
    card.dataset.demandLow = a.low ?? '';
    card.dataset.demandHigh = a.high ?? '';
    card.dataset.availableLow = a.available_low ?? '';
    card.dataset.availableHigh = a.available_high ?? '';
    card.setAttribute('aria-label', `${w.mode === 'remaining' ? '未来剩余' : '整周'}预算分配`);
    const head = node('div', '', 'budget-chart-head');
    head.append(node('h3', w.mode === 'remaining' ? '未来剩余预算' : '这一周，留给事情的时间'), node('p', `${w.week || ''} 所在周 · ${w.mode === 'remaining' ? '单独确认的剩余口径' : '只有进行中投入计入整周预算'}`));
    card.append(head);
    const badge = node('div', '', 'budget-feeling-badge');
    badge.append(node('strong', feeling.percent ? `时间负载 ${feeling.percent} · ${feeling.label}` : feeling.label));
    if (feeling.rangeText) badge.append(node('span', `预计 ${feeling.rangeText}，按上界提示`));
    else if (!feeling.percent && feeling.level === 'unknown') badge.append(node('small', '补全时间后再判断节奏'));
    card.append(badge, node('p', '负载以扣除留白后的容量为 100%；圆环展示总预算的分配。', 'budget-feeling-basis'));
    const body = node('div', '', 'budget-chart-body'), ring = node('div', '', 'budget-chart-ring');
    const svg = svgNode('svg', { viewBox: '0 0 200 200', 'aria-hidden': 'true', focusable: 'false' });
    svg.append(svgNode('circle', { cx: 100, cy: 100, r: 77, class: 'budget-ring-track' }));
    // Arc lengths use the confirmed total budget. Capping prevents a second lap for an overfull plan.
    if (budgetKnown && w.budget_minutes > 0) {
      const total = w.budget_minutes;
      const bufferShare = Math.min(1, Math.max(0, w.buffer_minutes / total));
      const knownAmount = demandKnown ? a.high : a.known_low;
      const taskShare = Math.min(1 - bufferShare, Math.max(0, Number(knownAmount || 0) / total));
      const circumference = 2 * Math.PI * 77;
      let offset = 0;
      [[taskShare, 'budget-ring-task'], [bufferShare, 'budget-ring-buffer']].forEach(([share, className]) => {
        if (share > 0) svg.append(svgNode('circle', { cx: 100, cy: 100, r: 77, class: className, 'stroke-dasharray': `${share * circumference} ${circumference}`, 'stroke-dashoffset': -offset * circumference, transform: 'rotate(-90 100 100)' }));
        offset += share;
      });
    }
    ring.append(svg);
    const center = node('div', '', 'budget-chart-center');
    const awaitingBudget = !budgetKnown && demandKnown;
    center.append(node('span', awaitingBudget ? '进行中投入' : verdict === 'conflict' ? '投入超出容量' : verdict === 'unknown' ? '信息待确认' : '可再安排'), node('strong', awaitingBudget ? interval(a.low, a.high) : budgetKnown && demandKnown ? remaining(a) : knownConflict ? `至少缺 ${minutes(a.deficit_low)}` : '待确认'));
    if (awaitingBudget) center.append(node('small', w.stale ? '预算待重新确认' : '总预算待设置'));
    ring.append(center); body.append(ring);
    const detail = node('div', '', 'budget-chart-detail'), legend = node('dl', '', 'budget-chart-legend');
    const rows = [
      ['整段总预算', budgetKnown ? minutes(w.budget_minutes) : '待设置 / 确认', 'budget-total'],
      ['其中留白缓冲', budgetKnown ? minutes(w.buffer_minutes) : '待确认', 'budget-buffer'],
      [w.mode === 'remaining' ? '进行中剩余投入' : '进行中投入', interval(a.low, a.high), 'budget-task'],
      ['可再安排', budgetKnown && demandKnown ? remaining(a) : '待确认', 'budget-free'],
    ];
    rows.forEach(([label, value, className]) => { const dt = node('dt', '', className); dt.append(node('i', '', 'budget-legend-dot'), node('span', label)); legend.append(dt, node('dd', value)); });
    detail.append(legend);
    if (!budgetKnown) detail.append(node('p', `已计入进行中投入 ${demandKnown ? interval(a.low, a.high) : `至少 ${minutes(a.known_low ?? 0)}，还有未知项`}。${w.stale ? '预算确认已过期，请重新确认' : '请填写'}${w.mode === 'remaining' ? '未来剩余' : '这一周的'}总预算与留白后，圆环即可显示占比和余量。`, 'budget-chart-note'));
    else if (!demandKnown || a.unknown_count) detail.append(node('p', `已知进行中投入至少 ${minutes(a.known_low ?? 0)}；${knownConflict ? `保留缓冲，至少超出 ${minutes(a.deficit_low)}。` : ''}${a.unknown_count || '仍有'} 项信息待确认，进行中的未知估时需要补充，想法池不占用预算。`, 'budget-chart-note'));
    else if (a.deficit_low > 0) detail.append(node('p', `保留留白缓冲，至少超出 ${minutes(a.deficit_low)}。图上的投入最多填满一圈，超额另用文字列出。`, 'budget-chart-note'));
    else if (a.deficit_high > 0) detail.append(node('p', `投入达到上界时将超出 ${minutes(a.deficit_high)}，可以减少安排或调整预算。`, 'budget-chart-note'));
    else if (a.low !== a.high) detail.append(node('p', '圆环按进行中投入的上界显示；可再安排时间同时保留下限与上限。', 'budget-chart-note'));
    else detail.append(node('p', '想法、暂停和结束的事情不占用当前预算。进行中投入与实际耗时分别记录，步骤和维护不会重复相加。', 'budget-chart-note'));
    body.append(detail);
    if (editor) {
      const workspace = node('div', '', 'budget-chart-workspace'), visual = node('div', '', 'budget-chart-visual');
      visual.append(body, renderTaskSources(data, onEditTask)); workspace.append(visual, editor); card.append(workspace);
    } else card.append(body);
    if (w.mode === 'remaining') card.append(node('p', '整周投入请切到「整周计划」查看；这里需要单独确认今天之后的可用时间和安排。', 'budget-chart-note'));
    return card;
  }
  async function show(task) {
    if (!task || !state.user) return;
    const request = ++generation, epoch = state.epoch;
    const week = task.budget_week || currentMonday();
    dialog.dataset.week = week;
    $('budget-reservation-ideas').hidden = task.status !== 'planned';
    $('budget-reservation-title').textContent = task.status === 'planned' ? '想法已记录 · 尚未开始' : '已保存 · 看看本周预算';
    $('budget-reservation-task').textContent = task.status === 'planned' ? `「${task.title}」已放入想法池，尚未开始，不占用预算。${task.weekly_minutes == null ? '估计时间可等想清楚以后补充。' : `预计投入 ${minutes(task.weekly_minutes)}，开始投入后才计入。`}` : task.status !== 'in_progress' ? `「${task.title}」当前${labels[task.status]}，不占用预算。` : task.budget_schedule === 'recurring' ? `「${task.title}」正在投入，从 ${week} 所在周起每周计入 ${minutes(task.weekly_minutes)}。暂停或结束后释放占用。` : `「${task.title}」正在投入，${week} 所在周计入 ${minutes(task.weekly_minutes)}。`;
    $('budget-reservation-result').replaceChildren(node('p', '正在读取已保存任务对应的整周预算…', 'load-muted'));
    if (!dialog.open) dialog.showModal();
    try {
      const data = await api(`/api/load/workspace?${new URLSearchParams({ week, mode: 'week' })}`);
      if (request !== generation || epoch !== state.epoch || !state.user || !dialog.open) return;
      $('budget-reservation-result').replaceChildren(render(data));
      const saved = data.tasks.find((item) => item.id === task.id);
      if (saved?.allocation_source === 'manual') $('budget-reservation-result').append(node('p', '这一周已有手工确认的投入，图中采用手工计划；其他周采用进行中的每周估时。', 'load-notice'));
      if (task.status !== 'in_progress') $('budget-reservation-result').append(node('p', '这次记录没有新增预算占用，圆盘仅显示进行中的事情。', 'load-notice'));
    } catch (error) {
      if (request !== generation || epoch !== state.epoch || [401, -1].includes(error.status)) return;
      $('budget-reservation-result').replaceChildren(node('p', `任务已保存；预算结果暂时读取失败：${error.message}。可关闭后在预算总览刷新。`, 'error'));
    }
  }
  function lock() { close(); dialog.dataset.week = ''; $('budget-reservation-task').textContent = ''; $('budget-reservation-result').replaceChildren(); }
  window.BudgetReservation = { currentMonday, monday, render, show, lock };
})();
