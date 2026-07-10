// NBACore v8.1 §8 — TeamContributionChart (pure render, no computation).
// Consumes the `seasons` array from /players/{id}/growth (each has scoring_share %).
(function () {
  const V81 = (window.V81 = window.V81 || {});
  const esc = window.escapeHtml || function (s) {
    const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML;
  };
  const TH = window.THEME || { purple: '#8b5cf6', textDim: '#7f8c9b', border: '#e1e8f0' };
  const sl = (s) => { if (!s) return '—'; const st = s - 1, en = s % 100; return st + '-' + (en < 10 ? '0' + en : en); };
  const initChart = (el) => { const i = (typeof echarts !== 'undefined' && echarts.getInstanceByDom(el)); if (i) i.dispose(); return echarts.init(el); };
  const track = (key, inst) => { if (typeof charts !== 'undefined') charts[key] = inst; };

  V81.renderTeamContributionChart = function (containerId, seasons) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const list = (seasons || []).filter(s => s.scoring_share != null);
    if (!list.length) {
      el.innerHTML = '<div class="card v81-card"><div class="card-header"><div class="card-title">球队得分贡献 <span class="v81-sub">Team Scoring Share</span></div></div><div class="v81-empty">暂无数据</div></div>';
      return;
    }
    el.innerHTML = `
      <div class="card v81-card">
        <div class="card-header">
          <div class="card-title">球队得分贡献 <span class="v81-sub">Team Scoring Share</span></div>
          <div class="card-badge">${list.length} 赛季</div>
        </div>
        <div id="${containerId}-canvas" class="v81-chart" style="height:300px;"></div>
      </div>`;
    const canvas = document.getElementById(containerId + '-canvas');
    if (typeof echarts === 'undefined' || !canvas) return;
    const inst = initChart(canvas);
    track(containerId, inst);
    const labels = list.map(s => sl(s.season));
    const vals = list.map(s => s.scoring_share);
    inst.setOption({
      tooltip: { trigger: 'axis', formatter: (p) => esc(p[0].axisValue) + '<br/>球队得分占比: ' + p[0].value + '%' },
      grid: { left: 50, right: 20, top: 30, bottom: 30 },
      xAxis: { type: 'category', data: labels, axisLabel: { color: TH.textDim, rotate: 45, fontSize: 10 }, axisLine: { lineStyle: { color: TH.border } } },
      yAxis: { type: 'value', axisLabel: { color: TH.textDim, formatter: '{value}%' }, splitLine: { lineStyle: { color: TH.border } } },
      series: [{
        name: '球队得分占比%', type: 'line', data: vals, smooth: true,
        itemStyle: { color: TH.purple }, areaStyle: { color: 'rgba(139,92,246,0.12)' },
        symbol: 'circle', symbolSize: 6,
      }],
    });
  };
})();
