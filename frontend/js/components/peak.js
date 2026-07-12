/**
 * NBACore v8.2-C — Peak (巅峰期) Component (纯渲染)
 * 生涯单季峰值排名。数据来自 /api/career/peak。
 * 仅做展示与格式化，无任何聚合/派生计算（计算全在 career_engine）。
 */
(function () {
  'use strict';

  // 与后端 METRIC_WHITELIST 对齐（展示用，计算口径以后端为准）
  var METRICS = [
    { v: 'pts_per_game', t: '得分/场 PPG' },
    { v: 'per', t: 'PER' },
    { v: 'ws', t: '胜利贡献 WS' },
    { v: 'vorp', t: '胜利替代值 VORP' },
    { v: 'ts_percent', t: '真实命中率 TS%' },
    { v: 'bpm', t: '正负值 BPM' }
  ];

  function eh(text) {
    if (typeof escapeHtml === 'function') return escapeHtml(text == null ? '' : String(text));
    return String(text == null ? '' : text);
  }
  function fmt(v, d) {
    if (v == null || isNaN(Number(v))) return '—';
    return Number(v).toFixed(d == null ? 2 : d);
  }

  function metricOptions(sel) {
    return METRICS.map(function (m) {
      return '<option value="' + m.v + '"' + (m.v === sel ? ' selected' : '') + '>' + eh(m.t) + '</option>';
    }).join('');
  }

  function buildFilters(container) {
    container.innerHTML =
      '<div class="card">' +
      '  <div class="card-header"><div class="card-title">生涯巅峰榜 · Peak</div></div>' +
      '  <div class="form-row" style="flex-wrap:wrap; gap:12px; align-items:flex-end;">' +
      '    <div style="min-width:180px;"><label class="label">指标 Metric</label>' +
      '      <select class="select" id="peakMetric" onchange="Peak.reload()">' + metricOptions('pts_per_game') + '</select></div>' +
      '    <div style="min-width:120px;"><label class="label">最小出场 Min Games</label>' +
      '      <input class="input" id="peakMinGames" type="number" value="20" min="0" onchange="Peak.reload()"></div>' +
      '    <div style="min-width:120px;"><label class="label">位置 Position</label>' +
      '      <input class="input" id="peakPos" type="text" placeholder="如 PG/SF" onchange="Peak.reload()"></div>' +
      '    <div style="min-width:120px;"><label class="label">年代 Era</label>' +
      '      <input class="input" id="peakEra" type="text" placeholder="如 2010s" onchange="Peak.reload()"></div>' +
      '    <div style="min-width:100px;"><label class="label">数量 Limit</label>' +
      '      <input class="input" id="peakLimit" type="number" value="30" min="1" max="100" onchange="Peak.reload()"></div>' +
      '  </div>' +
      '</div>';
  }

  async function load() {
    var m = document.getElementById('peakMetric');
    var mg = document.getElementById('peakMinGames');
    var pos = document.getElementById('peakPos');
    var era = document.getElementById('peakEra');
    var lim = document.getElementById('peakLimit');
    var metric = m ? m.value : 'pts_per_game';
    var minGames = mg ? (parseInt(mg.value, 10) || 0) : 20;
    var position = pos && pos.value.trim() ? pos.value.trim() : '';
    var eraVal = era && era.value.trim() ? era.value.trim() : '';
    var limit = lim ? Math.max(1, Math.min(100, parseInt(lim.value, 10) || 30)) : 30;

    var qs = 'metric=' + encodeURIComponent(metric) +
      '&min_games=' + minGames + '&limit=' + limit;
    if (position) qs += '&position=' + encodeURIComponent(position);
    if (eraVal) qs += '&era=' + encodeURIComponent(eraVal);

    var card = document.getElementById('peakTableCard');
    if (card) {
      card.innerHTML = '<div class="card-header"><div class="card-title">Top ' + limit + ' 排名</div>' +
        '<div class="card-badge" id="peakCount">—</div></div>' +
        '<div class="tbl-wrap" style="max-height:640px;"><div style="text-align:center; padding:30px; color:var(--text-dim);">' +
        '<div class="spinner"></div> 加载中...</div></div>';
    }
    try {
      var resp = await api('/api/career/peak?' + qs);
      renderTable((resp && resp.data) || []);
    } catch (e) {
      var wrap = document.getElementById('peakTableCard');
      if (wrap) {
        wrap.innerHTML = '<div class="card-header"><div class="card-title">Top ' + limit + ' 排名</div></div>' +
          '<div class="v81-empty" style="color:var(--danger);">加载失败: ' + eh(e.message) + '</div>';
      }
    }
  }

  function renderTable(data) {
    var card = document.getElementById('peakTableCard');
    if (!card) return;
    if (!data || data.length === 0) {
      card.innerHTML = '<div class="card-header"><div class="card-title">Top 排名</div>' +
        '<div class="card-badge">0</div></div>' +
        '<div class="v81-empty">暂无符合阈值（最小出场）的球员数据</div>';
      return;
    }
    var rows = data.map(function (p) {
      var name = eh(p.player_name || p.player_id || 'Unknown');
      var team = p.peak_team ? ('<span class="badge badge-blue">' + eh(p.peak_team) + '</span>') : '—';
      return '<tr>' +
        '<td style="font-weight:700; color:var(--text-dim); text-align:center;">' + p.rank + '</td>' +
        '<td><div style="font-weight:600;">' + name + '</div></td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + fmt(p.peak_value) + '</td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + (p.peak_season || '—') + '</td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + fmt(p.peak_age, 1) + '</td>' +
        '<td>' + team + '</td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + fmt(p.second_value) + '</td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + (p.seasons_played || 0) + '</td>' +
        '</tr>';
    }).join('');
    card.innerHTML = '<div class="card-header"><div class="card-title">Top ' + data.length + ' 排名</div>' +
      '<div class="card-badge" id="peakCount">' + data.length + ' 名</div></div>' +
      '<div class="tbl-wrap" style="max-height:640px; overflow:auto;">' +
      '<table class="tbl" id="peakTable">' +
      '<thead><tr>' +
      '<th style="width:40px; text-align:center;">#</th>' +
      '<th>球员</th>' +
      '<th style="text-align:right;">峰值值</th>' +
      '<th style="text-align:right;">巅峰赛季</th>' +
      '<th style="text-align:right;">巅峰年龄</th>' +
      '<th>球队</th>' +
      '<th style="text-align:right;">次优值</th>' +
      '<th style="text-align:right;">赛季数</th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table></div>';
  }

  async function render(containerId) {
    var container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML =
      '<div class="page-header"><h2>生涯巅峰榜 · Peak</h2></div>' +
      '<div id="peakFilters"></div>' +
      '<div id="peakTableCard"></div>';
    buildFilters(document.getElementById('peakFilters'));
    await load();
  }

  window.Peak = { render: render, reload: function () { load(); } };
})();
