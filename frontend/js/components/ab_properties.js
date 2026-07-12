/**
 * NBACore Studio v8.3.2 — Analytics Builder: properties panel
 * ===================================================================
 * Renders an editable form for the currently selected node. The form is a
 * pure view over the node's params; any edit calls onChange(updatedParams).
 * No computation: field/value parsing is trivial (numbers vs strings), all
 * real validation happens in the backend.
 *
 * Exposes: window.AB_Props.render(container, node, ctx)
 *   ctx = {
 *     meta,                  // /meta payload
 *     canvas,                // AB_Canvas instance (for upstreamColumns)
 *     onChange(params)       // commit new params
 *   }
 */
(function () {
  'use strict';

  var N = window.AB_Nodes;

  function eh(s) {
    if (typeof window.escapeHtml === 'function') return window.escapeHtml(s == null ? '' : String(s));
    return String(s == null ? '' : s);
  }

  function label(txt) {
    return '<label class="label" style="display:block;margin:8px 0 3px;color:var(--text-dim);font-size:12px;">' + eh(txt) + '</label>';
  }
  function input(id, val, type) {
    return '<input class="input ab-input" id="' + id + '" type="' + (type || 'text') + '" value="' + eh(val) + '">';
  }
  function select(id, opts, val) {
    var h = '<select class="select ab-input" id="' + id + '">';
    opts.forEach(function (o) {
      var v = typeof o === 'object' ? o.value : o;
      var t = typeof o === 'object' ? o.text : o;
      h += '<option value="' + eh(v) + '"' + (String(v) === String(val) ? ' selected' : '') + '>' + eh(t) + '</option>';
    });
    h += '</select>';
    return h;
  }

  // split a comma text into a trimmed array of non-empty strings
  function splitList(s) {
    if (!s) return [];
    return s.split(',').map(function (x) { return x.trim(); }).filter(Boolean);
  }
  // coerce a single value: number if numeric, else string
  function coerce(v) {
    var s = String(v).trim();
    if (s === '') return '';
    if (/^-?\d+(\.\d+)?$/.test(s)) return parseFloat(s);
    return s;
  }

  function colDatalist(cols) {
    if (!cols || !cols.length) return '';
    return '<datalist id="abCols">' + cols.map(function (c) { return '<option value="' + eh(c) + '">'; }).join('') + '</datalist>';
  }

  function render(container, node, ctx) {
    if (!container) return;
    if (!node) {
      container.innerHTML = '<div class="v81-empty" style="color:var(--text-dim);">选择一个节点以编辑其参数</div>';
      return;
    }
    var meta = ctx.meta || {};
    var canvas = ctx.canvas;
    var p = node.params || {};
    var cols = canvas && canvas.upstreamColumns ? (canvas.upstreamColumns(node.id) || []) : [];
    var tableOpts = (meta.tables || []).map(function (t) { return { value: t.name, text: t.name }; });
    var aggOpts = (meta.agg_functions || []).map(function (a) { return { value: a, text: a }; });
    var vizOpts = (meta.viz_types || []).map(function (v) { return { value: v, text: v }; });
    var opOpts = (meta.filter_ops || []).map(function (o) {
      return { value: o.op, text: (o.label ? o.label + ' (' + o.op + ')' : o.op) };
    });

    var html = '';
    html += '<div class="ab-prop-head" style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">';
    html += '<span class="ab-dot" style="width:12px;height:12px;border-radius:50%;background:' + (N.TYPES[node.type] || {}).color + ';"></span>';
    html += '<strong>' + eh(node.title || node.type) + '</strong>';
    html += '<span class="badge badge-gray" style="margin-left:auto;">' + eh(node.type) + '</span>';
    html += '</div>';
    html += colDatalist(cols);

    if (node.type === 'source') {
      html += label('表 (table)');
      html += select('ab_source_table', tableOpts, p.table || '');
      html += label('行数上限 (limit, ≤ ' + (meta.row_limit || 5000) + ')');
      html += input('ab_source_limit', p.limit != null ? p.limit : 500, 'number');
      html += label('赛季起 (season_from, 可选)');
      html += input('ab_source_sfrom', p.season_from != null ? p.season_from : '', 'number');
      html += label('赛季止 (season_to, 可选)');
      html += input('ab_source_sto', p.season_to != null ? p.season_to : '', 'number');
    }

    else if (node.type === 'filter') {
      html += label('逻辑 (logic)');
      html += select('ab_filter_logic', [{ value: 'AND', text: 'AND (全部满足)' }, { value: 'OR', text: 'OR (任一满足)' }], p.logic || 'AND');
      html += '<div id="ab_filter_conds"></div>';
      html += '<button class="btn btn-sm" style="margin-top:6px;" onclick="AB_Props._addCond()">+ 添加条件</button>';
    }

    else if (node.type === 'aggregate') {
      html += label('分组字段 (group_by, 逗号分隔)');
      html += input('ab_agg_group', (p.group_by || []).join(', '));
      html += '<div id="ab_agg_measures"></div>';
      html += '<button class="btn btn-sm" style="margin-top:6px;" onclick="AB_Props._addMeasure()">+ 添加度量</button>';
    }

    else if (node.type === 'transform') {
      html += label('排序字段 (sort.field, 可选)');
      html += input('ab_tf_sort', p.sort ? p.sort.field || '' : '', 'text') + (cols.length ? ' list="abCols"' : '');
      html += label('排序方向 (asc/desc)');
      html += select('ab_tf_order', [{ value: 'asc', text: 'asc 升序' }, { value: 'desc', text: 'desc 降序' }], p.sort ? (p.sort.order || 'asc') : 'asc');
      html += label('取前 N 行 (top_n, 可选)');
      html += input('ab_tf_topn', p.top_n != null ? p.top_n : '', 'number');
      html += '<div id="ab_tf_derived"></div>';
      html += '<button class="btn btn-sm" style="margin-top:6px;" onclick="AB_Props._addDerived()">+ 添加派生列</button>';
      html += '<div style="font-size:11px;color:var(--text-dim);margin-top:6px;">派生列表达式仅支持 + - * / ( ) 与列名，例如 pts + ast</div>';
    }

    else if (node.type === 'visualize') {
      html += label('图表类型 (viz_type)');
      html += select('ab_viz_type', vizOpts, p.viz_type || 'table');
      html += label('标题 (title, 可选)');
      html += input('ab_viz_title', p.title || '');
      html += label('X 轴字段 (x_field' + (cols.length ? ', 可选列见下方' : '') + ')');
      html += '<input class="input ab-input" id="ab_viz_x" value="' + eh(p.x_field || '') + '"' + (cols.length ? ' list="abCols"' : '') + '>';
      html += label('Y 轴字段 (y_fields, 逗号分隔)');
      html += input('ab_viz_y', (p.y_fields || []).join(', '));
    }

    container.innerHTML = html;

    // wire dynamic lists
    if (node.type === 'filter') renderConds(container, p.conditions || [], opOpts, cols);
    if (node.type === 'aggregate') renderMeasures(container, p.measures || [], aggOpts, cols);
    if (node.type === 'transform') renderDerived(container, p.derived || [], cols);

    // bind static field changes -> commit
    bindStatic(node, ctx);
  }

  // ── dynamic sub-lists ──
  function renderConds(container, conds, opOpts, cols) {
    var box = container.querySelector('#ab_filter_conds');
    if (!box) return;
    box.innerHTML = conds.map(function (c, i) {
      return '<div class="ab-row" style="display:flex;gap:4px;margin:4px 0;align-items:center;">' +
        '<input class="input ab-input" data-cond="field" data-i="' + i + '" value="' + eh(c.field || '') + '" placeholder="字段"' + (cols.length ? ' list="abCols"' : '') + ' style="flex:1.2;">' +
        '<select class="select ab-input" data-cond="op" data-i="' + i + '" style="flex:1;">' +
        opOpts.map(function (o) { return '<option value="' + eh(o.value) + '"' + (o.value === c.op ? ' selected' : '') + '>' + eh(o.text) + '</option>'; }).join('') +
        '</select>' +
        '<input class="input ab-input" data-cond="value" data-i="' + i + '" value="' + eh(c.value != null ? (Array.isArray(c.value) ? c.value.join(', ') : c.value) : '') + '" placeholder="值" style="flex:1.2;">' +
        '<button class="btn btn-sm btn-danger" onclick="AB_Props._delCond(' + i + ')">×</button>' +
        '</div>';
    }).join('');
    bindConds(container);
  }

  function renderMeasures(container, measures, aggOpts, cols) {
    var box = container.querySelector('#ab_agg_measures');
    if (!box) return;
    box.innerHTML = measures.map(function (m, i) {
      var fieldDisabled = m.agg === 'count' ? ' disabled' : '';
      return '<div class="ab-row" style="display:flex;gap:4px;margin:4px 0;align-items:center;">' +
        '<select class="select ab-input" data-measure="agg" data-i="' + i + '" style="flex:1;">' +
        aggOpts.map(function (o) { return '<option value="' + eh(o.value) + '"' + (o.value === m.agg ? ' selected' : '') + '>' + eh(o.text) + '</option>'; }).join('') +
        '</select>' +
        '<input class="input ab-input" data-measure="field" data-i="' + i + '" value="' + eh(m.field || '') + '" placeholder="字段"' + (cols.length ? ' list="abCols"' : '') + ' style="flex:1.3;"' + fieldDisabled + '>' +
        '<input class="input ab-input" data-measure="alias" data-i="' + i + '" value="' + eh(m.alias || '') + '" placeholder="别名" style="flex:1.2;">' +
        '<button class="btn btn-sm btn-danger" onclick="AB_Props._delMeasure(' + i + ')">×</button>' +
        '</div>';
    }).join('');
    bindMeasures(container);
  }

  function renderDerived(container, derived, cols) {
    var box = container.querySelector('#ab_tf_derived');
    if (!box) return;
    box.innerHTML = derived.map(function (d, i) {
      return '<div class="ab-row" style="display:flex;gap:4px;margin:4px 0;align-items:center;">' +
        '<input class="input ab-input" data-derived="name" data-i="' + i + '" value="' + eh(d.name || '') + '" placeholder="新列名" style="flex:1;">' +
        '<input class="input ab-input" data-derived="expr" data-i="' + i + '" value="' + eh(d.expr || '') + '" placeholder="表达式" style="flex:1.6;">' +
        '<button class="btn btn-sm btn-danger" onclick="AB_Props._delDerived(' + i + ')">×</button>' +
        '</div>';
    }).join('');
    bindDerived(container);
  }

  // ── global handlers (referenced by inline onclick) ──
  // These operate on the currently selected node stored in module state.
  var _ctx = null;   // {node, ctx}
  function _setCtx(node, ctx) { _ctx = { node: node, ctx: ctx }; }

  function _read() {
    if (!_ctx) return;
    var node = _ctx.node, ctx = _ctx.ctx;
    var p = node.params || {};
    var g = function (id) { var e = document.getElementById(id); return e ? e.value : null; };

    if (node.type === 'source') {
      var sfrom = g('ab_source_sfrom'), sto = g('ab_source_sto');
      p = {
        source_mode: 'table',
        table: g('ab_source_table') || '',
        limit: Math.max(1, parseInt(g('ab_source_limit') || '500', 10) || 500),
        season_from: sfrom !== '' ? parseInt(sfrom, 10) : null,
        season_to: sto !== '' ? parseInt(sto, 10) : null
      };
    } else if (node.type === 'filter') {
      p.logic = g('ab_filter_logic') || 'AND';
      p.conditions = readConds();
    } else if (node.type === 'aggregate') {
      p.group_by = splitList(g('ab_agg_group'));
      p.measures = readMeasures();
    } else if (node.type === 'transform') {
      var sf = g('ab_tf_sort');
      var topn = g('ab_tf_topn');
      p.sort = sf ? { field: sf, order: g('ab_tf_order') || 'asc' } : null;
      p.top_n = topn !== '' ? parseInt(topn, 10) : null;
      p.derived = readDerived();
    } else if (node.type === 'visualize') {
      p.viz_type = g('ab_viz_type') || 'table';
      p.title = g('ab_viz_title') || '';
      p.x_field = g('ab_viz_x') || '';
      p.y_fields = splitList(g('ab_viz_y'));
    }
    ctx.onChange(p);
  }

  function readConds() {
    var out = [];
    document.querySelectorAll('[data-cond="field"]').forEach(function (e) {
      var i = e.getAttribute('data-i');
      var op = document.querySelector('[data-cond="op"][data-i="' + i + '"]').value;
      var raw = document.querySelector('[data-cond="value"][data-i="' + i + '"]').value;
      if (!e.value) return;
      var value = op === 'in'
        ? raw.split(',').map(function (x) { return coerce(x.trim()); }).filter(function (x, idx, arr) { return x !== '' || arr.length === 1; })
        : coerce(raw);
      out.push({ field: e.value, op: op, value: value });
    });
    return out;
  }
  function readMeasures() {
    var out = [];
    document.querySelectorAll('[data-measure="agg"]').forEach(function (e) {
      var i = e.getAttribute('data-i');
      var agg = e.value;
      var field = document.querySelector('[data-measure="field"][data-i="' + i + '"]').value;
      var alias = document.querySelector('[data-measure="alias"][data-i="' + i + '"]').value;
      if (!alias) return;
      out.push({ agg: agg, field: agg === 'count' ? null : field, alias: alias });
    });
    return out;
  }
  function readDerived() {
    var out = [];
    document.querySelectorAll('[data-derived="name"]').forEach(function (e) {
      var i = e.getAttribute('data-i');
      var expr = document.querySelector('[data-derived="expr"][data-i="' + i + '"]').value;
      if (!e.value || !expr) return;
      out.push({ name: e.value, expr: expr });
    });
    return out;
  }

  // ── add/delete buttons (re-render the dynamic section then re-bind) ──
  function _addCond() {
    if (!_ctx) return;
    var p = _ctx.node.params || {};
    p.conditions = (p.conditions || []).concat([{ field: '', op: '=', value: '' }]);
    _ctx.ctx.onChange(p); renderProps();
  }
  function _delCond(i) {
    if (!_ctx) return;
    var p = _ctx.node.params || {};
    p.conditions = (p.conditions || []).filter(function (_, idx) { return idx !== i; });
    _ctx.ctx.onChange(p); renderProps();
  }
  function _addMeasure() {
    if (!_ctx) return;
    var p = _ctx.node.params || {};
    p.measures = (p.measures || []).concat([{ agg: 'sum', field: '', alias: '' }]);
    _ctx.ctx.onChange(p); renderProps();
  }
  function _delMeasure(i) {
    if (!_ctx) return;
    var p = _ctx.node.params || {};
    p.measures = (p.measures || []).filter(function (_, idx) { return idx !== i; });
    _ctx.ctx.onChange(p); renderProps();
  }
  function _addDerived() {
    if (!_ctx) return;
    var p = _ctx.node.params || {};
    p.derived = (p.derived || []).concat([{ name: '', expr: '' }]);
    _ctx.ctx.onChange(p); renderProps();
  }
  function _delDerived(i) {
    if (!_ctx) return;
    var p = _ctx.node.params || {};
    p.derived = (p.derived || []).filter(function (_, idx) { return idx !== i; });
    _ctx.ctx.onChange(p); renderProps();
  }

  function renderProps() {
    if (_ctx) render(document.getElementById('abProps'), _ctx.node, _ctx.ctx);
  }

  // re-bind after dynamic re-render
  function bindConds(container) {
    container.querySelectorAll('[data-cond]').forEach(function (e) {
      e.addEventListener('change', _read); e.addEventListener('input', _read);
    });
  }
  function bindMeasures(container) {
    container.querySelectorAll('[data-measure]').forEach(function (e) {
      e.addEventListener('change', function () {
        if (e.getAttribute('data-measure') === 'agg') {
          // toggle field disabled for count
          var i = e.getAttribute('data-i');
          var f = document.querySelector('[data-measure="field"][data-i="' + i + '"]');
          if (f) f.disabled = (e.value === 'count');
        }
        _read();
      });
      e.addEventListener('input', _read);
    });
  }
  function bindDerived(container) {
    container.querySelectorAll('[data-derived]').forEach(function (e) {
      e.addEventListener('change', _read); e.addEventListener('input', _read);
    });
  }

  function bindStatic(node, ctx) {
    ['ab_source_table', 'ab_source_limit', 'ab_source_sfrom', 'ab_source_sto',
     'ab_filter_logic', 'ab_agg_group', 'ab_tf_sort', 'ab_tf_order', 'ab_tf_topn',
     'ab_viz_type', 'ab_viz_title', 'ab_viz_x', 'ab_viz_y'].forEach(function (id) {
      var e = document.getElementById(id);
      if (e) { e.addEventListener('change', _read); e.addEventListener('input', _read); }
    });
  }

  window.AB_Props = {
    render: function (container, node, ctx) { _setCtx(node, ctx); render(container, node, ctx); },
    _addCond: _addCond, _delCond: _delCond,
    _addMeasure: _addMeasure, _delMeasure: _delMeasure,
    _addDerived: _addDerived, _delDerived: _delDerived
  };
})();
