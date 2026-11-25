"""Rule-based improvement suggestions (lean: line balancing, motion waste, waiting, stability).

Add new rules here; each rule returns Recommendation objects. Keep the wording actionable.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..schemas import Recommendation

if TYPE_CHECKING:
    from ..schemas import LineAnalytics, StationSummary

SEV_ORDER = {"critical": 0, "warning": 1, "info": 2}


def _name(s: "StationSummary") -> str:
    return f"Step {s.station.sequence} ({s.station.name})"


def for_station(la: "LineAnalytics", station_id: int) -> list[Recommendation]:
    s = next((x for x in la.stations if x.station.id == station_id), None)
    if s is None:
        return []
    out: list[Recommendation] = []
    st, mv, sid, lid = s.stats, s.movement, s.station.id, la.line.id
    target = s.station.target_cycle_sec

    if st.count == 0:
        if not s.station.camera_ids:
            out.append(Recommendation(id=f"setup-{sid}", line_id=lid, station_id=sid, category="setup", severity="info",
                                      title=f"{_name(s)} has no camera",
                                      detail="Add a camera and draw the part zone / work area, or enter cycle times manually so this step is included in line balancing."))
        return out
    if st.count < 5:  # not enough data for a reliable suggestion
        return out

    content = st.avg_content or 0.0
    if content > target * 1.08:
        pct = (content / target - 1) * 100
        out.append(Recommendation(id=f"target-{sid}", line_id=lid, station_id=sid, category="target",
                                  severity="critical" if pct > 20 else "warning",
                                  title=f"{_name(s)} runs {pct:.0f}% over its target",
                                  detail=f"Average operator time {content:.1f}s vs target {target:.0f}s "
                                         f"({st.over_target_pct or 0:.0f}% of cycles over target). Review the standard work sequence for this step.",
                                  est_saving_sec=round(content - target, 1)))

    if st.cv is not None and st.cv > 0.15 and st.count >= 10:
        out.append(Recommendation(id=f"stability-{sid}", line_id=lid, station_id=sid, category="stability",
                                  severity="warning" if st.cv > 0.25 else "info",
                                  title=f"Unstable cycle time at {_name(s)} (CV {st.cv:.2f})",
                                  detail=f"Median {st.median:.1f}s but p90 {st.p90:.1f}s and max {st.max:.1f}s. Large variation usually means "
                                         "missing parts, fitting problems, rework or a non-standard method. Watch the slow cycles on camera and standardize."))

    reach = mv.avg_reach_count or 0.0
    if reach >= 0.8:
        save = round(reach * 1.5, 1)
        out.append(Recommendation(id=f"motion-reach-{sid}", line_id=lid, station_id=sid, category="motion",
                                  severity="warning" if reach >= 1.5 else "info",
                                  title=f"{reach:.1f} long reaches per cycle at {_name(s)}",
                                  detail="The operator's hand leaves the normal work area to pick parts/tools. Move those bins or tools "
                                         "inside the normal reach zone (≈ 40–50 cm from the body, in front of the operator) or use gravity-feed bins. "
                                         "Check the heatmap to see which location is used.",
                                  est_saving_sec=save))

    walk = mv.avg_walk_m or 0.0
    if walk >= 0.8:
        out.append(Recommendation(id=f"motion-walk-{sid}", line_id=lid, station_id=sid, category="motion",
                                  severity="warning" if walk >= 2 else "info",
                                  title=f"Operator walks {walk:.1f} m per cycle at {_name(s)}",
                                  detail="Walking is pure motion waste. Bring material to the point of use (kitting, line-side racks, water-spider "
                                         "replenishment) and keep tools on balancers at the station.",
                                  est_saving_sec=round(walk / 1.0 + 0.5, 1)))

    exp = mv.expected_picks
    picks = mv.avg_pick_count or 0.0
    if exp > 0 and picks > exp + 0.3:
        out.append(Recommendation(id=f"motion-picks-{sid}", line_id=lid, station_id=sid, category="motion", severity="info",
                                  title=f"Extra picks at {_name(s)}: {picks:.1f} vs {exp} expected",
                                  detail="Re-picking means parts are hard to grab, mixed, tangled or dropped. Present parts oriented, one part type per bin, "
                                         "or use a kitting tray per unit.",
                                  est_saving_sec=round(picks - exp, 1)))

    hands = [x.movement.avg_hand_travel_m for x in la.stations if x.movement.avg_hand_travel_m]
    if mv.avg_hand_travel_m and len(hands) > 1:
        avg = sum(hands) / len(hands)
        if mv.avg_hand_travel_m > avg * 1.3 and mv.avg_hand_travel_m > 2.5:
            out.append(Recommendation(id=f"motion-hand-{sid}", line_id=lid, station_id=sid, category="motion", severity="info",
                                      title=f"High hand travel at {_name(s)}: {mv.avg_hand_travel_m:.1f} m/cycle",
                                      detail=f"Line average is {avg:.1f} m. Re-arrange the workplace so parts flow in one direction "
                                             "(pick → assemble → place) and both hands work simultaneously."))

    wait = mv.wait_pct or 0.0
    if wait >= 25 and not s.is_bottleneck:
        why = f" It is paced by the bottleneck {la.bottleneck_label}." if la.bottleneck_label else ""
        out.append(Recommendation(id=f"waiting-{sid}", line_id=lid, station_id=sid, category="waiting", severity="info",
                                  title=f"{_name(s)} waits {wait:.0f}% of the time",
                                  detail=f"Average wait {st.avg_wait or 0:.1f}s per cycle.{why} Use this spare capacity: take over work elements from the "
                                         "bottleneck or combine this step with a neighbour to free an operator."))
    return out


def for_line(la: "LineAnalytics") -> list[Recommendation]:
    out: list[Recommendation] = []
    lid = la.line.id
    takt = la.line.takt_time_sec
    # balancing is per person: one operator may run several steps (see analytics.operator_groups)
    data = [o for o in la.operators if o.per_part_sec]
    bn = next((o for o in data if o.is_bottleneck), None)

    if bn and bn.per_part_sec:
        c = bn.per_part_sec
        # receiver with the most slack, preferring the people next to him on the line
        others = [o for o in data if o is not bn]
        neigh = [o for o in others if min(abs(a - b) for a in o.sequences for b in bn.sequences) == 1]
        pool = neigh or others
        recv = max(pool, key=lambda o: takt - (o.per_part_sec or 0), default=None)
        if c > takt:
            excess = c - takt
            if recv and recv.per_part_sec and recv.per_part_sec < takt:
                slack = takt - recv.per_part_sec
                move = (f" Move ~{min(excess, slack):.1f}s of work to {recv.label}, who needs only {recv.per_part_sec:.1f}s "
                        f"({slack:.1f}s spare), and/or remove the {bn.motion_sec or 0:.1f}s motion waste per part at the bottleneck.")
            else:
                move = f" Remove the {bn.motion_sec or 0:.1f}s of motion waste per part, simplify the method or add a second operator."
            out.append(Recommendation(id=f"balancing-bn-{lid}", line_id=lid, station_id=la.bottleneck_station_id, category="balancing",
                                      severity="critical", title=f"Bottleneck: {bn.label} needs {c:.1f}s per part > takt {takt:.1f}s",
                                      detail=f"This limits the line to {la.capacity_per_hour or 0:.0f} units/hr while demand needs {3600 / takt:.0f}/hr." + move,
                                      est_saving_sec=round(excess, 1)))
        else:
            out.append(Recommendation(id=f"balancing-bn-{lid}", line_id=lid, station_id=la.bottleneck_station_id, category="balancing",
                                      severity="info", title=f"Slowest operator: {bn.label} at {c:.1f}s per part ({c / takt * 100:.0f}% of takt)",
                                      detail="The line meets takt. Any improvement here directly raises line capacity; improvements elsewhere only add idle time."))

    if la.balance_efficiency_pct is not None and la.balance_efficiency_pct < 85 and len(data) > 1:
        total = sum(o.per_part_sec or 0 for o in data)
        ideal = total / len(data)
        heavy = [o.label for o in data if (o.per_part_sec or 0) > ideal * 1.1]
        light = [o.label for o in data if (o.per_part_sec or 0) < ideal * 0.9]
        out.append(Recommendation(id=f"balancing-eff-{lid}", line_id=lid, category="balancing",
                                  severity="warning" if la.balance_efficiency_pct < 75 else "info",
                                  title=f"Line balance efficiency {la.balance_efficiency_pct:.0f}% (target ≥ 85%)",
                                  detail=f"Total work content {total:.0f}s per part over {len(data)} operators → {ideal:.1f}s each if perfectly balanced. "
                                         f"Overloaded: {', '.join(heavy) or '–'}. Underloaded: {', '.join(light) or '–'}. Shift work elements from "
                                         f"overloaded to underloaded operators (use the Yamazumi chart)."))

    station_recs = [r for s in la.stations for r in for_station(la, s.station.id)]
    out += station_recs
    out.sort(key=lambda r: (SEV_ORDER[r.severity], -(r.est_saving_sec or 0)))
    return out[:20]
