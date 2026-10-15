'use strict';

const $ = (id) => document.getElementById(id);
const labels = { planned: '想法 / 待开始', in_progress: '进行中', paused: '暂停', completed: '完成', abandoned: '放弃' };
const kinds = { general: '其他事项', study: '学习成长', work: '工作项目', life: '生活日常' };
const priorities = { low: '不着急', normal: '普通优先级', high: '优先处理' };
const tabs = {
  in_progress: ['当前清单', '把精力，留给正在做的事。', '正在投入的事', '这里，还留着一片空白', '从待选择中开始一件事，或先记下新的想法。'],
  planned: ['想法池', '先记下想法，想清楚再开始投入。', '留待开始的想法', '给下一件事，留好位置', '记录想法不会占用预算；开始投入后，估计时间才会计入。'],
  paused: ['暂停一下', '暂时放下，也是一种认真选择。', '暂时放下的事', '暂时没有停下的脚步', '暂停的任务会留在这里，准备好了再继续。'],
  history: ['历史记录', '完成的、放下的，都成为走过的路。', '已经走过的路', '你的足迹，会慢慢出现在这里', '完成和放弃的任务都会保留，也可以重新开始。'],
  trash: ['回收站', '先从眼前放下，需要时仍然可以找回来。', '暂时收起的事', '回收站还是空的', '删除的任务会保留在这里，恢复后回到原来的状态，步骤和耗时也会保留。'],
};
const state = { user: null, tab: 'in_progress', tasks: [], counts: {}, epoch: 0, load: 0, editing: null, baseline: '', createKey: '', draft: null, busy: false, authMode: 'login' };
let toastTimer;
let searchTimer;

