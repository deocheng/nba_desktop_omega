/**
 * NBACore Studio v8.3 — Workspace Component
 * ==========================================
 * List + detail CRUD over /api/workspaces. Pure render, all data via api().
 *
 * Depends on globals from js/app.js (loaded first):
 *   api(), escapeHtml(), toast(), window.THEME
 *
 * List view:  window.Workspace.renderList(containerId)
 * Detail view: window.Workspace.renderDetail(containerId, id)
 *
 * Action helpers (WS_*) are attached to window so inline onclick handlers work.
 */
(function () {
  'use strict';

  var THEME = window.THEME || {};

  // Module state used by action handlers to re-render in place
  var currentContainerId = 'workspaceRoot';
  var currentWsId = null;

  // ── Helpers ──
  function eh(text) {
    if (typeof escapeHtml === 'function') return escapeHtml(text == null ? '' : String(text));
    return String(text == null ? '' : text);
  }

  function statusClass(s) {
    if (s === 'active') return 'badge-green';
    if (s === 'archived') return 'badge-orange';
    return 'badge-gray';
  }

  function statusLabel(s) {
    if (s === 'active') return '启用';
    if (s === 'archived') return '归档';
    if (s === 'inactive') return '停用';
    return eh(s || '—');
  }

  // ── List view ──
  async function renderList(containerId) {
    var container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML =
      '<div style="text-align:center; padding:30px; color:var(--text-dim);">' +
      '<div class="spinner"></div> 加载工作区...</div>';
    try {
      var list = await api('/api/workspaces');
      if (!Array.isArray(list)) list = [];
      renderListData(container, list);
    } catch (e) {
      container.innerHTML =
        '<div class="card"><div class="v81-empty" style="color:var(--danger);">加载失败: ' + eh(e.message) + '</div></div>';
    }
  }

  function renderListData(container, list) {
    var html = '';

    // Toolbar card
    html += '<div class="card">';
    html += '  <div class="card-header">';
    html += '    <div class="card-title">工作区列表 · Workspaces</div>';
    html += '    <button class="btn btn-primary btn-sm" onclick="WS_newToggle()">＋ 新建工作区</button>';
    html += '  </div>';
    html += '  <div id="wsNewForm" class="ws-new-form" style="display:none;">';
    html += '    <div class="form-row" style="align-items:flex-end;">';
    html += '      <div style="flex:1; min-width:200px;"><label class="label">名称</label><input class="input" id="wsNewName" placeholder="我的工作区"></div>';
    html += '      <div style="flex:2; min-width:260px;"><label class="label">描述</label><input class="input" id="wsNewDesc" placeholder="可选描述"></div>';
    html += '      <button class="btn btn-primary" onclick="WS_create()">创建</button>';
    html += '      <button class="btn" onclick="WS_newToggle()">取消</button>';
    html += '    </div>';
    html += '  </div>';
    html += '</div>';

    if (list.length === 0) {
      html += '<div class="card"><div class="v81-empty">暂无工作区，点击上方按钮新建</div></div>';
    } else {
      html += '<div class="ws-grid">';
      html += list.map(function (ws) {
        var chartsN = (ws.charts || []).length;
        var dsN = (ws.datasets || []).length;
        var fmN = (ws.formulas || []).length;
        return '<div class="ws-card">' +
          '<div class="ws-card-head">' +
          '<div class="ws-name">' + eh(ws.name) + '</div>' +
          '<span class="badge ' + statusClass(ws.status) + '">' + statusLabel(ws.status) + '</span>' +
          '</div>' +
          '<div class="ws-desc">' + (ws.description ? eh(ws.description) : '<span style="color:var(--text-dim);">无描述</span>') + '</div>' +
          '<div class="ws-counts">' +
          '<span class="ws-count">📊 ' + chartsN + ' 图表</span>' +
          '<span class="ws-count">📁 ' + dsN + ' 数据集</span>' +
          '<span class="ws-count">ƒ ' + fmN + ' 公式</span>' +
          '</div>' +
          '<div class="ws-actions">' +
          '<button class="btn btn-sm" onclick="WS_open(' + ws.id + ')">打开</button>' +
          '<button class="btn btn-sm" onclick="WS_export(' + ws.id + ')">导出</button>' +
          '<button class="btn btn-sm" onclick="WS_duplicate(' + ws.id + ')">复制</button>' +
          '<button class="btn btn-sm btn-danger" onclick="WS_delete(' + ws.id + ')">删除</button>' +
          '</div>' +
          '</div>';
      }).join('');
      html += '</div>';
    }

    container.innerHTML = html;
  }

  // ── Detail view ──
  async function renderDetail(containerId, id) {
    currentContainerId = containerId || 'workspaceRoot';
    currentWsId = id;
    var container = document.getElementById(currentContainerId);
    if (!container) return;
    container.innerHTML =
      '<div style="text-align:center; padding:30px; color:var(--text-dim);">' +
      '<div class="spinner"></div> 加载工作区详情...</div>';
    try {
      var ws = await api('/api/workspaces/' + id);
      renderDetailData(container, ws);
    } catch (e) {
      container.innerHTML =
        '<div class="card"><div class="v81-empty" style="color:var(--danger);">加载失败: ' + eh(e.message) + '</div>' +
        '<button class="btn btn-sm" onclick="WS_back()">← 返回列表</button></div>';
    }
  }

  function renderDetailData(container, ws) {
    var html = '';

    // Back + header
    html += '<button class="btn btn-sm" onclick="WS_back()">← 返回列表</button>';
    html += '<div class="card" style="margin-top:12px;">';
    html += '  <div class="card-header">';
    html += '    <div class="card-title">' + eh(ws.name) + '</div>';
    html += '    <span class="badge ' + statusClass(ws.status) + '">' + statusLabel(ws.status) + '</span>';
    html += '  </div>';
    html += '  <div class="ws-desc" style="font-size:13px; margin-bottom:8px;">' +
      (ws.description ? eh(ws.description) : '<span style="color:var(--text-dim);">无描述</span>') + '</div>';
    html += '  <div class="ws-meta">';
    html += '    <span>ID: ' + eh(ws.id) + '</span>';
    html += '    <span>创建: ' + eh(ws.created_at || '—') + '</span>';
    html += '    <span>更新: ' + eh(ws.updated_at || '—') + '</span>';
    html += '  </div>';
    html += '</div>';

    // Datasets section
    html += buildResourceSection('数据集 · Datasets', 'dataset', ws.datasets, 'wsAddDatasetId', 'dataset id', 'WS_addDataset');
    // Formulas section
    html += buildResourceSection('公式 · Formulas', 'formula', ws.formulas, 'wsAddFormulaId', 'formula id', 'WS_addFormula');

    // Charts section
    html += '<div class="card">';
    html += '  <div class="card-header"><div class="card-title">图表 · Charts</div></div>';
    var charts = ws.charts || [];
    if (charts.length === 0) {
      html += '<div class="v81-empty">暂无图表</div>';
    } else {
      html += charts.map(function (c) {
        return '<div class="ws-chart-item">' +
          '<span class="ws-chart-name" onclick="WS_renameChart(' + c.id + ')">' + eh(c.name) + '</span>' +
          '<button class="btn btn-sm btn-danger" onclick="WS_removeChart(' + c.id + ')">删除</button>' +
          '</div>';
      }).join('');
    }
    html += '  <div class="ws-addform">' +
      '<input class="input" id="wsAddChartName" placeholder="图表名称" style="width:160px;">' +
      '<button class="btn btn-sm btn-primary" onclick="WS_addChart()">添加图表</button>' +
      '</div>';
    html += '</div>';

    // Formula Presets section
    html += '<div class="card">';
    html += '  <div class="card-header"><div class="card-title">📐 预设公式 · Formula Presets</div></div>';
    html += '  <div id="wsPresetsContainer" style="max-height:260px; overflow-y:auto;">';
    html += '    <div style="text-align:center; padding:12px; color:var(--text-dim);"><div class="spinner" style="width:18px;height:18px;display:inline-block;"></div> 加载中...</div>';
    html += '  </div>';
    html += '</div>';

    container.innerHTML = html;

    // Load presets async
    loadPresets(ws.id);
  }

  async function loadPresets(wsId) {
    var cont = document.getElementById('wsPresetsContainer');
    if (!cont) return;
    try {
      var presets = await api('/api/workspaces/formulas/presets');
      var currentFormulas = [];  // will be populated from ws
      var html = '';
      var categoryOrder = ['效率', '影响力', '命中率', '投篮', '组织', '篮板', '综合'];
      var grouped = {};
      presets.forEach(function(p) {
        if (!grouped[p.category]) grouped[p.category] = [];
        grouped[p.category].push(p);
      });
      categoryOrder.forEach(function(cat) {
        var items = grouped[cat] || [];
        if (items.length === 0) return;
        html += '<div style="margin-top:8px;"><span class="card-badge">' + cat + '</span></div>';
        items.forEach(function(p) {
          html += '<div class="ws-preset-item" style="display:flex; align-items:center; gap:8px; padding:6px 8px; border-bottom:1px solid var(--border);">' +
            '<span style="font-weight:600; min-width:60px;">' + eh(p.name) + '</span>' +
            '<span style="flex:1; font-size:11px; color:var(--text-dim);">' + eh(p.description) + '</span>' +
            '<button class="btn btn-sm btn-primary" onclick="WS_importPreset(' + wsId + ',' + p.id + ',\'' + eh(p.name) + '\')">导入</button>' +
            '</div>';
        });
      });
      if (!html) html = '<div style="color:var(--text-dim); padding:8px;">暂无预设公式</div>';
      cont.innerHTML = html;
    } catch (e) {
      cont.innerHTML = '<div style="color:var(--danger); padding:8px;">加载失败: ' + eh(e.message) + '</div>';
    }
  }

  function buildResourceSection(title, kind, ids, inputId, placeholder, addFn) {
    var html = '<div class="card">';
    html += '  <div class="card-header"><div class="card-title">' + title + '</div>' +
      '<span class="card-badge">' + (ids ? ids.length : 0) + '</span></div>';
    html += '  <div class="ws-chips">';
    if (!ids || ids.length === 0) {
      html += '<span style="color:var(--text-dim); font-size:12px;">（空）</span>';
    } else {
      html += ids.map(function (id) {
        var removeFn = kind === 'dataset' ? 'WS_removeDataset' : 'WS_removeFormula';
        return '<span class="ws-chip">' + eh(id) +
          '<span class="ws-chip-x" onclick="' + removeFn + '(' + currentWsId + ',' + id + ')">×</span></span>';
      }).join('');
    }
    html += '  </div>';
    html += '  <div class="ws-addform">' +
      '<input class="input" id="' + inputId + '" placeholder="' + placeholder + '" style="width:140px;">' +
      '<button class="btn btn-sm btn-primary" onclick="' + addFn + '()">添加</button>' +
      '</div>';
    html += '</div>';
    return html;
  }

  // ── Action handlers (exposed on window for inline onclick) ──
  function newToggle() {
    var f = document.getElementById('wsNewForm');
    if (f) f.style.display = (f.style.display === 'none') ? 'block' : 'none';
  }

  async function create() {
    var name = (document.getElementById('wsNewName') || {}).value;
    var desc = (document.getElementById('wsNewDesc') || {}).value || '';
    if (!name) { toast('请输入工作区名称', 'error'); return; }
    try {
      await api('/api/workspaces', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, owner_id: 1, description: desc, status: 'active' })
      });
      toast('工作区已创建', 'success');
      await renderList('workspaceRoot');
    } catch (e) {
      toast('创建失败: ' + e.message, 'error');
    }
  }

  async function openDetail(id) {
    await renderDetail('workspaceRoot', id);
  }

  function exportWs(id) {
    window.open('/api/workspaces/' + id + '/export');
  }

  async function duplicate(id) {
    try {
      await api('/api/workspaces/' + id + '/duplicate?new_name=' + encodeURIComponent('副本-' + id), { method: 'POST' });
      toast('已复制工作区', 'success');
      await renderList('workspaceRoot');
    } catch (e) {
      toast('复制失败: ' + e.message, 'error');
    }
  }

  async function deleteWs(id) {
    if (!confirm('确认删除该工作区？此操作不可恢复。')) return;
    try {
      await api('/api/workspaces/' + id, { method: 'DELETE' });
      toast('已删除', 'success');
      await renderList('workspaceRoot');
    } catch (e) {
      toast('删除失败: ' + e.message, 'error');
    }
  }

  function backToList() {
    renderList('workspaceRoot');
  }

  async function addDataset() {
    var id = parseInt((document.getElementById('wsAddDatasetId') || {}).value, 10);
    if (!id) { toast('请输入 dataset id', 'error'); return; }
    try {
      await api('/api/workspaces/' + currentWsId + '/datasets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dataset_id: id })
      });
      toast('已添加数据集', 'success');
      await renderDetail(currentContainerId, currentWsId);
    } catch (e) {
      toast('添加失败: ' + e.message, 'error');
    }
  }

  async function removeDataset(wsId, dsId) {
    try {
      await api('/api/workspaces/' + wsId + '/datasets/' + dsId, { method: 'DELETE' });
      toast('已移除数据集', 'success');
      await renderDetail(currentContainerId, currentWsId);
    } catch (e) {
      toast('移除失败: ' + e.message, 'error');
    }
  }

  async function addFormula() {
    var id = parseInt((document.getElementById('wsAddFormulaId') || {}).value, 10);
    if (!id) { toast('请输入 formula id', 'error'); return; }
    try {
      await api('/api/workspaces/' + currentWsId + '/formulas', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ formula_id: id })
      });
      toast('已添加公式', 'success');
      await renderDetail(currentContainerId, currentWsId);
    } catch (e) {
      toast('添加失败: ' + e.message, 'error');
    }
  }

  async function removeFormula(wsId, fmId) {
    try {
      await api('/api/workspaces/' + wsId + '/formulas/' + fmId, { method: 'DELETE' });
      toast('已移除公式', 'success');
      await renderDetail(currentContainerId, currentWsId);
    } catch (e) {
      toast('移除失败: ' + e.message, 'error');
    }
  }

  async function importPreset(wsId, presetId, presetName) {
    try {
      await api('/api/workspaces/' + wsId + '/formulas', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ formula_id: presetId })
      });
      toast('已导入公式: ' + presetName, 'success');
      await renderDetail(currentContainerId, currentWsId);
    } catch (e) {
      toast('导入失败: ' + e.message, 'error');
    }
  }

  async function addChart() {
    var name = (document.getElementById('wsAddChartName') || {}).value;
    if (!name) { toast('请输入图表名称', 'error'); return; }
    try {
      await api('/api/workspaces/' + currentWsId + '/charts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, chart_config: {} })
      });
      toast('已添加图表', 'success');
      await renderDetail(currentContainerId, currentWsId);
    } catch (e) {
      toast('添加失败: ' + e.message, 'error');
    }
  }

  async function removeChart(chartId) {
    try {
      await api('/api/workspaces/' + currentWsId + '/charts/' + chartId, { method: 'DELETE' });
      toast('已删除图表', 'success');
      await renderDetail(currentContainerId, currentWsId);
    } catch (e) {
      toast('删除失败: ' + e.message, 'error');
    }
  }

  async function renameChart(chartId) {
    var name = prompt('输入新的图表名称');
    if (!name) return;
    try {
      await api('/api/workspaces/' + currentWsId + '/charts/' + chartId, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name })
      });
      toast('已重命名', 'success');
      await renderDetail(currentContainerId, currentWsId);
    } catch (e) {
      toast('重命名失败: ' + e.message, 'error');
    }
  }

  // ── Expose public API + inline action handlers ──
  window.Workspace = {
    renderList: renderList,
    renderDetail: renderDetail
  };

  window.WS_newToggle = newToggle;
  window.WS_create = create;
  window.WS_open = openDetail;
  window.WS_export = exportWs;
  window.WS_duplicate = duplicate;
  window.WS_delete = deleteWs;
  window.WS_back = backToList;
  window.WS_addDataset = addDataset;
  window.WS_removeDataset = removeDataset;
  window.WS_addFormula = addFormula;
  window.WS_removeFormula = removeFormula;
  window.WS_importPreset = importPreset;
  window.WS_addChart = addChart;
  window.WS_removeChart = removeChart;
  window.WS_renameChart = renameChart;
})();
