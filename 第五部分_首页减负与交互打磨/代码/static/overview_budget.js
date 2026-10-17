'use strict';
(() => {
  // These helpers only present already-read facts. They never save a budget.
  const node = (tag, content = '', className = '') => text(tag, content, className);
  const help = $('overview-budget-help');
  const guide = document.createElement('dialog');
  guide.id = 'overview-budget-guide';
  guide.className = 'load-dialog overview-budget-guide';
  guide.setAttribute('aria-labelledby', 'overview-budget-guide-title');
  guide.innerHTML = `
    <div class="load-heading"><h2 id="overview-budget-guide-title" tabindex="-1">预算怎么填</h2><button id="overview-budget-guide-close" class="icon-button" type="button" aria-label="关闭预算说明">×</button></div>
    <p class="overview-budget-definition"><strong>总预算，就是这段时间准备分给这里这些任务的总时间。</strong>留白已经包含在总预算里，不是另外加上的时间。</p>
    <section class="overview-budget-example" aria-labelledby="overview-budget-example-title">
      <h3 id="overview-budget-example-title">用这一周举个例子</h3>
      <dl><dt>准备分给这些任务</dt><dd>20 小时</dd><dt>其中留白</dt><dd>2 小时</dd><dt>进行中任务预计投入</dt><dd>6 小时</dd><dt>可安排容量</dt><dd>20 − 2 = 18 小时</dd><dt>可再安排</dt><dd>18 − 6 = 12 小时</dd><dt>时间负载</dt><dd>6 ÷ 18 ≈ 33%</dd></dl>
      <p>如果另记了实际投入 <strong>1 小时</strong>，它会显示在实际记录里，<strong>不会自动再扣减</strong>这份计划。</p>
    </section>
    <section><h3>睡眠、工作会不会算两次？</h3><p>如果你填的是扣除睡眠、工作后的可用时间，就不要再把已经扣除的部分作为进行中任务计入。如果希望圆盘也包含睡眠、工作，总预算就要包含它们对应的时间。</p></section>
    <section><h3>整周和本周剩余，要分别确认</h3><p><strong>整周计划</strong>看这一整周的安排。<strong>本周剩余时间</strong>只看当前确认时点之后，预算和预计投入要单独确认；不会用整周值自动减去已记耗时。跨日后，请重新确认剩余安排。</p></section>
    <section><h3>预计投入与实际记录，各自说明一件事</h3><p>只有进行中的事情占用当前预算；想法、暂停和结束的事情不占用。长期事项在进行中时每周计入。实际耗时来自你记录的账本，反映已经做过的事情。</p><p>留空表示还不知道，填 0 表示确认不安排时间。时间负载百分比只说明计划排了多少，不能替你判断精力；觉得累了，也可以减少安排。</p></section>
    <p class="overview-budget-guide-footer">这里仅作说明，不会修改任何预算。可以按 Esc 关闭，接着填写。</p>`;
  document.body.append(guide);
  let sourcesOpen = false;
  function closeGuide() { guide.close(); }
  help.addEventListener('click', () => {
    if (!guide.open) guide.showModal();
    $('overview-budget-guide-title').focus({ preventScroll: true });
  });
  $('overview-budget-guide-close').addEventListener('click', closeGuide);

  function routeChanged(route) {
    const sources = $('overview-budget-sources');
    if (sources) sources.open = route === 'overview' ? sourcesOpen : true;
  }
  function render(data, chart) {
    const w = data.window || {};
    $('overview-budget-first-hint').hidden = w.budget_minutes != null && w.buffer_minutes != null;
    const source = chart.querySelector('.budget-chart-tasks');
    if (source) {
      const details = node('details', '', 'overview-budget-sources');
      details.id = 'overview-budget-sources';
      const title = source.querySelector('h4');
      const unknownIds = new Set((data.analysis?.unknowns || []).map((item) => item.task_id).filter(Boolean));
      const needsTime = [...source.querySelectorAll('[data-budget-task]')].some((item) => unknownIds.has(item.dataset.budgetTask));
      const summary = node('summary');
      const label = node('span', `${title?.textContent || '圆盘中的投入来源'} · ${source.querySelectorAll('[data-budget-task]').length} 项`);
      const hint = node('span', needsTime ? '有待补时间' : '', 'overview-source-warning');
      hint.hidden = !needsTime;
      const action = node('span', '', 'overview-source-action');
      summary.append(label, hint, action);
      details.append(summary);
      source.before(details); details.append(source);
      if (title) title.hidden = true;
      details.open = $('workspace').dataset.page === 'overview' ? sourcesOpen : true;
      const updateAction = () => { action.textContent = details.open ? '收起明细' : '展开明细'; };
      updateAction();
      details.addEventListener('toggle', () => {
        if (!details.isConnected) return;
        if ($('workspace').dataset.page === 'overview') sourcesOpen = details.open;
        updateAction();
      });
    }
    const actual = node('div', '', 'overview-actual'); actual.id = 'overview-actual';
    actual.dataset.minutes = data.actual?.minutes ?? '';
    actual.append(node('strong', `本周实际已记 ${window.Duration.format(data.actual?.minutes, '暂未记录')}`), node('span', `${data.actual?.entry_count || 0} 条账本记录 · 与预计投入分开，不会自动再次扣减计划`));
    chart.append(actual);
  }
  function lock() { sourcesOpen = false; closeGuide(); }
  window.OverviewBudget = { render, routeChanged, lock };
})();
