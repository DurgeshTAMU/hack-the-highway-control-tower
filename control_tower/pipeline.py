"""Per-event pipeline: understand -> ground -> compile -> prove on twin -> execute -> explain."""
from __future__ import annotations

import time
from collections import Counter

from .agents import Audit, Coordinator
from .clients import TwinClient
from .kg import idx_to_date, key_of
from .verify import WRITE_TOOLS, check

MAX_EDGES = 4000


def _edges_json(ev):
    seen, out = set(), []
    for e in ev.edges:
        if e not in seen:
            seen.add(e)
            out.append(list(e))
    return out[:MAX_EDGES]


def _example_path(kg, imp):
    """One concrete end-to-end chain, for the headline 'graph path' citation."""
    e = imp.evidence.edges
    k = imp.grounded.kind
    if k == "quality_hold":
        lot = f"Lot:{imp.lots[0]}"
        po = next((b for a, r, b in e if a == lot and r == "INSTALLED_IN"), None)
        v = next((b for a, r, b in e if a == po and r == "PRODUCED"), None)
        if not v:
            return []
        va = kg.attr(v)
        tail = f"Customer:{va['customer']}" if va["status"] == "sold" else f"Dealer:{va['dealer']}"
        return [lot, po, v, tail]
    po = f"ProductionOrder:{imp.pos[0]}" if imp.pos else None
    co = next((a for a, r, b in e if b == po and r == "FULFILLED_BY"), None)
    if not co:
        return []
    dealer = next(b for a, r, b in e if a == co and r == "SOLD_THROUGH")
    cust = next(b for a, r, b in e if a == co and r == "PLACED_BY")
    if k == "supplier_delay":
        sh = f"Shipment:{imp.grounded.bindings['shipment']}"
        part = f"Part:{imp.grounded.bindings['part']}"
        model = f"Model:{kg.attr(po)['model']}"
        return [sh, part, model, po, co, dealer, cust]
    return [f"Plant:{imp.plant}", po, co, dealer, cust]


def summarize(event, verdict, impacts, moves, executed, escalated, unplaced) -> str:
    if not verdict.incidents and not escalated:
        return f"No action. Judged not operational: {verdict.noise_reasons[0] if verdict.noise_reasons else 'no operational content'}."
    if not verdict.incidents:
        return "No operational change. Escalated to a human: " + "; ".join(verdict.escalations)[:600]
    parts = []
    for imp in impacts:
        b = imp.grounded.bindings
        if imp.grounded.kind == "supplier_delay":
            parts.append(f"Supplier delay: shipment {b['shipment']} ({b['part']} for {b['plant']}) moves "
                         f"{b['original_eta']} -> {b['new_eta']}; {len(imp.pos)} build(s) needing the part are blocked.")
        elif imp.grounded.kind == "plant_outage":
            parts.append(f"Plant outage at {b['plant']} {b['start']}..{b['end']}; {len(imp.pos)} build(s) blocked.")
        else:
            parts.append(f"Quality hold on {', '.join(b['lots'])} ({b['part']} @ {b['plant']}, built {b['first']}..{b['last']}); "
                         f"{len(imp.vehicles)} vehicles affected.")
    c = Counter(r["tool"] for r in executed if r.get("ok") and r["tool"] in WRITE_TOOLS)
    if moves:
        tr = sum(m["type"] == "transfer" for m in moves)
        parts.append(f"Moved {len(moves)} production order(s) ({tr} transferred).")
    parts.append("Actions: " + ", ".join(f"{n} x {t}" for t, n in sorted(c.items())) + ".")
    if unplaced:
        parts.append(f"{len(unplaced)} order(s) could not be placed in the window and were escalated.")
    if escalated:
        parts.append("Escalated: " + escalated[:300])
    return " ".join(parts)


