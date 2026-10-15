'use strict';
(() => {
  const levels = {
    light: ['轻松有余量', '还有余地，可以按自己的节奏来。空出来的时间，也可以留给自己。'],
    balanced: ['刚刚好', '安排有了重心，也保留着空间。一件一件来就好。'],
    challenge: ['有点挑战', '事情比较充实，记得给切换留点时间，先照顾最重要的那件事。'],
    high: ['负载偏高', '已经接近排满，新增事情前可以缓一缓。'],
    full: ['安排已满', '当前可安排时间已用满，可以先做眼前这一件。'],
    overload: ['该减一点', '计划超过了可安排时间，可以挪走一小部分，给变化留点余地。'],
    unknown: ['信息待补全', '先补上预算或估时，再看看这段时间适合怎样的节奏。'],
    zero: ['暂未留出可安排时间', '这段时间还没有可安排容量，可以先留白，准备好了再调整。'],
  };
  const percentText = (minutes, capacity) => `${Math.floor(minutes * 1000 / capacity + 1e-9) / 10}%`;
  function describe(analysis = {}, windowData = {}) {
    const a = analysis, capacity = a.capacity, low = a.low, high = a.high;
    let level = 'unknown', percent = null, rangeText = null;
    const known = windowData.confirmed !== false && !windowData.stale && a.verdict !== 'unknown' && !a.unknown_count
      && [capacity, low, high].every((n) => typeof n === 'number' && Number.isFinite(n) && n >= 0) && low <= high;
    if (known && capacity === 0) level = high > 0 ? 'overload' : 'zero';
    else if (known) {
      // Use unrounded amounts at each boundary; display to one decimal without crossing a band.
      level = high * 100 < capacity * 60 ? 'light' : high * 100 < capacity * 80 ? 'balanced'
        : high * 100 < capacity * 90 ? 'challenge' : high < capacity ? 'high' : high === capacity ? 'full' : 'overload';
      percent = percentText(high, capacity);
      if (low !== high) rangeText = `${percentText(low, capacity)}–${percent}`;
    }
    const [label, defaultMessage] = levels[level];
    const message = level === 'unknown' && a.deficit_low > 0
      ? '已知的安排已经超出可安排时间，还有信息需要补充。可以先挪走一点安排。'
      : known && capacity === 0 && high > 0
        ? '当前可安排容量为零，但已有进行中的投入。先确认可用时间，再决定保留哪些安排。'
        : defaultMessage;
    return { level, label, message, percent, rangeText };
  }
  window.LoadFeeling = { describe };
})();
