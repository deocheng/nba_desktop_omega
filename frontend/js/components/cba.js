/**
 * NBACore v8 — CBA 规则可视化组件（纯渲染，Layer 4）
 * ===================================================
 * 全部数据来自 /cba/* 接口（Layer 3 编排），本组件**零业务计算**。
 * 仅做展示格式化 fmtMoney(int → $X.XM) 与状态→颜色/标签的展示映射
 * （映射来自 API 返回的 status 字段，非前端判定）。
 *
 * 组件：window.Cba.render(containerId)
 *   - renderRules()   规则常量（5 张 stat-card）
 *   - renderTeam()    球队 Bird&Max（球员表 + 团队总额 + 状态徽标）
 *   - renderLeague()  联盟模拟（多队勾选 + ECharts 柱状 + 阈值线 + 状态表）
 *
 * 依赖全局：api(path)、escapeHtml()、toast()、THEME（见 js/app.js）。
 */
(function () {
  'use strict';

  // 30 队标准缩写（与 trade.js 一致；BRK 非 BKN）
  var TEAMS = {
    ATL: 'Atlanta Hawks', BOS: 'Boston Celtics', BRK: 'Brooklyn Nets',
    CHO: 'Charlotte Hornets', CHI: 'Chicago Bulls', CLE: 'Cleveland Cavaliers',
    DAL: 'Dallas Mavericks', DEN: 'Denver Nuggets', DET: 'Detroit Pistons',
    GSW: 'Golden State Warriors', HOU: 'Houston Rockets', IND: 'Indiana Pacers',
    LAC: 'LA Clippers', LAL: 'Los Angeles Lakers', MEM: 'Memphis Grizzlies',
    MIA: 'Miami Heat', MIL: 'Milwaukee Bucks', MIN: 'Minnesota Timberwolves',
    NOP: 'New Orleans Pelicans', NYK: 'New York Knicks', OKC: 'Oklahoma City Thunder',
    ORL: 'Orlando Magic', PHI: 'Philadelphia 76ers', PHO: 'Phoenix Suns',
    POR: 'Portland Trail Blazers', SAC: 'Sacramento Kings', SAS: 'San Antonio Spurs',
    TOR: 'Toronto Raptors', UTA: 'Utah Jazz', WAS: 'Washington Wizards'
  };
  var SEASONS = ['2025-26'];

  // 状态 -> 展示颜色 / 标签（映射来自 API 的 status 字段，非前端判定）
  var STATUS_COLOR = {
    HEALTHY: '#10b981',
    LUXURY_TAX: '#f59e0b',
    FIRST_APRON: '#f97316',
    SECOND_APRON: '#ef4444'
  };
  var STATUS_LABEL = {
    HEALTHY: '健康',
    LUXURY_TAX: '奢侈税',
    FIRST_APRON: '第一围裙',
    SECOND_APRON: '第二围裙'
  };

  var state = {
    season: '2025-26',
    tab: 'rules',          // rules | team | league
    isAllNba: false,       // Tab② 开关（仅覆盖展示判定，不伪造数据）
    teamAbbr: '',          // Tab② 当前球队
    leagueTeams: [],       // Tab③ 全联盟快照
    leagueThresholds: {}, // Tab③ 阈值（来自 API）
    selected: {}           // Tab③ 勾选 {abbr: true}
  };

  function eh(s) {
    if (typeof escapeHtml === 'function') return escapeHtml(s == null ? '' : String(s));
    return String(s == null ? '' : s);
  }
  function teamName(abbr) { return TEAMS[abbr] || abbr || '—'; }

  // 金额：全整数 → $XX.XM（展示层格式化，架构 §6，非业务计算）
  function fmtMoney(v) {
    if (v == null || isNaN(Number(v))) return '—';
    return '$' + (Number(v) / 1e6).toFixed(1) + 'M';
  }
  function statusBadge(status) {
    var color = STATUS_COLOR[status] || '#7f8c9b';
    var label = STATUS_LABEL[status] || status || '—';
    return '<span class="badge" style="background:' + color + '22; color:' + color +
      '; border:1px solid ' + color + '55;">' + eh(label) + '</span>';
  }

  // ── 渲染骨架 ──
  function render(containerId) {
    var container = document.getElementById(containerId);
    if (!container) return;
    var teamOpts = Object.keys(TEAMS).map(function (t) {
      return '<option value="' + t + '">' + t + ' · ' + TEAMS[t] + '</option>';
    }).join('');

    container.innerHTML =
      '<div class="page-header"><h2>CBA 规则 · cba_aux 可视化</h2>' +
      '<span class="badge badge-blue">v8.3.2</span>' +
      '<div class="form-row">' +
      '  <label class="label">赛季 Season</label>' +
      '  <select class="select" id="cbaSeason" onchange="Cba.onSeason(this.value)">' +
      SEASONS.map(function (s) {
        return '<option value="' + s + '"' + (s === state.season ? ' selected' : '') + '>' + s + '</option>';
      }).join('') +
      '  </select>' +
      '</div></div>' +
      '<div class="ctx-tabs" style="margin-bottom:16px;">' +
      '  <div class="ctx-tab active" data-tab="rules" onclick="Cba.switchTab(\'rules\')">① 规则常量</div>' +
      '  <div class="ctx-tab" data-tab="team" onclick="Cba.switchTab(\'team\')">② 球队 / Bird&amp;Max</div>' +
      '  <div class="ctx-tab" data-tab="league" onclick="Cba.switchTab(\'league\')">③ 联盟模拟</div>' +
      '</div>' +
      '<div id="cbaTabBody"></div>';

    renderRules();
  }

  function switchTab(tab) {
    state.tab = tab;
    document.querySelectorAll('#cbaRoot .ctx-tab').forEach(function (el) {
      el.classList.toggle('active', el.dataset.tab === tab);
    });
    if (tab === 'rules') renderRules();
    else if (tab === 'team') renderTeam();
    else if (tab === 'league') renderLeague();
  }

  function onSeason(v) {
    state.season = v;
    if (state.tab === 'rules') renderRules();
    else if (state.tab === 'team') renderTeam();
    else if (state.tab === 'league') renderLeague();
  }

  // ── Tab① 规则常量 ──
  async function renderRules() {
    var body = document.getElementById('cbaTabBody');
    if (!body) return;
    body.innerHTML = '<div class="card"><div id="cbaRulesBody" style="padding:16px;">' +
      '<div class="spinner"></div> 加载薪资规则…</div></div>';

    try {
      var resp = await api('/cba/rules?season=' + encodeURIComponent(state.season));
      var d = (resp && resp.data) || {};
      var cards = [
        { label: '工资帽 Cap', value: fmtMoney(d.base_cap), color: '#00b88a' },
        { label: '奢侈税线 Luxury Tax', value: fmtMoney(d.luxury_tax_line), color: '#f59e0b' },
        { label: '第一围裙 First Apron', value: fmtMoney(d.first_apron), color: '#f97316' },
        { label: '第二围裙 Second Apron', value: fmtMoney(d.second_apron), color: '#ef4444' },
        { label: '最低球队薪资 Min', value: fmtMoney(d.min_team_salary), color: '#3b82f6' }
      ];
      document.getElementById('cbaRulesBody').innerHTML =
        '<div class="grid-3col" style="grid-template-columns:repeat(auto-fill,minmax(200px,1fr));">' +
        cards.map(function (c) {
          return '<div class="card stat-card" style="border-top:3px solid ' + c.color + ';">' +
            '<div class="stat-card-label">' + eh(c.label) + '</div>' +
            '<div class="stat-card-value" style="color:' + c.color + '; font-family:var(--mono);">' + c.value + '</div>' +
            '</div>';
        }).join('') +
        '</div>' +
        '<div class="v81-empty" style="margin-top:14px; color:var(--text-dim); font-size:12px;">' +
        '⚠ 规则常量来自 league_salary_rules（DB 权威）；薪资为美元整数，前端仅做 $X.XM 展示格式化。</div>';
    } catch (e) {
      document.getElementById('cbaRulesBody').innerHTML =
        '<div class="v81-empty" style="color:var(--danger);">加载失败: ' + eh(e.message) + '</div>';
    }
  }

  // ── Tab② 球队 / Bird&Max ──
  function renderTeam() {
    var body = document.getElementById('cbaTabBody');
    if (!body) return;
    var teamOpts = Object.keys(TEAMS).map(function (t) {
      return '<option value="' + t + '"' + (t === state.teamAbbr ? ' selected' : '') + '>' + t + ' · ' + TEAMS[t] + '</option>';
    }).join('');

    body.innerHTML =
      '<div class="card"><div class="card-header"><div class="card-title">球队 Bird Rights &amp; Player Max</div></div>' +
      '<div style="padding:14px; display:flex; gap:16px; flex-wrap:wrap; align-items:center;">' +
      '  <label class="label">球队 Team</label>' +
      '  <select class="select" id="cbaTeamSel" onchange="Cba.onTeam(this.value)">' +
      '    <option value="">— 选择球队 —</option>' + teamOpts + '</select>' +
      '  <label class="label" style="display:flex; gap:6px; align-items:center; cursor:pointer;">' +
      '    <input type="checkbox" id="cbaAllNba" onchange="Cba.onAllNba(this.checked)"' + (state.isAllNba ? ' checked' : '') + '>' +
      '    标记 All-NBA（未接入真实数据，默认按 25%）</label>' +
      '</div>' +
      '<div id="cbaTeamBody"><div class="v81-empty">选择一支球队查看球员 Bird Rights / Cap Hold / Max%</div></div>' +
      '</div>';

    if (state.teamAbbr) loadTeam();
  }

  function onTeam(abbr) {
    state.teamAbbr = abbr;
    if (abbr) loadTeam();
    else document.getElementById('cbaTeamBody').innerHTML =
      '<div class="v81-empty">选择一支球队查看球员 Bird Rights / Cap Hold / Max%</div>';
  }
  function onAllNba(v) {
    state.isAllNba = v;
    if (state.teamAbbr) loadTeam();
  }

  async function loadTeam() {
    var el = document.getElementById('cbaTeamBody');
    if (!el || !state.teamAbbr) return;
    el.innerHTML = '<div style="padding:14px;"><div class="spinner"></div> 加载球队数据…</div>';
    try {
      var url = '/cba/team/' + encodeURIComponent(state.teamAbbr) +
        '?season=' + encodeURIComponent(state.season) + '&is_all_nba=' + (state.isAllNba ? 'true' : 'false');
      var resp = await api(url);
      var d = resp.data || {};
      var players = d.players || [];

      var rows = players.map(function (p) {
        return '<tr>' +
          '<td style="font-weight:600;">' + eh(p.name) + '</td>' +
          '<td style="text-align:right; font-family:var(--mono);">' + fmtMoney(p.salary) + '</td>' +
          '<td style="text-align:right; font-family:var(--mono);">' + (p.yos != null ? p.yos : '—') + '</td>' +
          '<td style="text-align:center;">' + (p.bird_factor != null ? p.bird_factor.toFixed(2) + 'x' : '—') + '</td>' +
          '<td style="text-align:right; font-family:var(--mono);">' + fmtMoney(p.cap_hold) + '</td>' +
          '<td style="text-align:right; font-family:var(--mono);">' + (p.max_pct != null ? (p.max_pct * 100).toFixed(0) + '%' : '—') + '</td>' +
          '<td style="color:var(--text-dim); font-size:12px;">yos=' + (p.basis && p.basis.yos != null ? p.basis.yos : '—') +
          ' · allNba=' + (p.basis && p.basis.is_all_nba ? 'Y' : 'N') + '</td>' +
          '</tr>';
      }).join('') || '<tr><td colspan="7" style="text-align:center; padding:20px; color:var(--text-dim);">该队暂无合同数据</td></tr>';

      el.innerHTML =
        '<div style="padding:0 14px 14px;">' +
        '<div style="display:flex; gap:16px; align-items:center; margin-bottom:12px; flex-wrap:wrap;">' +
        '  <div class="stat-chip"><span class="chip-label">球队总额</span><span class="chip-value" style="font-family:var(--mono);">' + fmtMoney(d.team_total) + '</span></div>' +
        '  <div class="stat-chip"><span class="chip-label">状态</span><span class="chip-value">' + statusBadge(d.status) + '</span></div>' +
        '</div>' +
        '<div class="tbl-wrap" style="max-height:520px;">' +
        '<table class="tbl"><thead><tr>' +
        '<th>球员</th><th style="text-align:right;">薪资</th><th style="text-align:right;">yos</th>' +
        '<th style="text-align:center;">Bird 系数</th><th style="text-align:right;">Cap Hold</th>' +
        '<th style="text-align:right;">Max%</th><th>判定依据</th>' +
        '</tr></thead><tbody>' + rows + '</tbody></table></div>' +
        '<div class="v81-empty" style="margin-top:12px; color:var(--text-dim); font-size:12px;">' +
        '⚠ yos 由 age-19 启发式估算，可信度有限；is_all_nba 未接入真实标记，默认按 25%（All-NBA 档 30%/35% 不触发）。' +
        'Cap Hold / Max% 由引擎计算，前端仅展示。</div>' +
        '</div>';
    } catch (e) {
      el.innerHTML = '<div class="v81-empty" style="padding:14px; color:var(--danger);">加载失败: ' + eh(e.message) + '</div>';
    }
  }

  // ── Tab③ 联盟模拟 ──
  async function renderLeague() {
    var body = document.getElementById('cbaTabBody');
    if (!body) return;
    body.innerHTML =
      '<div class="card"><div class="card-header"><div class="card-title">联盟薪资模拟 · League Simulator</div>' +
      '<div class="form-row" style="margin:0;">' +
      '  <button class="btn btn-primary btn-sm" onclick="Cba.runSimulate()">模拟选中队</button>' +
      '  <button class="btn btn-sm" onclick="Cba.exportLeague()">导出 JSON</button>' +
      '</div></div>' +
      '<div style="padding:14px;">' +
      '  <div id="cbaTeamChecks" style="display:flex; gap:10px; flex-wrap:wrap; margin-bottom:12px;">' +
      '    <div class="spinner"></div> 加载球队…</div>' +
      '  <div id="cbaLeagueChart" class="chart-container" style="height:380px;"></div>' +
      '  <div id="cbaLeagueTable"></div>' +
      '</div></div>';

    try {
      var resp = await api('/cba/league/summary?season=' + encodeURIComponent(state.season));
      var d = resp.data || {};
      state.leagueTeams = d.teams || [];
      state.leagueThresholds = d.thresholds || {};
      // 默认全选
      state.selected = {};
      state.leagueTeams.forEach(function (t) { state.selected[t.team] = true; });
      renderTeamChecks();
      renderLeagueChart(state.leagueTeams);
    } catch (e) {
      document.getElementById('cbaTeamChecks').innerHTML =
        '<div class="v81-empty" style="color:var(--danger);">加载失败: ' + eh(e.message) + '</div>';
    }
  }

  function renderTeamChecks() {
    var el = document.getElementById('cbaTeamChecks');
    if (!el) return;
    el.innerHTML = state.leagueTeams.map(function (t) {
      var checked = state.selected[t.team] ? ' checked' : '';
      return '<label style="display:flex; gap:4px; align-items:center; font-size:12px; cursor:pointer;">' +
        '<input type="checkbox" data-abbr="' + eh(t.team) + '"' + checked +
        ' onchange="Cba.toggleTeam(\'' + eh(t.team) + '\', this.checked)">' + eh(t.team) + '</label>';
    }).join('');
  }

  function toggleTeam(abbr, v) {
    state.selected[abbr] = v;
  }

  async function runSimulate() {
    var selected = state.leagueTeams.filter(function (t) { return state.selected[t.team]; })
      .map(function (t) { return t.team; });
    try {
      var resp = await api('/cba/league/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ season: state.season, team_abbrs: selected, trade: null })
      });
      var d = resp.data || {};
      state.leagueThresholds = d.thresholds || state.leagueThresholds;
      renderLeagueChart(d.teams || []);
      toast('模拟完成：' + (d.teams || []).length + ' 队', 'success');
    } catch (e) {
      toast('模拟失败: ' + e.message, 'error');
    }
  }

  async function exportLeague() {
    try {
      var resp = await api('/cba/league/export?season=' + encodeURIComponent(state.season));
      var data = (resp && resp.data) || {};
      var blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = 'cba_league_' + state.season + '.json';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast('已导出 league JSON', 'success');
    } catch (e) {
      toast('导出失败: ' + e.message, 'error');
    }
  }

  function renderLeagueChart(teams) {
    var chartEl = document.getElementById('cbaLeagueChart');
    var tableEl = document.getElementById('cbaLeagueTable');
    if (!chartEl) return;
    if (window._cbaChart) { window._cbaChart.dispose(); window._cbaChart = null; }
    window._cbaChart = echarts.init(chartEl);

    var th = state.leagueThresholds || {};
    var markLines = [];
    if (th.luxury_tax_line) markLines.push({ yAxis: th.luxury_tax_line, name: '奢侈税', lineStyle: { color: '#f59e0b' }, label: { formatter: '奢侈税' } });
    if (th.first_apron) markLines.push({ yAxis: th.first_apron, name: '第一围裙', lineStyle: { color: '#f97316' }, label: { formatter: '第一围裙' } });
    if (th.second_apron) markLines.push({ yAxis: th.second_apron, name: '第二围裙', lineStyle: { color: '#ef4444' }, label: { formatter: '第二围裙' } });

    var names = teams.map(function (t) { return t.team; });
    var barData = teams.map(function (t) {
      return {
        value: t.total_salary,
        itemStyle: { color: STATUS_COLOR[t.status] || '#00b88a' }
      };
    });

    window._cbaChart.setOption({
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: function (ps) {
          var p = ps[0];
          var t = teams[p.dataIndex];
          return eh(t.team) + ' · ' + (STATUS_LABEL[t.status] || t.status) +
            '<br/>薪资: ' + fmtMoney(t.total_salary);
        }
      },
      grid: { left: '3%', right: '4%', bottom: '12%', containLabel: true },
      xAxis: {
        type: 'category', data: names,
        axisLabel: { color: '#7f8c9b', fontSize: 10, rotate: 60 }
      },
      yAxis: {
        type: 'value', axisLabel: { color: '#7f8c9b', formatter: function (v) { return '$' + (v / 1e6) + 'M'; } },
        splitLine: { lineStyle: { color: '#e8edf3' } }
      },
      series: [{
        type: 'bar', data: barData, barMaxWidth: 28,
        markLine: { silent: true, symbol: 'none', lineStyle: { type: 'dashed' }, data: markLines }
      }]
    });

    // 状态表（颜色/标签来自 data.status，非前端判定）
    if (tableEl) {
      var rows = teams.map(function (t) {
        return '<tr>' +
          '<td style="font-weight:600;">' + eh(t.team) + ' <span style="color:var(--text-dim);font-weight:400;">' + eh(teamName(t.team)) + '</span></td>' +
          '<td style="text-align:right; font-family:var(--mono);">' + fmtMoney(t.total_salary) + '</td>' +
          '<td>' + statusBadge(t.status) + '</td>' +
          '</tr>';
      }).join('') || '<tr><td colspan="3" style="text-align:center; padding:20px; color:var(--text-dim);">无数据</td></tr>';
      tableEl.innerHTML =
        '<div class="tbl-wrap" style="max-height:360px; margin-top:12px;">' +
        '<table class="tbl"><thead><tr><th>球队</th><th style="text-align:right;">薪资总额</th><th>状态</th></tr></thead>' +
        '<tbody>' + rows + '</tbody></table></div>' +
        '<div class="v81-empty" style="margin-top:10px; color:var(--text-dim); font-size:12px;">' +
        '⚠ 状态（健康/奢侈税/围裙）由引擎按阈值判定，前端仅按 status 着色与标注；yos 启发式，可信度有限。</div>';
    }
  }

  // ── 暴露公共 API（供 index.html 内联 onchange/onclick 调用） ──
  window.Cba = {
    render: render,
    switchTab: switchTab,
    onSeason: onSeason,
    onTeam: onTeam,
    onAllNba: onAllNba,
    toggleTeam: toggleTeam,
    runSimulate: runSimulate,
    exportLeague: exportLeague
  };
})();
