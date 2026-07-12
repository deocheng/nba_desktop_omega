/**
 * NBACore Studio v8.3.2 — Analytics Builder: node type specifications
 * ===================================================================
 * Single source of truth for node-type UI metadata (mirrors the backend
 * ab_constants.NODE_*). Pure data + default-param factories. No computation,
 * no DOM here (v8 §6: frontend does zero calculation).
 *
 * Exposes: window.AB_Nodes
 */
(function () {
  'use strict';

  // geometry shared by the canvas
  var NODE_W = 180;
  var NODE_H = 66;
  var PORT_R = 7;
  var HEADER_H = 22;

  // node type metadata. hasInput/hasOutput describe the P0 single-in/single-out model.
  var TYPES = {
    source: {
      label: '数据源',
      color: '#3b82f6',
      icon: '▤',
      hasInput: false,
      hasOutput: true,
      hint: '选择一张分析表'
    },
    filter: {
      label: '筛选',
      color: '#94a3b8',
      icon: '⚲',
      hasInput: true,
      hasOutput: true,
      hint: '按条件过滤行'
    },
    aggregate: {
      label: '聚合',
      color: '#10b981',
      icon: '∑',
      hasInput: true,
      hasOutput: true,
      hint: '分组聚合'
    },
    transform: {
      label: '变换',
      color: '#8b5cf6',
      icon: 'ƒ',
      hasInput: true,
      hasOutput: true,
      hint: '排序/截断/派生列'
    },
    visualize: {
      label: '可视化',
      color: '#f97316',
      icon: '◧',
      hasInput: true,
      hasOutput: false,
      hint: '出图/表格'
    }
  };

  // palette ordering
  var ORDER = ['source', 'filter', 'aggregate', 'transform', 'visualize'];

  var _seq = 0;
  function genId(type) {
    _seq += 1;
    return type + '_' + Date.now().toString(36) + '_' + _seq;
  }

  // default params for a freshly created node (must pass backend static validation)
  function defaultParams(type) {
    switch (type) {
      case 'source':
        return { source_mode: 'table', table: '', limit: 500 };
      case 'filter':
        return { logic: 'AND', conditions: [] };
      case 'aggregate':
        return { group_by: [], measures: [] };
      case 'transform':
        return { sort: null, top_n: null, derived: [] };
      case 'visualize':
        return { viz_type: 'table', title: '', x_field: '', y_fields: [] };
      default:
        return {};
    }
  }

  function makeNode(type, x, y) {
    return {
      id: genId(type),
      type: type,
      title: TYPES[type] ? TYPES[type].label : type,
      x: x,
      y: y,
      params: defaultParams(type)
    };
  }

  window.AB_Nodes = {
    TYPES: TYPES,
    ORDER: ORDER,
    NODE_W: NODE_W,
    NODE_H: NODE_H,
    PORT_R: PORT_R,
    HEADER_H: HEADER_H,
    genId: genId,
    defaultParams: defaultParams,
    makeNode: makeNode
  };
})();
