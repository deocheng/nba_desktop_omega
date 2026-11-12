/**
 * Studio 工作台 — 战术视频分析流水线的编排 UI。
 *
 * Layer 4: 纯渲染。顺序、参数、放行规则全部来自 /studio/manifest 与 /studio/capabilities，
 * 前端不记任何脚本路径、不拼命令 —— 这正是「不再依赖 AI 记命令」的落点。
 * 零构建：原生 JS IIFE，挂 window.Studio，由 app.js 的 nav('studio') 调用。
 */
(function () {
  'use strict';

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function el(id) { return document.getElementById(id); }

  function capRow(name, item) {
    var ok = !!(item && item.ok);
    return '<div class="stat-chip" style="min-width:190px;">' +
      '<span class="chip-label">' + esc(name) + '</span>' +
      '<span class="chip-value" style="font-size:13px;color:' +
      (ok ? 'var(--text)' : 'var(--danger, #ef4444)') + '">' +
      (ok ? '可用' : '不可用') + '</span>' +
      '<span style="font-size:11px;color:var(--text-dim);word-break:break-all;" title="' +
      esc(item && item.detail) + '">' + esc((item && item.detail || '').slice(0, 58)) + '</span>' +
      '</div>';
  }

  function stepRow(step) {
    var active = step.status === 'active';
    var canRun = active && step.kind === 'probe' && !step.writes_data;
    var badge = active
      ? '<span class="card-badge" style="color:#10b981;">active</span>'
      : '<span class="card-badge">planned · 待签核</span>';
    return '<tr>' +
      '<td><strong>' + esc(step.title) + '</strong><br><span style="font-size:11px;color:var(--text-dim);">' +
      esc(step.id) + ' · ' + esc(step.kind) + '</span></td>' +
      '<td>' + badge + '</td>' +
      '<td style="font-size:12px;color:var(--text-dim);">' + esc(step.description) + '</td>' +
      '<td style="font-size:12px;">' + esc((step.requires || []).join(', ')) + '</td>' +
      '<td style="white-space:nowrap;">' +
      '<button class="btn btn-sm" data-studio-plan="' + esc(step.id) + '"' +
      (active ? '' : ' disabled') + '>生成计划</button> ' +
      '<button class="btn btn-sm btn-primary" data-studio-run="' + esc(step.id) + '"' +
      (canRun ? '' : ' disabled') + '>' + (canRun ? '运行' : '不可运行') + '</button>' +
      '</td></tr>';
  }

  function output(text) {
    var box = el('studioOutput');
    if (box) {
      box.textContent = text;
      box.scrollTop = box.scrollHeight;
    }
  }

  function bindActions() {
    document.querySelectorAll('[data-studio-plan]').forEach(function (btn) {
      btn.onclick = function () {
        var stepId = btn.getAttribute('data-studio-plan');
        output('生成计划中：' + stepId + ' …');
        api('/studio/plan', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ step_id: stepId, params: {} })
        }).then(function (res) {
          if (res.code !== 0) { output('[失败] ' + res.message); return; }
          var d = res.data || {};
          output('步骤：' + stepId + '\ncwd：' + (d.cwd || '') + '\n命令：\n  ' +
            (d.cmd || []).join(' ') +
            (d.blocked_reason ? '\n放行状态：BLOCKED — ' + d.blocked_reason : '\n放行状态：可运行') +
            '\nenv：' + JSON.stringify(d.env_delta || {}));
        }).catch(function (e) { output('[请求失败] ' + e.message); });
      };
    });

    document.querySelectorAll('[data-studio-run]').forEach(function (btn) {
      btn.onclick = function () {
        var stepId = btn.getAttribute('data-studio-run');
        output('提交任务：' + stepId + ' …');
        api('/studio/jobs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ step_id: stepId, params: {}, execute: true })
        }).then(function (res) {
          if (res.code !== 0) { output('[失败] ' + res.message); return; }
          pollJob(res.data.id, stepId);
        }).catch(function (e) { output('[请求失败] ' + e.message); });
      };
    });
  }

  function pollJob(jobId, stepId) {
    var tries = 0;
    var timer = setInterval(function () {
      tries += 1;
      api('/studio/jobs/' + encodeURIComponent(jobId)).then(function (res) {
        if (res.code !== 0) {
          clearInterval(timer);
          output('[查询失败] ' + res.message);
          return;
        }
        var job = res.data || {};
        var head = '任务 ' + job.id + ' · ' + stepId + ' · 状态 ' + job.status +
          (job.rc === null || job.rc === undefined ? '' : ' · rc=' + job.rc) +
          (job.blocked_reason ? ' · ' + job.blocked_reason : '');
        output(head + '\n' + '-'.repeat(48) + '\n' + (job.logs || []).join('\n'));
        if (job.status !== 'pending' && job.status !== 'running') {
          clearInterval(timer);
          if (window.toast) window.toast('Studio 任务结束：' + job.status);
        }
      }).catch(function (e) {
        clearInterval(timer);
        output('[轮询失败] ' + e.message);
      });
      if (tries >= 60) {
        clearInterval(timer);
        output('[超时] 任务仍在运行，请稍后刷新任务列表。');
      }
    }, 500);
  }

  function render(rootId) {
    var root = el(rootId);
    if (!root) { return; }
    root.innerHTML =
      '<div class="page-header"><h2>工作台 · Studio</h2>' +
      '<div class="form-row"><span class="badge" id="studioReady">加载中…</span></div></div>' +
      '<div class="card"><div class="card-header"><div class="card-title">外部资产状态</div></div>' +
      '<div id="studioCaps" style="display:flex;gap:12px;flex-wrap:wrap;padding:10px 0;">加载中…</div>' +
      '<div style="font-size:12px;color:var(--text-dim);" id="studioRoots"></div></div>' +
      '<div class="card"><div class="card-header"><div class="card-title">能力目录 · Manifest</div>' +
      '<span class="card-badge" id="studioStepCount">—</span></div>' +
      '<div class="tbl-wrap"><table class="tbl"><thead><tr>' +
      '<th>步骤</th><th>状态</th><th>说明</th><th>依赖</th><th>操作</th>' +
      '</tr></thead><tbody id="studioSteps"></tbody></table></div>' +
      '<div style="font-size:12px;color:var(--text-dim);padding:8px 0;">' +
      '顺序与参数由能力目录固化；planned 项需主理人视觉签核后才会转成 active。</div></div>' +
      '<div class="card"><div class="card-header"><div class="card-title">计划 / 运行日志</div>' +
      '<button class="btn btn-sm" id="studioJobsBtn">刷新任务列表</button></div>' +
      '<pre id="studioOutput" style="max-height:340px;overflow:auto;background:var(--bg-dark);' +
      'border-radius:8px;padding:12px;font-family:var(--mono);font-size:12px;line-height:1.6;">' +
      '选择一个步骤：生成计划（不执行）或运行（只读 probe）。</pre></div>';

    function showJobs() {
      api('/studio/jobs').then(function (res) {
        if (res.code !== 0) { output('[失败] ' + res.message); return; }
        var jobs = res.data || [];
        if (!jobs.length) { output('暂无任务。'); return; }
        output(jobs.map(function (j) {
          return [j.id, j.step_id, j.status, 'rc=' + (j.rc === null ? '-' : j.rc),
            (j.logs || []).length + ' 行日志'].join('  |  ');
        }).join('\n'));
      }).catch(function (e) { output('[请求失败] ' + e.message); });
    }
    var jobsBtn = el('studioJobsBtn');
    if (jobsBtn) { jobsBtn.onclick = showJobs; }

    Promise.all([api('/studio/capabilities'), api('/studio/manifest')])
      .then(function (results) {
        var capsRes = results[0];
        var manRes = results[1];
        if (capsRes.code !== 0 || manRes.code !== 0) {
          output('[加载失败] capabilities=' + capsRes.message + ' / manifest=' + manRes.message);
          return;
        }
        var caps = capsRes.data || {};
        var items = caps.capabilities || {};
        var capsBox = el('studioCaps');
        if (capsBox) {
          capsBox.innerHTML = Object.keys(items).map(function (k) {
            return capRow(k, items[k]);
          }).join('');
        }
        var ready = el('studioReady');
        if (ready) {
          ready.textContent = caps.ready_for_run ? '就绪 · 可运行只读步骤' : '能力未就绪 · 执行类步骤置灰';
        }
        var roots = el('studioRoots');
        if (roots) {
          roots.textContent = 'REPO: ' + (caps.repo_root || '') +
            '   |   DATA: ' + (caps.data_root || '') +
            (caps.frozen ? '   |   frozen（需 .env 指定路径根与 STUDIO_PYTHON）' : '');
        }
        var steps = (manRes.data && manRes.data.steps) || [];
        var body = el('studioSteps');
        if (body) { body.innerHTML = steps.map(stepRow).join(''); }
        var count = el('studioStepCount');
        if (count) {
          count.textContent = steps.length + ' 步 · ' +
            steps.filter(function (s) { return s.status === 'active'; }).length + ' active';
        }
        bindActions();
      })
      .catch(function (e) { output('[请求失败] ' + e.message); });
  }

  window.Studio = { render: render };
})();
