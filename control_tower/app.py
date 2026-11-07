"""Control-tower view.   streamlit run control_tower/app.py"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

PKG = Path(__file__).resolve().parent.parent
RUNS = PKG / "runs"
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"]       # sequential blue, 0..5 used
CAT_ICON = {"supplier_delay": "🚚 Supplier delay", "plant_outage": "🏭 Plant outage", "quality_hold": "🧪 Quality hold",
            "noise": "🔇 Noise", "unconfirmed": "❓ Unconfirmed → escalated"}
WRITE = {"mes.reschedule", "mes.transfer", "dealer.notify", "dealer.stop_sale", "crm.assign_loaner",
         "crm.notify_customer", "quality.hold_lot"}

st.set_page_config(page_title="Wacky Wheels Control Tower", layout="wide")


@st.cache_data
def load_run(run: str):
    d = RUNS / run
    traces = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((d / "traces").glob("*.json"))}
    log = [json.loads(l) for l in (d / "action_log.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()] \
        if (d / "action_log.jsonl").exists() else []
    summary = json.loads((d / "run_summary.json").read_text(encoding="utf-8")) if (d / "run_summary.json").exists() else {}
    onto = json.loads((d / "ontology" / "ontology.json").read_text(encoding="utf-8")) if (d / "ontology" / "ontology.json").exists() else {}
    return traces, log, summary, onto


@st.cache_data
def base_schedule():
    po = pd.read_csv(PKG / "data" / "production_orders.csv")
    po = po[po.build_date >= "2027-03-08"]
    return po


def cat_label(cats):
    return " + ".join(CAT_ICON.get(c, c) for c in cats)


runs = sorted([p.name for p in RUNS.glob("*") if (p / "traces").exists()]) if RUNS.exists() else []
if not runs:
    st.error("No runs found. Run `python -m control_tower.run --twin --out runs/offline` first.")
    st.stop()
with st.sidebar:
    st.header("Control tower")
    run = st.selectbox("Run", runs, index=runs.index("run1") if "run1" in runs else 0)
    traces, log, summary, onto = load_run(run)
    llm = summary.get("llm")
    st.caption(f"Reader model: **{llm['model']}** ({llm['backend']})" if llm else "Reader: rule-based reader (no LLM in this run)")
    st.caption(f"Transfer anchor: `{summary.get('settings', {}).get('transfer_anchor', '?')}`")

st.title("Wacky Wheels operations control tower")
st.caption("Today is Mon 2027-03-08 · each event is handled in its own copy of the world · "
           "every plan is proven on a digital twin before it touches the live systems")

real = [t for t in traces.values() if t["dry_run"] is not None]
k = st.columns(6)
k[0].metric("Events", len(traces))
k[1].metric("Real incidents", sum(len(t["incidents"]) for t in traces.values()))
k[2].metric("Escalated to a human", sum(bool(t["escalation"]) for t in traces.values()))
k[3].metric("Ignored as noise", sum(t["category"] == ["noise"] for t in traces.values()))
k[4].metric("Live tool calls", len(log))
k[5].metric("Failed calls", sum(not r["ok"] for r in log))

tab_feed, tab_event, tab_onto, tab_audit = st.tabs(["Event feed", "Event detail", "Ontology", "Action log"])

with tab_feed:
    rows = []
    for eid, t in traces.items():
        dr = t["dry_run"]
        rows.append({"event": eid, "received": t["event"].get("received_at", "")[11:16], "source": t["event"].get("source", ""),
                     "category": cat_label(t["category"]), "writes": t["stats"]["writes"],
                     "proof": "—" if dr is None else f"{sum(c['ok'] for c in dr['checks'])}/{len(dr['checks'])} ✔" if dr["ok"] else "✖ withheld",
                     "summary": t["summary"]})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"summary": st.column_config.TextColumn(width="large")})

with tab_event:
    eid = st.selectbox("Event", list(traces), format_func=lambda e: f"{e} · {cat_label(traces[e]['category'])}")
    t = traces[eid]
    left, right = st.columns([3, 2])
    with left:
        st.markdown(f"**{t['event'].get('source', '')}** · {t['event'].get('received_at', '')}")
        st.info(t["event"]["text"])
        st.markdown(f"**Decision:** {cat_label(t['category'])}")
        st.success(t["summary"]) if t["incidents"] else st.warning(t["summary"])
    with right:
        st.markdown("**Reasoning trace**")
        for i, a in enumerate(t["audit"], 1):
            st.markdown(f"{i}. `{a['agent']}` · *{a['step']}* — {a['detail']}")
    v = t["verdict"]
    with st.expander("How the message was read and grounded", expanded=not t["incidents"]):
        st.markdown(f"*Date convention:* {v['convention_note']}")
        for r in v["readings"]:
            rd = r["reading"]
            st.markdown(f"- **[{rd['source']}]** reads *{rd['kind']}* → status **{r['status']}**  \n"
                        f"  plants={rd['plants']} parts={rd['parts']} suppliers={rd['suppliers']} "
                        f"shipments={rd['shipments']} lots={rd['lots']}  \n"
                        f"  dates={ {k: v_['phrase'] + ' → ' + ', '.join(f'{a}:{b}' for a, b in v_['candidates'].items()) for k, v_ in rd['dates'].items()} }")
            for why in r["reasons"]:
                st.markdown(f"    - {why}")
        for g in v["incidents"]:
            st.markdown(f"**Grounded {g['kind']}** — " + "; ".join(g["checks"]))
        for e in v["escalations"]:
            st.markdown(f"**Escalation reason:** {e}")

    for inc in t["incidents"]:
        st.subheader(f"{inc['id']} — graph path")
        st.caption(" → ".join(inc["path_schema"]))
        edges = inc["evidence_edges"]
        counts = Counter(e[2].split(":")[0] for e in edges) + Counter(e[0].split(":")[0] for e in edges)
        nodes_by_cls = defaultdict(set)
        for a, _, b in edges:
            nodes_by_cls[a.split(":")[0]].add(a)
            nodes_by_cls[b.split(":")[0]].add(b)
        ex = inc["example_path"]
        dot = ["digraph G { rankdir=LR; bgcolor=transparent; node [shape=box, style=\"rounded,filled\", "
               "fillcolor=\"#cde2fb\", color=\"#256abf\", fontname=Helvetica, fontsize=11]; edge [color=\"#6f6f6b\", fontsize=9, fontname=Helvetica];"]
        for n in ex:
            cls = n.split(":")[0]
            more = len(nodes_by_cls.get(cls, ())) - 1
            label = n.replace(":", "\\n") + (f"\\n(+{more} more)" if more > 0 else "")
            dot.append(f'"{n}" [label="{label}"];')
        rel = {(a, b): r for a, r, b in edges}
        for a, b in zip(ex, ex[1:]):
            r = rel.get((a, b)) or rel.get((b, a), "")
            dot.append(f'"{a}" -> "{b}" [label="{r}"];')
        dot.append("}")
        st.graphviz_chart("\n".join(dot), width="stretch")
        c1, c2, c3 = st.columns(3)
        c1.metric("Production orders", len(inc["affected_production_orders"]))
        c2.metric("Customer orders / vehicles", len(nodes_by_cls.get("CustomerOrder", ())) or inc["vehicles"])
        c3.metric("Dealers reached", len(nodes_by_cls.get("Dealer", ())))
        with st.expander("Grounding checks and all evidence edges"):
            st.markdown("\n".join(f"- {c}" for c in inc["grounding_checks"]))
            st.dataframe(pd.DataFrame(edges, columns=["from", "relation", "to"]), hide_index=True, width="stretch")

    if t["moves"]:
        st.subheader("Slot reasoning — schedule before and after")
        po = base_schedule()
        plants = sorted({m["from"][0] for m in t["moves"]} | {m["to"][0] for m in t["moves"]})
        before = po[po.plant_id.isin(plants)].groupby(["plant_id", "build_date"]).size().rename("used").reset_index()
        after_counts = Counter({k_: n for k_, n in zip(zip(before.plant_id, before.build_date), before.used)})
        for m in t["moves"]:
            after_counts[tuple(m["from"])] -= 1
            after_counts[tuple(m["to"])] += 1
        blocked = set()
        for inc in t["incidents"]:
            if inc["blocked"]:
                b = inc["bindings"]
                for d in before.build_date.unique():
                    if inc["blocked"][0] <= d <= inc["blocked"][1]:
                        blocked.add((b["plant"], d))
        moved_in = Counter(tuple(m["to"]) for m in t["moves"])
        df = pd.DataFrame([{"plant": p, "date": d, "used": n, "state": "after", "moved_in": moved_in.get((p, d), 0),
                            "blocked": "disrupted" if (p, d) in blocked else ""} for (p, d), n in after_counts.items()] +
                          [{"plant": p, "date": d, "used": n, "state": "before", "moved_in": 0,
                            "blocked": "disrupted" if (p, d) in blocked else ""} for p, d, n in before.itertuples(index=False)])
        which = st.radio("View", ["after", "before"], horizontal=True, label_visibility="collapsed")
        view = df[df.state == which]
        base = alt.Chart(view).encode(x=alt.X("date:O", title=None, axis=alt.Axis(labelAngle=-45)),
                                      y=alt.Y("plant:N", title=None))
        heat = base.mark_rect(cornerRadius=3, stroke="#fcfcfb", strokeWidth=2).encode(
            color=alt.Color("used:Q", title="slots used (of 5)", scale=alt.Scale(domain=[0, 5], range=SEQ)),
            tooltip=["plant", "date", alt.Tooltip("used", title="slots used"), alt.Tooltip("moved_in", title="orders moved in"),
                     alt.Tooltip("blocked", title="status")])
        txt = base.mark_text(fontSize=10).encode(
            text=alt.Text("label:N"), color=alt.condition("datum.used >= 4", alt.value("#ffffff"), alt.value("#0b0b0b"))
        ).transform_calculate(label="datum.blocked ? 'down' : (datum.moved_in > 0 ? '+' + datum.moved_in : '')")
        st.altair_chart((heat + txt).properties(height=40 * len(plants) + 60), width="stretch")
        st.caption("Cell color = slots used out of 5. 'down' = disrupted day for the affected models; '+n' = orders moved in.")
        st.dataframe(pd.DataFrame([{"order": m["po"], "model": m["model"], "from": " ".join(m["from"]), "to": " ".join(m["to"]),
                                    "type": m["type"], "why": m["why"]} for m in t["moves"]]),
                     hide_index=True, width="stretch")

    st.subheader("Actions taken")
    acts = pd.DataFrame([{"agent": r.get("agent"), "tool": r["tool"], "ok": "✔" if r.get("ok") else ("skipped" if r.get("skipped") else "✖"),
                          "target": next(iter(r["args"].values())) if r["args"] else "",
                          "why": r.get("why", "")} for r in t["executed"]])
    if len(acts):
        st.dataframe(acts, hide_index=True, width="stretch")
    else:
        st.markdown("No tool calls — " + (t["verdict"]["noise_reasons"][0] if t["verdict"]["noise_reasons"] else "nothing to do"))
    if t["dry_run"]:
        with st.expander(f"Proof on the digital twin ({sum(c['ok'] for c in t['dry_run']['checks'])}/{len(t['dry_run']['checks'])} invariants)"):
            st.dataframe(pd.DataFrame(t["dry_run"]["checks"]), hide_index=True, width="stretch")

with tab_onto:
    if onto:
        dot = ["digraph O { rankdir=LR; bgcolor=transparent; node [shape=box, style=\"rounded,filled\", fillcolor=\"#cde2fb\", "
               "color=\"#256abf\", fontname=Helvetica]; edge [color=\"#6f6f6b\", fontname=Helvetica, fontsize=9];"]
        for a, r, b in onto["relations"]:
            style = ", style=dashed" if r in onto.get("inferred", {}) else ""
            dot.append(f'"{a}" -> "{b}" [label="{r}"{style}];')
        dot.append("}")
        st.graphviz_chart("\n".join(dot), width="stretch")
        st.caption("Dashed = inferred relation. " + "; ".join(f"{k_}: {v_}" for k_, v_ in onto.get("inferred", {}).items()))
        s = onto.get("stats", {})
        st.markdown(f"**{s.get('nodes')} nodes, {s.get('edges')} edges**")
        c1, c2 = st.columns(2)
        c1.dataframe(pd.DataFrame(s.get("nodes_by_class", {}).items(), columns=["class", "nodes"]), hide_index=True)
        c2.dataframe(pd.DataFrame(s.get("edges_by_relation", {}).items(), columns=["relation", "edges"]), hide_index=True)

with tab_audit:
    if log:
        df = pd.DataFrame(log)
        f1, f2 = st.columns(2)
        ev = f1.multiselect("Event", sorted(df.event_id.unique()))
        tl = f2.multiselect("Tool", sorted(df.tool.unique()))
        if ev:
            df = df[df.event_id.isin(ev)]
        if tl:
            df = df[df.tool.isin(tl)]
        df["args"] = df["args"].map(lambda a: json.dumps(a)[:160])
        st.dataframe(df, hide_index=True, width="stretch")
        st.caption(f"{len(df)} rows from {run}/action_log.jsonl — the file submitted for replay.")
