/**
 * NBACore Studio v8 — Player Avatar renderer (pure helper).
 * ====================================================
 * Pure function, ZERO dependency on app.js globals, so it can be unit-tested
 * under Node via `require('./frontend/js/components/player_avatar.js')`.
 *
 * Renders either a real headshot <img> (falling back to initials on error) or
 * an initials circle (deterministic color from player_id hash) when no image
 * is available. Covers all three "no image" cases:
 *   - headshot_path missing
 *   - headshot_status !== 'ok'
 *   - headshot fields absent entirely (undefined)
 */
(function (global) {
  'use strict';

  // Soft, accessible color palette for the initials circles.
  var AVATAR_COLORS = [
    '#00b88a', '#3b82f6', '#8b5cf6', '#f59e0b', '#06b6d4',
    '#ef4444', '#f97316', '#10b981', '#6366f1', '#ec4899'
  ];

  /** Escape text for safe insertion as HTML text / attribute. */
  function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /** Escape a JSON string for embedding inside a double-quoted HTML attribute. */
  function escapeAttr(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  /** Deterministic 32-bit hash (djb2) → used to pick a stable color. */
  function hashStr(s) {
    s = String(s == null ? '' : s);
    var h = 5381;
    for (var i = 0; i < s.length; i++) {
      h = ((h << 5) + h + s.charCodeAt(i)) | 0;
    }
    return Math.abs(h);
  }

  /** Pick a deterministic soft color for a given id. */
  function colorForId(id) {
    return AVATAR_COLORS[hashStr(id) % AVATAR_COLORS.length];
  }

  /** Extract 1–2 initials from a display name. */
  function computeInitials(name) {
    if (!name) return '';
    var parts = String(name).trim().split(/\s+/).filter(Boolean);
    if (parts.length >= 2) {
      return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    if (parts.length === 1) {
      return parts[0].slice(0, 2).toUpperCase();
    }
    return '';
  }

  /** Resolve the best available display name from a bio-like object. */
  function resolveName(bio) {
    if (!bio) return '';
    return bio.name || bio.player_name || bio.display_name || bio.full_name ||
      bio.player_id || '';
  }

  /**
   * Render the initials fallback node (also used by <img onerror>).
   * @returns {string} HTML string: <div class="player-avatar-initials ...">.
   */
  function avatarInitialsHTML(bio, opts) {
    opts = opts || {};
    var size = opts.size || 'md';
    var cls = opts.cls || '';
    var rounded = opts.rounded !== false;
    var name = resolveName(bio);
    var initials = computeInitials(name);
    if (!initials && bio && bio.player_id) {
      initials = String(bio.player_id).slice(0, 2).toUpperCase();
    }
    if (!initials) initials = '?';
    var color = colorForId(bio && bio.player_id);
    var sizeCls = ' ' + size;
    var roundCls = rounded ? '' : ' square';
    return '<div class="player-avatar-initials' + sizeCls + roundCls +
      (cls ? ' ' + cls : '') + '" style="background:' + color + '">' +
      escapeHtml(initials) + '</div>';
  }

  /**
   * Rebuild the initials node from an <img> element's data attributes.
   * Used as the onerror fallback so a 404 image degrades to initials.
   */
  function avatarInitialsFromData(imgEl) {
    try {
      var bio = JSON.parse(imgEl.getAttribute('data-avatar-bio') || '{}');
      var opts = JSON.parse(imgEl.getAttribute('data-avatar-opts') || '{}');
      return avatarInitialsHTML(bio, opts);
    } catch (e) {
      return avatarInitialsHTML({}, {});
    }
  }

  /**
   * Main entry. Returns an HTML string for a player avatar.
   *
   * @param {Object} bio  Player-like object:
   *   { player_id, name|player_name|display_name|full_name,
   *     headshot_path, headshot_status }
   * @param {Object} [opts] { size:'sm'|'md'|'lg', slot:1|2, rounded:true, cls:'' }
   * @returns {string} HTML string (<img> when ok, else initials <div>).
   */
  function renderPlayerAvatar(bio, opts) {
    opts = opts || {};
    bio = bio || {};
    var hasImg = bio.headshot_status === 'ok' && bio.headshot_path;
    if (hasImg) {
      var pid = bio.player_id || '';
      var name = resolveName(bio);
      var bioJson = escapeAttr(JSON.stringify(bio));
      var optsJson = escapeAttr(JSON.stringify(opts));
      return '<img class="player-avatar-img" src="/headshots/' +
        encodeURIComponent(pid) + '" alt="' + escapeHtml(name) +
        '" data-avatar-bio="' + bioJson + '" data-avatar-opts="' + optsJson +
        '" onerror="this.outerHTML=window.__avatarInitialsFromData(this)" loading="lazy">';
    }
    return avatarInitialsHTML(bio, opts);
  }

  var api = {
    renderPlayerAvatar: renderPlayerAvatar,
    avatarInitialsHTML: avatarInitialsHTML,
    avatarInitialsFromData: avatarInitialsFromData,
    computeInitials: computeInitials,
    colorForId: colorForId
  };

  if (typeof window !== 'undefined') {
    window.renderPlayerAvatar = renderPlayerAvatar;
    window.__avatarInitials = avatarInitialsHTML;
    window.__avatarInitialsFromData = avatarInitialsFromData;
    window.__avatarColorForId = colorForId;
    window.__avatarComputeInitials = computeInitials;
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  return api;
})(typeof window !== 'undefined' ? window : globalThis);
