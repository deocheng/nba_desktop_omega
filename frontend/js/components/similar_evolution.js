/**
 * NBACore v8.2-C — Similar Evolution (相似球员进化轨迹) Component (纯渲染)
 * 给定目标球员，按生涯轨迹相似度找出最相似球员并叠加对比（echarts）。
 * 数据来自 /api/career/similar-evolution。仅渲染，无计算。
 */
(function () {
  'use strict';

  var METRICS = [
    { v: 'pts_per_game', t: '得分/场 PPG' },
    { v: 'per', t: 'PER' },
    { v: 'ws', t: '胜利贡献 WS' },
    { v: 'vorp', t: '胜利替代值 VORP' },
    { v: 'ts_percent', t: '真实命中率 TS%' },
    { v: 'bpm', t: '正负值 BPM' }
  ];
  var ALGOS = [
    { v: 'pearson', t: 'Pearson 相关' },
    { v: 'cosine', t: 'Cosine 余弦' },
    { v: 'euclidean', t: 'Euclidean 欧氏' }
  ];

  var TARGET_COLOR = '#00b88a';
  var FADE = ['#94a3b8', '#cbd5e1', '#a5b4fc', '#fca5a5', '#fdba74', '#86efac'];

  var targetId = null;
  var targetName = '';
  var chart = null;
  var searchTimer = null;

  function eh(text) {
    if (typeof escapeHtml === 'function') return escapeHtml(text == null ? '' : String(text));
    return String(text == null ? '' : text);
  }
  function fmt(v, d) {
    if (v == null || isNaN(Number(v))) return '—';
    return Number(v).toFixed(d == null ? 2 : d);
  }

  function options(list, sel) {
    return list.map(function (m) {
      return '<option value="' + m.v + '"' + (m.v === sel ? ' selected' : '') + '>' + eh(m.t) + '</option>';
    }).join('');
  }

  // ── Target search ──
  function onSearchInput() {
    var input = document.getElementById('seSearch');
    var q = input ? input.value.trim() : '';
    clearTimeout(searchTimer);
    if (q.length < 2) { hideDropdown(); return; }
    searchTimer = setTimeout(async function () {
      try {
        var d = await api('/players?name=' + encodeURIComponent(q) + '&limit=8');
        var dd = document.getElementById('seDropdown');
        if (!dd) return;
        var list = (d && d.players) || [];
        if (list.length === 0) {
          dd.innerHTML = '<div class="dropdown-item" style="color:var(--text-dim);">无结果</div>';
        } else {
          dd.innerHTML = list.map(function (p) {
            var pid = eh(p.player_id || '');
            var pname = eh(p.full_name || p.player_name || '');
            var sub = [p.team_abbr || p.team, p.position].filter(Boolean).map(eh).join(' · ');
            return '<div class="dropdown-item" onmousedown="SimilarEvo.pick(\'' + pid + '\',\'' + pname.replace(/'/g, "\\'") + '\')">' +
              '<div>' + pname + '</div>' + (sub ? '<div class="sub">' + sub + '</div>' : '') + '</div>';
          }).join('');
        }
        dd.classList.add('show');
      } catch (e) {
        if (typeof toast === 'function') toast(e.message, 'error');
      }
    }, 300);
  }
  function hideDropdown() {
    var dd = document.getElementById('seDropdown');
    if (dd) dd.classList.remove('show');
  }
  function pick(id, name) {
    if (!id) return;
    targetId = id;
    targetName = name;
    var box = document.getElementById('seTarget');
    if (box) box.innerHTML = '<span class="chip" style="border-left:4px solid ' + TARGET_COLOR + ';">' + eh(name) + '</span>';
    var input = document.getElementById('seSearch');
    if (input) input.value = '';
    hideDropdown();
    reload();
  }

  // ── Data + chart ──
  async function reload() {
    var box = document.getElementById('seChart');
    var rankBox = document.getElementById('seRank');
    if (!box) return;
    if (!targetId) {
      if (chart) chart.clear();
      box.innerHTML = '<div class="v81-empty">请搜索并选择目标球员</div>';
      if (rankBox) rankBox.innerHTML = '';
      return;
    }
    box.innerHTML = '<div style="text-align:center; padding:60px; color:var(--text-dim);"><div class="spinner"></div> 加载中...</div>';

    var m = document.getElementById('seMetric');
    var a = document.getElementById('seAlgo');
    var k = document.getElementById('seTopK');
    var mg = document.getElementById('seMinGames');
    var ms = document.getElementById('seMinSeasons');
    var sp = document.getElementById('seSamePos');
    var metric = m ? m.value : 'pts_per_game';
    var algorithm = a ? a.value : 'pearson';
    var top_k = k ? Math.max(1, Math.min(20, parseInt(k.value, 10) || 5)) : 5;
    var minGames = mg ? (parseInt(mg.value, 10) || 20) : 20;
    var minSeasons = ms ? Math.max(1, parseInt(ms.value, 10) || 3) : 3;
    var samePos = sp ? sp.checked : true;

    var qs = 'player_id=' + encodeURIComponent(targetId) +
      '&metric=' + encodeURIComponent(metric) +
      '&top_k=' + top_k + '&min_games=' + minGames +
      '&same_position=' + (samePos ? 'true' : 'false') +
      '&algorithm=' + encodeURIComponent(algorithm) +
      '&min_seasons=' + minSeasons;
    try {
      var resp = await api('/api/career/similar-evolution?' + qs);
      var data = (resp && resp.data) || {};
      draw(data);
      renderRank((data.target || {}), (data.similar || []));
    } catch (e) {
      box.innerHTML = '<div class="v81-empty" style="color:var(--danger);">加载失败: ' + eh(e.message) + '</div>';
      if (rankBox) rankBox.innerHTML = '';
    }
  }

  function draw(data) {
    var box = document.getElementById('seChart');
    if (!box) return;
    if (chart) { try { chart.dispose(); } catch (e) {} }
    box.innerHTML = '';
    var target = data.target || {};
    var similar = data.similar || [];
    if (!target.curve || target.curve.length === 0) {
      box.innerHTML = '<div class="v81-empty">目标球员暂无足够生涯数据</div>';
      return;
    }
    chart = echarts.init(box);

    var ageSet = {};
    function addCurve(curve) { (curve || []).forEach(function (pt) { if (pt.age != null) ageSet[pt.age] = true; }); }
    addCurve(target.curve);
    similar.forEach(function (s) { addCurve(s.curve); });
    var ages = Object.keys(ageSet).map(Number).sort(function (a, b) { return a - b; });

    function toData(curve) {
      var map = {};
      (curve || []).forEach(function (pt) { if (pt.age != null) map[pt.age] = pt.value; });
      return ages.map(function (a) { return (a in map) ? map[a] : null; });
    }

    var series = [{
      name: target.player_name || target.player_id || '目标',
      type: 'line', smooth: true, showSymbol: true, symbolSize: 6,
      data: toData(target.curve),
      connectNulls: false,
      lineStyle: { width: 3.5, color: TARGET_COLOR },
      itemStyle: { color: TARGET_COLOR },
      z: 10
    }];
    similar.forEach(function (s, i) {
      var color = FADE[i % FADE.length];
      series.push({
        name: s.player_name || s.player_id,
        type: 'line', smooth: true, showSymbol: false,
        data: toData(s.curve),
        connectNulls: false,
        lineStyle: { width: 1.5, color: color, opacity: 0.7 },
        itemStyle: { color: color },
        z: 5
      });
    });

    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: series.map(function (s) { return s.name; }), top: 0, type: 'scroll' },
      grid: { left: 50, right: 24, top: 40, bottom: 40 },
      xAxis: { type: 'category', name: '年龄', data: ages, boundaryGap: false },
      yAxis: { type: 'value', name: 'value' },
      series: series
    });
    window.addEventListener('resize', function () { if (chart) chart.resize(); });
  }

  function renderRank(target, similar) {
    var box = document.getElementById('seRank');
    if (!box) return;
    if (!similar || similar.length === 0) {
      box.innerHTML = '<div class="v81-empty">暂无足够相似球员（检查最小出场/赛季数或放宽同位置限制）</div>';
      return;
    }
    var rows = similar.map(function (s, i) {
      var name = eh(s.player_name || s.player_id);
      var bar = Math.max(2, Math.round((s.similarity || 0) * 100));
      return '<tr>' +
        '<td style="font-weight:700; color:var(--text-dim); text-align:center;">' + (i + 1) + '</td>' +
        '<td><div style="font-weight:600;">' + name + '</div></td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + fmt(s.similarity, 3) + '</td>' +
        '<td style="text-align:right; font-family:var(--mono);">' + fmt(s.peak_age, 1) + '</td>' +
        '<td style="min-width:120px;"><div class="sim-bar" style="width:' + bar + '%;"></div></td>' +
        '</tr>';
    }).join('');
    box.innerHTML = '<div class="card-header"><div class="card-title">相似度排名</div>' +
      '<div class="card-badge">目标: ' + eh(target.player_name || target.player_id || '—') + '</div></div>' +
      '<div class="tbl-wrap" style="max-height:420px; overflow:auto;">' +
      '<table class="tbl"><thead><tr>' +
      '<th style="width:36px; text-align:center;">#</th><th>球员</th>' +
      '<th style="text-align:right;">相似度</th><th style="text-align:right;">巅峰年龄</th><th>轨迹</th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table></div>';
  }

  async function render(containerId) {
    var container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML =
      '<div class="page-header"><h2>相似球员进化轨迹 · Similar Evolution</h2></div>' +
      '<div class="card">' +
      '  <div class="card-header"><div class="card-title">目标球员与参数</div></div>' +
      '  <div class="form-row" style="flex-wrap:wrap; gap:12px; align-items:flex-end;">' +
      '    <div style="min-width:260px; position:relative;">' +
      '      <label class="label">目标球员 Target</label>' +
      '      <input class="input" id="seSearch" type="text" placeholder="输入球员名…" oninput="SimilarEvo.onSearch()" onblur="setTimeout(SimilarEvo.hideDropdown,200)">' +
      '      <div class="dropdown" id="seDropdown"></div>' +
      '    </div>' +
      '    <div style="min-width:170px;"><label class="label">指标 Metric</label>' +
      '      <select class="select" id="seMetric" onchange="SimilarEvo.reload()">' + options(METRICS, 'pts_per_game') + '</select></div>' +
      '    <div style="min-width:160px;"><label class="label">算法 Algorithm</label>' +
      '      <select class="select" id="seAlgo" onchange="SimilarEvo.reload()">' + options(ALGOS, 'pearson') + '</select></div>' +
      '    <div style="min-width:90px;"><label class="label">Top K</label>' +
      '      <input class="input" id="seTopK" type="number" value="5" min="1" max="20" onchange="SimilarEvo.reload()"></div>' +
      '    <div style="min-width:100px;"><label class="label">最小出场</label>' +
      '      <input class="input" id="seMinGames" type="number" value="20" min="0" onchange="SimilarEvo.reload()"></div>' +
      '    <div style="min-width:100px;"><label class="label">最小赛季</label>' +
      '      <input class="input" id="seMinSeasons" type="number" value="3" min="1" onchange="SimilarEvo.reload()"></div>' +
      '    <div style="min-width:140px; display:flex; align-items:center; gap:6px; padding-bottom:8px;">' +
      '      <input type="checkbox" id="seSamePos" checked onchange="SimilarEvo.reload()"> <label class="label" for="seSamePos">同位置</label></div>' +
      '  </div>' +
      '  <div id="seTarget" style="margin-top:10px;"></div>' +
      '</div>' +
      '<div class="card"><div class="card-header"><div class="card-title">轨迹叠加（目标高亮）</div></div>' +
      '  <div class="chart-box" id="seChart" style="min-height:400px;"></div></div>' +
      '<div class="card"><div id="seRank"></div></div>';
    if (chart) { try { chart.dispose(); } catch (e) {} chart = null; }
  }

  window.SimilarEvo = {
    render: render,
    reload: reload,
    onSearch: onSearchInput,
    hideDropdown: hideDropdown,
    pick: pick
  };
})();
