'use strict';
(() => {
  const anchor = $('footprints-panel');
  if (!anchor) return;
  const rules = window.OverviewFocusRules;
  const panel = document.createElement('section');
  panel.id = 'overview-focus'; panel.className = 'overview-focus';
  panel.setAttribute('aria-labelledby', 'overview-focus-heading');
  panel.innerHTML = `<div class="overview-focus-body"><h2 id="overview-focus-heading">继续手头的事</h2><strong id="overview-focus-title"></strong><p id="overview-focus-copy">正在读取可继续的事情…</p></div><div class="overview-focus-actions"><button id="overview-focus-steps" type="button" class="primary" hidden>继续一个步骤 ↗</button><button id="overview-focus-ledger" type="button" class="secondary" hidden>记录耗时</button><button id="overview-focus-ideas" type="button" class="secondary" hidden>去想法池看看</button><button id="overview-focus-new" type="button" class="primary" hidden>记录想法</button></div>`;
  anchor.before(panel);
  const model = {owner: null, epoch: -1, tasks: null, remembered: null, selected: null};
  const current = () => rules.contextMatches(model, state.user?.id, state.epoch);
  const storageKey = () => `liubai.phase5.overview.last-task.${model.owner}`;
  const taskButtons = ['overview-focus-steps', 'overview-focus-ledger'];
  const ideaButtons = ['overview-focus-ideas', 'overview-focus-new'];
  function display() {
    const ready = current() && Array.isArray(model.tasks);
    const task = ready ? rules.chooseTask(model.tasks, model.remembered) : null;
    model.selected = task;
    panel.dataset.state = !ready ? 'loading' : task ? 'task' : 'empty';
    if (task) panel.dataset.taskId = task.id; else delete panel.dataset.taskId;
    $('overview-focus-heading').textContent = task && task.id === model.remembered ? '继续上次查看' : '继续手头的事';
    $('overview-focus-title').textContent = task?.title || '';
    $('overview-focus-title').hidden = !task;
    $('overview-focus-copy').textContent = !ready ? '正在读取可继续的事情…' : task ? '选一个小步骤继续，或记下刚才的投入。' : '现在没有进行中的事，可以从想法池选一件，也可以先记下来。';
    if (task) $('overview-focus-copy').textContent = (priorities[task.priority] || '普通优先级') + ' · 做完下面这一步，就可以直接勾选。';
    panel.querySelector('.inline-step-preview')?.remove();
    const preview = task ? window.InlineSteps?.preview(task) : null;
    if (preview) panel.append(preview);
    panel.classList.toggle('has-steps', Boolean(preview));
    $('overview-focus-steps').textContent = task?.step_preview?.total ? '全部步骤 / 完成记录 ↗' : '拆分 / 查看步骤 ↗';
    taskButtons.forEach((id) => { $(id).hidden = !task; $(id).disabled = !task; });
    ideaButtons.forEach((id) => { $(id).hidden = !ready || Boolean(task); $(id).disabled = !ready; });
  }
  function lock() {
    model.owner = null; model.epoch = -1; model.tasks = null; model.remembered = null; model.selected = null;
    display();
  }
  function enter(user) {
    lock(); model.owner = user.id; model.epoch = state.epoch;
    try { model.remembered = rules.parseId(localStorage.getItem(storageKey())); } catch { model.remembered = null; }
    display();
  }
  function render(data) {
    if (!current()) return;
    model.tasks = Array.isArray(data?.tasks) ? data.tasks.slice() : null;
    display();
  }
  function invalidate() {
    model.tasks = null; model.selected = null; display();
  }
  function remember(task, ctx) {
    if (!current() || !rules.contextMatches(ctx, model.owner, model.epoch) || !task) return;
    if (model.tasks) model.tasks = model.tasks.map((item) => item.id === task.id ? {...item, ...task} : item);
    if (rules.chooseTask([task], task.id)) {
      model.remembered = task.id;
      try { localStorage.setItem(storageKey(), JSON.stringify(task.id)); } catch { /* Continue in memory when browser storage is unavailable. */ }
    }
    display();
  }
  function open(section) {
    if (!current() || !model.selected) return;
    const task = rules.chooseTask(model.tasks, model.selected.id);
    if (task?.id === model.selected.id) window.LoadWorkspace?.openTask(task.id, section);
  }
  $('overview-focus-steps').addEventListener('click', () => open('steps'));
  $('overview-focus-ledger').addEventListener('click', () => open('ledger'));
  $('overview-focus-ideas').addEventListener('click', () => { if (current()) window.LoadWorkspace?.navigate('tasks/planned'); });
  $('overview-focus-new').addEventListener('click', () => { if (current()) window.LoadWorkspace?.navigate('new'); });
  window.OverviewFocus = Object.freeze({enter, lock, render, invalidate, remember});
  display();
})();
