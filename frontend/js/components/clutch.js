/**
 * NBACore v8 — Clutch Time Players Component (纯渲染)
 * ===================================================
 * 关键时刻球员表现排名（最后 5 分钟、分差 ≤ 5、默认第 4 节）。
 * 所有数据来自 /api/clutch/players 与 /api/clutch/seasons。
 *
 * 字段口径（前端命名）：
 *   FG% / 2P% / 3P% / Catch / Dribble / Cov% /
 *   OREB / DREB / AST / STL / TOV / PF / POSS / PTS
 * 无法区分的维度（运球信号）后端返回 null，前端显示 "—"。
 *
 * Depends on globals from js/app.js (loaded first): api(), escapeHtml(), toast().
 */
(function () {
  'use strict';

  var THEME = window.THEME || {};

  function eh(text) {
    if (typeof escapeHtml === 'function') return escapeHtml(text == null ? '' : String(text));
    return String(text == null ? '' : text);
  }

  // 百分比：0-100 浮点；null/undefined → "—"
  function fmtPct(v) {
    if (v == null || isNaN(Number(v))) return '—';
    return Number(v).toFixed(1) + '%';
  }
  // 整数；null/undefined → "—"
  function fmtInt(v) {
    if (v == null || isNaN(Number(v))) return '—';
    return String(Number(v));
  }

  function getSeasons() {
    return api('/api/clutch/seasons').then(function (r) { return (r && r.data) || []; });
  }

  function buildFilters(container) {
    container.innerHTML =
      '<div class="card">' +
      '  <div class="card-header"><div class="card-title">关键时刻球员表现 · Clutch Time</div></div>' +
      '  <div class="form-row" style="flex-wrap:wrap; gap:12px; align-items:flex-end;">' +
      '    <div style="min-width:160px;"><label class="label">赛季 Season</label>' +
      '      <select class="select" id="clutchSeason" onchange="Clutch.reload()"><option value="">全部</option></select></div>' +
      '    <div style="min-width:180px;"><label class="label">排名口径 Metric</label>' +
      '      <select class="select" id="clutchMetric" onchange="Clutch.reload()">' +
      '        <option value="possessions">出场回合 Possessions</option>' +
      '        <option value="points">得分 Points</option>' +
      '      </select></div>' +
      '    <div style="min-width:130px;"><label class="label">最小出手 Min FGA</label>' +
      '      <input class="input" id="clutchMinPoss" type="number" value="10" min="0" onchange="Clutch.reload()"></div>' +
      '  </div>' +
      '</div>';
  }

  function loadSeasonsInto() {
    var sel = document.getElementById('clutchSeason');
    if (!sel) return;
    getSeasons().then(function (seasons) {
      seasons.sort(function (a, b) { return b - a; });
      seasons.forEach(function (s) {
        var opt = document.createElement('option');
        opt.value = s;
        opt.textContent = s + '-' + String(s + 1).slice(-2);
        sel.appendChild(opt);
      });
    }).catch(function (e) {
      console.error('clutch seasons failed', e);
    });
  }

  async function loadPlayers() {
    var seasonEl = document.getElementById('clutchSeason');
    var metricEl = document.getElementById('clutchMetric');
    var minEl = document.getElementById('clutchMinPoss');
    var season = seasonEl ? seasonEl.value : '';
    var metric = metricEl ? metricEl.value : 'possessions';
    var minPoss = minEl ? (parseInt(minEl.value, 10) || 0) : 10;

    var qs = 'metric=' + encodeURIComponent(metric) +
      '&min_poss=' + minPoss +
      '&limit=30';
    if (season) qs += '&season=' + encodeURIComponent(season);

    var card = document.getElementById('clutchTableCard');
    if (card) {
      card.innerHTML = '<div class="card-header"><div class="card-title">Top 30 排名</div>' +
        '<div class="card-badge" id="clutchCount">—</div></div>' +
        '<div class="tbl-wrap" style="max-height:640px;"><div style="text-align:center; padding:30px; color:var(--text-dim);">' +
        '<div class="spinner"></div> 加载中...</div></div>';
    }

    try {
      var resp = await api('/api/clutch/players?' + qs);
      var data = (resp && resp.data) || [];
      renderTable(data);
    } catch (e) {
      var wrap = document.getElementById('clutchTableCard');
      if (wrap) {
        wrap.innerHTML = '<div class="card-header"><div class="card-title">Top 30 排名</div></div>' +
          '<div class="v81-empty" style="color:var(--danger);">加载失败: ' + eh(e.message) + '</div>';
      }
    }
  }

  function renderTable(data) {
    var card = document.getElementById('clutchTableCard');
    if (!card) return;

    if (!data || data.length === 0) {
      card.innerHTML = '<div class="card-header"><div class="card-title">Top 30 排名</div>' +
        '<div class="card-badge">0</div></div>' +
        '<div class="v81-empty">暂无符合阈值（最小出手）的球员数据</div>' + coverageHint();
      return;
    }

    var rows = data.map(function (p, i) {
      var name = eh(p.player_name || p.player_id || 'Unknown');
      var team = p.team ? ('<span class="badge badge-blue">' + eh(p.team) + '</span>') : null;
      return '<tr>' +
        '<td style="font-weight:700; color:var(--text-dim); text-align:center;">' + (i + 1) + '</td>' +
        '<td><div style="font-weight:600;">' + name + '</div>' +
          (team ? '<div class="sub">' + team + '</div>' : '') + '</td>' +
        '<td>' + (team ? team : '—') + '</td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + fmtInt(p.poss) + '</td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + fmtPct(p.fg_pct) + '</td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + fmtPct(p.fg2_pct) + '</td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + fmtPct(p.fg3_pct) + '</td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + fmtInt(p.catch_shots) + '</td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + fmtInt(p.dribble_shots) + '</td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + fmtPct(p.dribble_coverage) + '</td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + fmtInt(p.oreb) + '</td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + fmtInt(p.dreb) + '</td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + fmtInt(p.ast) + '</td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + fmtInt(p.stl) + '</td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + fmtInt(p.tov) + '</td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + fmtInt(p.pf) + '</td>' +
        '<td style="text-align:right; font-family:var(--mono); font-weight:700; color:var(--accent);">' + fmtInt(p.pts) + '</td>' +
        '</tr>';
    }).join('');

    card.innerHTML = '<div class="card-header"><div class="card-title">Top 30 排名</div>' +
      '<div class="card-badge" id="clutchCount">' + data.length + ' 名</div></div>' +
      '<div class="tbl-wrap" style="max-height:640px; overflow:auto;">' +
      '<table class="tbl" id="clutchTable">' +
      '<thead><tr>' +
      '<th style="width:40px; text-align:center;">#</th>' +
      '<th>球员</th>' +
      '<th>球队</th>' +
      '<th style="text-align:right;">POSS</th>' +
      '<th style="text-align:right;">FG%</th>' +
      '<th style="text-align:right;">2P%</th>' +
      '<th style="text-align:right;">3P%</th>' +
      '<th style="text-align:right;">Catch</th>' +
      '<th style="text-align:right;">Dribble</th>' +
      '<th style="text-align:right;">Cov%</th>' +
      '<th style="text-align:right;">OREB</th>' +
      '<th style="text-align:right;">DREB</th>' +
      '<th style="text-align:right;">AST</th>' +
      '<th style="text-align:right;">STL</th>' +
      '<th style="text-align:right;">TOV</th>' +
      '<th style="text-align:right;">PF</th>' +
      '<th style="text-align:right;">PTS</th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table>' +
      '</div>' + coverageHint();
  }

  function coverageHint() {
    return '<div style="margin-top:10px; padding:10px 12px; font-size:12px; color:var(--text-dim); background:var(--bg-dark, #f6f8fb); border-radius:8px;">' +
      '运球可识别覆盖率 Cov% = 可识别运球出手（Catch + Dribble）/ 总出手 FGA。' +
      '标记为 <strong>—</strong> 表示该球员关键时刻出手主要来自无法区分运球信号的源（BBRef / nba_api），后端按约定返回 null。</div>';
  }

  async function render(containerId) {
    var container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML =
      '<div class="page-header">' +
      '  <h2>关键时刻球员表现 · Clutch Time</h2>' +
      '</div>' +
      '<div id="clutchFilters"></div>' +
      '<div id="clutchTableCard"></div>';
    buildFilters(document.getElementById('clutchFilters'));
    loadSeasonsInto();
    await loadPlayers();
  }

  // ── Public API ──
  window.Clutch = {
    render: render,
    reload: function () {
      loadPlayers();
    },
  };
})();
