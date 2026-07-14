// NBACore v8.1 §9 — CareerDefenseSummary (pure render, no computation).
// Consumes GET /players/{id}/career-defense (career defensive totals).
(function () {
  const V81 = (window.V81 = window.V81 || {});
  const esc = window.escapeHtml || function (s) {
    const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML;
  };
  const TH = window.THEME || { accent: '#00b88a', info: '#3b82f6', warn: '#f59e0b', danger: '#ef4444', purple: '#8b5cf6' };
  const num = (v, d) => { d = d == null ? 1 : d; return (v == null || v === '' || isNaN(Number(v))) ? '—' : Number(v).toFixed(d); };
  const big = (v) => (v == null || v === '') ? '—' : Number(v).toLocaleString();
  const tile = (k, label, v, color) => `<div class="v81-tile"><div class="v81-tile-key">${esc(k)}</div><div class="v81-tile-label">${esc(label)}</div><div class="v81-tile-val" style="color:${color};">${v == null || v === '' ? '—' : (Number(v).toLocaleString())}</div></div>`;
  const chip = (label, v) => `<div class="v81-chip"><span class="v81-chip-label">${esc(label)}</span><span class="v81-chip-val">${num(v, 2)}</span></div>`;

  V81.renderCareerDefenseSummary = function (containerId, d) {
    const el = document.getElementById(containerId);
    if (!el) return;
    if (!d || !d.found) {
      el.innerHTML = '<div class="card v81-card"><div class="card-header"><div class="card-title">生涯防守 <span class="v81-sub">Career Defense</span></div></div><div class="v81-empty">暂无数据</div></div>';
      return;
    }
    el.innerHTML = `
      <div class="card v81-card">
        <div class="card-header">
          <div class="card-title">生涯防守 <span class="v81-sub">Career Defense</span></div>
          <div class="card-badge">${d.seasons || ''} 赛季 · ${big(d.total_games)} 场</div>
        </div>
        <div class="v81-career-grid">
          ${tile('STL', '抢断', d.total_steals, TH.info)}
          ${tile('BLK', '盖帽', d.total_blocks, TH.warn)}
          ${tile('PF', '犯规', d.total_fouls, TH.danger)}
          ${tile('STOCKS', '抢断+盖帽', d.stocks, TH.accent)}
        </div>
        <div class="v81-rate-chips">
          ${chip('STL/G', d.steals_per_game)}
          ${chip('BLK/G', d.blocks_per_game)}
          ${chip('STOCKS/G', d.stocks_per_game)}
          ${chip('DAE', d.def_activity_efficiency)}
        </div>
      </div>`;
  };
})();
