'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const filename = path.join(root, 'static/overview_focus_core.js');
const report = {contracts: [], properties: [], mutants: [], scope: 'Pure selection/preferences/context only; browser integration is separate.'};
const ids = ['00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000003'];
const makeTask = (id, status = 'in_progress', priority = 'normal', deleted_at = null) => ({id, title: `task-${id.slice(-1)}`, status, priority, deleted_at});
function run(source, record = false, failures = null, propertiesOnly = false) {
  const context = {window: {}};
  vm.runInNewContext(source, context, {filename});
  const rules = context.window.OverviewFocusRules;
  function check(name, fn, property = false) {
    if (propertiesOnly && !property) return;
    try { fn(); if (record) report[property ? 'properties' : 'contracts'].push(name); }
    catch (error) { if (!failures) throw error; failures.push({name, error: error.message}); }
  }
  check('Invalid or oversized stored values fall back to no remembered ID', () => {
    for (const raw of [null, undefined, '', '{', 'null', 'true', '123', '[]', '{}', JSON.stringify({id: ids[0]}), JSON.stringify('someone else'), ' '.repeat(300)]) assert.equal(rules.parseId(raw), null);
    assert.equal(rules.parseId(JSON.stringify(ids[0])), ids[0]);
  });
  check('Expanded preference only accepts the stored boolean true', () => {
    for (const raw of [null, undefined, '', 'false', '"true"', '1', '{}', '[]', 'true ']) assert.equal(rules.parseExpanded(raw), false);
    assert.equal(rules.parseExpanded('true'), true);
  });
  check('Remembered active task wins; inactive, trash and absent IDs never do', () => {
    const tasks = [makeTask(ids[0], 'in_progress', 'high'), makeTask(ids[1], 'in_progress', 'low')];
    assert.equal(rules.chooseTask(tasks, ids[1]).id, ids[1]);
    assert.equal(rules.chooseTask(tasks, ids[2]).id, ids[0]);
    assert.equal(rules.chooseTask([], ids[0]), null);
    assert.equal(rules.chooseTask(null, ids[0]), null);
    assert.equal(rules.chooseTask([null, {}, makeTask('not-an-id')], null), null);
  });
  check('Fallback is priority then ID, independent of title and input order', () => {
    const a = makeTask(ids[2], 'in_progress', 'high');
    const b = makeTask(ids[0], 'in_progress', 'high');
    const c = makeTask(ids[1], 'in_progress', 'low');
    const input = Object.freeze([Object.freeze(c), Object.freeze(a), Object.freeze(b)]);
    assert.equal(rules.chooseTask(input, null).id, ids[0]);
    assert.equal(rules.chooseTask([a, {...b, title: 'zzz'}, c], null).id, ids[0]);
    assert.equal(rules.chooseTask([makeTask(ids[0]), makeTask(ids[1], 'in_progress', 'high')], null).id, ids[1]);
  });
  check('Account and epoch must both match and an authenticated owner must exist', () => {
    assert.equal(rules.contextMatches({owner: 1, epoch: 2}, 1, 2), true);
    for (const [ctx, owner, epoch] of [[{owner: 1, epoch: 2}, 2, 2], [{owner: 1, epoch: 2}, 1, 3], [{owner: null, epoch: 2}, null, 2], [null, 1, 2]]) assert.equal(rules.contextMatches(ctx, owner, epoch), false);
  });
  check('Every task-state and deletion combination selects exactly a legal task without mutating input', () => {
    const states = ['planned', 'in_progress', 'paused', 'completed', 'abandoned'];
    let cases = 0;
    for (const first of states) for (const second of states) for (const deleted of [null, '2026-10-15T00:00:00Z']) for (const remembered of [null, ...ids]) {
      const tasks = [makeTask(ids[0], first, 'normal', deleted), makeTask(ids[1], second, 'high')];
      const snapshot = JSON.stringify(tasks);
      const result = rules.chooseTask(tasks, remembered);
      const legal = tasks.filter((task) => task.status === 'in_progress' && !task.deleted_at);
      assert.equal(result === null, legal.length === 0);
      if (result) assert(legal.includes(result));
      if (legal.some((task) => task.id === remembered)) assert.equal(result.id, remembered);
      assert.equal(rules.chooseTask([...tasks].reverse(), remembered)?.id, result?.id);
      assert.equal(JSON.stringify(tasks), snapshot);
      cases += 1;
    }
    assert.equal(cases, 200);
  }, true);
  check('Stored expansion only accepts true across malformed scalar and object encodings', () => {
    for (const raw of [undefined, null, '', 'true', 'false', '"true"', '0', '1', '{}', '[]', 'true ']) assert.equal(rules.parseExpanded(raw), raw === 'true');
  }, true);
  check('Finite account transitions reject every previous owner or login epoch', () => {
    let accepted = 0;
    for (let savedOwner = 1; savedOwner <= 3; savedOwner += 1) for (let liveOwner = 1; liveOwner <= 3; liveOwner += 1) for (let savedEpoch = 1; savedEpoch <= 3; savedEpoch += 1) for (let liveEpoch = 1; liveEpoch <= 3; liveEpoch += 1) {
      const result = rules.contextMatches({owner: savedOwner, epoch: savedEpoch}, liveOwner, liveEpoch);
      assert.equal(result, savedOwner === liveOwner && savedEpoch === liveEpoch);
      accepted += Number(result);
    }
    assert.equal(accepted, 9);
  }, true);
}
try {
  if (process.argv.includes('--red')) {
    const failures = [];
    run('window.OverviewFocusRules = {parseId: () => undefined, parseExpanded: () => undefined, chooseTask: () => undefined, contextMatches: () => undefined};', false, failures);
    assert.equal(failures.length, 8, 'each new contract/property must fail against its stub');
    console.log(JSON.stringify({stage: 'RED', failures}, null, 2));
    process.exit(1);
  }
  const source = fs.readFileSync(filename, 'utf8');
  run(source, true);
  const faults = [
    ['inactive task allowed', "task.status === 'in_progress'", 'true'],
    ['trash allowed', '!task.deleted_at', 'true'],
    ['remembered task ignored', 'eligible.find((task) => task.id === rememberedId)', 'null'],
    ['broken default expands calendar', "raw === 'true'", "raw !== 'false'"],
    ['stale login epoch accepted', 'ctx.epoch === epoch', 'true'],
  ];
  for (const [name, from, to] of faults) {
    assert(source.includes(from), `mutant target missing: ${name}`);
    let killed = false;
    try { run(source.replace(from, to)); } catch { killed = true; }
    let propertiesKilled = false;
    try { run(source.replace(from, to), false, null, true); } catch { propertiesKilled = true; }
    report.mutants.push({name, killed, propertiesKilled});
    assert(killed, `surviving mutant: ${name}`);
    assert(propertiesKilled, `property-only surviving mutant: ${name}`);
  }
  report.passed = true;
  fs.writeFileSync(path.join(root, 'evidence/overview-focus-checks.json'), `${JSON.stringify(report, null, 2)}\n`);
  console.log(`PASS ${report.contracts.length} contracts, ${report.properties.length} bounded properties (292 cases), ${report.mutants.length} killed in-memory mutants`);
} catch (error) {
  console.error(error.stack);
  process.exitCode = 1;
}
