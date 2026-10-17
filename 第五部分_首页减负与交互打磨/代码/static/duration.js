'use strict';
(() => {
  // Stored values stay in whole minutes; only the presentation uses hours + minutes.
  function format(value, unknown = '未知') {
    if (value == null || !Number.isFinite(value)) return unknown;
    const amount = Math.abs(value), hours = Math.floor(amount / 60), minutes = amount % 60;
    const parts = [];
    if (hours) parts.push(`${hours} 小时`);
    if (minutes || !hours) parts.push(`${minutes} 分钟`);
    return `${value < 0 ? '−' : ''}${parts.join(' ')}`;
  }
  function range(low, high, unknown = '待确认') {
    if (low == null || high == null) return unknown;
    return low === high ? format(low, unknown) : `${format(low, unknown)}–${format(high, unknown)}`;
  }
  function read(prefix) {
    const hours = document.getElementById(`${prefix}-hours`).value.trim();
    const minutes = document.getElementById(`${prefix}-minutes`).value.trim();
    return hours === '' && minutes === '' ? null : Number(hours || 0) * 60 + Number(minutes || 0);
  }
  function fill(prefix, value) {
    document.getElementById(`${prefix}-hours`).value = value == null ? '' : Math.floor(value / 60);
    document.getElementById(`${prefix}-minutes`).value = value == null ? '' : value % 60;
  }
  const prose = (value) => value.replace(/(\d+) 分钟/g, (_, minutes) => format(Number(minutes)));
  window.Duration = { format, range, read, fill, prose };
})();
