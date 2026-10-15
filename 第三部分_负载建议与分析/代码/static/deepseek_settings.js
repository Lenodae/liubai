'use strict';
(() => {
  const dialog = $('deepseek-dialog');
  let current = null, serial = 0, load = 0, busy = false;
  function result(message = '', bad = false) {
    $('deepseek-result').textContent = message;
    $('deepseek-result').hidden = !message;
    $('deepseek-result').dataset.error = String(bad);
  }
  function render(data) {
    current = data;
    const label = !data.configured ? '未配置' : data.verified_at ? '已验证' : '待验证';
    $('deepseek-badge').textContent = label;
    $('deepseek-badge').dataset.state = data.verified_at ? 'verified' : 'pending';
    $('deepseek-current').textContent = `${label} · ${data.model}${data.verified_at ? ' · 最近验证 ' + new Date(data.verified_at).toLocaleString('zh-CN', {hour12:false}) : ''}`;
    $('deepseek-model').value = data.model;
    $('deepseek-key').placeholder = data.configured ? '已保存，留空验证；粘贴新密钥可替换' : '粘贴你的 DeepSeek API Key';
    $('deepseek-key').disabled = $('deepseek-model').disabled = !data.can_manage || data.managed_by_env;
    $('deepseek-submit').disabled = !data.can_manage || busy;
    $('deepseek-submit').textContent = data.managed_by_env ? '验证现有配置' : '验证并保存';
    $('deepseek-permission').textContent = data.managed_by_env ? '当前由环境变量提供配置；网页可验证，修改请在本机环境设置中完成。' : data.can_manage ? '此设置供本机账号共用，由初始账号管理。' : '此设置供本机账号共用，请使用最早创建的账号进行配置。';
    window.Execution?.updateProvider(data);
  }
  async function refresh() {
    const request = ++load;
    try {
      const data = await api('/api/settings/deepseek');
      if (request !== load || !state.user) return null;
      render(data);
      return data;
    } catch (error) {
      if (request !== load || !state.user || [401,-1].includes(error.status)) return null;
      $('deepseek-badge').textContent = '状态未读取';
      if (dialog.open) result('配置读取失败，请关闭后重试。', true);
      return null;
    }
  }
  async function open() {
    const token = ++serial;
    current = null; busy = false;
    $('deepseek-form').reset(); result();
    $('deepseek-submit').disabled = true;
    $('deepseek-key').disabled = $('deepseek-model').disabled = true;
    $('deepseek-current').textContent = '正在读取配置…';
    $('deepseek-permission').textContent = '';
    if (!dialog.open) dialog.showModal();
    await refresh();
    if (token === serial && dialog.open && !$('deepseek-key').disabled) $('deepseek-key').focus();
  }
  function close() {
    serial += 1; load += 1; busy = false;
    $('deepseek-form').reset(); $('deepseek-key').value = ''; result();
    dialog.close();
  }
  function lock() {
    close(); current = null;
    $('deepseek-current').textContent = '';
    $('deepseek-permission').textContent = '';
    $('deepseek-badge').textContent = '待检查';
    $('deepseek-badge').dataset.state = 'pending';
  }
  $('deepseek-open').addEventListener('click', open);
  $('ex-deepseek-settings').addEventListener('click', open);
  $('deepseek-close').addEventListener('click', close);
  dialog.addEventListener('cancel', (event) => { event.preventDefault(); close(); });
  $('deepseek-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (busy || !current?.can_manage) return;
    const token = serial;
    const body = {api_key:$('deepseek-key').value.trim(), model:$('deepseek-model').value.trim(), revision:current.revision};
    $('deepseek-key').value = '';
    busy = true; load += 1;
    $('deepseek-submit').disabled = true;
    $('deepseek-submit').textContent = '正在验证…';
    $('deepseek-key').disabled = $('deepseek-model').disabled = true;
    result('正在连接 DeepSeek 验证密钥，请稍候…');
    try {
      const data = await api('/api/settings/deepseek', {method:'POST', body});
      if (token !== serial || !state.user) return;
      busy = false; render(data);
      result(data.managed_by_env ? '验证通过，现有配置可连接。' : '验证通过，已保存。现在可以生成任务草稿了。');
    } catch (error) {
      if (token !== serial || !state.user || [401,-1].includes(error.status)) return;
      result(error.status === 0 ? '连接中断，保存结果尚未确认。请重新打开设置查看状态。' : `${error.message}\n若要替换密钥，请重新粘贴后验证。`, true);
    } finally {
      body.api_key = '';
      if (token === serial && state.user) {
        busy = false;
        $('deepseek-submit').disabled = !current?.can_manage;
        $('deepseek-submit').textContent = current?.managed_by_env ? '验证现有配置' : '验证并保存';
        $('deepseek-key').disabled = $('deepseek-model').disabled = !current?.can_manage || current.managed_by_env;
      }
    }
  });
  window.DeepSeekSettings = {refresh, lock, open};
})();
