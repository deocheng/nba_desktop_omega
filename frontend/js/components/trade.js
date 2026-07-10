/**
 * NBACore v8 — 交易模拟器 v1 组件（纯渲染，Layer 4）
 * ===================================================
 * 全部数据来自 /trade/* 接口（Layer 3 编排），本组件零薪资/税档/匹配计算。
 * 组件：TradeBuilder / ValidationPanel / MatchSuggestion / CapImpactView /
 *       PlayerTimeline / TeamTimeline（含 PO/TO/PART 徽标）。
 *
 * 依赖全局：api(path)、escapeHtml()、toast()（见 js/app.js）。
 */
(function () {
  'use strict';

  // 30 队标准缩写（BRK 非 BKN）
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

  var state = {
    season: '2025-26',
    league: 'NBA',
    legs: [
      { team_abbr: '', outgoing: [], incoming: [] },
      { team_abbr: '', outgoing: [], incoming: [] }
    ],
    teamPlayers: {}   // abbr -> [{player_id, player_name, salary, guaranteed, opt_type, is_two_way, is_partial}]
  };

  function eh(s) {
    if (typeof escapeHtml === 'function') return escapeHtml(s == null ? '' : String(s));
    return String(s == null ? '' : s);
  }
  function teamName(abbr) { return TEAMS[abbr] || abbr || '—'; }

  // 金额：全整数 → $XX.XM（前端展示层格式化，架构 §八）
  function fmtMoney(v) {
    if (v == null || isNaN(Number(v))) return '—';
    return '$' + (Number(v) / 1e6).toFixed(1) + 'M';
  }
  // PO/TO/PART 徽标（TRADE-04）
  function optBadge(opt) {
    if (opt === 'player_option') return '<span class="badge badge-po" title="球员选项：球员可选择执行/跳出">PO</span>';
    if (opt === 'team_option') return '<span class="badge badge-to" title="球队选项：球队可选择执行/跳出">TO</span>';
    return '';
  }
  function partBadge(isPartial) {
    return isPartial ? '<span class="badge badge-part" title="部分保障：guaranteed 低于总额">PART</span>' : '';
  }
  function twoWayBadge(isTwoWay) {
    return isTwoWay ? '<span class="badge badge-tw" title="双向合同：匹配/税档按 $0 计">2W</span>' : '';
  }

  // ── 载入某队球员（构建器下拉） ──
  async function loadTeamPlayers(abbr) {
    if (!abbr || state.teamPlayers[abbr]) return;
    try {
      var resp = await api('/trade/players/' + encodeURIComponent(abbr) + '?season=' + encodeURIComponent(state.season));
      var data = (resp && resp.data) || [];
      state.teamPlayers[abbr] = data;
    } catch (e) {
      state.teamPlayers[abbr] = [];
      console.error('loadTeamPlayers failed', abbr, e);
    }
  }

  // ── 渲染骨架 ──
  async function render(containerId) {
    var container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML =
      '<div class="page-header"><h2>交易模拟器 v1 · Trade Simulator</h2>' +
      '<div class="trade-controls">' +
      '  <label class="label">赛季 Season</label>' +
      '  <select class="select" id="tradeSeason" onchange="Trade.onSeason(this.value)">' +
      SEASONS.map(function (s) { return '<option value="' + s + '"' + (s === state.season ? ' selected' : '') + '>' + s + '</option>'; }).join('') +
      '  </select>' +
      '  <label class="label">联赛 League</label>' +
      '  <select class="select" id="tradeLeague" onchange="Trade.onLeague(this.value)">' +
      '    <option value="NBA" selected>NBA</option>' +
      '  </select>' +
      '  <button class="btn btn-primary" onclick="Trade.runValidate()">校验交易</button>' +
      '  <button class="btn" onclick="Trade.runSuggest()">匹配建议</button>' +
      '  <button class="btn" onclick="Trade.runGenerate()">生成方案</button>' +
      '  <button class="btn btn-ghost" onclick="Trade.addLeg()">+ 添加球队</button>' +
      '</div></div>' +
      '<div id="tradeBuilder"></div>' +
      '<div class="trade-grid">' +
      '  <div class="card"><div class="card-header"><div class="card-title">校验结果 · Validation</div><div class="card-badge" id="tradeLegalBadge">—</div></div><div id="tradeValidation" class="trade-panel"><div class="v81-empty">点击「校验交易」开始</div></div></div>' +
      '  <div class="card"><div class="card-header"><div class="card-title">薪资匹配建议 · Suggestion</div></div><div id="tradeSuggestion" class="trade-panel"><div class="v81-empty">点击「匹配建议」</div></div></div>' +
      '  <div class="card"><div class="card-header"><div class="card-title">税档 / 工资帽影响 · Cap Impact</div></div><div id="tradeCapImpact" class="trade-panel"><div class="v81-empty">交易前后税档对比</div></div></div>' +
      '</div>' +
      '<div class="card" style="margin-top:16px;"><div class="card-header"><div class="card-title">薪资时间线 · Timeline</div></div>' +
      '  <div style="padding:12px 14px;"><label class="label">球员 / 球队检索</label>' +
      '    <input class="input" id="tradeTlInput" placeholder="输入 player_id 或选择球队" style="max-width:320px;display:inline-block;" />' +
      '    <select class="select" id="tradeTlTeam" style="max-width:200px;display:inline-block;"><option value="">— 球队时间线 —</option>' +
      Object.keys(TEAMS).map(function (t) { return '<option value="' + t + '">' + t + ' ' + TEAMS[t] + '</option>'; }).join('') +
      '    </select>' +
      '    <button class="btn" onclick="Trade.runPlayerTimeline()">球员时间线</button>' +
      '    <button class="btn" onclick="Trade.runTeamTimeline()">球队时间线</button>' +
      '  </div>' +
      '  <div id="tradeTimeline" class="trade-panel"></div>' +
      '</div>';

    renderBuilder();
  }

  // ── 构建器 ──
  function renderBuilder() {
    var el = document.getElementById('tradeBuilder');
    if (!el) return;
    var html = state.legs.map(function (leg, i) {
      var teamOpts = Object.keys(TEAMS).map(function (t) {
        return '<option value="' + t + '"' + (t === leg.team_abbr ? ' selected' : '') + '>' + t + ' · ' + TEAMS[t] + '</option>';
      }).join('');
      return '<div class="card trade-leg">' +
        '<div class="card-header"><div class="card-title">球队 ' + (i + 1) +
        ' <select class="select" onchange="Trade.setTeam(' + i + ', this.value)"><option value="">选择球队…</option>' + teamOpts + '</select></div>' +
        (state.legs.length > 2 ? '<button class="btn btn-ghost" onclick="Trade.removeLeg(' + i + ')">移除</button>' : '') +
        '</div>' +
        '<div class="leg-cols">' +
          legCol(i, 'outgoing', '送出 Outgoing', leg.outgoing) +
          legCol(i, 'incoming', '接收 Incoming', leg.incoming) +
        '</div></div>';
    }).join('');
    el.innerHTML = html;
    // 触发已选球队的球员加载
    state.legs.forEach(function (leg) { if (leg.team_abbr) loadTeamPlayers(leg.team_abbr); });
  }

  function legCol(legIdx, side, title, list) {
    var rows = list.map(function (p, j) {
      return '<div class="player-row">' +
        '<span class="player-name">' + eh(p.player_name) + '</span>' +
        '<span class="player-sal">' + fmtMoney(p.guaranteed) + '</span>' +
        optBadge(p.opt_type) + partBadge(p.is_partial) + twoWayBadge(p.is_two_way) +
        '<button class="btn btn-ghost btn-sm" onclick="Trade.removePlayer(' + legIdx + ',\'' + side + '\',' + j + ')">✕</button>' +
        '</div>';
    }).join('');
    var selId = 'sel-' + legIdx + '-' + side;
    return '<div class="leg-col">' +
      '<div class="leg-col-title">' + title + '</div>' +
      '<div class="player-list">' + (rows || '<div class="v81-empty" style="padding:8px;">暂无</div>') + '</div>' +
      '<div class="add-row"><select class="select" id="' + selId + '"><option value="">+ 球员…</option></select>' +
      '<button class="btn btn-sm" onclick="Trade.addPlayer(' + legIdx + ',\'' + side + '\')">添加</button></div>' +
      '</div>';
  }

  function fillPlayerSelect(legIdx, side) {
    var leg = state.legs[legIdx];
    if (!leg.team_abbr) return;
    var sel = document.getElementById('sel-' + legIdx + '-' + side);
    if (!sel) return;
    var players = state.teamPlayers[leg.team_abbr] || [];
    // 已选 id 集合，避免重复
    var chosen = {};
    leg.outgoing.concat(leg.incoming).forEach(function (p) { chosen[p.player_id] = true; });
    sel.innerHTML = '<option value="">+ 球员…</option>' + players.filter(function (p) {
      return !chosen[p.player_id];
    }).map(function (p) {
      return '<option value="' + eh(p.player_id) + '">' + eh(p.player_name) + ' · ' + fmtMoney(p.guaranteed) + '</option>';
    }).join('');
  }

  // ── 状态操作（暴露到 window.Trade） ──
  function onSeason(v) { state.season = v; }
  function onLeague(v) { state.league = v; }
  async function setTeam(i, abbr) {
    state.legs[i].team_abbr = abbr;
    state.legs[i].outgoing = [];
    state.legs[i].incoming = [];
    await loadTeamPlayers(abbr);
    renderBuilder();
  }
  function addLeg() {
    state.legs.push({ team_abbr: '', outgoing: [], incoming: [] });
    renderBuilder();
  }
  function removeLeg(i) {
    state.legs.splice(i, 1);
    renderBuilder();
  }
  function addPlayer(i, side) {
    var sel = document.getElementById('sel-' + i + '-' + side);
    if (!sel || !sel.value) return;
    var pid = sel.value;
    var players = state.teamPlayers[state.legs[i].team_abbr] || [];
    var p = players.find(function (x) { return x.player_id === pid; });
    if (p) state.legs[i][side].push(p);
    renderBuilder();
  }
  function removePlayer(i, side, j) {
    state.legs[i][side].splice(j, 1);
    renderBuilder();
  }

  // ── 构建请求 payload ──
  function buildLegsPayload() {
    return state.legs.filter(function (l) { return l.team_abbr; }).map(function (l) {
      return {
        team_abbr: l.team_abbr,
        outgoing: l.outgoing.map(function (p) { return p.player_id; }),
        incoming: l.incoming.map(function (p) { return p.player_id; })
      };
    });
  }

  // ── 校验 ──
  async function runValidate() {
    var legs = buildLegsPayload();
    if (legs.length < 2) { toast('请至少选择 2 支球队并配置资产', 'error'); return; }
    var panel = document.getElementById('tradeValidation');
    panel.innerHTML = '<div class="spinner"></div> 校验中…';
    try {
      var resp = await api('/trade/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ league: state.league, season: state.season, as_of: new Date().toISOString(), legs: legs })
      });
      renderValidation(resp.data);
    } catch (e) {
      panel.innerHTML = '<div class="v81-empty" style="color:var(--danger);">校验失败: ' + eh(e.message) + '</div>';
    }
  }

  function renderValidation(data) {
    var panel = document.getElementById('tradeValidation');
    if (!panel || !data) return;
    var badge = document.getElementById('tradeLegalBadge');
    if (badge) {
      badge.textContent = data.legal ? '✅ 合规' : '❌ 违规';
      badge.className = 'card-badge ' + (data.legal ? 'badge-green' : 'badge-red');
    }
    var rows = (data.results || []).map(function (r) {
      var issues = (r.issues || []).map(function (iss) {
        var color = iss.severity === 'error' ? 'var(--danger)' : 'var(--warn)';
        var delta = iss.amount_delta ? '（缺口 ' + fmtMoney(iss.amount_delta) + '）' : '';
        return '<div class="issue" style="color:' + color + ';">• [' + iss.rule_code + '] ' + eh(iss.message) + delta + '</div>';
      }).join('') || '<div class="issue" style="color:var(--accent);">• 无违规</div>';
      return '<div class="leg-result ' + (r.legal ? 'ok' : 'bad') + '">' +
        '<div class="leg-result-head"><strong>' + eh(r.team_abbr) + '</strong> ' +
        (r.legal ? '<span style="color:var(--accent);">通过</span>' : '<span style="color:var(--danger);">不通过</span>') + '</div>' +
        '<div class="leg-result-num">送出 ' + fmtMoney(r.outbound_guaranteed) + ' · 接收 ' + fmtMoney(r.inbound_guaranteed) +
        ' · 上限 ' + fmtMoney(r.max_inbound_allowed) + ' · 缺口 ' + fmtMoney(r.deficit) + '</div>' +
        issues +
        '</div>';
    }).join('');
    panel.innerHTML = rows || '<div class="v81-empty">无结果</div>';

    // 同时渲染税档影响（与校验同批返回）
    if (data.cap_impact) renderCapImpact(data.cap_impact);
  }

  // ── 匹配建议 ──
  async function runSuggest() {
    var legs = buildLegsPayload();
    if (legs.length < 2) { toast('请先配置交易腿', 'error'); return; }
    var panel = document.getElementById('tradeSuggestion');
    panel.innerHTML = '<div class="spinner"></div> 计算中…';
    try {
      var resp = await api('/trade/suggest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ league: state.league, season: state.season, as_of: new Date().toISOString(), legs: legs })
      });
      renderSuggestion(resp.data);
    } catch (e) {
      panel.innerHTML = '<div class="v81-empty" style="color:var(--danger);">建议失败: ' + eh(e.message) + '</div>';
    }
  }

  function renderSuggestion(data) {
    var panel = document.getElementById('tradeSuggestion');
    if (!panel || !data) return;
    var blocks = (data.suggestions || []).map(function (s) {
      var sugs = (s.suggestions || []).map(function (sg) {
        var tag = sg.passes ? '<span style="color:var(--accent);">✅ 通过</span>' : '<span style="color:var(--warn);">残余缺口 ' + fmtMoney(sg.residual_deficit) + '</span>';
        var detail = '';
        if (sg.add_player_ids && sg.add_player_ids.length) detail += '加: ' + sg.add_player_ids.join(', ');
        if (sg.remove_player_ids && sg.remove_player_ids.length) detail += (detail ? ' ｜ ' : '') + '减: ' + sg.remove_player_ids.join(', ');
        return '<div class="sug ' + (sg.passes ? 'ok' : 'warn') + '"><div>' + tag + '</div><div class="sub">' + eh(detail) + '</div></div>';
      }).join('') || '<div class="v81-empty">无建议</div>';
      return '<div class="sug-block"><div class="sug-team">' + eh(s.team_abbr) + '</div>' + sugs + '</div>';
    }).join('');
    panel.innerHTML = blocks || '<div class="v81-empty">无建议</div>';
  }

  // ── 税档 / 工资帽影响 ──
  function renderCapImpact(capImpact) {
    var panel = document.getElementById('tradeCapImpact');
    if (!panel) return;
    var rows = (capImpact || []).map(function (c) {
      function statusLabel(s) { return s === 'IN_TAX' ? '税' : (s === 'SECOND' ? '二土豪线' : (s === 'FIRST' ? '一土豪线' : '低于一土豪线')); }
      function apronClass(s) { return s === 'SECOND' ? 'badge-red' : (s === 'FIRST' ? 'badge-warn' : 'badge-green'); }
      return '<div class="cap-row">' +
        '<div class="cap-team">' + eh(c.team_abbr) + '</div>' +
        '<div class="cap-cell">总额 ' + fmtMoney(c.payroll_before) + ' → <strong>' + fmtMoney(c.payroll_after) + '</strong></div>' +
        '<div class="cap-cell">税: ' + (c.tax_status_after === 'IN_TAX' ? '🟡 税档' : '🟢 非税') + '</div>' +
        '<div class="cap-cell">Apron: <span class="badge ' + apronClass(c.apron_status_after) + '">' + statusLabel(c.apron_status_after) + '</span></div>' +
        '</div>';
    }).join('');
    panel.innerHTML = rows || '<div class="v81-empty">无数据</div>';
  }

  // ── 方案生成 ──
  async function runGenerate() {
    var tid = document.getElementById('tradeTlInput').value.trim();
    if (!tid) { toast('请输入目标球员 player_id', 'error'); return; }
    var panel = document.getElementById('tradeTimeline');
    panel.innerHTML = '<div class="spinner"></div> 生成方案中…';
    try {
      var resp = await api('/trade/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ league: state.league, season: state.season, target_player_id: tid, initiator_team: '' })
      });
      var props = (resp.data && resp.data.proposals) || [];
      var html = props.length ? props.map(function (p, i) {
        var legs = p.legs.map(function (l) {
          return '<div class="gen-leg"><strong>' + eh(l.team_abbr) + '</strong> 送出: ' + (l.outgoing.join(', ') || '—') + ' ｜ 接收: ' + (l.incoming.join(', ') || '—') + '</div>';
        }).join('');
        return '<div class="gen-prop"><div class="gen-idx">方案 ' + (i + 1) + '</div>' + legs + '</div>';
      }).join('') : '<div class="v81-empty">未找到可行方案（尝试更换目标球员或发起队）</div>';
      panel.innerHTML = '<div class="card-title" style="margin-bottom:8px;">生成方案（' + props.length + '）</div>' + html;
    } catch (e) {
      panel.innerHTML = '<div class="v81-empty" style="color:var(--danger);">生成失败: ' + eh(e.message) + '</div>';
    }
  }

  // ── 时间线 ──
  async function runPlayerTimeline() {
    var pid = document.getElementById('tradeTlInput').value.trim();
    if (!pid) { toast('请输入 player_id', 'error'); return; }
    var panel = document.getElementById('tradeTimeline');
    panel.innerHTML = '<div class="spinner"></div> 加载中…';
    try {
      var resp = await api('/trade/timeline/player/' + encodeURIComponent(pid) + '?season=' + encodeURIComponent(state.season));
      var d = resp.data;
      if (!d) { panel.innerHTML = '<div class="v81-empty">未找到球员</div>'; return; }
      var seasons = Object.keys(d.salaries || {});
      var rows = seasons.map(function (s) {
        return '<tr><td>' + s + '</td><td style="text-align:right;font-family:var(--mono);">' + fmtMoney(d.salaries[s]) + '</td>' +
          '<td style="text-align:right;font-family:var(--mono);">' + fmtMoney(d.guaranteed[s]) + '</td>' +
          '<td>' + optBadge(d.opts[s]) + partBadge(d.is_partial) + twoWayBadge(d.is_two_way) + '</td></tr>';
      }).join('');
      panel.innerHTML = '<div class="card-title" style="margin:4px 0 8px;">球员 ' + eh(d.player_name) + ' · ' + eh(d.team_abbr) + '</div>' +
        '<table class="tbl"><thead><tr><th>赛季</th><th style="text-align:right;">薪资</th><th style="text-align:right;">保障</th><th>选项</th></tr></thead><tbody>' + rows + '</tbody></table>';
    } catch (e) {
      panel.innerHTML = '<div class="v81-empty" style="color:var(--danger);">失败: ' + eh(e.message) + '</div>';
    }
  }

  async function runTeamTimeline() {
    var sel = document.getElementById('tradeTlTeam');
    var abbr = sel ? sel.value : '';
    if (!abbr) { toast('请选择球队', 'error'); return; }
    var panel = document.getElementById('tradeTimeline');
    panel.innerHTML = '<div class="spinner"></div> 加载中…';
    try {
      var resp = await api('/trade/timeline/team/' + encodeURIComponent(abbr) + '?season=' + encodeURIComponent(state.season));
      var d = resp.data;
      if (!d) { panel.innerHTML = '<div class="v81-empty">未找到球队</div>'; return; }
      var seasons = Object.keys(d.total_salary || {});
      var rows = seasons.map(function (s) {
        var apron = d.apron_status[s];
        var apronCls = apron === 'SECOND' ? 'badge-red' : (apron === 'FIRST' ? 'badge-warn' : 'badge-green');
        return '<tr><td>' + s + '</td><td style="text-align:right;font-family:var(--mono);">' + fmtMoney(d.total_salary[s]) + '</td>' +
          '<td style="text-align:right;font-family:var(--mono);">' + fmtMoney(d.total_guaranteed[s]) + '</td>' +
          '<td>' + (d.tax_status[s] === 'IN_TAX' ? '🟡税' : '🟢非税') + '</td>' +
          '<td><span class="badge ' + apronCls + '">' + apron + '</span></td></tr>';
      }).join('');
      panel.innerHTML = '<div class="card-title" style="margin:4px 0 8px;">球队 ' + eh(d.team_name) + ' · ' + eh(d.team_abbr) + '</div>' +
        '<table class="tbl"><thead><tr><th>赛季</th><th style="text-align:right;">总薪资</th><th style="text-align:right;">保障总额</th><th>税档</th><th>Apron</th></tr></thead><tbody>' + rows + '</tbody></table>';
    } catch (e) {
      panel.innerHTML = '<div class="v81-empty" style="color:var(--danger);">失败: ' + eh(e.message) + '</div>';
    }
  }

  // 暴露公共 API（供 index.html 内联 onchange/onclick 调用）
  window.Trade = {
    render: render,
    onSeason: onSeason,
    onLeague: onLeague,
    setTeam: setTeam,
    addLeg: addLeg,
    removeLeg: removeLeg,
    addPlayer: addPlayer,
    removePlayer: removePlayer,
    runValidate: runValidate,
    runSuggest: runSuggest,
    runGenerate: runGenerate,
    runPlayerTimeline: runPlayerTimeline,
    runTeamTimeline: runTeamTimeline
  };
})();
