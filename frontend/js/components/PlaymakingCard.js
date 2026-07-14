// NBACore v8.1 §5 — PlaymakingCard (pure render, no computation).
// Consumes the latest season object from the /players/{id}/growth report.
(function () {
  const V81 = (window.V81 = window.V81 || {});
  const esc = window.escapeHtml || function (s) {
    const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML;
  };
  const TH = window.THEME || { accent: '#00b88a', danger: '#ef4444', purple: '#8b5cf6' };
  const num = (v, d) => { d = d == null ? 1 : d; return (v == null || v === '' || isNaN(Number(v))) ? '—' : Number(v).toFixed(d); };
  const sl = (s) => { if (!s) return '—'; const st = s - 1, en = s % 100; return st + '-' + (en < 10 ? '0' + en : en); };
  const tile = (k, label, v, color) => `<div class="v81-tile"><div class="v81-tile-key">${esc(k)}</div><div class="v81-tile-label">${esc(label)}</div><div class="v81-tile-val" style="color:${color};">${num(v)}</div></div>`;

  V81.renderPlaymakingCard = function (containerId, season) {
    const el = document.getElementById(containerId);
    if (!el) return;
    if (!season) {
      el.innerHTML = '<div class="card v81-card"><div class="card-header"><div class="card-title">组织能力 <span class="v81-sub">Playmaking</span></div></div><div class="v81-empty">暂无数据</div></div>';
      return;
    }
    const ast = season.ast_per_game != null ? season.ast_per_game : season.ast;
    const tov = season.tov_per_game != null ? season.tov_per_game : season.tov;
    const ratio = season.ast_per_tov != null ? season.ast_per_tov : season.ast_to_ratio;
    el.innerHTML = `
      <div class="card v81-card">
        <div class="card-header">
          <div class="card-title">组织能力 <span class="v81-sub">Playmaking</span></div>
          <div class="card-badge">${sl(season.season)}</div>
        </div>
        <div class="v81-career-grid">
          ${tile('AST', '助攻', ast, TH.accent)}
          ${tile('TOV', '失误', tov, TH.danger)}
          ${tile('AST/TO', '助失比', ratio, TH.purple)}
        </div>
      </div>`;
  };
})();
