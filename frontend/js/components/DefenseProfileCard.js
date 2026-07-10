// NBACore v8.1 §6 — DefenseProfileCard (pure render, no computation).
// Consumes the latest season object from the /players/{id}/growth report.
(function () {
  const V81 = (window.V81 = window.V81 || {});
  const esc = window.escapeHtml || function (s) {
    const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML;
  };
  const TH = window.THEME || { accent: '#00b88a', danger: '#ef4444', info: '#3b82f6', warn: '#f59e0b' };
  const num = (v, d) => { d = d == null ? 1 : d; return (v == null || v === '' || isNaN(Number(v))) ? '—' : Number(v).toFixed(d); };
  const sl = (s) => { if (!s) return '—'; const st = s - 1, en = s % 100; return st + '-' + (en < 10 ? '0' + en : en); };
  const tile = (k, label, v, color) => `<div class="v81-tile"><div class="v81-tile-key">${esc(k)}</div><div class="v81-tile-label">${esc(label)}</div><div class="v81-tile-val" style="color:${color};">${num(v)}</div></div>`;

  V81.renderDefenseProfileCard = function (containerId, season) {
    const el = document.getElementById(containerId);
    if (!el) return;
    if (!season) {
      el.innerHTML = '<div class="card v81-card"><div class="card-header"><div class="card-title">防守画像 <span class="v81-sub">Defense Profile</span></div></div><div class="v81-empty">暂无数据</div></div>';
      return;
    }
    const stl = season.stl_per_game != null ? season.stl_per_game : season.stl;
    const blk = season.blk_per_game != null ? season.blk_per_game : season.blk;
    const pf = season.pf_per_game != null ? season.pf_per_game : season.pf;
    const dae = season.steal_block_per_foul != null ? season.steal_block_per_foul : season.def_activity_efficiency;
    el.innerHTML = `
      <div class="card v81-card">
        <div class="card-header">
          <div class="card-title">防守画像 <span class="v81-sub">Defense Profile</span></div>
          <div class="card-badge">${sl(season.season)}</div>
        </div>
        <div class="v81-career-grid">
          ${tile('STL', '抢断', stl, TH.info)}
          ${tile('BLK', '盖帽', blk, TH.warn)}
          ${tile('PF', '犯规', pf, TH.danger)}
          ${tile('DAE', '防守效率', dae, TH.accent)}
        </div>
      </div>`;
  };
})();
