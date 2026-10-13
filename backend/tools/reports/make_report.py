"""Builds reports/<dir>/index.html from data.json + key frames of the reference cycle."""
import json, sys, html, datetime as dt
from pathlib import Path
import numpy as np, cv2, rec

out = Path(sys.argv[1])
D = json.load(open(out / "data.json", encoding="utf-8"))
a, b = D["window"]
idx = rec.index(3, rec.ts(a), rec.ts(b))
T = np.array([x[0] for x in idx])
fps = len(T) / (T[-1] - T[0])
vt = lambda t: float(np.searchsorted(T, t) / fps)  # wall clock -> seconds into video.webm
L = D["labels"]
cycles = D["cycles"]
normal = [c for c in cycles if c["normal"]]
REF = 3  # reference cycle, checked frame by frame

# ---- reference cycle: steps seen in the video (+-0.5 s)
STEPS = [
    ("M1", "09:21:02.1", "09:21:03.5", "Machine #01 ke fixture se rail nikaalna (rail haath me)", "09:21:03", (0.0, 0.25, 0.62, 1.0)),
    ("M1", "09:21:03.5", "09:21:04.5", "Machine #01 me haath daal ke rail / part set karna", "09:21:04", (0.0, 0.25, 0.62, 1.0)),
    ("M1", "09:21:04.5", "09:21:09.5", "Hare bin se chhote parts utha ke fixture me lagana (~4 baar bin tak haath)", "09:21:06", (0.0, 0.25, 0.62, 1.0)),
    ("M1", "09:21:09.5", "09:21:12.0", "Fixture me parts baithana / machine chalu karna", "09:21:10", (0.0, 0.25, 0.62, 1.0)),
    ("M1", "09:21:12.0", "09:21:14.3", "Rail uthana aur #02 ki taraf mudna", "09:21:13", (0.2, 0.2, 0.82, 1.0)),
    ("W12", "09:21:14.3", "09:21:15.6", "Rail lekar machine #02 tak chalna", "09:21:14", (0.3, 0.0, 0.92, 1.0)),
    ("M2", "09:21:15.6", "09:21:17.0", "Rail machine #02 me rakhna", "09:21:15", (0.42, 0.0, 0.88, 0.7)),
    ("M2", "09:21:17.0", "09:21:24.5", "Hare tray se parts utha ke #02 me lagana (tray tak haath ~3 baar)", "09:21:20", (0.42, 0.0, 0.88, 0.7)),
    ("M2", "09:21:24.5", "09:21:27.6", "Machine #02 se rail nikaalna aur mudna", "09:21:26", (0.42, 0.0, 0.88, 0.7)),
    ("W21", "09:21:27.6", "09:21:28.9", "Wapas machine #01 tak chalna (raste me chehra / topi theek)", "09:21:28", (0.2, 0.0, 0.85, 1.0)),
]
img_dir = out / "frames"
img_dir.mkdir(exist_ok=True)
steps_html = []
ref = next(c for c in cycles if c["n"] == REF)
for k, (code, s0, s1, what, shot, crop) in enumerate(STEPS, start=1):
    t0_ = rec.ts(s0[:8]) + float(s0[8:] or 0); t1_ = rec.ts(s1[:8]) + float(s1[8:] or 0)
    ts_ = rec.ts(shot) + 0.3
    near = min(idx, key=lambda x: abs(x[0] - ts_))
    img = rec.frame(near[1], near[2], near[3]); h, w = img.shape[:2]
    x0, y0, x1, y1 = crop
    img = img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    img = cv2.resize(img, (300, int(img.shape[0] * 300 / img.shape[1])))
    cv2.imwrite(str(img_dir / f"step{k}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 82])
    steps_html.append(f"""<tr><td class=n>{k}</td><td><span class=dot style="background:{L[code][1]}"></span>{html.escape(L[code][0])}</td>
<td>{html.escape(what)}</td><td class=num>{t0_ - ref['start']:.1f} – {t1_ - ref['start']:.1f}s</td><td class=num><b>{t1_ - t0_:.1f}s</b></td>
<td><img src="frames/step{k}.jpg" alt="" loading=lazy onclick="seek({vt(t0_):.2f})"></td></tr>""")


def bar(c, scale):
    parts = []
    for s in c["segments"]:
        wpc = (s["t1"] - s["t0"]) / scale * 100
        parts.append(f'<i style="width:{wpc:.2f}%;background:{L[s["code"]][1]}" title="{html.escape(L[s["code"]][0])}: {s["t1"] - s["t0"]:.1f}s"></i>')
    return '<div class=bar>' + "".join(parts) + "</div>"


scale = max(c["sec"] for c in normal) * 1.05
rows = []
for c in cycles:
    p = c["per"]
    cls = "" if c["normal"] else " class=bad"
    b_ = bar(c, c["sec"] if not c["normal"] else scale)
    rows.append(f"""<tr{cls} onclick="seek({vt(c['start']):.2f})"><td class=n>{c['n']}</td><td class=num>{c['start_s']}</td><td class=num>{c['end_s']}</td>
<td class=num><b>{c['sec']:.1f}s</b></td><td class=num>{p['M1']:.1f}</td><td class=num>{p['W12']:.1f}</td><td class=num>{p['M2']:.1f}</td>
<td class=num>{p['W21']:.1f}</td><td class=num>{p['AWAY']:.1f}</td><td class=wide>{b_}</td><td>{html.escape('; '.join(c['notes']))}</td></tr>""")

ms = D["median_seg"]
med = float(np.median([c["sec"] for c in normal]))
lost = sum(c["sec"] - med for c in cycles if not c["normal"])
legend = "".join(f'<span><span class=dot style="background:{v[1]}"></span>{html.escape(v[0])}</span>' for v in L.values())
first, last = cycles[0], cycles[-1]
page = f"""<!doctype html><html lang=hi><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Rail Assy breakup</title>
<style>
:root{{--bg:#f8fafc;--panel:#fff;--ink:#0f172a;--ink2:#475569;--edge:#e2e8f0;--bad:#fef2f2}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b1220;--panel:#111827;--ink:#e5e7eb;--ink2:#9ca3af;--edge:#1f2937;--bad:#3b1111}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,Segoe UI,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:16px}}
h1{{font-size:20px;margin:4px 0}} h2{{font-size:16px;margin:22px 0 8px}}
.sub{{color:var(--ink2)}} .card{{background:var(--panel);border:1px solid var(--edge);border-radius:10px;padding:14px;margin:12px 0}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}}
.kpi b{{display:block;font-size:22px}} .kpi span{{color:var(--ink2);font-size:12px}}
video{{width:100%;max-height:560px;background:#000;border-radius:8px}}
table{{width:100%;border-collapse:collapse}} th,td{{padding:6px 8px;border-bottom:1px solid var(--edge);text-align:left;vertical-align:middle}}
th{{font-size:12px;color:var(--ink2);font-weight:600}} td.num{{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}} td.n{{color:var(--ink2)}}
tr.bad{{background:var(--bad)}} tbody tr{{cursor:pointer}} tbody tr:hover{{outline:1px solid #3b82f6}}
.bar{{display:flex;height:14px;border-radius:3px;overflow:hidden;background:var(--edge);min-width:160px}} .bar i{{display:block;height:100%}}
td.wide{{width:28%}} .dot{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}}
.legend{{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--ink2);margin:6px 0}}
td img{{width:150px;border-radius:4px;cursor:pointer}} ul{{margin:6px 0;padding-left:20px}} li{{margin:4px 0}}
.scroll{{overflow-x:auto}}
</style></head><body><main>
<h1>Rail Assy m/c #01 + #02 — cycle aur segment breakup</h1>
<div class=sub>Camera 3 (Rail Assy m/c #01) · 9 Oct 2026, {a}–{b} · recording {D['fps']} frame/s · ek hi operator dono machine chalata hai (camera 4 se bhi confirm)</div>

<div class="card kpis">
<div class=kpi><b>{len(cycles)}</b><span>poori cycles is video me</span></div>
<div class=kpi><b>{med:.1f}s</b><span>normal cycle (median)</span></div>
<div class=kpi><b>{min(c['sec'] for c in normal):.1f} – {max(c['sec'] for c in normal):.1f}s</b><span>normal cycles ki range</span></div>
<div class=kpi><b>{len(cycles) - len(normal)}</b><span>asaamaanya cycle ({lost:.0f}s extra)</span></div>
</div>

<div class=card>
<video id=v src="video.webm" controls preload=metadata></video>
<div class=legend>{legend}</div>
<div class=sub>Video me upar: ghadi, cycle number, cycle ka timer, abhi ka segment. Neeche rang ki patti = us cycle ke segments. Peela gol = operator. Table ki kisi line pe click karo, video wahin chala jayega.</div>
</div>

<h2>Cycle kahan se shuru, kahan khatam</h2>
<div class=card><ul>
<li><b>Cycle start</b> = operator #02 se wapas aakar jab uske haath machine #01 ke fixture tak pahunchte hain. <b>Cycle end</b> = agli baar yahi pal.</li>
<li>Video {a} se shuru hota hai, lekin pehli poori cycle <b>{first['start_s']}</b> pe shuru hui. Pehle ke {D['partial']['before']:.0f}s adhoori cycle hain, unhe gina nahi.</li>
<li>Aakhri poori cycle <b>{last['end_s']}</b> pe khatam hui. Uske baad ke {D['partial']['after']:.0f}s bhi adhoore hain.</li>
<li>Cycle 7 cycle to hai, lekin normal nahi. Operator ~55s apni dono machine chhod kar daayein taraf doosre operator ke paas raha (video {vt(rec.ts('09:23:08')):.0f}s ke aas-paas). Isliye ise median me nahi gina.</li>
</ul></div>

<h2>Har cycle ka segment breakup (seconds)</h2>
<div class="card scroll"><table><thead><tr><th>#</th><th>Start</th><th>End</th><th>Cycle</th><th>#01 kaam</th><th>→ #02</th><th>#02 kaam</th><th>→ #01</th><th>Door</th><th>Segments</th><th>Note</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
<tfoot><tr><th></th><th colspan=2>Normal (median)</th><th class=num>{med:.1f}s</th><th class=num>{ms['M1']}</th><th class=num>{ms['W12']}</th><th class=num>{ms['M2']}</th><th class=num>{ms['W21']}</th><th class=num>{ms['AWAY']}</th><th colspan=2></th></tr></tfoot>
</table></div>

<h2>Ek cycle ka detailed breakup (Cycle {REF}: {ref['start_s']} → {ref['end_s']}, {ref['sec']:.1f}s), video frame-by-frame dekh kar</h2>
<div class="card scroll"><table><thead><tr><th>#</th><th>Segment</th><th>Kya ho raha hai</th><th>Cycle me samay</th><th>Kitna</th><th>Frame</th></tr></thead>
<tbody>{''.join(steps_html)}</tbody></table>
<div class=sub>Ye steps video dekh kar likhe hain; boundaries ±0.5s. Upar wali table ke segments apne aap (operator ki jagah se) nikle hain; jahan chalna 0.0 hai wahan operator itni tezi se mud gaya ki chalna saath wale segment me gina gaya.</div></div>

<h2>Kya dikha</h2>
<div class=card><ul>
<li><b>Ek operator, do machine:</b> cycle = #01 pe ~{ms['M1']:.0f}s + #02 pe ~{ms['M2']:.0f}s + chalna ~{ms['W12'] + ms['W21']:.1f}s ≈ {med:.0f}s. Isliye #01 aur #02 dono ka cycle time ek jaisa (~25–26s) aata hai. Ye dono alag bottleneck nahi, ek hi operator ka loop hain.</li>
<li><b>Chalna kam hai:</b> sirf ~{ms['W12'] + ms['W21']:.1f}s har cycle (~{100 * (ms['W12'] + ms['W21']) / med:.0f}%). Layout theek hai.</li>
<li><b>Sabse zyada samay haath ke kaam me jaata hai:</b> hare bin/tray se chhote parts utha ke lagana. #01 pe ~5s aur #02 pe ~7.5s, yaani cycle ka lagbhag aadha. Bin paas/tircha rakhne, parts feeder, ya pehle se kit banane se yahan seconds bach sakte hain.</li>
<li><b>Machine ka intezaar nahi dikha:</b> normal cycles me operator kisi machine pe khaali khada nahi milta; jaate hi kaam shuru hota hai.</li>
<li><b>Variation:</b> normal cycles {min(c['sec'] for c in normal):.1f}–{max(c['sec'] for c in normal):.1f}s. #02 ka kaam zyada badalta hai ({min(c['per']['M2'] for c in normal):.1f}–{max(c['per']['M2'] for c in normal):.1f}s).</li>
<li><b>Nuksaan:</b> 6.5 minute me ek baar operator ~55s door gaya, yaani lagbhag 2 cycle ka samay gaya.</li>
<li><b>Takt:</b> agar 15.5s takt ek set (#01 + #02) ka hai, to ye pair har cycle ~{med - 15.5:.0f}s peeche hai.</li>
</ul></div>
<div class=sub>Data: Line Monitor recording (camera 3, pose ke saath). Video sirf is PC pe hai.</div>
</main>
<script>function seek(s){{const v=document.getElementById('v');v.currentTime=Math.max(0,s-0.5);v.play();window.scrollTo({{top:v.getBoundingClientRect().top+scrollY-10,behavior:'smooth'}});}}</script>
</body></html>"""
(out / "index.html").write_text(page, encoding="utf-8")
print("report", out / "index.html")
