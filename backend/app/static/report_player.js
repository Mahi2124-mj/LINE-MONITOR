/* Video-editor style player for breakup reports: coloured segment timeline you can drag (scrub), a zoomed timeline of the
   current cycle, frame-by-frame stepping, speed 0.1x-4x, cycle / segment jumps and keyboard shortcuts.
   Needs <video id="v"> in the page and timeline.json next to it (works without it as a plain scrubber). */
(function () {
  'use strict';
  var v = document.getElementById('v');
  if (!v) return;
  var SPEEDS = [0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 4];
  var tl = null, fps = 5, ui, segsAll, segsZoom, headAll, headZoom, tipAll, tipZoom, nowEl, zoomLbl, playBtn;

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function clock(vsec) { // wall clock of a video time (from the recorded frame times)
    if (!tl || !tl.t || !tl.t.length) return '';
    var i = Math.max(0, Math.min(tl.t.length - 1, Math.floor(vsec * fps + 1e-6)));
    var d = new Date((tl.t0 + tl.t[i]) * 1000);
    return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()) + '.' + Math.floor(d.getMilliseconds() / 100);
  }
  function wall(vsec) { // seconds of real (wall-clock) time at a video time: recordings do not have an even frame rate
    if (!tl || !tl.t || !tl.t.length) return vsec;
    var i = Math.max(0, Math.min(tl.t.length - 1, Math.floor(vsec * fps + 1e-6)));
    return tl.t[i];
  }
  function dur() { return isFinite(v.duration) && v.duration > 0 ? v.duration : (tl && tl.t ? tl.t.length / fps : 1); }
  function cycleAt(s) {
    if (!tl) return null;
    for (var i = 0; i < tl.cycles.length; i++) { var c = tl.cycles[i]; if (s >= c[1] && s < c[2]) return c; }
    return null;
  }
  function segAt(s) {
    if (!tl) return null;
    for (var i = 0; i < tl.segments.length; i++) { var g = tl.segments[i]; if (s >= g[1] && s < g[2]) return g; }
    return null;
  }
  function name(code) { return tl && tl.names[code] ? tl.names[code][0] : code; }
  function color(code) { return tl && tl.names[code] ? tl.names[code][1] : '#64748b'; }

  // ---- seeking (frame accurate)
  // while the browser is still seeking, only the newest target is kept and applied when that seek is done
  var pending = null;
  function seek(s) {
    s = Math.max(0, Math.min(dur() - 0.001, s));
    if (v.seeking) pending = s; else v.currentTime = s;
    draw(s);
  }
  v.addEventListener('seeked', function () { if (pending != null) { var p = pending; pending = null; v.currentTime = p; } });
  function frameStep(n) {
    v.pause();
    var cur = pending != null ? pending : v.currentTime;
    var f = Math.round(cur * fps - 0.1) + n;
    seek(f / fps + 0.1 / fps);
  }
  function setSpeed(x) {
    v.playbackRate = x;
    ui.querySelectorAll('[data-s]').forEach(function (b) { b.classList.toggle('on', +b.dataset.s === x); });
    draw();
  }
  function jumpCycle(dir) {
    if (!tl || !tl.cycles.length) return;
    var t = v.currentTime, cs = tl.cycles, target = null;
    t = pending != null ? pending : t;
    if (dir > 0) { for (var i = 0; i < cs.length; i++) if (cs[i][1] > t + 0.05) { target = cs[i]; break; } }
    else { for (var j = cs.length - 1; j >= 0; j--) if (cs[j][1] < t - 0.3) { target = cs[j]; break; } }
    if (target) seek(target[1] + 0.01);
  }
  function jumpSegment(dir) {
    if (!tl || !tl.segments.length) return;
    var t = v.currentTime, gs = tl.segments, target = null;
    t = pending != null ? pending : t;
    if (dir > 0) { for (var i = 0; i < gs.length; i++) if (gs[i][1] > t + 0.05) { target = gs[i]; break; } }
    else { for (var j = gs.length - 1; j >= 0; j--) if (gs[j][1] < t - 0.3) { target = gs[j]; break; } }
    if (target) seek(target[1] + 0.01);
  }

  // ---- tracks
  function zoomRange(t) {
    var c = cycleAt(t);
    if (c) return [Math.max(0, c[1] - 1), Math.min(dur(), c[2] + 1), c];
    return [Math.max(0, t - 10), Math.min(dur(), t + 10), null];
  }
  function fill(box, a, b) {
    box.innerHTML = '';
    if (!tl) return;
    var span = b - a;
    tl.segments.forEach(function (g) {
      var s0 = Math.max(a, g[1]), s1 = Math.min(b, g[2]);
      if (s1 <= s0) return;
      var i = el('i');
      i.style.left = ((s0 - a) / span * 100) + '%';
      i.style.width = ((s1 - s0) / span * 100) + '%';
      i.style.background = color(g[0]);
      box.appendChild(i);
    });
    tl.cycles.forEach(function (c) {
      if (c[1] < a || c[1] > b) return;
      var k = el('b', c[3] ? '' : 'bad', String(c[0]));
      k.style.left = ((c[1] - a) / span * 100) + '%';
      box.appendChild(k);
    });
  }
  var zoomFor = null;
  function draw(at) {
    var t = at != null ? at : v.currentTime, D = dur();
    headAll.style.left = (t / D * 100) + '%';
    var z = zoomRange(t);
    var key = z[0].toFixed(2) + '-' + z[1].toFixed(2);
    if (key !== zoomFor) { fill(segsZoom, z[0], z[1]); zoomFor = key; }
    headZoom.style.left = ((t - z[0]) / (z[1] - z[0]) * 100) + '%';
    var c = z[2], g = segAt(t);
    zoomLbl.textContent = c ? 'Zoom: cycle ' + c[0] + ' (' + (wall(c[2]) - wall(c[1])).toFixed(1) + 's)' : 'Zoom: ±10 s';
    var parts = [];
    var ck = clock(t);
    if (ck) parts.push('<b>' + ck + '</b>');
    parts.push('video ' + t.toFixed(1) + 's');
    if (c) parts.push('cycle ' + c[0] + ': ' + (wall(t) - wall(c[1])).toFixed(1) + 's / ' + (wall(c[2]) - wall(c[1])).toFixed(1) + 's');
    if (g) parts.push('<span class=rp-dot style="background:' + color(g[0]) + '"></span>' + name(g[0]) + ' (' + (wall(t) - wall(g[1])).toFixed(1) + 's / ' + (wall(g[2]) - wall(g[1])).toFixed(1) + 's)');
    parts.push('speed ' + v.playbackRate + 'x');
    nowEl.innerHTML = parts.join(' · ');
    playBtn.textContent = v.paused ? '▶' : '❚❚';
  }
  function scrubber(track, range) {
    var dragging = false, wasPlaying = false;
    function at(e) {
      var r = track.getBoundingClientRect(), x = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
      var ab = range(); return ab[0] + x * (ab[1] - ab[0]);
    }
    track.addEventListener('pointerdown', function (e) {
      dragging = true; wasPlaying = !v.paused; v.pause();
      track.setPointerCapture(e.pointerId); seek(at(e)); e.preventDefault();
    });
    track.addEventListener('pointermove', function (e) {
      var tip = track.querySelector('.rp-tip'), s = at(e), g = segAt(s);
      tip.style.display = 'block';
      tip.style.left = ((e.clientX - track.getBoundingClientRect().left)) + 'px';
      tip.textContent = (clock(s) || s.toFixed(1) + 's') + (g ? ' · ' + name(g[0]) : '');
      if (dragging) seek(s);
    });
    track.addEventListener('pointerleave', function () { track.querySelector('.rp-tip').style.display = 'none'; });
    function end() { if (dragging) { dragging = false; if (wasPlaying) v.play(); } }
    track.addEventListener('pointerup', end);
    track.addEventListener('pointercancel', end);
  }

  function build() {
    ui = el('div', 'rp');
    var speeds = SPEEDS.map(function (s) { return '<button data-s="' + s + '"' + (s === 1 ? ' class=on' : '') + '>' + s + 'x</button>'; }).join('');
    ui.innerHTML =
      '<div class=rp-ctl>' +
      '<button data-a=prevc title="Previous cycle  [">⏮</button>' +
      '<button data-a=prevs title="Previous element  ,">«</button>' +
      '<button data-a=back title="Back 1 frame  ←">◂|</button>' +
      '<button data-a=play class=rp-play title="Play / pause  Space">▶</button>' +
      '<button data-a=fwd title="Forward 1 frame  →">|▸</button>' +
      '<button data-a=nexts title="Next element  .">»</button>' +
      '<button data-a=nextc title="Next cycle  ]">⏭</button>' +
      '<span class=rp-sp>Speed ' + speeds + '</span></div>' +
      '<div class=rp-now></div>' +
      '<div class="rp-track rp-all" title="Drag or click to seek"><div class=rp-segs></div><div class=rp-head></div><div class=rp-tip></div></div>' +
      '<div class=rp-zl></div>' +
      '<div class="rp-track rp-zoom"><div class=rp-segs></div><div class=rp-head></div><div class=rp-tip></div></div>' +
      '<div class=rp-help>Drag a timeline to scrub. Keys: Space play/pause · ← → 1 frame · Shift+← → 1 s · ↑ ↓ speed · [ ] cycle · , . element · 1–8 speed</div>';
    v.parentNode.insertBefore(ui, v.nextSibling);
    var all = ui.querySelector('.rp-all'), zoom = ui.querySelector('.rp-zoom');
    segsAll = all.querySelector('.rp-segs'); headAll = all.querySelector('.rp-head'); tipAll = all.querySelector('.rp-tip');
    segsZoom = zoom.querySelector('.rp-segs'); headZoom = zoom.querySelector('.rp-head'); tipZoom = zoom.querySelector('.rp-tip');
    nowEl = ui.querySelector('.rp-now'); zoomLbl = ui.querySelector('.rp-zl'); playBtn = ui.querySelector('.rp-play');
    scrubber(all, function () { return [0, dur()]; });
    scrubber(zoom, function () { var z = zoomRange(v.currentTime); return [z[0], z[1]]; });
    ui.addEventListener('click', function (e) {
      var b = e.target.closest('button'); if (!b) return;
      if (b.dataset.s) return setSpeed(+b.dataset.s);
      var a = b.dataset.a;
      if (a === 'play') v.paused ? v.play() : v.pause();
      else if (a === 'back') frameStep(-1);
      else if (a === 'fwd') frameStep(1);
      else if (a === 'prevc') jumpCycle(-1);
      else if (a === 'nextc') jumpCycle(1);
      else if (a === 'prevs') jumpSegment(-1);
      else if (a === 'nexts') jumpSegment(1);
    });
    ['timeupdate', 'play', 'pause', 'seeked', 'ratechange', 'loadedmetadata'].forEach(function (ev) { v.addEventListener(ev, function () { draw(); }); });
    (function loop() { if (!v.paused) draw(); requestAnimationFrame(loop); })();
    document.addEventListener('keydown', function (e) {
      if (e.target && /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
      var k = e.key, i = SPEEDS.indexOf(v.playbackRate);
      if (k === ' ') { v.paused ? v.play() : v.pause(); }
      else if (k === 'ArrowLeft') { e.shiftKey ? seek(v.currentTime - 1) : frameStep(-1); }
      else if (k === 'ArrowRight') { e.shiftKey ? seek(v.currentTime + 1) : frameStep(1); }
      else if (k === 'ArrowUp') setSpeed(SPEEDS[Math.min(SPEEDS.length - 1, (i < 0 ? 4 : i) + 1)]);
      else if (k === 'ArrowDown') setSpeed(SPEEDS[Math.max(0, (i < 0 ? 4 : i) - 1)]);
      else if (k === '[') jumpCycle(-1);
      else if (k === ']') jumpCycle(1);
      else if (k === ',') jumpSegment(-1);
      else if (k === '.') jumpSegment(1);
      else if (k >= '1' && k <= '8') setSpeed(SPEEDS[+k - 1]);
      else return;
      e.preventDefault();
    });
  }

  // table rows of the report call seek(videoSeconds)
  window.seek = function (s) {
    v.currentTime = Math.max(0, s - 0.5);
    v.play();
    window.scrollTo({ top: v.getBoundingClientRect().top + scrollY - 10, behavior: 'smooth' });
  };

  build();
  fetch('timeline.json', { cache: 'no-cache' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .catch(function () { return null; })
    .then(function (data) {
      tl = data;
      if (tl && tl.fps) fps = tl.fps;
      fill(segsAll, 0, tl && tl.t ? tl.t.length / fps : dur());
      zoomFor = null;
      draw();
    });
  v.addEventListener('loadedmetadata', function () { if (tl) fill(segsAll, 0, dur()); });
})();
