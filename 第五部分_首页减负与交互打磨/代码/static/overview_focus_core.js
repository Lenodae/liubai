'use strict';
(() => {
  const validId = (value) => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
  function parseId(raw) {
    if (typeof raw !== 'string' || raw.length > 80) return null;
    try { const id = JSON.parse(raw); return validId(id) ? id : null; }
    catch { return null; }
  }
  function parseExpanded(raw) { return raw === 'true'; }
  function chooseTask(tasks, rememberedId) {
    if (!Array.isArray(tasks)) return null;
    const eligible = tasks.filter((task) => task && validId(task.id) && task.status === 'in_progress' && !task.deleted_at);
    const remembered = eligible.find((task) => task.id === rememberedId);
    if (remembered) return remembered;
    const priority = {high: 0, normal: 1, low: 2};
    eligible.sort((a, b) => (priority[a.priority] ?? 1) - (priority[b.priority] ?? 1) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    return eligible[0] || null;
  }
  function contextMatches(ctx, owner, epoch) {
    return Boolean(ctx && owner && ctx.owner === owner && ctx.epoch === epoch);
  }
  window.OverviewFocusRules = Object.freeze({parseId, parseExpanded, chooseTask, contextMatches});
})();
