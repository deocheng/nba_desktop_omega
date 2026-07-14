/**
 * NBACore Studio v8.2 — Player Intelligence Component
 * ====================================================
 * Renders the Player DNA 7-dimension radar + bars, availability,
 * and scoring-profile (shooting zones). Pure render, all data via api().
 *
 * Depends on globals defined by js/app.js (loaded first):
 *   api(), escapeHtml(), toast(), charts, echarts, window.THEME
 */
(function () {
  'use strict';

  // Shared theme from app.js (assigned to window.THEME at end of app.js)
  var THEME = window.THEME || {};

  // DNA dimensions — order drives radar + bars
  var DNA_DIMS = [
    { key: 'scoring', label: '得分' },
    { key: 'playmaking', label: '组织' },
    { key: 'defense', label: '防守' },
    { key: 'rebounding', label: '篮板' },
    { key: 'efficiency', label: '效率' },
    { key: 'durability', label: '耐久' },
    { key: 'leadership', label: '领导力' }
  ];

  // 4 shooting zones (order: rim → three)
  var SCORING_ZONES = ['At Rim', 'Paint', 'Mid-Range', 'Three Point'];

  // ── Helpers ──
  function eh(text) {
    if (typeof escapeHtml === 'function') return escapeHtml(text == null ? '' : String(text));
    return String(text == null ? '' : text);
  }

  function fmtNum(v, d) {
    if (v == null || isNaN(Number(v))) return null;
    return Number(v).toFixed(d == null ? 1 : d);
  }

  function fmtPct(v) {
    if (v == null || isNaN(Number(v))) return null;
    return (Number(v) * 100).toFixed(1) + '%';
  }

  function dnaColor(v) {
    if (isNaN(Number(v))) return THEME.textDim || '#7f8c9b';
    var n = Number(v);
    if (n >= 75) return THEME.accent || '#00b88a';
    if (n >= 50) return THEME.info || '#3b82f6';
    if (n >= 30) return THEME.warning || THEME.warn || '#f59e0b';
    return THEME.danger || '#ef4444';
  }

  function chip(label, value) {
    return '<div class="stat-chip"><span class="chip-label">' + eh(label) + '</span>' +
      '<span class="chip-value">' + (value == null ? '—' : eh(value)) + '</span></div>';
  }

  // ── Public render entry ──
  async function render(containerId, playerId, season) {
    var container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML =
      '<div style="text-align:center; padding:30px; color:var(--text-dim);">' +
      '<div class="spinner"></div> 加载球员情报中...</div>';
    try {
      var data = await api(
        '/players/' + encodeURIComponent(playerId) +
        '/intelligence?season=' + encodeURIComponent(season) +
        '&season_type=Regular'
      );
      renderData(container, data);
    } catch (e) {
      container.innerHTML =
        '<div class="card"><div class="card-header"><div class="card-title">球员情报</div></div>' +
        '<div class="v81-empty" style="color:var(--danger);">加载失败: ' + eh(e.message) + '</div></div>';
    }
  }

  function renderData(container, data) {
    var role = data.role || '—';
    var season = data.season != null ? data.season : '—';
    var seasonType = data.season_type || 'Regular';
    var dna = data.dna || {};
    var avail = data.availability || null;
    var scoring = data.scoring_profile || {};

    var html = '';

    // 1. Role header card
    html += '<div class="card">';
    html += '  <div class="card-header">';
    html += '    <div class="card-title">球员角色 · Role</div>';
    html += '    <div class="form-row" style="margin:0; gap:8px;">';
    html += '      <span class="card-badge" style="background:var(--purple); color:#fff;">' + eh(season) + '</span>';
    html += '      <span class="card-badge" style="background:var(--info); color:#fff;">' + eh(seasonType) + '</span>';
    html += '    </div>';
    html += '  </div>';
    html += '  <div class="role-badge">' + eh(role) + '</div>';
    html += '</div>';

    // 2. DNA radar + bars
    html += '<div class="grid-2col chart-grid">';
    html += '  <div class="card">';
    html += '    <div class="card-header"><div class="card-title">Player DNA 雷达</div></div>';
    html += '    <div id="intelRadar" class="intel-radar"></div>';
    html += '  </div>';
    html += '  <div class="card">';
    html += '    <div class="card-header"><div class="card-title">Player DNA 维度</div></div>';
    html += '    <div class="dna-list">';
    html += DNA_DIMS.map(function (d) {
      var v = dna[d.key];
      var val = fmtNum(v);
      var w = (v == null || isNaN(Number(v))) ? 0 : Math.max(0, Math.min(100, Number(v)));
      var color = dnaColor(v);
      return '<div class="dna-row">' +
        '<div class="dna-label">' + eh(d.label) + '</div>' +
        '<div class="dna-bar"><div class="dna-fill" style="width:' + w + '%;background:' + color + ';"></div></div>' +
        '<div class="dna-val">' + (val == null ? '—' : val) + '</div>' +
        '</div>';
    }).join('');
    html += '    </div>';
    html += '  </div>';
    html += '</div>';

    // 3. Availability
    var team = avail ? avail.team : null;
    var games = avail ? avail.games : null;
    var teamGames = avail ? avail.team_games : null;
    var availPct = avail ? fmtPct(avail.availability) : null;
    var minShare = avail ? fmtPct(avail.minutes_share) : null;
    html += '<div class="card">';
    html += '  <div class="card-header"><div class="card-title">可用性 · Availability</div></div>';
    html += '  <div class="ws-chips" style="flex-wrap:wrap;">';
    html += chip('球队', team);
    html += chip('出场', (games == null ? '—' : games) + ' / ' + (teamGames == null ? '—' : teamGames));
    html += chip('出勤率', availPct);
    html += chip('时间占比', minShare);
    html += '  </div>';
    html += '</div>';

    // 4. Scoring profile
    html += '<div class="card">';
    html += '  <div class="card-header"><div class="card-title">投篮区域分布 · Scoring Profile</div></div>';
    html += '  <div class="sp-list">';
    html += SCORING_ZONES.map(function (zone) {
      var z = scoring[zone] || {};
      var freq = z.frequency;
      var eff = z.efficiency;
      var freqPct = (freq == null ? 0 : Number(freq) * 100).toFixed(1);
      var effPct = (eff == null ? 0 : Number(eff) * 100).toFixed(1);
      return '<div class="sp-row">' +
        '<div class="sp-zone">' + eh(zone) + '</div>' +
        '<div class="sp-bars">' +
        '<div class="sp-bar-line"><span class="sp-bar-label">出手</span>' +
        '<div class="sp-bar"><div class="sp-fill freq" style="width:' + freqPct + '%;"></div></div>' +
        '<span class="sp-val">' + freqPct + '%</span></div>' +
        '<div class="sp-bar-line"><span class="sp-bar-label">效率</span>' +
        '<div class="sp-bar"><div class="sp-fill eff" style="width:' + effPct + '%;"></div></div>' +
        '<span class="sp-val">' + effPct + '%</span></div>' +
        '</div>' +
        '</div>';
    }).join('');
    html += '  </div>';
    html += '</div>';

    container.innerHTML = html;

    // Initialize the radar chart (after DOM is in place)
    initRadar(dna);
  }

  function initRadar(dna) {
    var el = document.getElementById('intelRadar');
    if (!el || typeof echarts === 'undefined') return;
    if (charts.intelRadar) charts.intelRadar.dispose();
    var chart = echarts.init(el);
    charts.intelRadar = chart;

    var indicator = DNA_DIMS.map(function (d) { return { name: d.label, max: 100 }; });
    var values = DNA_DIMS.map(function (d) {
      var v = dna[d.key];
      return (v == null || isNaN(Number(v))) ? 0 : Number(v);
    });

    chart.setOption({
      tooltip: {},
      radar: {
        indicator: indicator,
        radius: '65%',
        center: ['50%', '52%'],
        axisName: { color: THEME.textDim || '#7f8c9b', fontSize: 12 },
        splitArea: { areaStyle: { color: ['rgba(0,184,138,.02)', 'rgba(0,184,138,.05)'] } },
        splitLine: { lineStyle: { color: THEME.splitLine || '#e8edf3' } },
        axisLine: { lineStyle: { color: THEME.splitLine || '#e8edf3' } }
      },
      series: [{
        type: 'radar',
        data: [{
          value: values,
          name: 'DNA',
          itemStyle: { color: THEME.accent || '#00b88a' },
          areaStyle: { color: 'rgba(0,184,138,.18)' },
          lineStyle: { width: 2 },
          symbolSize: 5
        }]
      }]
    });

    // Trigger a resize so the chart fills its container correctly
    setTimeout(function () { window.dispatchEvent(new Event('resize')); }, 60);
  }

  // ── Expose public API ──
  window.Intelligence = { render: render };
})();
