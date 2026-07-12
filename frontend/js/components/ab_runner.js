/**
 * NBACore Studio v8.3.2 — Analytics Builder: run + results
 * ===================================================================
 * Sends the graph to the backend /run endpoint and renders the returned
 * viz_results (table / line / bar via echarts) plus per-node status and
 * errors. Performs NO computation itself (v8 §6).
 *
 * Exposes: window.AB_Runner
 */
(function () {
  'use strict';

  var _charts = [];   // track echarts instances for disposal

  function eh(s) {
    if (typeof window.escapeHtml === 'function') return window.escapeHtml(s == null ? '' : String(s));
    return String(s == null ? '' : s);
  }

  function disposeCharts() {
    _charts.forEach(function (c) { try { c.dispose(); } catch (e) {} });
    _charts = [];
  }

  // build the request payload from a canvas graph
  function buildFlow(canvasGraph) {
    return {
      nodes: canvasGraph.nodes.map(function (n) {
        return { id: n.id, type: n.type, title: n.title, params: n.params || {} };
      }),
      edges: canvasGraph.edges.map(function (e) {
        return { id: e.id, from: e.from, to: e.to };
      })
    };
  }

  async function run(canvasGraph, workspaceId) {
    var flow = buildFlow(canvasGraph);
    var resp = await window.api('/api/analytics-builder/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ flow: flow, workspace_id: workspaceId || null })
    });
    // envelope {code, data, message}
    if (resp && typeof resp.data !== 'undefined') return resp.data;
    return resp;
  }

  function renderResults(container, result) {
    if (!container) return;
    disposeCharts();
    if (!result) { container.innerHTML = '<div class="v81-empty" style="color:var(--text-dim);">暂无结果</div>'; return; }

    var html = '';

    // node status summary
    var status = result.node_status || {};
    var ids = Object.keys(status);
    if (ids.length) {
      html += '<div class="ab-status-row" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;">';
      ids.forEach(function (id) {
        var st = status[id];
        var color = st === 'ok' ? 'var(--success)' : (st === 'error' ? 'var(--danger)' : 'var(--text-dim)');
        html += '<span class="badge" style="border:1px solid ' + color + ';color:' + color + ';">' + eh(id) + ': ' + eh(st) + '</span>';
      });
      html += '</div>';
    }

    // errors
    var errors = result.errors || [];
    if (errors.length) {
      html += '<div class="card" style="border-color:var(--danger);margin-bottom:10px;">';
      html += '<div class="card-header"><div class="card-title" style="color:var(--danger);">运行错误 (' + errors.length + ')</div></div>';
      html += errors.map(function (e) {
        return '<div style="font-size:12px;color:var(--danger);padding:4px 0;">• ' + eh(e.node_id) + ': ' + eh(e.message) + '</div>';
      }).join('');
      html += '</div>';
    }

    // viz results
    var viz = result.viz_results || [];
    if (!viz.length) {
      html += '<div class="v81-empty" style="color:var(--text-dim);">没有可视化节点输出（请添加 visualize 节点并运行）</div>';
    } else {
      viz.forEach(function (v, idx) {
        html += '<div class="card" style="margin-bottom:12px;">';
        html += '<div class="card-header"><div class="card-title">' + eh(v.title || (v.node_id + ' · ' + (v.viz_type || ''))) + '</div>' +
          '<span class="card-badge">' + eh(v.viz_type || '') + ' · ' + (v.row_count != null ? v.row_count : 0) + ' 行</span></div>';
        if (v.viz_type === 'table') {
          html += renderTable(v);
        } else {
          var domId = 'abChart_' + idx;
          html += '<div id="' + domId + '" class="chart-container" style="height:320px;"></div>';
        }
        html += '</div>';
      });
    }

    container.innerHTML = html;

    // instantiate echarts after DOM insertion
    viz.forEach(function (v, idx) {
      if (v.viz_type === 'table') return;
      var dom = document.getElementById('abChart_' + idx);
      if (!dom || typeof window.echarts === 'undefined') return;
      try {
        var chart = window.echarts.init(dom);
        chart.setOption(buildEchartsOption(v));
        _charts.push(chart);
      } catch (e) {
        dom.innerHTML = '<div style="color:var(--danger);padding:12px;">图表渲染失败: ' + eh(e.message) + '</div>';
      }
    });
  }

  function renderTable(v) {
    var cols = v.columns || [];
    var rows = v.rows || [];
    if (!cols.length) return '<div class="v81-empty" style="color:var(--text-dim);">无列</div>';
    var head = '<tr>' + cols.map(function (c) { return '<th>' + eh(c.name) + '</th>'; }).join('') + '</tr>';
    var body = rows.map(function (r) {
      return '<tr>' + cols.map(function (c) { return '<td>' + eh(r[c.name]) + '</td>'; }).join('') + '</tr>';
    }).join('');
    return '<div class="tbl-wrap" style="max-height:420px;"><table class="tbl"><thead>' + head + '</thead><tbody>' + body + '</tbody></table></div>';
  }

  function buildEchartsOption(v) {
    var cols = v.columns || [];
    var rows = v.rows || [];
    var xField = v.x_field;
    var yFields = v.y_fields || [];

    // fallback: pick sensible defaults if not provided
    if (!xField && cols.length) xField = cols[0].name;
    if (!yFields.length && cols.length > 1) yFields = [cols[1].name];

    var categories = rows.map(function (r) { return r[xField]; });
    var series = yFields.map(function (yf) {
      return {
        name: yf,
        type: v.viz_type === 'bar' ? 'bar' : 'line',
        data: rows.map(function (r) { return r[yf]; }),
        smooth: v.viz_type === 'line'
      };
    });

    return {
      tooltip: { trigger: 'axis' },
      legend: { data: yFields, textStyle: { color: '#cbd5e1' } },
      grid: { left: 50, right: 20, top: 40, bottom: 50 },
      xAxis: { type: 'category', data: categories, axisLabel: { color: '#94a3b8', rotate: categories.length > 8 ? 30 : 0 } },
      yAxis: { type: 'value', axisLabel: { color: '#94a3b8' } },
      backgroundColor: 'transparent'
    };
  }

  window.AB_Runner = {
    run: run,
    renderResults: renderResults,
    dispose: disposeCharts
  };
})();
