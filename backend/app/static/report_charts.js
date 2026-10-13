/* Variation (baratsuki) chart of breakup reports: the actual element times of consecutive cycles side by side.
   Views: stacked bar per cycle, one strip per element (with median and 10-90 % band), statistics table.
   Needs <div id="baratsuki"></div> in the page and cycles.json next to it:
   {elements: [{code, name, color}], cycles: [{n, vn, clock, v, sec, el: {code: sec|null}, flag, note}]} */
(function () {
  'use strict';
  var box = document.getElementById('baratsuki');
  if (!box) return;
  var NS = 'http://www.w3.org/2000/svg';
  var REST = { code: '_rest', name: 'Not detected', color: '#94a3b8' };
  var D = null, view = 'stack', range = 'video', hideStops = true, off = {}, tip = null, body, legend;

  var css = document.createElement('style');
  css.textContent =
    '.bt-bar{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin-bottom:8px}' +
    '.bt-grp{display:inline-flex;border:1px solid var(--edge,#e2e8f0);border-radius:7px;overflow:hidden}' +
    '.bt-grp button{border:0;background:transparent;color:var(--ink2,#475569);padding:5px 10px;font:inherit;font-size:13px;cursor:pointer}' +
    '.bt-grp button+button{border-left:1px solid var(--edge,#e2e8f0)}' +
    '.bt-grp button.on{background:var(--ink,#0f172a);color:var(--panel,#fff)}' +
    '.bt-chk{font-size:13px;color:var(--ink2,#475569);display:inline-flex;gap:5px;align-items:center;cursor:pointer}' +
    '.bt-legend{display:flex;flex-wrap:wrap;gap:4px 6px;margin:4px 0 8px}' +
    '.bt-chip{border:1px solid var(--edge,#e2e8f0);background:transparent;color:var(--ink,#0f172a);border-radius:999px;padding:2px 9px;font:inherit;font-size:12px;cursor:pointer}' +
    '.bt-chip.off{opacity:.35;text-decoration:line-through}' +
    '.bt-chip i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;vertical-align:-1px}' +
    '.bt-body{overflow-x:auto;overflow-y:hidden}' +
    '.bt-body svg{display:block}' +
    '.bt-body svg .c{cursor:pointer}' +
    '.bt-body svg .c:hover rect.hl{fill-opacity:.12}' +
    '.bt-note{font-size:12px;color:var(--ink2,#475569);margin-top:6px}' +
    '.bt-tip{position:fixed;z-index:50;pointer-events:none;background:var(--panel,#fff);color:var(--ink,#0f172a);border:1px solid var(--edge,#e2e8f0);' +
    'border-radius:8px;padding:8px 10px;font-size:12px;line-height:1.5;box-shadow:0 6px 20px rgba(0,0,0,.18);display:none;max-width:320px}' +
    '.bt-tip table{border-collapse:collapse;width:100%} .bt-tip td{padding:0 4px;border:0} .bt-tip td.r{text-align:right;font-variant-numeric:tabular-nums}' +
    '.bt-tip i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:4px}' +
    '.bt-tab td.num,.bt-tab th.num{text-align:right;font-variant-numeric:tabular-nums}' +
    '.bt-cv{display:inline-block;height:7px;border-radius:2px;background:#f59e0b;margin-left:6px;vertical-align:0}';
  document.head.appendChild(css);

  // ---- numbers
  function pct(s, p) { // s sorted
    if (!s.length) return NaN;
    var i = (s.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i);
    return s[lo] + (s[hi] - s[lo]) * (i - lo);
  }
  function stats(v) {
    if (!v.length) return null;
    var s = v.slice().sort(function (a, b) { return a - b; }), n = s.length;
    var mean = s.reduce(function (a, b) { return a + b; }, 0) / n;
    var sd = Math.sqrt(s.reduce(function (a, b) { return a + (b - mean) * (b - mean); }, 0) / Math.max(1, n - 1));
    return { n: n, med: pct(s, 0.5), mean: mean, min: s[0], max: s[n - 1], p10: pct(s, 0.1), p90: pct(s, 0.9), p95: pct(s, 0.95), sd: sd, cv: mean > 0 ? 100 * sd / mean : 0 };
  }
  function step(max) {
    var raw = max / 4, p = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10)), m = raw / p;
    return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
  }
  function f1(x) { return x == null || isNaN(x) ? '–' : x.toFixed(1); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  // ---- data selection
  function cycles() {
    return D.cycles.filter(function (c) { return (range === 'all' || c.v != null) && !(hideStops && c.flag === 'stop'); });
  }
  function els() { return D.elements.filter(function (e) { return !off[e.code]; }); }
  function allOn() { return els().length === D.elements.length; }
  function rest(c) {
    var s = 0;
    D.elements.forEach(function (e) { if (c.el[e.code] != null) s += c.el[e.code]; });
    return Math.max(0, c.sec - s);
  }
  function value(c) { // height of a cycle's bar = visible elements (+ undetected rest when all are shown)
    var s = 0;
    els().forEach(function (e) { if (c.el[e.code] != null) s += c.el[e.code]; });
    return allOn() ? s + rest(c) : s;
  }
  function label(c) { return range === 'video' && c.vn != null ? c.vn : c.n; }

  // ---- svg helpers
  function svg(w, h) { var s = document.createElementNS(NS, 'svg'); s.setAttribute('width', w); s.setAttribute('height', h); s.setAttribute('viewBox', '0 0 ' + w + ' ' + h); return s; }
  function add(parent, tag, attrs, text) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (text != null) e.textContent = text;
    parent.appendChild(e);
    return e;
  }
  function geometry(n) {
    var W = body.clientWidth || 800, L = 46, R = 12;
    var bw = Math.max(9, Math.min(36, (W - L - R) / Math.max(1, n)));
    return { L: L, bw: bw, W: Math.max(W, Math.ceil(L + R + bw * n)) };
  }
  function yScale(vals, med) {
    var st = stats(vals.filter(function (x) { return x > 0; }));
    if (!st) return 1;
    var cap = Math.min(st.max, Math.max(st.p95 * 1.3, med * 2, st.p90 * 1.15));
    var s = step(cap || 1);
    return Math.ceil((cap || 1) / s) * s;
  }
  function axis(g, x0, x1, y0, h, ymax) {
    var s = step(ymax);
    for (var v = 0; v <= ymax + 1e-9; v += s) {
      var y = y0 + h - v / ymax * h;
      add(g, 'line', { x1: x0, x2: x1, y1: y, y2: y, style: 'stroke:var(--edge,#e2e8f0);stroke-width:1' });
      add(g, 'text', { x: x0 - 6, y: y + 4, 'text-anchor': 'end', style: 'fill:var(--ink2,#475569);font-size:11px' }, (Math.round(v * 10) / 10) + 's');
    }
  }
  function medianLine(g, x0, x1, y, txt) {
    add(g, 'line', { x1: x0, x2: x1, y1: y, y2: y, style: 'stroke:var(--ink,#0f172a);stroke-width:1.2;stroke-dasharray:5 4;opacity:.75' });
    add(g, 'text', { x: x1 - 2, y: y - 4, 'text-anchor': 'end', style: 'fill:var(--ink,#0f172a);font-size:11px;font-weight:600;paint-order:stroke;stroke:var(--panel,#fff);stroke-width:3px' }, txt);
  }
  function hit(g, c, x, w, y, h) { // whole-column hover / click target
    var cg = add(g, 'g', { class: 'c' });
    add(cg, 'rect', { x: x, y: y, width: w, height: h, class: 'hl', style: 'fill:var(--ink,#0f172a);fill-opacity:0' });
    cg.addEventListener('mousemove', function (e) { showTip(e, c); });
    cg.addEventListener('mouseleave', hideTip);
    cg.addEventListener('click', function () { if (c.v != null && window.seek) window.seek(c.v); });
    return cg;
  }

  function labelled(cs, bw) { // which cycle numbers fit under the bars: abnormal ones first, then every n-th
    var need = function (c) { return String(label(c)).length * 6 + 4; }, x = function (i) { return i * bw + bw / 2; };
    var chosen = [], every = bw >= 18 ? 1 : bw >= 11 ? 2 : 5;
    var free = function (i) { return chosen.every(function (j) { return Math.abs(x(i) - x(j)) >= (need(cs[i]) + need(cs[j])) / 2; }); };
    cs.forEach(function (c, i) { if (c.flag !== 'normal' && free(i)) chosen.push(i); });
    cs.forEach(function (c, i) { if (c.flag === 'normal' && i % every === 0 && free(i)) chosen.push(i); });
    var set = {};
    chosen.forEach(function (i) { set[i] = true; });
    return set;
  }

  // ---- stacked bar per cycle
  function drawStack() {
    var cs = cycles(), g = geometry(cs.length), H = 300, T = 14, B = 34, h = H - T - B;
    var vals = cs.map(value), st = stats(vals) || { med: 0 };
    var ymax = yScale(vals, st.med), k = h / ymax;
    var s = svg(g.W, H);
    axis(s, g.L, g.W - 4, T, h, ymax);
    var lab = labelled(cs, g.bw);
    cs.forEach(function (c, i) {
      var x = g.L + i * g.bw, w = Math.max(3, g.bw * 0.78), xb = x + (g.bw - w) / 2;
      var cg = hit(s, c, x, g.bw, T, h + B - 4);
      var y = 0, parts = [];
      els().forEach(function (e) { if (c.el[e.code] != null && c.el[e.code] > 0) parts.push([e.color, c.el[e.code], 1]); });
      if (allOn() && rest(c) > 0.05) parts.push([REST.color, rest(c), 0.35]);
      parts.forEach(function (p) {
        var a = Math.min(y, ymax), b = Math.min(y + p[1], ymax);
        if (b > a) add(cg, 'rect', { x: xb, y: T + h - b * k, width: w, height: Math.max(0.5, (b - a) * k), style: 'fill:' + p[0] + ';fill-opacity:' + p[2] });
        y += p[1];
      });
      if (y > ymax + 1e-6) add(cg, 'text', { x: x + g.bw / 2, y: T + 9, 'text-anchor': 'middle', style: 'fill:#dc2626;font-size:10px;font-weight:700' }, '▲');
      var bad = c.flag !== 'normal';
      if (lab[i]) {
        add(cg, 'text', { x: x + g.bw / 2, y: T + h + 14, 'text-anchor': 'middle', style: 'font-size:10px;fill:' + (bad ? '#dc2626' : 'var(--ink2,#475569)') + (bad ? ';font-weight:700' : '') }, String(label(c)));
      }
      if (c.v != null && range === 'all') add(cg, 'rect', { x: xb, y: T + h + 20, width: w, height: 3, style: 'fill:var(--ink2,#475569);opacity:.6' });
    });
    if (cs.length) medianLine(s, g.L, g.W - 4, T + h - st.med * k, 'median ' + f1(st.med) + 's');
    add(s, 'text', { x: g.L, y: H - 4, style: 'fill:var(--ink2,#475569);font-size:11px' }, range === 'all' ? 'cycle number (underline = in the video)' : 'cycle number (same as the video table)');
    return s;
  }

  // ---- one strip per element
  function drawRows() {
    var cs = cycles(), g = geometry(cs.length), RH = 78, HD = 20, GAPR = 10;
    var rows = [{ code: '_cycle', name: 'Cycle time', color: '#64748b' }].concat(els());
    var s = svg(g.W, rows.length * (RH + HD + GAPR) + 22);
    var lab = labelled(cs, g.bw);
    rows.forEach(function (e, r) {
      var top = r * (RH + HD + GAPR), y0 = top + HD, vals = cs.map(function (c) { return e.code === '_cycle' ? value(c) : c.el[e.code]; });
      var st = stats(vals.filter(function (x) { return x != null; }));
      add(s, 'rect', { x: g.L - 40, y: top + 4, width: 10, height: 10, rx: 2, style: 'fill:' + e.color });
      var t = add(s, 'text', { x: g.L - 26, y: top + 13, style: 'fill:var(--ink,#0f172a);font-size:12px;font-weight:600' }, e.name);
      if (st) add(t, 'tspan', { style: 'fill:var(--ink2,#475569);font-weight:400' },
        '   median ' + f1(st.med) + 's · min ' + f1(st.min) + ' · max ' + f1(st.max) + ' · range ' + f1(st.max - st.min) + 's · CV ' + st.cv.toFixed(0) + '%');
      if (!st) return;
      var ymax = yScale(vals.filter(function (x) { return x != null; }), st.med), k = RH / ymax;
      add(s, 'line', { x1: g.L, x2: g.W - 4, y1: y0 + RH, y2: y0 + RH, style: 'stroke:var(--edge,#e2e8f0)' });
      add(s, 'text', { x: g.L - 6, y: y0 + 8, 'text-anchor': 'end', style: 'fill:var(--ink2,#475569);font-size:10px' }, f1(ymax) + 's');
      add(s, 'text', { x: g.L - 6, y: y0 + RH, 'text-anchor': 'end', style: 'fill:var(--ink2,#475569);font-size:10px' }, '0');
      var b0 = Math.min(st.p10, ymax), b1 = Math.min(st.p90, ymax);
      add(s, 'rect', { x: g.L, y: y0 + RH - b1 * k, width: g.W - 4 - g.L, height: Math.max(1, (b1 - b0) * k), style: 'fill:' + e.color + ';fill-opacity:.12' });
      cs.forEach(function (c, i) {
        var x = g.L + i * g.bw, w = Math.max(3, g.bw * 0.7), xb = x + (g.bw - w) / 2, v = vals[i];
        var cg = hit(s, c, x, g.bw, y0, RH);
        if (v == null) { add(cg, 'text', { x: x + g.bw / 2, y: y0 + RH - 2, 'text-anchor': 'middle', style: 'fill:var(--ink2,#475569);font-size:9px' }, '×'); return; }
        var hv = Math.min(v, ymax);
        add(cg, 'rect', { x: xb, y: y0 + RH - hv * k, width: w, height: Math.max(0.5, hv * k), style: 'fill:' + e.color });
        if (v > ymax) add(cg, 'text', { x: x + g.bw / 2, y: y0 + 8, 'text-anchor': 'middle', style: 'fill:#dc2626;font-size:9px;font-weight:700' }, '▲');
      });
      medianLine(s, g.L, g.W - 4, y0 + RH - Math.min(st.med, ymax) * k, f1(st.med) + 's');
    });
    var yl = rows.length * (RH + HD + GAPR) + 12;
    cs.forEach(function (c, i) {
      var bad = c.flag !== 'normal';
      if (lab[i]) add(s, 'text', { x: g.L + i * g.bw + g.bw / 2, y: yl, 'text-anchor': 'middle', style: 'font-size:10px;fill:' + (bad ? '#dc2626' : 'var(--ink2,#475569)') }, String(label(c)));
    });
    return s;
  }

  // ---- statistics table
  function drawTable() {
    var cs = cycles();
    var secSum = cs.reduce(function (a, c) { return a + c.sec; }, 0);
    var rows = D.elements.map(function (e) {
      var v = cs.map(function (c) { return c.el[e.code]; }).filter(function (x) { return x != null; });
      return { e: e, st: stats(v), sum: v.reduce(function (a, b) { return a + b; }, 0) };
    });
    var tot = stats(cs.map(function (c) { return c.sec; }));
    var maxcv = Math.max.apply(null, rows.map(function (r) { return r.st ? r.st.cv : 0; }).concat([1]));
    function tr(name, color, st, share) {
      if (!st) return '<tr><td>' + name + '</td><td class=num colspan=10>not seen</td></tr>';
      return '<tr><td>' + (color ? '<span class=dot style="background:' + color + '"></span>' : '') + name + '</td><td class=num>' + st.n + '</td>' +
        '<td class=num><b>' + f1(st.med) + '</b></td><td class=num>' + f1(st.mean) + '</td><td class=num>' + f1(st.min) + '</td><td class=num>' + f1(st.max) + '</td>' +
        '<td class=num>' + f1(st.max - st.min) + '</td><td class=num>' + f1(st.p10) + ' – ' + f1(st.p90) + '</td><td class=num>' + f1(st.sd) + '</td>' +
        '<td class=num>' + st.cv.toFixed(0) + '%<span class=bt-cv style="width:' + Math.round(40 * st.cv / maxcv) + 'px"></span></td>' +
        '<td class=num>' + (share == null ? '' : share.toFixed(0) + '%') + '</td></tr>';
    }
    var html = '<table class=bt-tab><thead><tr><th>Element</th><th class=num>Cycles</th><th class=num>Median</th><th class=num>Mean</th><th class=num>Min</th>' +
      '<th class=num>Max</th><th class=num>Range</th><th class=num>10–90 %</th><th class=num>Std dev</th><th class=num>CV</th><th class=num>Share</th></tr></thead><tbody>';
    rows.forEach(function (r) { html += tr(esc(r.e.name), r.e.color, r.st, secSum > 0 ? 100 * r.sum / secSum : null); });
    html += tr('<b>Cycle time</b>', null, tot, null) + '</tbody></table>' +
      '<div class=bt-note>Cycles = cycles in which the element was seen. Share = the element\'s part of the total cycle time. ' +
      'CV = std dev ÷ mean (higher = less stable).</div>';
    var d = document.createElement('div');
    d.innerHTML = html;
    return d;
  }

  // ---- tooltip
  function showTip(e, c) {
    if (!tip) { tip = document.createElement('div'); tip.className = 'bt-tip'; document.body.appendChild(tip); }
    var h = '<b>Cycle ' + label(c) + '</b> · ' + c.clock + ' · <b>' + f1(c.sec) + 's</b>' + (c.note ? '<br>' + esc(c.note) : '') + '<table>';
    D.elements.forEach(function (el) {
      var v = c.el[el.code];
      h += '<tr' + (off[el.code] ? ' style="opacity:.45"' : '') + '><td><i style="background:' + el.color + '"></i>' + esc(el.name) + '</td><td class=r>' + (v == null ? '–' : f1(v) + 's') + '</td></tr>';
    });
    if (rest(c) > 0.05) h += '<tr><td><i style="background:' + REST.color + ';opacity:.5"></i>' + REST.name + '</td><td class=r>' + f1(rest(c)) + 's</td></tr>';
    h += '</table>' + (c.v != null ? '<span style="opacity:.7">Click to play this cycle</span>' : '<span style="opacity:.7">Outside the video</span>');
    tip.innerHTML = h;
    tip.style.display = 'block';
    var x = e.clientX + 14, y = e.clientY + 14, r = tip.getBoundingClientRect();
    if (x + r.width > innerWidth - 8) x = e.clientX - r.width - 14;
    if (y + r.height > innerHeight - 8) y = Math.max(8, e.clientY - r.height - 14);
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
  }
  function hideTip() { if (tip) tip.style.display = 'none'; }

  // ---- page
  function render() {
    hideTip();
    box.querySelectorAll('[data-view]').forEach(function (b) { b.classList.toggle('on', b.dataset.view === view); });
    box.querySelectorAll('[data-range]').forEach(function (b) { b.classList.toggle('on', b.dataset.range === range); });
    legend.style.display = view === 'table' ? 'none' : '';
    legend.querySelectorAll('[data-el]').forEach(function (b) { b.classList.toggle('off', !!off[b.dataset.el]); });
    body.innerHTML = '';
    if (!cycles().length) { body.textContent = 'No cycles in this range.'; return; }
    body.appendChild(view === 'stack' ? drawStack() : view === 'rows' ? drawRows() : drawTable());
  }
  function init(data) {
    D = data;
    if (!D || !D.cycles || !D.cycles.length) { box.textContent = 'No cycle data for this report.'; return; }
    var nv = D.cycles.filter(function (c) { return c.v != null; }).length;
    var ns = D.cycles.filter(function (c) { return c.flag === 'stop'; }).length;
    if (!nv) range = 'all';
    var b = function (k, v, t) { return '<button data-' + k + '="' + v + '">' + t + '</button>'; };
    box.innerHTML = '<div class=bt-bar><span class=bt-grp>' + b('view', 'stack', 'Cycle by cycle') + b('view', 'rows', 'Each element') + b('view', 'table', 'Table') + '</span>' +
      '<span class=bt-grp>' + (nv ? b('range', 'video', 'Video cycles (' + nv + ')') : '') + b('range', 'all', 'Whole window (' + D.cycles.length + ')') + '</span>' +
      (ns ? '<label class=bt-chk><input type=checkbox checked> Hide line stops (' + ns + ')</label>' : '') + '</div>' +
      '<div class=bt-legend>' + D.elements.map(function (e) { return '<button class=bt-chip data-el="' + e.code + '"><i style="background:' + e.color + '"></i>' + esc(e.name) + '</button>'; }).join('') + '</div>' +
      '<div class=bt-body></div>' +
      '<div class=bt-note>Each bar is one cycle, in the order they ran. Click an element above to hide or show it. ▲ = bar cut at the top of the scale. ' +
      'Red number = abnormal cycle. Click a bar to play that cycle.</div>';
    body = box.querySelector('.bt-body'); legend = box.querySelector('.bt-legend');
    box.addEventListener('click', function (e) {
      var t = e.target.closest('button'); if (!t) return;
      if (t.dataset.view) view = t.dataset.view;
      else if (t.dataset.range) range = t.dataset.range;
      else if (t.dataset.el) {
        off[t.dataset.el] = !off[t.dataset.el];
        if (!els().length) off = {};
      }
      render();
    });
    var chk = box.querySelector('.bt-chk input');
    if (chk) chk.addEventListener('change', function () { hideStops = chk.checked; render(); });
    var w = body.clientWidth, tm = null;
    addEventListener('resize', function () { clearTimeout(tm); tm = setTimeout(function () { if (body.clientWidth !== w) { w = body.clientWidth; render(); } }, 150); });
    render();
  }
  fetch('cycles.json', { cache: 'no-cache' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .catch(function () { return null; })
    .then(init);
})();
