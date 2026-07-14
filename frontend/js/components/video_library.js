/**
 * NBACore Studio v8 — Video Library Component (Layer 4: Pure Render)
 * =====================================================================
 * Provides two views:
 *   - renderList(rootId):     Game list with 🎬/— video badges
 *   - renderPlayback(rootId): Playback page with <video> + Tactics SVG + Clutch Timeline
 *
 * Reuses the locked shared frontend contracts (§3.2 / §8.6):
 *   - window.Tactics drivable API (setFrames/seekFrame/seekProgress/play/pause/onTick)
 *   - window.ClutchReplay.Timeline.mount(container, {segments, frameCount, onSeek})
 *     → {setProgress(p), onSeek(cb)}
 *
 * SyncController bridges <video> ↔ Timeline ↔ Tactics using binary search on
 * the precomputed timeline[] from the backend. ZERO offset/clock math in
 * the frontend (v8 §11 red line).
 */
(function () {
  'use strict';

  // ── Module state (reset on each render) ──
  var currentView = 'list';       // 'list' | 'playback'
  var currentGameId = null;
  var currentSeason = null;
  var playbackData = null;        // PlaybackResponse from backend
  var syncController = null;      // SyncController instance
  var timelineHandle = null;      // window.ClutchReplay.Timeline.mount handle

  // ── Utility ──
  function eh(v) {
    if (typeof escapeHtml === 'function') return escapeHtml(v == null ? '' : String(v));
    return String(v == null ? '' : v);
  }

  function api(path, opts) {
    if (typeof window.api === 'function') return window.api(path, opts);
    // Fallback: use the global api() from app.js
    return fetch(path, opts).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  function toast(msg, type) {
    if (typeof window.toast === 'function') return window.toast(msg, type || 'success');
    console.log('[toast]', msg);
  }

  // ═════════════════════════════════════════════════════════════════════════
  // SyncController — bridges <video> ↔ Timeline ↔ Tactics (binary search only)
  // ═════════════════════════════════════════════════════════════════════════

  /**
   * @param {Object} opts
   * @param {Array}  opts.timeline   Precomputed EventTimeMark[] from backend
   * @param {number} opts.frameCount meta.frame_count for p↔frame projection
   * @param {HTMLVideoElement} opts.videoEl
   */
  function SyncController(opts) {
    this.timeline = opts.timeline || [];
    this.frameCount = opts.frameCount || 1;
    this.videoEl = opts.videoEl;
    this.guarded = false;
    this._seekCbs = [];
    this._bound = false;
  }

  SyncController.prototype._bindVideo = function () {
    if (this._bound || !this.videoEl) return;
    var self = this;
    this.videoEl.addEventListener('timeupdate', function () {
      self.onVideoTimeUpdate();
    });
    this._bound = true;
  };

  /**
   * Convert a normalized progress p (0–1000) to video.currentTime
   * by projecting p → frame_index → binary search timeline for nearest video_time.
   * NO offset/clock math — pure lookup on precomputed timeline[].
   */
  SyncController.prototype.videoTimeAt = function (p) {
    if (!this.timeline.length) return 0;
    // Project p (0–1000) to frame_index
    var frameIdx = Math.round((p / 1000) * (this.frameCount - 1));
    // Binary search for the timeline entry with frame_index closest to frameIdx
    var vt = this._binarySearchFrame(frameIdx);
    return vt;
  };

  /**
   * Convert video.currentTime to normalized progress p (0–1000)
   * by binary searching timeline[].video_time for the containing interval.
   * NO offset/clock math — pure lookup on precomputed timeline[].
   */
  SyncController.prototype.progressAt = function (currentTime) {
    if (!this.timeline.length) return 0;
    // Binary search for the timeline entry whose video_time is closest to currentTime
    var mark = this._binarySearchTime(currentTime);
    if (!mark) return 0;
    // Project frame_index back to 0–1000
    if (this.frameCount <= 1) return 0;
    return Math.round((mark.frame_index / (this.frameCount - 1)) * 1000);
  };

  /**
   * Timeline → Video + Tactics (forward sync).
   * Called when user drags/clicks the Timeline.
   */
  SyncController.prototype.onTimelineSeek = function (p) {
    if (!this.videoEl) return;
    this.guarded = true;
    var vt = this.videoTimeAt(p);
    try { this.videoEl.currentTime = vt; } catch (e) { /* not loaded yet */ }
    if (window.Tactics && typeof window.Tactics.seekProgress === 'function') {
      window.Tactics.seekProgress(p);
    }
    var self = this;
    setTimeout(function () { self.guarded = false; }, 50);
  };

  /**
   * Video → Timeline + Tactics (reverse sync).
   * Called on <video> 'timeupdate' event.
   */
  SyncController.prototype.onVideoTimeUpdate = function () {
    if (this.guarded) return;
    if (!this.videoEl) return;
    var ct = this.videoEl.currentTime;
    var p = this.progressAt(ct);
    if (window.Tactics && typeof window.Tactics.seekProgress === 'function') {
      window.Tactics.seekProgress(p);
    }
    if (timelineHandle && typeof timelineHandle.setProgress === 'function') {
      timelineHandle.setProgress(p);
    }
  };

  // ── Binary search helpers ──

  SyncController.prototype._binarySearchFrame = function (frameIdx) {
    var tl = this.timeline;
    if (!tl.length) return 0;
    var lo = 0, hi = tl.length - 1;
    // Find the entry with frame_index closest to frameIdx
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (tl[mid].frame_index < frameIdx) {
        lo = mid + 1;
      } else {
        hi = mid;
      }
    }
    // Check if lo-1 is closer
    if (lo > 0) {
      var diff1 = Math.abs(tl[lo].frame_index - frameIdx);
      var diff2 = Math.abs(tl[lo - 1].frame_index - frameIdx);
      if (diff2 < diff1) lo = lo - 1;
    }
    return tl[lo].video_time;
  };

  SyncController.prototype._binarySearchTime = function (currentTime) {
    var tl = this.timeline;
    if (!tl.length) return null;
    var lo = 0, hi = tl.length - 1;
    // Find the entry with video_time closest to currentTime
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (tl[mid].video_time < currentTime) {
        lo = mid + 1;
      } else {
        hi = mid;
      }
    }
    // Check if lo-1 is closer
    if (lo > 0) {
      var diff1 = Math.abs(tl[lo].video_time - currentTime);
      var diff2 = Math.abs(tl[lo - 1].video_time - currentTime);
      if (diff2 < diff1) lo = lo - 1;
    }
    return tl[lo];
  };

  // ═════════════════════════════════════════════════════════════════════════
  // List View
  // ═════════════════════════════════════════════════════════════════════════

  function renderList(rootId) {
    currentView = 'list';
    var root = document.getElementById(rootId);
    if (!root) return;

    root.innerHTML = '\
      <div class="page-header">\
        <h2>录像库 · Video Library</h2>\
        <div class="form-row">\
          <label class="label">Season:</label>\
          <select class="select" id="vlSeasonSelect" onchange="window.VideoLibrary._refreshList()">\
            <option value="2025">2024-25</option>\
            <option value="2024">2023-24</option>\
            <option value="2023">2022-23</option>\
            <option value="2022">2021-22</option>\
            <option value="2021">2020-21</option>\
          </select>\
          <label class="label">Team:</label>\
          <input class="input" id="vlTeamInput" placeholder="e.g. LAL" style="width:100px;">\
          <button class="btn btn-sm" onclick="window.VideoLibrary._refreshList()">Filter</button>\
        </div>\
      </div>\
      <div class="card">\
        <div class="card-header">\
          <div class="card-title">Games</div>\
          <div class="card-badge" id="vlCount">—</div>\
        </div>\
        <div class="tbl-wrap" style="max-height:650px;">\
          <table class="tbl" id="vlTable">\
            <thead>\
              <tr>\
                <th style="width:120px;">Date</th>\
                <th>Game</th>\
                <th style="width:80px; text-align:center;">Score</th>\
                <th style="width:80px; text-align:center;">Video</th>\
                <th style="width:120px; text-align:center;">Action</th>\
              </tr>\
            </thead>\
            <tbody id="vlTableBody">\
              <tr><td colspan="5" style="text-align:center; padding:30px; color:var(--text-dim);">\
                <div class="spinner"></div> Loading...\
              </td></tr>\
            </tbody>\
          </table>\
        </div>\
      </div>\
      <!-- Add Video Source Modal -->\
      <div id="vlAddModal" class="vl-modal" style="display:none;">\
        <div class="vl-modal-backdrop" onclick="window.VideoLibrary._closeAddModal()"></div>\
        <div class="vl-modal-panel">\
          <div class="vl-modal-header">\
            <div class="vl-modal-title">Add Video Source</div>\
            <button class="vl-modal-close" onclick="window.VideoLibrary._closeAddModal()">✕</button>\
          </div>\
          <div class="vl-modal-body" id="vlAddModalBody"></div>\
        </div>\
      </div>\
    ';

    // Try to populate seasons from API
    _populateSeasons();

    // Load initial list
    _refreshList();
  }

  function _populateSeasons() {
    api('/players/seasons').then(function (d) {
      var sel = document.getElementById('vlSeasonSelect');
      if (!sel || !d || !d.length) return;
      var opts = d.map(function (s) {
        var label = (s - 1) + '-' + (s % 100 < 10 ? '0' + (s % 100) : s % 100);
        return '<option value="' + s + '">' + label + '</option>';
      }).join('');
      sel.innerHTML = opts;
      var def = d.indexOf(2025) >= 0 ? 2025 : d[0];
      sel.value = def;
      _refreshList();
    }).catch(function () {
      // Fallback seasons already in HTML
      _refreshList();
    });
  }

  function _refreshList() {
    var season = document.getElementById('vlSeasonSelect');
    var team = document.getElementById('vlTeamInput');
    var s = season ? season.value : '2025';
    var t = team ? team.value.trim() : '';

    var qs = '?season=' + encodeURIComponent(s);
    if (t) qs += '&team=' + encodeURIComponent(t);

    var tbody = document.getElementById('vlTableBody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:30px; color:var(--text-dim);">\
      <div class="spinner"></div> Loading...</td></tr>';

    api('/video-library/games' + qs).then(function (d) {
      if (d.code !== 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:30px; color:var(--danger);">\
          ' + eh(d.message) + '</td></tr>';
        return;
      }
      var data = d.data || {};
      var games = data.games || [];
      document.getElementById('vlCount').textContent = (data.total || 0) + ' games';

      if (!games.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:30px; color:var(--text-dim);">\
          No games found</td></tr>';
        return;
      }

      tbody.innerHTML = games.map(function (g) {
        var teams = (g.teams || []).join(' vs ') || g.game_id;
        var dateStr = g.date || '—';
        var score = g.score || '—';
        var videoBadge = g.has_video
          ? '<span class="badge badge-green" title="' + eh(g.source || '') + '">🎬</span>'
          : '<span style="color:var(--text-dim);">—</span>';
        var actionBtn = g.has_video
          ? '<button class="btn btn-sm btn-primary" onclick="window.VideoLibrary._play(\'' + eh(g.game_id) + '\', \'' + eh(g.season) + '\')">Play</button>'
          : '<button class="btn btn-sm" onclick="window.VideoLibrary._openAddModal(\'' + eh(g.game_id) + '\', \'' + eh(g.season) + '\')">+ Add</button>';
        return '<tr>\
          <td>' + eh(dateStr) + '</td>\
          <td style="font-weight:500;">' + eh(teams) + '</td>\
          <td style="text-align:center; font-family:var(--mono);">' + eh(score) + '</td>\
          <td style="text-align:center;">' + videoBadge + '</td>\
          <td style="text-align:center;">' + actionBtn + '</td>\
        </tr>';
      }).join('');
    }).catch(function (e) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:30px; color:var(--danger);">\
        Failed: ' + eh(e.message) + '</td></tr>';
    });
  }

  // ═════════════════════════════════════════════════════════════════════════
  // Add Video Source Modal
  // ═════════════════════════════════════════════════════════════════════════

  var addModalGameId = null;
  var addModalSeason = null;

  function _openAddModal(gameId, season) {
    addModalGameId = gameId;
    addModalSeason = season;
    var modal = document.getElementById('vlAddModal');
    var body = document.getElementById('vlAddModalBody');
    if (!modal || !body) return;

    body.innerHTML = '\
      <div style="display:flex; flex-direction:column; gap:12px;">\
        <div>\
          <label class="label">Game ID</label>\
          <input class="input" value="' + eh(gameId) + '" disabled>\
        </div>\
        <div>\
          <label class="label">Season</label>\
          <input class="input" value="' + eh(season) + '" disabled>\
        </div>\
        <div>\
          <label class="label">Source Type</label>\
          <select class="select" id="vlAddSource">\
            <option value="youtube">YouTube (URL)</option>\
            <option value="local_file">Local File</option>\
            <option value="cloud_drive">Cloud Drive (URL)</option>\
            <option value="other">Other (URL)</option>\
          </select>\
        </div>\
        <div id="vlAddUrlRow">\
          <label class="label">Video URL</label>\
          <input class="input" id="vlAddUrl" placeholder="https://...">\
        </div>\
        <div id="vlAddPathRow" style="display:none;">\
          <label class="label">Local Path (relative to videos/ dir)</label>\
          <input class="input" id="vlAddPath" placeholder="2025/LAL_BOS.mp4">\
        </div>\
        <div>\
          <label class="label">Offset (seconds)</label>\
          <input class="input" id="vlAddOffset" type="number" step="0.1" value="0" placeholder="0.0">\
        </div>\
        <button class="btn btn-primary" onclick="window.VideoLibrary._submitAddModal()">Save Source</button>\
      </div>\
    ';

    // Toggle URL/Path visibility based on source type
    var srcSel = document.getElementById('vlAddSource');
    srcSel.onchange = function () {
      var isLocal = srcSel.value === 'local_file';
      document.getElementById('vlAddUrlRow').style.display = isLocal ? 'none' : '';
      document.getElementById('vlAddPathRow').style.display = isLocal ? '' : 'none';
    };

    modal.style.display = 'flex';
  }

  function _closeAddModal() {
    var modal = document.getElementById('vlAddModal');
    if (modal) modal.style.display = 'none';
  }

  function _submitAddModal() {
    var source = document.getElementById('vlAddSource').value;
    var urlEl = document.getElementById('vlAddUrl');
    var pathEl = document.getElementById('vlAddPath');
    var offsetEl = document.getElementById('vlAddOffset');

    var body = {
      gameid: addModalGameId,
      season: addModalSeason,
      source: source,
      video_url: urlEl && urlEl.value.trim() ? urlEl.value.trim() : null,
      local_path: pathEl && pathEl.value.trim() ? pathEl.value.trim() : null,
      video_offset_seconds: offsetEl ? parseFloat(offsetEl.value) || 0.0 : 0.0,
    };

    api('/video-library/source', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(function (d) {
      if (d.code === 0) {
        toast('Video source saved');
        _closeAddModal();
        _refreshList();
      } else {
        toast(d.message || 'Save failed', 'error');
      }
    }).catch(function (e) {
      toast('Save failed: ' + e.message, 'error');
    });
  }

  // ═════════════════════════════════════════════════════════════════════════
  // Playback View
  // ═════════════════════════════════════════════════════════════════════════

  function _play(gameId, season) {
    currentGameId = gameId;
    currentSeason = season;
    renderPlayback('videoLibraryRoot', gameId, season);
  }

  function renderPlayback(rootId, gameId, season) {
    currentView = 'playback';
    var root = document.getElementById(rootId);
    if (!root) return;

    root.innerHTML = '\
      <div class="page-header">\
        <button class="btn btn-sm" onclick="window.VideoLibrary._backToList()">← Back to List</button>\
        <h2 id="vlPlayTitle">Loading playback...</h2>\
      </div>\
      <div id="vlPlayContent" style="display:flex; gap:16px; flex-wrap:wrap;">\
        <div style="text-align:center; padding:40px; color:var(--text-dim); flex:1;">\
          <div class="spinner"></div> Loading playback data...\
        </div>\
      </div>\
    ';

    api('/video-library/play/' + encodeURIComponent(gameId) + '?season=' + encodeURIComponent(season))
      .then(function (d) {
        if (d.code !== 0) {
          document.getElementById('vlPlayContent').innerHTML = '\
            <div class="card" style="flex:1; text-align:center; padding:40px;">\
              <div style="font-size:48px; margin-bottom:16px;">📹</div>\
              <h3>' + eh(d.message) + '</h3>\
              <button class="btn btn-primary" style="margin-top:16px;" \
                onclick="window.VideoLibrary._openAddModal(\'' + eh(gameId) + '\', \'' + eh(season) + '\')">\
                + Add Video Source\
              </button>\
            </div>';
          return;
        }
        playbackData = d.data;
        _renderPlaybackContent(playbackData);
      })
      .catch(function (e) {
        document.getElementById('vlPlayContent').innerHTML = '\
          <div class="card" style="flex:1; text-align:center; padding:40px; color:var(--danger);">\
            Failed: ' + eh(e.message) + '\
          </div>';
      });
  }

  function _renderPlaybackContent(data) {
    var title = data.game_id + ' (' + data.season + ')';
    document.getElementById('vlPlayTitle').textContent = title;

    var content = document.getElementById('vlPlayContent');
    var hasFrames = data.frames && data.frames.length > 0;
    var hasTimeline = data.timeline && data.timeline.length > 0;

    // Build video element
    var videoSrc = data.video_ref || '';
    var videoHtml = '';
    if (videoSrc) {
      videoHtml = '<video id="vlVideo" controls style="width:100%; max-height:480px; background:#000; border-radius:8px;" src="' + eh(videoSrc) + '"></video>';
    } else {
      videoHtml = '<div style="width:100%; height:300px; display:flex; align-items:center; justify-content:center; background:var(--bg-dark); border-radius:8px; color:var(--text-dim);">No video source</div>';
    }

    // Build Tactics container (reused drivable API)
    var tacticsHtml = hasFrames
      ? '<div id="vlTacticsContainer" style="width:100%; min-height:400px;"></div>'
      : '<div style="padding:20px; color:var(--text-dim); text-align:center;">No replay frames available</div>';

    // Build Timeline container (reused ClutchReplay.Timeline)
    var timelineHtml = hasFrames
      ? '<div id="vlTimelineContainer" style="width:100%; padding:8px 0;"></div>'
      : '';

    // Build clutch players sidebar
    var sidebarHtml = '';
    if (data.clutch_players && data.clutch_players.length) {
      sidebarHtml = '<div class="card" style="flex:0 0 280px;">\
        <div class="card-header"><div class="card-title">Clutch Players</div></div>\
        <div style="max-height:400px; overflow-y:auto;">\
          <table class="tbl" style="font-size:12px;">\
            <thead><tr><th>Player</th><th style="text-align:right;">PTS</th><th style="text-align:right;">FG%</th></tr></thead>\
            <tbody>' +
            data.clutch_players.map(function (p) {
              return '<tr>\
                <td>' + eh(p.player_name || '') + '</td>\
                <td style="text-align:right; font-family:var(--mono);">' + (p.pts || 0) + '</td>\
                <td style="text-align:right; font-family:var(--mono);">' + (p.fg_pct != null ? Number(p.fg_pct).toFixed(1) : '—') + '</td>\
              </tr>';
            }).join('') +
            '</tbody>\
          </table>\
        </div>\
      </div>';
    }

    content.innerHTML = '\
      <div style="flex:1; min-width:400px; display:flex; flex-direction:column; gap:12px;">\
        <div class="card">\
          <div class="card-header">\
            <div class="card-title">📹 Video</div>\
            <div class="form-row" style="margin:0;">\
              <button class="btn btn-sm" onclick="window.VideoLibrary._togglePlay()">▶/⏸</button>\
              <span class="badge badge-blue" id="vlSpeedBadge">1x</span>\
              <button class="btn btn-sm" onclick="window.VideoLibrary._cycleSpeed()">Speed</button>\
            </div>\
          </div>\
          ' + videoHtml + '\
        </div>\
        <div class="card">\
          <div class="card-header"><div class="card-title">🏟️ Tactics Board</div></div>\
          ' + tacticsHtml + '\
        </div>\
        <div class="card">\
          <div class="card-header"><div class="card-title">📊 Timeline</div></div>\
          ' + timelineHtml + '\
        </div>\
      </div>\
      ' + sidebarHtml + '\
    ';

    // Initialize Tactics drivable player + Timeline + SyncController
    if (hasFrames) {
      _initPlayback(data);
    }
  }

  function _initPlayback(data) {
    var frameCount = (data.meta && data.meta.frame_count) || data.frames.length || 1;

    // (1) Load frames into Tactics drivable engine
    if (window.Tactics && typeof window.Tactics.setFrames === 'function') {
      window.Tactics.setFrames(data.frames, data.meta);
    }

    // (2) Render Tactics SVG in the container
    var tacticsContainer = document.getElementById('vlTacticsContainer');
    if (tacticsContainer && window.Tactics && typeof window.Tactics.render === 'function') {
      // Render tactics in the container (mode defaults to standard)
      window.Tactics.render('vlTacticsContainer');
      // Re-load frames after render (render may reset internal state)
      window.Tactics.setFrames(data.frames, data.meta);
    }

    // (3) Mount the ClutchReplay Timeline component (reused, DRY)
    var timelineContainer = document.getElementById('vlTimelineContainer');
    if (timelineContainer && window.ClutchReplay && window.ClutchReplay.Timeline) {
      timelineHandle = window.ClutchReplay.Timeline.mount(
        timelineContainer,
        {
          segments: data.clutch_segments || [],
          frameCount: frameCount,
          onSeek: function (p) {
            if (syncController) syncController.onTimelineSeek(p);
          },
        }
      );
    }

    // (4) Initialize SyncController with precomputed timeline
    var videoEl = document.getElementById('vlVideo');
    syncController = new SyncController({
      timeline: data.timeline || [],
      frameCount: frameCount,
      videoEl: videoEl,
    });
    syncController._bindVideo();

    // (5) Register Tactics onTick for video-driven sync fallback
    if (window.Tactics && typeof window.Tactics.onTick === 'function') {
      window.Tactics.onTick(function (fraction, frameIndex) {
        // Tactics tick → update video if not guarded (forward sync from tactics)
        // This is secondary; primary sync is video timeupdate → tactics
      });
    }
  }

  // ── Playback controls ──

  var currentSpeed = 1;
  var speeds = [1, 2, 4];

  function _togglePlay() {
    var videoEl = document.getElementById('vlVideo');
    if (!videoEl) return;
    if (videoEl.paused) {
      videoEl.play();
      if (window.Tactics && typeof window.Tactics.play === 'function') {
        window.Tactics.play();
      }
    } else {
      videoEl.pause();
      if (window.Tactics && typeof window.Tactics.pause === 'function') {
        window.Tactics.pause();
      }
    }
  }

  function _cycleSpeed() {
    var idx = speeds.indexOf(currentSpeed);
    idx = (idx + 1) % speeds.length;
    currentSpeed = speeds[idx];
    var videoEl = document.getElementById('vlVideo');
    if (videoEl) videoEl.playbackRate = currentSpeed;
    var badge = document.getElementById('vlSpeedBadge');
    if (badge) badge.textContent = currentSpeed + 'x';
    // Note: Tactics speed is controlled by its own rAF loop;
    // video playbackRate handles the <video> element speed.
  }

  function _backToList() {
    // Cleanup: stop video + tactics
    var videoEl = document.getElementById('vlVideo');
    if (videoEl) {
      videoEl.pause();
      videoEl.src = '';
    }
    if (window.Tactics && typeof window.Tactics.pause === 'function') {
      window.Tactics.pause();
    }
    syncController = null;
    timelineHandle = null;
    playbackData = null;
    renderList('videoLibraryRoot');
  }

  // ═════════════════════════════════════════════════════════════════════════
  // Public API
  // ═════════════════════════════════════════════════════════════════════════

  window.VideoLibrary = {
    renderList: renderList,
    renderPlayback: renderPlayback,
    _refreshList: _refreshList,
    _play: _play,
    _backToList: _backToList,
    _openAddModal: _openAddModal,
    _closeAddModal: _closeAddModal,
    _submitAddModal: _submitAddModal,
    _togglePlay: _togglePlay,
    _cycleSpeed: _cycleSpeed,
  };

})();
