/**
 * NBACore v8.2-C — Age Curve (年龄曲线) Component (纯渲染)
 * 以年龄为 X、选定指标为 Y 的生涯轨迹折线，多球员 × 多指标叠加（echarts）。
 * 数据来自 /api/career/age-curve（支持 metrics 多指标）。仅渲染，无计算。
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
  // metric -> label lookup
  var METRIC_LABEL = {};
  METRICS.forEach(function (m) { METRIC_LABEL[m.v] = m.t; });

  // per-player color, per-metric line style
  var PALETTE = ['#00b88a', '#3b82f6', '#f97316', '#8b5cf6', '#ef4444', '#06b6d4', '#f59e0b'];
  var DASH = ['solid', 'dashed', 'dotted', 'dashDot', 'dashDotDot', 'longDash'];

  // module-level state
  var selectedIds = [];      // BBR ids currently plotted
  var selectedNames = {};    // id -> name
  var selectedMetrics = ['pts_per_game']; // default PPG
  var chart = null;
  var searchTimer = null;

  function eh(text) {
    if (typeof escapeHtml === 'function') return escapeHtml(text == null ? '' : String(text));
    return String(text == null ? '' : text);
  }

  // ── Metric pills (multi-select) ──
  function metricPills() {
    return METRICS.map(function (m) {
      var on = selectedMetrics.indexOf(m.v) !== -1;
      return '<span class="ac-pill' + (on ? ' on' : '') + '" ' +
        'data-metric="' + m.v + '" onclick="AgeCurve.toggleMetric(\'' + m.v + '\')">' +
        eh(m.t) + '</span>';
    }).join('');
  }

  // ── Player search (self-contained, reuse /players?name=) ──
  function onSearchInput() {
    var input = document.getElementById('acSearch');
    var q = input ? input.value.trim() : '';
    clearTimeout(searchTimer);
    if (q.length < 2) { hideDropdown(); return; }
    searchTimer = setTimeout(async function () {
      try {
        var d = await api('/players?name=' + encodeURIComponent(q) + '&limit=8');
        var dd = document.getElementById('acDropdown');
        if (!dd) return;
        var list = (d && d.players) || [];
        if (list.length === 0) {
          dd.innerHTML = '<div class="dropdown-item" style="color:var(--text-dim);">无结果</div>';
        } else {
          dd.innerHTML = list.map(function (p) {
            var pid = eh(p.player_id || '');
            var pname = eh(p.full_name || p.player_name || '');
            var sub = [p.team_abbr || p.team, p.position].filter(Boolean).map(eh).join(' · ');
            return '<div class="dropdown-item" onmousedown="AgeCurve.pick(\'' + pid + '\',\'' + pname.replace(/'/g, "\\'") + '\')">' +
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
    var dd = document.getElementById('acDropdown');
    if (dd) dd.classList.remove('show');
  }
  function pick(id, name) {
    if (!id) return;
    if (selectedIds.indexOf(id) === -1) {
      selectedIds.push(id);
      selectedNames[id] = name;
      renderChips();
      reload();
    }
    var input = document.getElementById('acSearch');
    if (input) input.value = '';
    hideDropdown();
  }
  function removeId(id) {
    selectedIds = selectedIds.filter(function (x) { return x !== id; });
    delete selectedNames[id];
    renderChips();
    reload();
  }
  function renderChips() {
    var box = document.getElementById('acChips');
    if (!box) return;
    if (selectedIds.length === 0) {
      box.innerHTML = '<span style="color:var(--text-dim); font-size:12px;">未选择球员</span>';
      return;
    }
    box.innerHTML = selectedIds.map(function (id, i) {
      return '<span class="chip" style="border-left:4px solid ' + PALETTE[i % PALETTE.length] + ';">' +
        eh(selectedNames[id] || id) +
        ' <span class="chip-x" onclick="AgeCurve.remove(\'' + id + '\')">✕</span></span>';
    }).join('');
  }

  // ── Metric toggle ──
  function toggleMetric(v) {
    var idx = selectedMetrics.indexOf(v);
    if (idx === -1) {
      selectedMetrics.push(v);
    } else if (selectedMetrics.length > 1) {
      selectedMetrics.splice(idx, 1);
    } else {
      return; // keep at least one metric selected
    }
    var mw = document.getElementById('acMetricWrap');
    if (mw) mw.innerHTML = metricPills();
    reload();
  }

  // ── Data + chart ──
  async function reload() {
    var box = document.getElementById('acChart');
    if (!box) return;
    if (selectedIds.length === 0) {
      if (chart) { chart.clear(); }
      box.innerHTML = '<div class="v81-empty">请搜索并添加球员以绘制年龄曲线</div>';
      return;
    }
    box.innerHTML = '<div style="text-align:center; padding:60px; color:var(--text-dim);"><div class="spinner"></div> 加载中...</div>';
    try {
      var qs = 'player_ids=' + encodeURIComponent(selectedIds.join(',')) +
        '&metrics=' + encodeURIComponent(selectedMetrics.join(','));
      var resp = await api('/api/career/age-curve?' + qs);
      var players = (resp && resp.data && resp.data.players) || [];
      draw(players);
    } catch (e) {
      box.innerHTML = '<div class="v81-empty" style="color:var(--danger);">加载失败: ' + eh(e.message) + '</div>';
    }
  }

  function resolveCurves(p) {
    // Prefer multi-metric `curves`; fall back to legacy single `curve`.
    if (p.curves && Object.keys(p.curves).length) return p.curves;
    var m0 = selectedMetrics[0] || 'pts_per_game';
    var c = {};
    if (p.curve) c[m0] = p.curve;
    return c;
  }
  function resolvePeakAges(p) {
    if (p.peak_ages && Object.keys(p.peak_ages).length) return p.peak_ages;
    var m0 = selectedMetrics[0] || 'pts_per_game';
    var pa = {};
    if (p.peak_age != null) pa[m0] = p.peak_age;
    return pa;
  }

  function draw(players) {
    var box = document.getElementById('acChart');
    if (!box) return;
    // dispose previous
    if (chart) { try { chart.dispose(); } catch (e) {} }
    box.innerHTML = '';
    chart = echarts.init(box);

    var normEl = document.getElementById('acNorm');
    var norm = !!(normEl && normEl.checked);

    // union of ages across all metrics/players
    var ageSet = {};
    players.forEach(function (p) {
      var curves = resolveCurves(p);
      Object.keys(curves).forEach(function (m) {
        (curves[m] || []).forEach(function (pt) { if (pt.age != null) ageSet[pt.age] = true; });
      });
    });
    var ages = Object.keys(ageSet).map(Number).sort(function (a, b) { return a - b; });

    // per-metric normalization range (min/max across all players)
    var normRange = {};
    if (norm) {
      METRICS.forEach(function (m) {
        var lo = Infinity, hi = -Infinity, has = false;
        players.forEach(function (p) {
          var pts = resolveCurves(p)[m.v] || [];
          pts.forEach(function (pt) {
            if (pt.value != null) { lo = Math.min(lo, pt.value); hi = Math.max(hi, pt.value); has = true; }
          });
        });
        normRange[m.v] = has ? { min: lo, max: hi } : { min: 0, max: 0 };
      });
    }
    function normVal(m, v) {
      if (v == null) return null;
      var r = normRange[m];
      if (!r || r.max === r.min) return 0;
      return (v - r.min) / (r.max - r.min) * 100;
    }

    // count total lines (for peak markPoint density control)
    var totalLines = 0;
    players.forEach(function (p) {
      var curves = resolveCurves(p);
      selectedMetrics.forEach(function (m) {
        if ((curves[m] || []).length) totalLines++;
      });
    });

    var series = [];
    var rawMap = {};   // seriesIndex -> { age: rawValue }
    var legendData = [];

    players.forEach(function (p, i) {
      var color = PALETTE[i % PALETTE.length];
      var curves = resolveCurves(p);
      var peakAges = resolvePeakAges(p);
      selectedMetrics.forEach(function (m, mi) {
        var pts = curves[m] || [];
        if (!pts.length) return;
        var map = {};
        var rawByAge = {};
        pts.forEach(function (pt) {
          if (pt.age == null) return;
          map[pt.age] = norm ? normVal(m, pt.value) : pt.value;
          rawByAge[pt.age] = pt.value;
        });
        var data = ages.map(function (a) { return (a in map) ? map[a] : null; });
        var sIdx = series.length;
        rawMap[sIdx] = rawByAge;
        var name = (p.player_name || p.player_id) + ' · ' + (METRIC_LABEL[m] || m);
        legendData.push(name);

        // peak markPoint (only when not too crowded)
        var markPoint = undefined;
        if (totalLines <= 6) {
          var peakAge = (peakAges[m] != null) ? peakAges[m] : null;
          if (peakAge != null && (peakAge in map)) {
            markPoint = {
              symbolSize: 46,
              data: [{ coord: [peakAge, map[peakAge]], value: '巅' }],
              itemStyle: { color: color },
              label: { color: '#fff', fontSize: 11 }
            };
          }
        }

        series.push({
          name: name,
          type: 'line',
          smooth: true,
          showSymbol: true,
          symbolSize: 5,
          connectNulls: false,
          data: data,
          lineStyle: { width: 2.5, color: color, type: DASH[mi % DASH.length] },
          itemStyle: { color: color },
          markPoint: markPoint
        });
      });
    });

    var yName = norm
      ? '归一化值 (0-100%)'
      : ((selectedMetrics[0] && METRIC_LABEL[selectedMetrics[0]]) || '值');

    chart.setOption({
      tooltip: {
        trigger: 'axis',
        formatter: function (params) {
          if (!params || !params.length) return '';
          var age = params[0].axisValue;
          var html = '<b>年龄 ' + age + '</b>';
          params.forEach(function (it) {
            var rb = rawMap[it.seriesIndex] || {};
            var raw = (age in rb) ? rb[age] : null;
            var valStr = raw == null ? '—' : (typeof raw === 'number' ? raw.toFixed(2) : raw);
            html += '<br/>' + it.marker + it.seriesName + ' : ' + valStr;
          });
          return html;
        }
      },
      legend: {
        data: legendData,
        top: 0,
        type: legendData.length > 8 ? 'scroll' : 'plain'
      },
      grid: { left: 60, right: 24, top: 50, bottom: 40 },
      xAxis: { type: 'category', name: '年龄', data: ages, boundaryGap: false },
      yAxis: { type: 'value', name: yName },
      series: series
    });
    window.addEventListener('resize', function () { if (chart) chart.resize(); });
  }

  async function render(containerId) {
    var container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML =
      '<div class="page-header"><h2>年龄曲线 · Age Curve</h2></div>' +
      '<div class="card">' +
      '  <div class="card-header"><div class="card-title">选择球员</div></div>' +
      '  <div class="form-row" style="flex-wrap:wrap; gap:12px; align-items:flex-end;">' +
      '    <div style="min-width:260px; position:relative;">' +
      '      <label class="label">搜索球员 Search</label>' +
      '      <input class="input" id="acSearch" type="text" placeholder="输入球员名…" oninput="AgeCurve.onSearch()" onblur="setTimeout(AgeCurve.hideDropdown,200)">' +
      '      <div class="dropdown" id="acDropdown"></div>' +
      '    </div>' +
      '    <div style="min-width:240px;"><label class="label">指标 Metric（可多选叠加）</label>' +
      '      <div id="acMetricWrap" style="display:flex; gap:6px; flex-wrap:wrap; align-items:center;">' + metricPills() + '</div></div>' +
      '    <div style="min-width:120px;"><label class="label">&nbsp;</label>' +
      '      <label style="display:inline-flex; align-items:center; gap:6px; cursor:pointer; font-size:13px;">' +
      '        <input type="checkbox" id="acNorm" checked onchange="AgeCurve.reload()"> 归一化 0-100%</label></div>' +
      '  </div>' +
      '  <div id="acChips" style="margin-top:10px; display:flex; gap:8px; flex-wrap:wrap;"></div>' +
      '</div>' +
      '<div class="card"><div class="card-header"><div class="card-title">生涯轨迹</div></div>' +
      '  <div class="chart-box" id="acChart" style="min-height:380px;"></div>' +
      '</div>';
    renderChips();
    if (chart) { try { chart.dispose(); } catch (e) {} chart = null; }
  }

  window.AgeCurve = {
    render: render,
    reload: reload,
    onSearch: onSearchInput,
    hideDropdown: hideDropdown,
    pick: pick,
    remove: removeId,
    toggleMetric: toggleMetric
  };
})();
