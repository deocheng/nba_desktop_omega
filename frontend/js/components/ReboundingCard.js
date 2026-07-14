// NBACore v8.1 §4 — ReboundingCard (pure render, no computation).
// Consumes the latest season object from the /players/{id}/growth report.
(function () {
  const V81 = (window.V81 = window.V81 || {});
  const esc = window.escapeHtml || function (s) {
    const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML;
  };
  const TH = window.THEME || { accent: '#00b88a', info: '#3b82f6', purple: '#8b5cf6', textDim: '#7f8c9b', border: '#e1e8f0' };
  const num = (v, d) => { d = d == null ? 1 : d; return (v == null || v === '' || isNaN(Number(v))) ? '—' : Number(v).toFixed(d); };
  const sl = (s) => { if (!s) return '—'; const st = s - 1, en = s % 100; return st + '-' + (en < 10 ? '0' + en : en); };
  const chip = (label, v) => `<div class="v81-chip"><span class="v81-chip-label">${esc(label)}</span><span class="v81-chip-val">${num(v, 1)}%</span></div>`;
  const REB_SCALE = 15; // per-game reference for bar width (presentation only)

  V81.renderReboundingCard = function (containerId, season) {
    const el = document.getElementById(containerId);
    if (!el) return;
    if (!season) {
      el.innerHTML = '<div class="card v81-card"><div class="card-header"><div class="card-title">篮板分析 <span class="v81-sub">Rebounding Profile</span></div></div><div class="v81-empty">暂无数据</div></div>';
      return;
    }
    const orb = season.orb_per_game != null ? season.orb_per_game : season.orb;
    const drb = season.drb_per_game != null ? season.drb_per_game : season.drb;
    const trb = season.trb_per_game != null ? season.trb_per_game : season.trb;
    const rows = [
      { key: 'ORB', label: '进攻篮板', val: orb, color: TH.info },
      { key: 'DRB', label: '防守篮板', val: drb, color: TH.purple },
      { key: 'TRB', label: '总篮板', val: trb, color: TH.accent },
    ];
    const bar = (v) => {
      const n = (v == null) ? 0 : Number(v);
      return Math.max(0, Math.min(100, (n / REB_SCALE) * 100)).toFixed(1) + '%';
    };
    el.innerHTML = `
      <div class="card v81-card">
        <div class="card-header">
          <div class="card-title">篮板分析 <span class="v81-sub">Rebounding Profile</span></div>
          <div class="card-badge">${sl(season.season)}</div>
        </div>
        <div class="v81-reb-rows">
          ${rows.map(r => `
            <div class="v81-reb-row">
              <div class="v81-reb-label"><span class="v81-reb-key">${r.key}</span> ${esc(r.label)}</div>
              <div class="v81-reb-bar"><div class="v81-reb-fill" style="width:${bar(r.val)}; background:${r.color};"></div></div>
              <div class="v81-reb-val">${num(r.val)}<span class="v81-reb-unit">/G</span></div>
            </div>`).join('')}
        </div>
        <div class="v81-rate-chips">
          ${chip('ORB%', season.orb_percent)}
          ${chip('DRB%', season.drb_percent)}
          ${chip('TRB%', season.trb_percent)}
        </div>
      </div>`;
  };
})();