class RequestError extends Error {
  constructor(message, status = 0) { super(message); this.status = status; }
}
function csrf() {
  return document.cookie.split('; ').find((v) => v.startsWith('taskflow4_csrf='))?.split('=').slice(1).join('=') || '';
}
function showError(id, message) { $(id).textContent = message; $(id).hidden = !message; }
function toast(message, bad = false) {
  clearTimeout(toastTimer);
  $('toast').textContent = message;
  $('toast').classList.toggle('error-toast', bad);
  $('toast').hidden = false;
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 4500);
}
function text(tag, content, className = '') {
  const el = document.createElement(tag);
  el.textContent = content;
  el.className = className;
  return el;
}
async function api(path, { method = 'GET', body, headers = {}, protectedRequest = true } = {}) {
  const epoch = state.epoch;
  let response;
  try {
    response = await fetch(path, { method, credentials: 'same-origin', cache: 'no-store', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf(), ...(protectedRequest && state.user ? { 'X-Workspace-User': String(state.user.id) } : {}), ...headers }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  } catch {
    throw new RequestError('未保存确认：网络连接中断，结果尚未确认。你的输入已保留，可以重试。');
  }
  if (protectedRequest && epoch !== state.epoch) throw new RequestError('请求已取消。', -1);
  let data;
  try { data = await response.json(); } catch { throw new RequestError('服务暂时不可用，未确认保存成功。你的输入已保留。', response.status); }
  if (protectedRequest && epoch !== state.epoch) throw new RequestError('请求已取消。', -1);
  if (response.status === 401 && protectedRequest) expireSession();
  if (!response.ok) throw new RequestError(data.error || '操作未完成，请稍后重试。', response.status);
  return data;
}
function clearPrivateUI() {
  window.Footprints?.lock();
  window.TaskTrash?.lock();
  window.Encouragement?.lock();
  window.BudgetReservation?.lock();
  window.LoadWorkspace?.lock();
  window.DeepSeekSettings?.lock();
  window.Execution?.lock();
  state.tasks = [];
  state.counts = {};
  state.load += 1;
  $('task-list').replaceChildren();
  $('event-list').replaceChildren();
  $('account-name').textContent = '';
  $('task-form').reset();
  $('search').value = '';
  $('draft-recovery').hidden = true;
  state.editing = null;
  state.baseline = '';
  showError('save-error', '');
  $('task-dialog').close();
}
function showAuth(message = '') {
  $('boot').hidden = true;
  $('workspace').hidden = true;
  $('auth-screen').hidden = false;
  $('password').value = '';
  showError('auth-error', message);
}
function expireSession() {
  if ($('task-dialog').open && state.user) {
    state.draft = { userId: state.user.id, raw: readRaw(), editing: state.editing, key: state.createKey, baseline: state.baseline };
  }
  state.epoch += 1;
  state.user = null;
  clearPrivateUI();
  showAuth('登录已失效，请重新登录。未保存草稿仅能由原账号恢复。');
}
async function enterWorkspace(user) {
  state.epoch += 1;
  state.user = user;
  window.Encouragement?.enter(user);
  window.Footprints?.enter(user);
  if (state.draft && state.draft.userId !== user.id) state.draft = null;
  $('auth-screen').hidden = true;
  $('workspace').hidden = false;
  $('boot').hidden = true;
  $('password').value = '';
  $('account-name').textContent = user.username;
  $('avatar').textContent = user.username.slice(0, 1).toUpperCase();
  window.DeepSeekSettings?.refresh();
  setTab('in_progress', false);
  await window.LoadWorkspace?.enter(user);
  $('draft-recovery').hidden = !(state.draft || window.Execution?.hasDraft(user) || window.LoadWorkspace?.hasDraft(user));
}
function setAuthMode(mode) {
  state.authMode = mode;
  $('login-tab').classList.toggle('active', mode === 'login');
  $('register-tab').classList.toggle('active', mode === 'register');
  $('auth-title').textContent = mode === 'login' ? '欢迎回来' : '从一片留白开始';
  $('auth-description').textContent = mode === 'login' ? '登录，继续照顾那些重要的小事。' : '创建属于你的空间，让想法慢慢生长。';
  $('auth-submit').textContent = mode === 'login' ? '进入我的空间 ↗' : '创建我的空间 ↗';
  $('password').autocomplete = mode === 'login' ? 'current-password' : 'new-password';
  $('password').minLength = mode === 'login' ? 1 : 10;
  $('password-hint').hidden = mode === 'login';
  showError('auth-error', '');
}
$('login-tab').addEventListener('click', () => setAuthMode('login'));
$('register-tab').addEventListener('click', () => setAuthMode('register'));
$('auth-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if ($('auth-submit').disabled) return;
  $('auth-submit').disabled = true;
  $('login-tab').disabled = true;
  $('register-tab').disabled = true;
  showError('auth-error', '');
  try {
    const result = await api(`/api/auth/${state.authMode}`, { method: 'POST', body: { username: $('username').value, password: $('password').value }, protectedRequest: false });
    await enterWorkspace(result.user);
  } catch (error) { showError('auth-error', error.message); }
  finally { $('auth-submit').disabled = false; $('login-tab').disabled = false; $('register-tab').disabled = false; }
});
$('logout').addEventListener('click', async () => {
  $('logout').disabled = true;
  try {
    await api('/api/auth/logout', { method: 'POST' });
    state.epoch += 1;
    state.user = null;
    state.draft = null;
    clearPrivateUI();
    setAuthMode('login');
    showAuth();
  } catch (error) { if (error.status !== 401) toast(error.message, true); }
  finally { $('logout').disabled = false; }
});
function setTab(tab, load = true) {
  state.tab = tab;
  const [title, description, listTitle, emptyTitle, emptyCopy] = tabs[tab];
  $('breadcrumb-current').textContent = title;
  $('page-title').replaceChildren(text('span', title), text('span', '.', 'title-dot'));
  $('page-description').textContent = description;
  $('list-title').textContent = listTitle;
  $('empty-title').textContent = emptyTitle;
  $('empty-copy').textContent = emptyCopy;
  document.querySelectorAll('[data-tab]').forEach((el) => { el.classList.toggle('active', el.dataset.tab === tab); el.setAttribute('aria-current', el.dataset.tab === tab ? 'page' : 'false'); });
  if (load) loadTasks(false);
}
document.querySelectorAll('[data-tab]').forEach((el) => el.addEventListener('click', () => { $('search').value = ''; window.LoadWorkspace.navigate(`tasks/${el.dataset.tab}`); }));
async function loadTasks(refreshLoad = true) {
  if (refreshLoad) window.LoadWorkspace?.invalidate();
  const sequence = ++state.load;
  $('task-list').setAttribute('aria-busy', 'true');
  showError('load-error-text', '');
  $('load-error').hidden = true;
  try {
    const params = new URLSearchParams({ status: state.tab, q: $('search').value.trim() });
    const result = await api(`/api/tasks?${params}`);
    if (sequence !== state.load || !state.user) return;
    state.tasks = result.tasks;
    state.counts = result.counts;
    renderTasks();
  } catch (error) {
    if (error.status === 401 || error.status === -1 || sequence !== state.load) return;
    state.tasks = [];
    $('task-list').replaceChildren();
    $('empty').hidden = true;
    $('load-error').hidden = false;
    $('load-error-text').textContent = '清单读取失败，请检查连接后重试。';
  } finally { if (sequence === state.load) $('task-list').setAttribute('aria-busy', 'false'); }
}
function hours(minutes) {
  return window.Duration.format(minutes, '未估计');
}
function renderTasks() {
  const counts = state.counts;
  document.querySelectorAll('[data-count]').forEach((el) => { const key = el.dataset.count; el.textContent = key === 'history' ? (counts.completed || 0) + (counts.abandoned || 0) : counts[key] || 0; });
  $('stat-current').textContent = counts.in_progress || 0;
  $('stat-planned').textContent = counts.planned || 0;
  $('stat-completed').textContent = counts.completed || 0;
  const tasks = [...state.tasks];
  if ($('sort').value === 'priority') { const weight = { high: 0, normal: 1, low: 2 }; tasks.sort((a, b) => weight[a.priority] - weight[b.priority]); }
  $('task-list').replaceChildren();
  $('visible-count').textContent = tasks.length;
  $('empty').hidden = tasks.length > 0;
  if ($('search').value.trim()) {
    $('empty-title').textContent = '还没有找到这件事';
    $('empty-copy').textContent = '试试其他关键词，或切换任务区域。';
    $('empty-new').hidden = true;
  } else {
    $('empty-title').textContent = tabs[state.tab][3];
    $('empty-copy').textContent = tabs[state.tab][4];
    $('empty-new').hidden = state.tab === 'trash';
  }
  tasks.forEach((task) => {
    const deleted = state.tab === 'trash';
    const wrapper = text('div', '', 'task-row'); wrapper.dataset.taskRow = task.id;
    const row = text(deleted ? 'article' : 'button', '', 'task-card'); if (!deleted) row.type = 'button';
    row.dataset.taskId = task.id;
    const main = text('div', '', 'task-main');
    main.append(text('span', task.title, 'task-name'));
    const sub = text('span', '', 'task-sub');
    sub.append(text('span', kinds[task.kind]), text('span', '·'), text('span', deleted ? `原状态：${labels[task.status]}` : priorities[task.priority], !deleted && task.priority === 'high' ? 'priority-high' : ''));
    main.append(sub);
    const time = text('div', hours(task.weekly_minutes), 'task-time');
    if (task.weekly_minutes !== null) time.append(text('span', deleted ? '/ 原预计投入' : task.status !== 'in_progress' ? '/ 开始后计入' : task.budget_schedule === 'recurring' ? '/ 每周投入' : `/ ${task.budget_week || '所选周'}`));
    row.append(text('span', { general: '◇', study: '⌘', work: '▤', life: '✳' }[task.kind], `task-symbol ${task.kind}`), main, time, text('span', deleted ? '已收起' : labels[task.status], `status-badge status-${task.status}`));
    if (!deleted) { row.append(text('span', '›', 'task-arrow')); row.addEventListener('click', () => window.LoadWorkspace.openTask(task.id)); }
    const action = text('button', deleted ? '恢复' : '删除', deleted ? 'task-restore' : 'task-delete'); action.type = 'button';
    action.dataset[deleted ? 'restoreTask' : 'deleteTask'] = task.id;
    action.setAttribute('aria-label', `${deleted ? '恢复' : '删除'}「${task.title}」`);
    action.addEventListener('click', () => window.TaskTrash?.start(task, deleted ? 'restore' : 'trash'));
    action.disabled = Boolean(state.busy || window.TaskTrash?.pending());
    wrapper.append(row, action); $('task-list').append(wrapper);
  });
}
$('search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadTasks(false), 180); });
$('sort').addEventListener('change', renderTasks);
$('retry-list').addEventListener('click', () => loadTasks(false));
function readRaw() {
  return { title: $('task-title').value, description: $('task-description').value, kind: $('task-kind').value, priority: $('task-priority').value, status: $('task-status').value, hours: $('task-hours').value, budget_schedule: $('task-budget-schedule').value, budget_week: $('task-budget-week').value };
}
function fillRaw(raw) {
  $('task-title').value = raw.title;
  $('task-description').value = raw.description;
  $('task-kind').value = raw.kind;
  $('task-priority').value = raw.priority;
  $('task-status').value = raw.status;
  $('task-hours').value = raw.hours;
  $('task-budget-schedule').value = raw.budget_schedule || 'weekly';
  $('task-budget-week').value = raw.budget_week || window.LoadWorkspace?.selectedWeek() || window.BudgetReservation.currentMonday();
  updateScheduleHelp();
}
function updateScheduleHelp() {
  const recurring = $('task-budget-schedule').value === 'recurring';
  $('task-budget-week-label').textContent = recurring ? '从哪一周开始' : '安排在哪一周';
  $('task-hours-label').textContent = recurring ? '预计每周投入（小时，可后补）' : '预计本周投入（小时，可后补）';
  $('task-budget-help').textContent = recurring ? '先记录想法，只有开始投入后才按所选起始周持续计入每周预算。暂停、完成或放弃后停止占用；实际耗时另行保留。' : '想法不占用预算，开始投入后才在所选周计入。时间可稍后补充；进行中未估时会提示待确认，填写 0 表示明确不占用。';
}
$('task-budget-schedule').addEventListener('change', updateScheduleHelp);
$('task-budget-week').addEventListener('change', () => {
  if ($('task-budget-week').value) $('task-budget-week').value = window.BudgetReservation.monday($('task-budget-week').value);
});
function openEditor(task = null, events = []) {
  if (state.busy) return;
  window.Encouragement?.dismiss();
  state.editing = task;
  state.createKey = crypto.randomUUID();
  $('task-form').reset();
  fillRaw(task ? { ...task, hours: task.weekly_minutes === null ? '' : String(task.weekly_minutes / 60) } : { title: '', description: '', kind: 'general', priority: 'normal', status: 'planned', hours: '' });
  state.baseline = JSON.stringify(readRaw());
  $('task-more-settings').open = Boolean(task);
  $('editor-heading').textContent = task ? '照顾这件事' : '记录一个想法';
  $('editor-help').textContent = task ? '进行中的时间会计入预算；暂停或结束后释放占用，状态变化会留下记录。' : '先写下你在想什么，只需要一个名称。保存到想法池，开始投入以后才占用预算。';
  $('save-task').textContent = task ? '保存修改' : '保存想法';
  $('delete-task').hidden = !task;
  $('delete-task').disabled = Boolean(window.TaskTrash?.pending());
  $('save-indicator').textContent = task ? '已载入保存记录' : '尚未保存';
  showError('save-error', '');
  $('reload-task').hidden = true;
  $('quick-actions').replaceChildren();
  if (task) {
    const executionButton = text('button', '分析与执行 ↗', 'primary'); executionButton.type = 'button';
    executionButton.addEventListener('click', () => window.Execution.open(task.id)); $('quick-actions').append(executionButton);
    const actions = task.status === 'in_progress' ? [['paused', '暂停一下'], ['completed', '标记完成'], ['abandoned', '决定放弃']] : [['in_progress', task.status === 'planned' ? '开始投入' : '恢复进行']];
    actions.forEach(([status, label]) => { const button = text('button', label, 'secondary'); button.type = 'button'; button.addEventListener('click', () => { if (status === 'completed') { window.Execution.open(task.id, 'steps'); return; } $('task-status').value = status; $('task-form').requestSubmit(); }); $('quick-actions').append(button); });
  }
  $('event-list').replaceChildren();
  $('history-section').hidden = !task;
  if (!events.length && task) $('event-list').append(text('li', '还没有状态变化。'));
  events.slice().reverse().forEach((event) => { const item = text('li', `${labels[event.from_status]} → ${labels[event.to_status]}`); item.append(text('time', new Date(event.created_at).toLocaleString('zh-CN', { hour12: false }))); $('event-list').append(item); });
  if (!$('task-dialog').open) $('task-dialog').showModal();
  $('task-title').focus();
}
async function fetchEditor(id) {
  const epoch = state.epoch, route = location.hash;
  try { const result = await api(`/api/tasks/${id}`); if (epoch !== state.epoch || route !== location.hash) return; openEditor(result.task, result.events); }
  catch (error) { if (error.status !== 401 && error.status !== -1) toast(error.message, true); }
}
function closeEditor() {
  if (state.busy) return;
  if (state.baseline !== JSON.stringify(readRaw()) && !confirm('还有未保存的修改，确定放弃这些修改吗？')) return;
  $('task-dialog').close();
  state.editing = null;
  window.LoadWorkspace?.dialogClosed();
}
$('new-task').addEventListener('click', () => window.LoadWorkspace.navigate('new'));
$('empty-new').addEventListener('click', () => window.LoadWorkspace.navigate('new'));
$('close-editor').addEventListener('click', closeEditor);
$('cancel-editor').addEventListener('click', closeEditor);
$('task-dialog').addEventListener('cancel', (event) => { event.preventDefault(); closeEditor(); });
$('task-form').addEventListener('input', () => { $('save-indicator').textContent = '有未保存的修改'; });
$('reload-task').addEventListener('click', () => { if (state.editing && confirm('重新载入会替换当前输入。请先复制需要保留的内容，确定继续吗？')) fetchEditor(state.editing.id); });
function setSaving(busy) {
  state.busy = busy;
  $('new-task').disabled = busy;
  $('empty-new').disabled = busy;
  $('task-form').querySelectorAll('input, textarea, select, button').forEach((el) => { el.disabled = busy; });
  $('close-editor').disabled = busy;
  $('delete-task').disabled = busy || Boolean(window.TaskTrash?.pending());
  $('save-task').textContent = busy ? '正在保存…' : state.editing ? '保存修改' : '保存想法';
  window.TaskTrash?.syncControls();
}
$('task-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (state.busy) return;
  showError('save-error', '');
  const raw = readRaw();
  const minutes = raw.hours === '' ? null : Number(raw.hours) * 60;
  if (minutes !== null && (!Number.isFinite(minutes) || minutes < 0 || minutes > 10080 || Math.abs(Math.round(minutes) - minutes) > 1e-7)) {
    showError('save-error', '每周时间需要在 0–168 小时之间，精确到整数分钟。'); return;
  }
  if (!raw.budget_week) { showError('save-error', '请选择安排所在的一周。'); return; }
  const data = { title: raw.title, description: raw.description, kind: raw.kind, priority: raw.priority, status: raw.status, weekly_minutes: minutes === null ? null : Math.round(minutes), budget_schedule: raw.budget_schedule, budget_week: window.BudgetReservation.monday(raw.budget_week) };
  const editing = state.editing;
  const completionContext = {owner:state.user?.id, epoch:state.epoch, feedback:window.Encouragement?.context()};
  setSaving(true);
  try {
    const result = await api(editing ? `/api/tasks/${editing.id}` : '/api/tasks', { method: editing ? 'PATCH' : 'POST', body: editing ? { ...data, version: editing.version } : data, headers: editing ? {} : { 'Idempotency-Key': state.createKey } });
    $('task-dialog').close();
    state.editing = null;
    state.draft = null;
    $('search').value = '';
    window.LoadWorkspace?.dialogClosed();
    await loadTasks();
    toast(result.task.status === 'planned' ? '想法已记录，尚未开始，不占用预算。' : result.task.status === 'in_progress' ? '已保存，进行中的投入已更新到预算。' : '已保存，当前状态不占用预算。');
    if (editing && editing.status !== 'completed' && result.task.status === 'completed') {
      // The save has succeeded. Optional feedback cannot turn it into a failed save.
      void api(`/api/tasks/${result.task.id}/workspace`).then((workspace) => {
        if (completionContext.epoch !== state.epoch || completionContext.owner !== state.user?.id || workspace.task?.version !== result.task.version || $('task-dialog').open || $('execution-dialog').open) return;
        window.Encouragement?.completed({owner:completionContext.owner, taskId:result.task.id, result:workspace, context:completionContext.feedback});
      }).catch(() => {});
    }
    if (!editing && state.user) await window.BudgetReservation.show(result.task);
  } catch (error) {
    if (error.status !== 401 && error.status !== -1) {
      showError('save-error', error.message);
      $('save-indicator').textContent = '未确认保存成功';
      $('reload-task').hidden = !(error.status === 409 && editing);
    }
  } finally { setSaving(false); }
});
window.addEventListener('beforeunload', (event) => { if ($('task-dialog').open && state.baseline !== JSON.stringify(readRaw())) { event.preventDefault(); event.returnValue = ''; } });
$('today').textContent = new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' });
// All deferred workspace modules must register before restoring a signed-in session.
document.addEventListener('DOMContentLoaded', async () => {
  try { const result = await api('/api/me', { protectedRequest: false }); await enterWorkspace(result.user); }
  catch (error) { showAuth(error.status === 401 ? '' : '暂时无法连接，请稍后重试登录。'); }
}, {once:true});

document.addEventListener('visibilitychange', async () => {
  if (document.visibilityState === 'visible' && state.user) {
    try { await api('/api/me'); } catch (error) { if (error.status !== 401 && error.status !== -1) toast('暂时无法核对登录状态，请检查连接。', true); }
  }
});

$('restore-draft').addEventListener('click', async () => {
  if (!state.user) return;
  if (state.draft?.userId === state.user.id) {
    const draft = state.draft; state.draft = null;
    openEditor(draft.editing); fillRaw(draft.raw); state.createKey = draft.key; state.baseline = draft.baseline;
    showError('save-error', '已恢复本账号的未保存输入，请核对后保存。');
  } else if (window.Execution?.hasDraft(state.user)) await window.Execution.resume(state.user);
  else await window.LoadWorkspace?.restoreDraft(state.user);
  $('draft-recovery').hidden = !(state.draft || window.Execution?.hasDraft(state.user) || window.LoadWorkspace?.hasDraft(state.user));
});
