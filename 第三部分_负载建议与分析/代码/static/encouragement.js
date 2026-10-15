'use strict';
(() => {
  const toggle = document.getElementById('encouragement-toggle');
  const card = document.createElement('aside');
  card.id = 'encouragement-toast';
  card.className = 'encouragement-toast';
  card.hidden = true;
  card.setAttribute('role', 'status');
  card.setAttribute('aria-live', 'polite');
  card.setAttribute('aria-atomic', 'true');
  const title = document.createElement('strong');
  title.id = 'encouragement-title';
  const detail = document.createElement('p');
  detail.id = 'encouragement-detail';
  const progress = document.createElement('p');
  progress.id = 'encouragement-progress';
  const close = document.createElement('button');
  close.id = 'encouragement-close';
  close.type = 'button';
  close.className = 'encouragement-close';
  close.textContent = '×';
  close.setAttribute('aria-label', '收起这句鼓励');
  card.append(title, detail, progress, close);
  document.body.append(card);

  const stepMessages = [
    '又完成一小步，挺好的。',
    '这一小步已经完成了。',
    '你刚刚做成的这一步，值得记下来。',
    '做到这里也不错，歇一下也可以。',
    '一点一点，想做的事正在成为现实。',
  ];
  const taskMessages = [
    '这件事，可以安心收尾了。',
    '又少了一件挂心的事。',
    '这段投入有了一个落点。',
    '完成了，给自己留一点休息的时间吧。',
  ];
  let owner = null, enabled = true, timer = null, remaining = 6000, started = 0;
  let showCount = 0, lastStep = -1, lastTask = -1, revision = 0;
  const seen = new Set();
  const paused = new Set();
  const preferenceKey = () => `liubai:encouragement:${owner}`;

  function syncToggle() {
    if (!toggle) return;
    toggle.textContent = `完成鼓励：${enabled ? '开' : '关'}`;
    toggle.setAttribute('aria-pressed', String(enabled));
    toggle.title = '完成步骤或任务后，显示一句鼓励；偏好仅保存在本机当前账号。';
    toggle.disabled = owner === null;
  }
  function dismiss(invalidate = true) {
    if (invalidate) revision += 1;
    clearTimeout(timer);
    timer = null;
    paused.clear();
    remaining = 6000;
    card.hidden = true;
    title.textContent = detail.textContent = progress.textContent = '';
    delete card.dataset.eventId;
    delete card.dataset.taskId;
    // A closed modal must never retain a previous task's visible content.
    if (card.parentElement !== document.body) document.body.append(card);
  }
  function schedule() {
    clearTimeout(timer);
    timer = null;
    if (card.hidden || paused.size) return;
    started = performance.now();
    timer = setTimeout(() => dismiss(false), Math.max(0, remaining));
  }
  function pause(reason) {
    if (card.hidden || paused.has(reason)) return;
    if (!paused.size && timer !== null) remaining = Math.max(0, remaining - (performance.now() - started));
    paused.add(reason);
    clearTimeout(timer);
    timer = null;
  }
  function resume(reason) {
    paused.delete(reason);
    if (!paused.size) schedule();
  }
  card.addEventListener('pointerenter', () => pause('pointer'));
  card.addEventListener('pointerleave', () => resume('pointer'));
  card.addEventListener('focusin', () => pause('focus'));
  card.addEventListener('focusout', (event) => {
    if (!card.contains(event.relatedTarget)) resume('focus');
  });
  close.addEventListener('click', () => dismiss(false));

  function enter(user) {
    const next = user?.id === undefined || user?.id === null ? null : String(user.id);
    if (next !== owner) {
      dismiss();
      seen.clear();
      showCount = 0;
      card.dataset.showCount = '0';
      lastStep = lastTask = -1;
    }
    owner = next;
    enabled = true;
    if (owner !== null) {
      try { enabled = localStorage.getItem(preferenceKey()) !== 'false'; } catch { /* Storage is optional. */ }
    }
    syncToggle();
  }
  function lock() {
    dismiss();
    owner = null;
    enabled = true;
    seen.clear();
    showCount = 0;
    card.dataset.showCount = '0';
    syncToggle();
  }
  toggle?.addEventListener('click', () => {
    if (owner === null || String(state.user?.id) !== owner) return;
    enabled = !enabled;
    try { localStorage.setItem(preferenceKey(), String(enabled)); } catch { /* Keep the choice for this session. */ }
    if (!enabled) dismiss();
    syncToggle();
  });

  function completed({owner: receiptOwner, taskId, result, stepId = null, host = null, context = null}) {
    try {
      if (owner === null || String(receiptOwner) !== owner || String(state.user?.id) !== owner) return;
      if (context !== null && context !== revision) return;
      if (!result?.task || result.task.id !== taskId) return;
      const step = stepId === null ? null : result.steps?.find((item) => item.id === stepId);
      if (stepId !== null && !step) return;
      const target = step || result.task;
      const record = step ? step.completion : result.completion;
      if (target.status !== 'completed' || !Number.isSafeInteger(record?.event_id) || record.event_id < 1) return;
      const eventKey = `${owner}:${record.event_id}`;
      if (seen.has(eventKey)) return;
      seen.add(eventKey);
      if (!enabled) return;
      // Showing inside the current modal keeps feedback above its top-layer backdrop.
      const activeDialog = host?.tagName === 'DIALOG' && host.open ? host : null;
      if (host && !activeDialog) return;
      if (card.parentElement !== (activeDialog || document.body)) (activeDialog || document.body).append(card);
      clearTimeout(timer);
      timer = null;
      paused.clear();
      remaining = 6000;
      const messages = step ? stepMessages : taskMessages;
      const previous = step ? lastStep : lastTask;
      let index = Math.floor(Math.random() * messages.length);
      if (index === previous) index = (index + 1) % messages.length;
      if (step) lastStep = index; else lastTask = index;
      title.textContent = messages[index];
      detail.textContent = `已完成「${target.title}」`;
      const steps = Array.isArray(result.steps) ? result.steps : [];
      const count = steps.filter((item) => item.status === 'completed').length;
      progress.textContent = step
        ? `已完成步骤 ${count} / ${steps.length} · 只是步骤数量，不代表耗时进度。`
        : '这份进展已经记下，接下来可以按自己的节奏来。';
      card.dataset.eventId = String(record.event_id);
      card.dataset.taskId = taskId;
      card.dataset.showCount = String(++showCount);
      close.disabled = false;
      card.hidden = false;
      if (card.matches(':hover')) paused.add('pointer');
      if (card.contains(document.activeElement)) paused.add('focus');
      schedule();
    } catch { /* Encouragement must never change a successful save into an error. */ }
  }
  card.dataset.showCount = '0';
  window.Encouragement = {enter, lock, dismiss, completed, context:() => revision};
  enter(state.user);
})();
