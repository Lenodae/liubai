'use strict';
(() => {
  let pendingPacket = null, undoTask = null, working = false, generation = 0, activeRoute = '', queuedNavigation = null;
  const notice = text('aside', '', 'task-trash-notice');
  notice.id = 'task-trash-notice'; notice.hidden = true;
  notice.setAttribute('role', 'status'); notice.setAttribute('aria-live', 'polite');
  const message = text('p'); message.id = 'task-trash-message';
  const actions = text('div', '', 'task-trash-actions');
  const makeButton = (id, label, handler, style = 'secondary') => {
    const button = text('button', label, style); button.id = id; button.type = 'button';
    button.addEventListener('click', handler); actions.append(button); return button;
  };
  const undo = makeButton('task-trash-undo', '撤销删除', () => { if (undoTask) start(undoTask, 'restore'); });
  const openTrash = makeButton('task-trash-open', '查看回收站', () => window.LoadWorkspace?.navigate('tasks/trash'), 'text-button');
  const retry = makeButton('task-trash-retry', '核实并重试', () => transmit());
  const reload = makeButton('task-trash-reload', '重新载入', () => reloadLatest());
  const dismiss = makeButton('task-trash-dismiss', '收起', () => { if (!pendingPacket && !working) clearNotice(); }, 'text-button');
  notice.append(message, actions); document.body.append(notice);

  function reserveNoticeSpace() {
    document.body.classList.toggle('task-trash-visible', !notice.hidden);
    document.documentElement.style.setProperty('--task-trash-space', notice.hidden ? '0px' : `${Math.ceil(notice.getBoundingClientRect().height) + 28}px`);
  }
  new ResizeObserver(reserveNoticeSpace).observe(notice);
  function placeNotice() {
    const host = [...document.querySelectorAll('dialog[open]')].at(-1) || document.body;
    if (notice.parentNode !== host) host.append(notice);
  }
  new MutationObserver(placeNotice).observe(document.body, {subtree:true, attributes:true, attributeFilter:['open']});
  const sameContext = (packet) => packet.owner === state.user?.id && packet.epoch === state.epoch && packet.generation === generation;
  function deferNavigation(run) {
    if (!working) return false;
    queuedNavigation = {run, owner:state.user?.id, epoch:state.epoch, generation};
    return true;
  }
  function finishWork(packet) {
    if (!sameContext(packet)) return;
    working = false; setSaving(false); syncControls();
    const destination = queuedNavigation; queuedNavigation = null;
    if (destination) queueMicrotask(() => { if (sameContext(destination) && !working) destination.run(); });
  }
  function syncControls() {
    document.querySelectorAll('[data-delete-task], [data-restore-task], #delete-task').forEach((button) => { button.disabled = working || state.busy || Boolean(pendingPacket); });
    undo.disabled = openTrash.disabled = retry.disabled = reload.disabled = dismiss.disabled = working || state.busy;
  }
  function feedback(copy, mode) {
    message.textContent = copy; notice.hidden = false;
    notice.dataset.state = mode;
    undo.hidden = mode !== 'trashed'; openTrash.hidden = !['trashed', 'current-trash'].includes(mode);
    retry.hidden = mode !== 'retry'; reload.hidden = mode !== 'conflict';
    dismiss.hidden = !['trashed', 'restored', 'reloaded', 'current-trash'].includes(mode);
    placeNotice(); reserveNoticeSpace(); syncControls();
  }
  function clearNotice() {
    notice.hidden = true; message.textContent = ''; notice.removeAttribute('data-state');
    undoTask = null; [undo, openTrash, retry, reload, dismiss].forEach((button) => { button.hidden = true; });
    document.body.append(notice);
    reserveNoticeSpace();
  }
  function start(task, action, fromEditor = false) {
    if (!state.user || state.busy || working) return;
    if (pendingPacket) { placeNotice(); return; }
    if (!task || !['trash', 'restore'].includes(action)) return;
    if (fromEditor && state.baseline !== JSON.stringify(readRaw()) && !confirm('删除会收起这件事，并放弃面板里尚未保存的修改。已保存的内容可在回收站恢复，继续删除吗？')) return;
    window.Encouragement?.dismiss();
    pendingPacket = {owner:state.user.id, epoch:state.epoch, generation, id:task.id, title:task.title, action,
      body:{action, version:task.version}, key:crypto.randomUUID(), fromEditor};
    undoTask = null;
    void transmit();
  }
  async function currentTask(packet) {
    const detail = () => {
      if (!sameContext(packet)) throw new RequestError('请求已取消。', -1);
      return api(`/api/tasks/${encodeURIComponent(packet.id)}`);
    };
    let task;
    try { task = (await detail()).task; }
    catch (error) {
      if (error.status !== 404) throw error;
      if (!sameContext(packet)) throw new RequestError('请求已取消。', -1);
      const trash = await api('/api/tasks?status=trash');
      task = trash.tasks?.find((item) => String(item.id) === String(packet.id));
      // A different tab may restore it between the detail and collection reads.
      if (!task) task = (await detail()).task;
    }
    if (String(task?.id) !== String(packet.id) || !Number.isSafeInteger(task?.version)) throw new RequestError('暂时无法核实任务的最新状态，请重试同一次操作。');
    return task;
  }
  async function transmit() {
    if (!pendingPacket || working || state.busy || !sameContext(pendingPacket)) return;
    const packet = pendingPacket;
    working = true; activeRoute = location.hash; setSaving(true);
    feedback(packet.action === 'trash' ? `正在把「${packet.title}」移入回收站…` : `正在恢复「${packet.title}」…`, 'working');
    try {
      const result = await api(`/api/tasks/${encodeURIComponent(packet.id)}/lifecycle`, {method:'POST', body:packet.body, headers:{'Idempotency-Key':packet.key}});
      if (!sameContext(packet)) return;
      if (String(result.task?.id) !== String(packet.id) || !Number.isSafeInteger(result.task?.version) || Boolean(result.task?.deleted_at) !== (packet.action === 'trash')) {
        throw new RequestError('暂时无法核实操作结果，请重试同一次操作。');
      }
      packet.acknowledged = true;
      // Idempotency receipts describe the original write, not necessarily now.
      const current = await currentTask(packet);
      if (!sameContext(packet)) return;
      pendingPacket = null;
      if (current.deleted_at) {
        undoTask = packet.action === 'trash' ? current : null;
        if ($('task-dialog').open && String(state.editing?.id) === String(packet.id)) {
          $('task-dialog').close(); state.editing = null; state.baseline = ''; $('task-form').reset();
          window.LoadWorkspace?.dialogClosed();
          activeRoute = location.hash;
        }
        // A saved draft for this task must not reopen a deleted editor later.
        if (String(state.draft?.editing?.id) === String(packet.id)) state.draft = null;
      }
      await loadTasks();
      if (!sameContext(packet)) return;
      if (current.deleted_at) {
        feedback(packet.action === 'trash'
          ? `「${current.title}」已移入回收站，不再占用当前预算。步骤、完成记录和耗时都保留。`
          : `这次恢复已核实，但「${current.title}」已在其他页面再次移入回收站。需要时可前往回收站恢复。`,
        packet.action === 'trash' ? 'trashed' : 'current-trash');
      } else {
        feedback(packet.action === 'trash'
          ? `这次删除已核实，但「${current.title}」已在其他页面恢复。当前状态是${labels[current.status] || '原来的状态'}，预算按现在的安排计算。`
          : `「${current.title}」已恢复到${labels[current.status] || '原来的状态'}，预算会按原状态和估时计算。`, 'restored');
      }
    } catch (error) {
      if (!sameContext(packet) || [401, -1].includes(error.status)) return;
      const conflict = error.status > 0 && error.status < 500;
      feedback(conflict
        ? `${error.message} 任务可能已更新，请重新载入后再操作；当前输入仍保留。`
        : packet.acknowledged
          ? `这次操作已收到回执，但「${packet.title}」的最新状态暂时无法核实。输入仍保留，重试只核实同一次操作。`
          : `尚未确认${packet.action === 'trash' ? '删除' : '恢复'}「${packet.title}」成功。任务和输入仍保留，重试会核实同一次操作。`,
      conflict ? 'conflict' : 'retry');
    } finally {
      finishWork(packet);
    }
  }
  async function reloadLatest() {
    if (!pendingPacket || working || state.busy) return;
    const packet = pendingPacket;
    const editingThis = $('task-dialog').open && String(state.editing?.id) === String(packet.id);
    if (editingThis && state.baseline !== JSON.stringify(readRaw()) && !confirm('重新载入会替换面板里的未保存修改。请先复制需要保留的内容，确定继续吗？')) return;
    working = true; activeRoute = location.hash; setSaving(true); syncControls();
    try {
      const latest = editingThis ? await api(`/api/tasks/${encodeURIComponent(packet.id)}`) : null;
      if (!sameContext(packet)) return;
      await loadTasks();
      if (!sameContext(packet)) return;
      pendingPacket = null; working = false; setSaving(false);
      if (latest && $('task-dialog').open && String(state.editing?.id) === String(packet.id)) openEditor(latest.task, latest.events);
      feedback('已重新载入最新清单，请核对后再决定删除或恢复。', 'reloaded');
    } catch (error) {
      if (!sameContext(packet) || [401, -1].includes(error.status)) return;
      if (error.status === 404 && editingThis) {
        pendingPacket = null; $('task-dialog').close(); state.editing = null; state.baseline = ''; $('task-form').reset(); window.LoadWorkspace?.dialogClosed();
        await loadTasks();
        if (sameContext(packet)) feedback('这件事已不在当前清单，可到回收站查看并恢复。', 'reloaded');
      } else feedback('最新清单暂时无法读取，原输入仍保留，请稍后重新载入。', 'conflict');
    } finally {
      finishWork(packet);
    }
  }
  function lock() {
    const wasWorking = working;
    generation += 1; pendingPacket = null; undoTask = null; working = false; activeRoute = ''; queuedNavigation = null;
    if (wasWorking) setSaving(false);
    clearNotice(); syncControls();
  }
  $('delete-task').addEventListener('click', () => start(state.editing, 'trash', true));
  window.TaskTrash = {start, lock, syncControls, deferNavigation, busy:()=>working, pending:()=>Boolean(pendingPacket), route:()=>activeRoute};
})();