def handle_event(coord: Coordinator, event: dict, client) -> dict:
    t0 = time.time()
    audit = Audit()
    eid = event["event_id"]
    audit.log("Coordinator", "receive", f"{event.get('source')}: {event['text'][:120]}")
    verdict, readings, reader_info = coord.understand(event, audit)
    trace = {"event": event, "readers": reader_info, "verdict": verdict.to_json(), "category": verdict.category,
             "incidents": [], "plan": [], "dry_run": None, "executed": [], "settings": coord.s.to_json()}
    executed, escalation = [], ""
    impacts, moves, unplaced = [], [], []
    if verdict.incidents:
        impacts, actions, moves, unplaced = coord.compile(verdict, audit)
        trace["plan"] = [a.to_json() for a in actions]
        twin = TwinClient()
        dry_id = twin.fresh(eid)
        _, dry_fail = coord.execute(twin, dry_id, actions, audit)
        rep = check(coord.kg, verdict.incidents, twin.calls, twin.state(dry_id), coord.scp.base_loc)
        trace["dry_run"] = {"ok": rep.ok, "calls": len(twin.calls), "checks": rep.checks}
        audit.log("Coordinator", "prove", f"dry run on twin: {len(twin.calls)} calls, "
                                          f"{sum(c['ok'] for c in rep.checks)}/{len(rep.checks)} invariants hold")
        if rep.ok and not dry_fail:
            executed, failures = coord.execute(client, eid, actions, audit)
            reasons = list(verdict.escalations)
            if unplaced:
                reasons.append(f"no feasible slot in the planning window for {unplaced}; needs a planner decision")
            if failures:
                reasons.append(f"{len(failures)} live call(s) failed after recovery: "
                               + "; ".join(f"{f['tool']} {f['args']} -> {f['result']}" for f in failures[:3]))
            if reasons:
                escalation = " | ".join(reasons)
        else:
            escalation = ("Plan withheld: the dry run did not prove it safe. Failing checks: "
                          + "; ".join(f"{c['check']} ({c['detail']})" for c in rep.failures())
                          + (f"; {len(dry_fail)} dry-run call failures" if dry_fail else ""))
    elif verdict.escalations:
        escalation = f"Event {eid} not actionable: " + " | ".join(verdict.escalations)
    if escalation:
        executed.append(coord.escalate(client, eid, escalation, audit))
    for imp in impacts:
        trace["incidents"].append({
            "id": imp.incident_id, "kind": imp.grounded.kind, "bindings": imp.grounded.bindings,
            "grounding_checks": imp.grounded.checks, "path_schema": imp.evidence.schema,
            "example_path": _example_path(coord.kg, imp), "evidence_edges": _edges_json(imp.evidence),
            "affected_production_orders": imp.pos, "lots": imp.lots, "vehicles": len(imp.vehicles),
            "blocked": [str(idx_to_date(imp.blocked[0])), str(idx_to_date(imp.blocked[1]))] if imp.blocked else None,
            "restart": str(idx_to_date(imp.restart_idx)) if imp.restart_idx is not None and imp.restart_idx <= 19 else None,
        })
    trace["moves"] = [{**m, "from": [m["from"][0], str(idx_to_date(m["from"][1]))],
                       "to": [m["to"][0], str(idx_to_date(m["to"][1]))]} for m in moves]
    trace["unplaced"] = unplaced
    trace["executed"] = executed
    trace["escalation"] = escalation
    trace["summary"] = summarize(event, verdict, impacts, moves, executed, escalation, unplaced)
    trace["audit"] = audit.rows
    trace["stats"] = {"seconds": round(time.time() - t0, 2), "live_calls": len(executed),
                      "failed_live_calls": sum(not r.get("ok") and not r.get("skipped") for r in executed),
                      "writes": sum(r["tool"] in WRITE_TOOLS and r.get("ok") for r in executed)}
    audit.log("Coordinator", "done", trace["summary"][:200])
    return trace


__all__ = ["handle_event", "key_of"]
