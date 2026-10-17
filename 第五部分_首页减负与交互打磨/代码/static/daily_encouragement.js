'use strict';
(() => {
  const card = document.getElementById('daily-encouragement');
  if (!card) return;
  const quoteNode = document.getElementById('daily-encouragement-text');
  const dateNode = document.getElementById('daily-encouragement-date');
  const sourceNode = document.getElementById('daily-encouragement-source');
  const retry = document.getElementById('daily-encouragement-retry');
  const fallback = Object.freeze({id:'liubai-fallback', text:'慢慢来，今天先迈出一小步。', source:'留白'});
  const dayMilliseconds = 86400000;
  const firstDay = Date.UTC(2026, 9, 15) / dayMilliseconds;
  let quotes = [], loading = false, timer = null;

  function quoteForDate(date) {
    if (!(date instanceof Date) || !Number.isFinite(date.getTime()) || !quotes.length) return fallback;
    // Count calendar dates, not elapsed local hours: daylight-saving days may be 23/25 hours.
    const day = Math.floor(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / dayMilliseconds);
    return quotes[((day - firstDay) % quotes.length + quotes.length) % quotes.length];
  }
  function refresh() {
    const now = new Date(), quote = quoteForDate(now);
    const date = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    dateNode.dateTime = date;
    dateNode.textContent = new Intl.DateTimeFormat('zh-CN', {month:'long', day:'numeric', weekday:'long'}).format(now);
    if (quoteNode.textContent !== quote.text) quoteNode.textContent = quote.text;
    const work = /^(自己|原创|原创句子|自创|自制|自编|未知|无|我)$/.test(quote.source.trim()) ? '' : quote.source;
    const source = [...new Set([quote.author, work].filter(Boolean))].join(' · ');
    sourceNode.textContent = `— ${source || '一言社区'}`;
    card.dataset.quoteId = quote.id;
    card.dataset.date = date;
    clearTimeout(timer);
    const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
    timer = setTimeout(refresh, Math.max(1000, midnight.getTime() - now.getTime() + 100));
  }
  async function loadQuotes() {
    if (loading || quotes.length) return;
    loading = true; retry.disabled = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const url = new URL(card.dataset.quotesUrl, location.href);
      if (url.origin !== location.origin) throw new Error('Daily quotes must be local.');
      const response = await fetch(url, {credentials:'same-origin', signal:controller.signal});
      if (!response.ok) throw new Error('Daily quotes are unavailable.');
      const data = await response.json();
      if (data.version !== 1 || !Array.isArray(data.quotes) || data.quotes.length !== 300) throw new Error('Invalid daily quote collection.');
      const ids = new Set(), texts = new Set();
      const checked = data.quotes.map((item) => {
        if (!item || typeof item.id !== 'string' || !item.id || typeof item.text !== 'string' || !item.text.trim() || item.text.length > 300 || ids.has(item.id) || texts.has(item.text.trim())) throw new Error('Invalid daily quote.');
        ids.add(item.id); texts.add(item.text.trim());
        return Object.freeze({id:item.id, text:item.text.trim(), source:typeof item.source === 'string' ? item.source : '', author:typeof item.author === 'string' ? item.author : ''});
      });
      quotes = checked;
      card.dataset.state = 'ready'; retry.hidden = true;
    } catch {
      card.dataset.state = 'fallback'; retry.hidden = false;
    } finally {
      clearTimeout(timeout); loading = false; retry.disabled = false; refresh();
    }
  }
  retry.addEventListener('click', loadQuotes);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  window.addEventListener('focus', refresh);
  window.addEventListener('pageshow', refresh);
  window.addEventListener('pagehide', () => clearTimeout(timer));
  window.DailyEncouragement = Object.freeze({quoteForDate, refresh});
  refresh();
  void loadQuotes();
})();
