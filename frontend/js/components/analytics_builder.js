/**
 * NBACore Studio v8.3.2 — Analytics Builder: main controller
 * ===================================================================
 * Assembles the builder UI: workspace/flow picker, node palette, SVG canvas,
 * properties panel, run + save/load. Wires the sub-modules together. The
 * frontend performs NO data computation — it only captures graph structure
 * and ships it to the backend (v8 §6).
 *
 * Exposes: window.AnalyticsBuilder.render(containerId)
 */
(function () {
  'use strict';

  var N = window.AB_Nodes;

  var state = {
    containerId: null,
    meta: null,
    canvas: null,
    workspaceId: null,
    currentFlowId: null,
    currentFlowName: '未命名流程',
    dirty: false
  };

  function eh(s) {
    if (typeof window.escapeHtml === 'function') return window.escapeHtml(s == null ? '' : String(s));
    return String(s == null ? '' : s);
  }

  function render(containerId) {
    state.containerId = containerId;
    var root = document.getElementById(containerId);
    if (!root) return;

    root.innerHTML =
      '<div class="ab-toolbar" style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px;">' +
        '<select class="select ab-input" id="abWs" style="max-width:200px;"></select>' +
        '<select class="select ab-input" id="abFlow" style="max-width:220px;"><option value="">— 选择已存流程 —</option></select>' +
        '<button class="btn btn-sm" onclick="AB_newFlow()">新建</button>' +
        '<button class="btn btn-sm btn-primary" onclick="AB_saveFlow()">保存</button>' +
        '<input class="input ab-input" id="abFlowName" placeholder="流程名称" value="未命名流程" style="max-width:160px;">' +
        '<span style="flex:1;"></span>' +
        '<button class="btn btn-sm btn-danger" onclick="AB_deleteFlow()">删除流程</button>' +
        '<button class="btn btn-sm" onclick="AB_clearCanvas()">清空画布</button>' +
        '<button class="btn btn-primary" onclick="AB_run()">▶ 运行</button>' +
      '</div>' +
      '<div class="ab-main" style="display:grid;grid-template-columns:150px 1fr 300px;gap:12px;height:calc(100vh - 220px);min-height:480px;">' +
        '<div class="card" style="overflow:auto;">' +
          '<div class="card-title" style="font-size:13px;margin-bottom:8px;">节点</div>' +
          '<div id="abPalette"></div>' +
        '</div>' +
        '<div class="card" style="padding:0;overflow:hidden;">' +
          '<svg id="abCanvasSvg"></svg>' +
        '</div>' +
        '<div class="card" style="overflow:auto;">' +
          '<div class="card-title" style="font-size:13px;margin-bottom:8px;">参数</div>' +
          '<div id="abProps"></div>' +
        '</div>' +
      '</div>' +
      '<div class="card" style="margin-top:12px;">' +
        '<div class="card-header"><div class="card-title">运行结果</div>' +
        '<span class="card-badge" id="abRunInfo"></span></div>' +
        '<div id="abResults" style="min-height:80px;"><div class="v81-empty" style="color:var(--text-dim);">点击「运行」执行分析流</div></div>' +
      '</div>';

    buildPalette();
    initCanvas();
    loadMeta();
    loadWorkspaces();
  }

  function buildPalette() {
    var box = document.getElementById('abPalette');
    if (!box) return;
    box.innerHTML = N.ORDER.map(function (type) {
      var m = N.TYPES[type];
      return '<div class="ab-pal-node" data-type="' + type + '" style="display:flex;align-items:center;gap:8px;padding:8px;margin-bottom:6px;border:1px solid #334155;border-radius:8px;cursor:pointer;background:#1e293b;" ' +
        'onclick="AB_addNode(\'' + type + '\')">' +
        '<span style="width:12px;height:12px;border-radius:50%;background:' + m.color + ';"></span>' +
        '<div><div style="font-weight:600;font-size:13px;">' + eh(m.label) + '</div>' +
        '<div style="font-size:11px;color:var(--text-dim);">' + eh(m.hint) + '</div></div>' +
        '</div>';
    }).join('');
  }

  function initCanvas() {
    var svg = document.getElementById('abCanvasSvg');
    var canvas = window.AB_Canvas.create();
    canvas.mount(svg);
    canvas.setOnSelect(function (node) {
      window.AB_Props.render(document.getElementById('abProps'), node, {
        meta: state.meta,
        canvas: canvas,
        onChange: function (params) {
          if (node) { canvas.updateNodeParams(node.id, params); state.dirty = true; }
        }
      });
    });
    canvas.setOnChange(function () { state.dirty = true; });
    state.canvas = canvas;
  }

  async function loadMeta() {
    try {
      var data = await window.api('/api/analytics-builder/meta');
      state.meta = data;
      var map = {};
      (data.tables || []).forEach(function (t) {
        map[t.name] = (t.columns || []).map(function (c) { return c.name; });
      });
      if (state.canvas) state.canvas.setTableColumns(map);
    } catch (e) {
      if (window.toast) window.toast('加载元数据失败: ' + e.message, 'error');
    }
  }

  async function loadWorkspaces() {
    var sel = document.getElementById('abWs');
    if (!sel) return;
    try {
      var list = await window.api('/api/workspaces');
      if (!Array.isArray(list)) list = [];
      sel.innerHTML = '<option value="">— 选择工作区 —</option>' +
        list.map(function (w) { return '<option value="' + w.id + '">' + eh(w.name) + ' (#' + w.id + ')</option>'; }).join('');
      sel.onchange = function () {
        state.workspaceId = sel.value ? parseInt(sel.value, 10) : null;
        state.currentFlowId = null;
        loadFlows(state.workspaceId);
      };
    } catch (e) {
      sel.innerHTML = '<option value="">（加载工作区失败）</option>';
    }
  }

  async function loadFlows(wsId) {
    var sel = document.getElementById('abFlow');
    if (!sel) return;
    if (!wsId) { sel.innerHTML = '<option value="">— 选择已存流程 —</option>'; return; }
    try {
      var flows = await window.api('/api/workspaces/' + wsId + '/flows');
      if (!Array.isArray(flows)) flows = [];
      sel.innerHTML = '<option value="">— 选择已存流程 —</option>' +
        flows.map(function (f) { return '<option value="' + f.id + '">' + eh(f.name) + ' (#' + f.id + ')</option>'; }).join('');
      sel.onchange = function () {
        var id = sel.value ? parseInt(sel.value, 10) : null;
        if (id) loadFlowDef(wsId, id);
      };
    } catch (e) {
      sel.innerHTML = '<option value="">（加载流程失败）</option>';
    }
  }

  async function loadFlowDef(wsId, flowId) {
    try {
      var f = await window.api('/api/workspaces/' + wsId + '/flows/' + flowId);
      state.currentFlowId = flowId;
      state.currentFlowName = f.name || '未命名流程';
      var nameEl = document.getElementById('abFlowName');
      if (nameEl) nameEl.value = state.currentFlowName;
      var def = f.definition_json || f.definition || { nodes: [], edges: [] };
      if (state.canvas) state.canvas.loadGraph(def);
      state.dirty = false;
      if (window.toast) window.toast('已载入流程: ' + state.currentFlowName, 'success');
    } catch (e) {
      if (window.toast) window.toast('载入流程失败: ' + e.message, 'error');
    }
  }

  // ── public actions (inline onclick) ──
  function addNode(type) {
    if (!state.canvas) return;
    var n = state.canvas.addNode(type, 80 + Math.random() * 40, 60 + Math.random() * 40);
    state.dirty = true;
    return n;
  }

  function newFlow() {
    if (state.canvas) state.canvas.clear();
    state.currentFlowId = null;
    state.currentFlowName = '未命名流程';
    state.dirty = false;
    var nameEl = document.getElementById('abFlowName');
    if (nameEl) nameEl.value = state.currentFlowName;
    var flowSel = document.getElementById('abFlow');
    if (flowSel) flowSel.value = '';
  }

  async function saveFlow() {
    if (!state.workspaceId) { if (window.toast) window.toast('请先选择一个工作区', 'error'); return; }
    var nameEl = document.getElementById('abFlowName');
    var name = (nameEl && nameEl.value) ? nameEl.value : '未命名流程';
    var graph = state.canvas ? state.canvas.getGraph() : { nodes: [], edges: [] };
    var payload = { name: name, definition: { version: '1', nodes: graph.nodes, edges: graph.edges } };
    try {
      if (state.currentFlowId) {
        await window.api('/api/workspaces/' + state.workspaceId + '/flows/' + state.currentFlowId, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
        });
        if (window.toast) window.toast('已更新流程', 'success');
      } else {
        var created = await window.api('/api/workspaces/' + state.workspaceId + '/flows', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
        });
        state.currentFlowId = created.id;
        if (window.toast) window.toast('已保存流程 #' + created.id, 'success');
      }
      state.dirty = false;
      await loadFlows(state.workspaceId);
      var flowSel = document.getElementById('abFlow');
      if (flowSel) flowSel.value = String(state.currentFlowId);
    } catch (e) {
      if (window.toast) window.toast('保存失败: ' + e.message, 'error');
    }
  }

  async function deleteFlow() {
    if (!state.workspaceId || !state.currentFlowId) {
      if (window.toast) window.toast('请先选择要删除的流程', 'error'); return;
    }
    if (!confirm('确认删除该流程？')) return;
    try {
      await window.api('/api/workspaces/' + state.workspaceId + '/flows/' + state.currentFlowId, { method: 'DELETE' });
      if (window.toast) window.toast('已删除流程', 'success');
      state.currentFlowId = null;
      await loadFlows(state.workspaceId);
      newFlow();
    } catch (e) {
      if (window.toast) window.toast('删除失败: ' + e.message, 'error');
    }
  }

  function clearCanvas() {
    if (state.canvas) state.canvas.clear();
    state.dirty = true;
  }

  async function run() {
    if (!state.canvas) return;
    if (state.canvas.nodeCount() === 0) { if (window.toast) window.toast('画布为空，请先添加节点', 'error'); return; }
    var info = document.getElementById('abRunInfo');
    var results = document.getElementById('abResults');
    if (info) info.textContent = '运行中...';
    if (results) results.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-dim);"><div class="spinner"></div> 执行分析流...</div>';
    try {
      var graph = state.canvas.getGraph();
      var data = await window.AB_Runner.run(graph, state.workspaceId);
      if (info) info.textContent = '完成';
      window.AB_Runner.renderResults(results, data);
    } catch (e) {
      if (info) info.textContent = '失败';
      if (results) results.innerHTML = '<div style="color:var(--danger);padding:12px;">运行失败: ' + eh(e.message) + '</div>';
      if (window.toast) window.toast('运行失败: ' + e.message, 'error');
    }
  }

  window.AnalyticsBuilder = { render: render };
  window.AB_addNode = addNode;
  window.AB_newFlow = newFlow;
  window.AB_saveFlow = saveFlow;
  window.AB_deleteFlow = deleteFlow;
  window.AB_clearCanvas = clearCanvas;
  window.AB_run = run;
})();
