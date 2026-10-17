'use strict';
(() => {
  const feedback = document.createElement('section');
  feedback.id = 'inline-step-feedback';
  feedback.className = 'inline-step-feedback';
  feedback.hidden = true;
  feedback.tabIndex = -1;
  feedback.setAttribute('aria-label', '步骤操作结果');
  feedback.innerHTML = '<p class="inline-step-message" role="status" aria-live="polite"></p><div class="inline-step-actions"><button id="inline-step-retry" type="button" class="secondary" hidden>重试同一次操作</button><button id="inline-step-undo" type="button" class="secondary" hidden>撤销刚才完成</button><button id="inline-step-record" type="button" class="text-button" hidden>查看 / 修改完成记录 ↗</button></div>';
  $('task-section').before(feedback);
  const model = {pending: null, busy: false, last: null, message: ''};
  const context = () => ({owner: state.user?.id, epoch: state.epoch});
  const current = (ctx) => Boolean(state.user && ctx.owner === state.user.id && ctx.epoch === state.epoch);
  const locked = () => model.busy || Boolean(model.pending) || !state.user;

  function sync() {
    document.querySelectorAll('[data-complete-step]').forEach((el) => { el.disabled = locked(); });
    feedback.hidden = !model.message;
    feedback.querySelector('.inline-step-message').textContent = model.message;
    $('inline-step-retry').hidden = !model.pending;
    $('inline-step-retry').disabled = model.busy;
    $('inline-step-undo').hidden = !model.last;
    $('inline-step-undo').disabled = locked();
    $('inline-step-record').hidden = !model.last;
    $('inline-step-record').disabled = locked();
    feedback.setAttribute('aria-busy', String(model.busy));
  }
  function lock() {
    model.pending = null; model.busy = false; model.last = null; model.message = '';
    sync();
  }
  function preview(task) {
    if (!state.user || task.status !== 'in_progress' || task.deleted_at) return null;
    const ctx = context(), data = task.step_preview;
    const box = text('section', '', 'inline-step-preview');
    box.dataset.taskId = task.id;
    box.dataset.state = data?.state || 'loading';
    box.setAttribute('aria-label', task.title + '的当前步骤');
    if (!data || data.state === 'inactive') {
      box.append(text('p', '步骤信息待刷新。', 'inline-step-hint'));
      return box;
    }
    if (data.total) box.append(text('p', '已完成 ' + data.completed + ' / ' + data.total + ' 个步骤', 'inline-step-progress'));
    if (data.state === 'ready' && data.current) {
      const step = data.current;
      const label = text('label', '', 'inline-step-current');
      const check = document.createElement('input');
      check.type = 'checkbox'; check.dataset.completeStep = step.id; check.disabled = locked();
      check.setAttribute('aria-label', '完成步骤 ' + step.number + '：' + step.title);
      const content = text('span', '', 'inline-step-content');
      content.append(text('small', step.status === 'in_progress' ? '正在做' : '现在可以做'), text('strong', '步骤 ' + step.number + ' · ' + step.title));
      label.append(check, content);
      check.addEventListener('change', () => {
        check.checked = false;
        if (current(ctx)) start(task, step, 'complete', ctx);
      });
      box.append(label);
      if (step.criterion) box.append(text('p', '完成标准：' + step.criterion, 'inline-step-criterion'));
      if (data.next) {
        const next = data.next;
        box.append(text('p', '下一步 · 步骤 ' + next.number + '：' + next.title + '（' + (next.after_current ? '完成当前步骤后可做' : '也可独立进行') + '）', 'inline-step-next'));
      } else {
        box.append(text('p', data.completed + 1 === data.total ? '做完这一步后，可核对整个任务是否完成。' : '后续暂无可直接继续的步骤，可查看全部步骤调整。', 'inline-step-next'));
      }
    } else {
      const hints = {
        empty: '还没有拆成步骤。先选出一件能动手的小事。',
        finished: '步骤已全部完成，请核对后确认整个任务完成。',
        blocked: '暂无可直接继续的步骤，请检查前置依赖、暂停或放弃的步骤。',
      };
      box.append(text('p', hints[data.state] || '步骤信息待刷新。', 'inline-step-hint'));
      const button = text('button', data.state === 'empty' ? '拆分几个小步骤 ↗' : '查看全部步骤 ↗', 'text-button');
      button.type = 'button';
      button.addEventListener('click', () => {
        if (current(ctx)) window.LoadWorkspace?.openTask(task.id, data.state === 'empty' ? 'plan' : 'steps');
      });
      box.append(button);
    }
    return box;
  }
  function start(task, step, action, ctx = context()) {
    if (locked() || !current(ctx)) return;
    model.pending = {
      ctx, taskId: task.id, step, source: document.activeElement,
      body: {action, version: task.version, step_id: step.id},
      key: crypto.randomUUID(), feedback: window.Encouragement?.context(),
    };
    transmit();
  }
  async function refresh() {
    // A replayed receipt may describe an older version; reload canonical server state.
    await loadTasks(false);
    window.LoadWorkspace?.invalidate();
  }
  async function transmit() {
    const packet = model.pending;
    if (!packet || model.busy || !current(packet.ctx)) return;
    model.busy = true;
    model.message = packet.body.action === 'complete' ? '正在登记这一步完成…' : '正在撤销这一步完成…';
    sync();
    try {
      const result = await api('/api/tasks/' + packet.taskId + '/workspace', {
        method: 'POST', body: packet.body, headers: {'Idempotency-Key': packet.key},
      });
      if (!current(packet.ctx) || model.pending !== packet) return;
      const savedStep = Array.isArray(result?.steps) ? result.steps.find((step) => step.id === packet.step.id) : null;
      const expectedStatus = packet.body.action === 'complete' ? 'completed' : packet.step.status;
      if (result?.task?.id !== packet.taskId || !Number.isSafeInteger(result.task.version) ||
          result.task.version <= packet.body.version || savedStep?.status !== expectedStatus) {
        throw new RequestError('保存回执不完整，请核对同一次操作。');
      }
      model.pending = null;
      if (packet.body.action === 'complete') {
        model.last = {ctx: packet.ctx, task: result.task, step: packet.step};
        model.message = '已完成「' + packet.step.title + '」。可以继续下一步；实际耗时可在账本中补记。';
        window.OverviewFocus?.remember(result.task, packet.ctx);
        window.Encouragement?.completed({owner: packet.ctx.owner, taskId: packet.taskId, result, stepId: packet.step.id, context: packet.feedback});
      } else {
        model.last = null;
        model.message = '已撤销「' + packet.step.title + '」的完成，已有耗时仍保留。';
        window.Encouragement?.dismiss();
      }
      await refresh();
    } catch (error) {
      if (!current(packet.ctx) || model.pending !== packet) return;
      if (!error.status || error.status < 400 || error.status >= 500) {
        model.message = '保存结果尚未确认。请重试同一次操作，系统会核对回执，避免重复登记。';
      } else {
        model.pending = null;
        model.message = '本次操作未保存：' + error.message + ' 请核对最新步骤后再操作。';
        if (packet.body.action === 'undo') model.last = null;
        await refresh();
      }
      if (current(packet.ctx)) toast(model.message, true);
    } finally {
      if (current(packet.ctx)) {
        model.busy = false; sync();
        if (document.activeElement === document.body || document.activeElement === packet.source) {
          feedback.focus({preventScroll: true});
        }
      }
    }
  }
  $('inline-step-retry').addEventListener('click', transmit);
  $('inline-step-undo').addEventListener('click', () => {
    const last = model.last;
    if (last && current(last.ctx)) start(last.task, last.step, 'undo', last.ctx);
  });
  $('inline-step-record').addEventListener('click', () => {
    const last = model.last;
    if (last && current(last.ctx) && !locked()) window.LoadWorkspace?.openTask(last.task.id, 'steps');
  });
  window.addEventListener('beforeunload', (event) => {
    if (model.pending) { event.preventDefault(); event.returnValue = ''; }
  });
  window.InlineSteps = Object.freeze({preview, lock, sync});
})();
