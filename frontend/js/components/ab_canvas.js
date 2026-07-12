/**
 * NBACore Studio v8.3.2 — Analytics Builder: SVG canvas
 * ===================================================================
 * Self-contained node-graph canvas (no external graph library, per the
 * v8.3.2 decision). Renders nodes + edges as SVG, supports pointer-drag of
 * nodes, dragging an edge from an output port to an input port, node/edge
 * deletion, and a real-time cycle guard (client-side backstop; the backend
 * re-validates). Emits selection + change callbacks so the parent can sync
 * the properties panel and the runnable graph.
 *
 * Exposes: window.AB_Canvas.create()
 *
 * NOTE: this module only renders + captures intent. It performs NO data
 * computation — the graph it produces is handed verbatim to the backend.
 */
(function () {
  'use strict';

  var SVGNS = 'http://www.w3.org/2000/svg';
  var N = window.AB_Nodes;

  function el(tag, attrs) {
    var e = document.createElementNS(SVGNS, tag);
    if (attrs) {
      for (var k in attrs) {
        if (Object.prototype.hasOwnProperty.call(attrs, k)) e.setAttribute(k, attrs[k]);
      }
    }
    return e;
  }

  // detect whether adding edge from->to would create a cycle (reachability)
  function wouldCreateCycle(edges, from, to) {
    if (from === to) return true;
    // can we reach `from` by walking forward from `to`? if yes, cycle.
    var adj = {};
    edges.forEach(function (e) {
      (adj[e.from] = adj[e.from] || []).push(e.to);
    });
    var stack = [to];
    var seen = {};
    while (stack.length) {
      var cur = stack.pop();
      if (cur === from) return true;
      if (seen[cur]) continue;
      seen[cur] = true;
      (adj[cur] || []).forEach(function (n) { stack.push(n); });
    }
    return false;
  }

  function create() {
    var svg = null;
    var nodes = [];          // [{id,type,title,x,y,params}]
    var edges = [];          // [{id,from,to}]
    var selectedId = null;
    var onSelect = null;     // fn(node|null)
    var onChange = null;     // fn() called when topology/params change
    var _edgeSeq = 0;

    // drag state
    var drag = null;         // {id, dx, dy}
    var linking = null;      // {from, tempLine}

    function emitChange() { if (typeof onChange === 'function') onChange(); }
    function emitSelect() {
      if (typeof onSelect === 'function') {
        onSelect(selectedId ? getNode(selectedId) : null);
      }
    }

    function getNode(id) {
      for (var i = 0; i < nodes.length; i++) if (nodes[i].id === id) return nodes[i];
      return null;
    }

    function inEdges(id) {
      return edges.filter(function (e) { return e.to === id; });
    }
    function outEdges(id) {
      return edges.filter(function (e) { return e.from === id; });
    }

    // ── port coordinates ──
    function inPortPos(n) { return { x: n.x, y: n.y + N.NODE_H / 2 }; }
    function outPortPos(n) { return { x: n.x + N.NODE_W, y: n.y + N.NODE_H / 2 }; }

    function edgePath(a, b) {
      var dx = Math.max(40, Math.abs(b.x - a.x) * 0.5);
      return 'M ' + a.x + ' ' + a.y +
        ' C ' + (a.x + dx) + ' ' + a.y + ', ' + (b.x - dx) + ' ' + b.y + ', ' + b.x + ' ' + b.y;
    }

    // ── rendering ──
    function render() {
      if (!svg) return;
      while (svg.firstChild) svg.removeChild(svg.firstChild);

      // edges first (under nodes)
      edges.forEach(function (e) {
        var from = getNode(e.from), to = getNode(e.to);
        if (!from || !to) return;
        var a = outPortPos(from), b = inPortPos(to);
        var d = el('path', {
          d: edgePath(a, b),
          fill: 'none',
          stroke: '#64748b',
          'stroke-width': 2,
          class: 'ab-edge'
        });
        d.addEventListener('click', function (ev) {
          ev.stopPropagation();
          if (confirm('删除这条连线？')) { removeEdge(e.id); }
        });
        svg.appendChild(d);
        // arrow head
        var head = el('circle', { cx: b.x, cy: b.y, r: 3, fill: '#64748b' });
        svg.appendChild(head);
      });

      // nodes
      nodes.forEach(function (n) {
        var meta = N.TYPES[n.type] || { color: '#64748b', icon: '?', label: n.type };
        var g = el('g', {
          transform: 'translate(' + n.x + ',' + n.y + ')',
          class: 'ab-node' + (n.id === selectedId ? ' selected' : ''),
          'data-id': n.id,
          style: 'cursor:move;'
        });

        var rect = el('rect', {
          width: N.NODE_W, height: N.NODE_H, rx: 8, ry: 8,
          fill: '#1e293b', stroke: n.id === selectedId ? '#38bdf8' : '#334155',
          'stroke-width': n.id === selectedId ? 2.5 : 1.5
        });
        g.appendChild(rect);

        // header bar
        var header = el('rect', { width: N.NODE_W, height: N.HEADER_H, rx: 8, ry: 8, fill: meta.color, opacity: 0.92 });
        g.appendChild(header);
        var headerFix = el('rect', { y: N.HEADER_H - 8, width: N.NODE_W, height: 8, fill: meta.color });
        g.appendChild(headerFix);

        var tIcon = el('text', { x: 10, y: 15, fill: '#0f172a', 'font-size': 13, 'font-weight': 700 });
        tIcon.textContent = meta.icon || '';
        g.appendChild(tIcon);

        var tTitle = el('text', { x: 28, y: 15, fill: '#0f172a', 'font-size': 12, 'font-weight': 700 });
        tTitle.textContent = n.title || meta.label || n.type;
        g.appendChild(tTitle);

        var tType = el('text', { x: 10, y: 42, fill: '#cbd5e1', 'font-size': 11 });
        tType.textContent = n.type;
        g.appendChild(tType);

        // input port
        if (meta.hasInput) {
          var pin = el('circle', {
            cx: 0, cy: N.NODE_H / 2, r: N.PORT_R, fill: '#0ea5e9',
            stroke: '#e2e8f0', 'stroke-width': 1.5, class: 'ab-port-in',
            style: 'cursor:crosshair;'
          });
          g.appendChild(pin);
        }
        // output port
        if (meta.hasOutput) {
          var pout = el('circle', {
            cx: N.NODE_W, cy: N.NODE_H / 2, r: N.PORT_R, fill: '#f59e0b',
            stroke: '#e2e8f0', 'stroke-width': 1.5, class: 'ab-port-out',
            style: 'cursor:crosshair;'
          });
          g.appendChild(pout);
        }

        // node interactions
        g.addEventListener('mousedown', function (ev) {
          if (ev.target.classList.contains('ab-port-out')) return; // handled separately
          ev.preventDefault();
          select(n.id);
          drag = { id: n.id, dx: ev.offsetX - n.x, dy: ev.offsetY - n.y };
        });
        if (meta.hasOutput) {
          var outPort = g.querySelector('.ab-port-out');
          outPort.addEventListener('mousedown', function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            startLink(n.id, ev);
          });
        }
        svg.appendChild(g);
      });
    }

    // ── selection ──
    function select(id) {
      selectedId = id;
      render();
      emitSelect();
    }

    // ── node ops ──
    function addNode(type, x, y) {
      var n = N.makeNode(type, x == null ? 60 : x, y == null ? 60 : y);
      nodes.push(n);
      render();
      emitChange();
      select(n.id);
      return n;
    }

    function removeNode(id) {
      nodes = nodes.filter(function (n) { return n.id !== id; });
      edges = edges.filter(function (e) { return e.from !== id && e.to !== id; });
      if (selectedId === id) selectedId = null;
      render();
      emitChange();
      emitSelect();
    }

    function updateNodeParams(id, params) {
      var n = getNode(id);
      if (n) { n.params = params; emitChange(); }
    }

    function clear() {
      nodes = []; edges = []; selectedId = null;
      render(); emitChange(); emitSelect();
    }

    // ── edge ops ──
    function addEdge(from, to) {
      if (from === to) return false;
      // single-input: replace any existing edge into `to`
      edges = edges.filter(function (e) { return e.to !== to; });
      if (edges.some(function (e) { return e.from === from && e.to === to; })) return false;
      if (wouldCreateCycle(edges, from, to)) {
        if (window.toast) window.toast('不能连接：会形成环(cycle)', 'error');
        return false;
      }
      _edgeSeq += 1;
      edges.push({ id: 'e' + _edgeSeq, from: from, to: to });
      render();
      emitChange();
      return true;
    }

    function removeEdge(id) {
      edges = edges.filter(function (e) { return e.id !== id; });
      render(); emitChange();
    }

    // ── linking (drag from output port) ──
    function startLink(fromId, ev) {
      var n = getNode(fromId);
      var start = outPortPos(n);
      var line = el('path', {
        d: edgePath(start, start), fill: 'none', stroke: '#f59e0b',
        'stroke-width': 2, 'stroke-dasharray': '4 3'
      });
      svg.appendChild(line);
      linking = { from: fromId, line: line };

      function move(e) {
        var pt = clientToSvg(e);
        line.setAttribute('d', edgePath(start, pt));
      }
      function up(e) {
        svg.removeEventListener('mousemove', move);
        svg.removeEventListener('mouseup', up);
        var target = e.target;
        if (target && target.classList && target.classList.contains('ab-port-in')) {
          var g = target.closest('.ab-node');
          if (g) {
            var toId = g.getAttribute('data-id');
            addEdge(fromId, toId);
          }
        }
        if (line.parentNode) line.parentNode.removeChild(line);
        linking = null;
      }
      svg.addEventListener('mousemove', move);
      svg.addEventListener('mouseup', up);
    }

    // ── coordinate helpers ──
    function clientToSvg(e) {
      var r = svg.getBoundingClientRect();
      var vb = svg.viewBox && svg.viewBox.baseVal;
      if (vb && vb.width) {
        return { x: (e.clientX - r.left) / r.width * vb.width, y: (e.clientY - r.top) / r.height * vb.height };
      }
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    }

    // global drag handling for nodes
    function onSvgMouseMove(e) {
      if (!drag) return;
      var n = getNode(drag.id);
      if (!n) return;
      var pt = clientToSvg(e);
      n.x = Math.round(pt.x - drag.dx);
      n.y = Math.round(pt.y - drag.dy);
      render();
    }
    function onSvgMouseUp() { drag = null; emitChange(); }
    function onSvgClick(e) {
      if (e.target === svg && !linking) { select(null); }
    }

    // ── public mount ──
    function mount(svgEl) {
      svg = svgEl;
      svg.setAttribute('viewBox', '0 0 1000 640');
      svg.style.width = '100%';
      svg.style.height = '100%';
      svg.style.background = '#0f172a';
      svg.style.backgroundImage =
        'radial-gradient(#1e293b 1px, transparent 1px)';
      svg.style.backgroundSize = '22px 22px';
      svg.addEventListener('mousemove', onSvgMouseMove);
      svg.addEventListener('mouseup', onSvgMouseUp);
      svg.addEventListener('click', onSvgClick);
      render();
    }

    // ── serialize / load ──
    function getGraph() {
      return {
        nodes: nodes.map(function (n) {
          return { id: n.id, type: n.type, title: n.title, x: n.x, y: n.y, params: n.params };
        }),
        edges: edges.map(function (e) { return { id: e.id, from: e.from, to: e.to }; })
      };
    }

    function loadGraph(graph) {
      nodes = []; edges = []; selectedId = null;
      if (graph && Array.isArray(graph.nodes)) {
        graph.nodes.forEach(function (n) {
          nodes.push({
            id: n.id, type: n.type, title: n.title || (N.TYPES[n.type] || {}).label || n.type,
            x: n.x != null ? n.x : 60, y: n.y != null ? n.y : 60,
            params: n.params || N.defaultParams(n.type)
          });
        });
      }
      if (graph && Array.isArray(graph.edges)) {
        graph.edges.forEach(function (e) {
          edges.push({ id: e.id || ('e' + (_edgeSeq += 1)), from: e.from, to: e.to });
        });
      }
      render(); emitChange(); emitSelect();
    }

    // best-effort available input columns for a node: walk upstream to a source
    function upstreamColumns(id) {
      // find source table feeding this node
      var incoming = inEdges(id);
      if (incoming.length === 0) return null;
      var src = incoming[0].from;
      var n = getNode(src);
      if (!n) return null;
      if (n.type === 'source' && n.params && n.params.table && _tableColumns) {
        return _tableColumns[n.params.table] || null;
      }
      // recurse (transformed output keeps same columns in P0 best-effort)
      return upstreamColumns(src);
    }

    var _tableColumns = null; // {tableName: [colNames]} set by parent from meta
    function setTableColumns(map) { _tableColumns = map; }

    return {
      mount: mount,
      addNode: addNode,
      removeNode: removeNode,
      updateNodeParams: updateNodeParams,
      getNode: getNode,
      getGraph: getGraph,
      loadGraph: loadGraph,
      clear: clear,
      select: select,
      setOnSelect: function (fn) { onSelect = fn; },
      setOnChange: function (fn) { onChange = fn; },
      setTableColumns: setTableColumns,
      upstreamColumns: upstreamColumns,
      nodeCount: function () { return nodes.length; }
    };
  }

  window.AB_Canvas = { create: create };
})();
