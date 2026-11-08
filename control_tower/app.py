"""Control-tower view.   streamlit run control_tower/app.py"""
from __future__ import annotations

import html
import inspect as _inspect
import json
from collections import Counter, defaultdict
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

# Streamlit >=1.50 takes width="stretch"; older releases only know use_container_width.
STRETCH = ({"width": "stretch"} if "width" in _inspect.signature(st.dataframe).parameters
           and "stretch" in str(_inspect.signature(st.dataframe).parameters["width"].annotation)
           else {"use_container_width": True})

PKG = Path(__file__).resolve().parent.parent
RUNS = PKG / "runs"
SEQ = ["#e4eefc", "#b9d4f7", "#8bb8f0", "#5b98e6", "#2f72cc", "#1b4f9a"]
WRITE = {"mes.reschedule", "mes.transfer", "dealer.notify", "dealer.stop_sale", "crm.assign_loaner",
         "crm.notify_customer", "quality.hold_lot"}

# category -> (label, text colour, background)
CAT = {
    "supplier_delay": ("Supplier delay", "#8a5200", "#fdf0d8"),
    "plant_outage": ("Plant outage", "#17517e", "#dcecf9"),
    "quality_hold": ("Quality hold", "#6b2f8f", "#eddff7"),
    "noise": ("Noise · no action", "#4b5563", "#e8eaee"),
    "unconfirmed": ("Unconfirmed · escalated", "#9b1c2c", "#fbe0e3"),
}
AGENT_COLOR = {"Coordinator": "#1c232b", "SupplyChainPlanner": "#17517e", "DealerNetwork": "#8a5200",
               "CustomerCareQuality": "#6b2f8f"}
CLASS_COLOR = {"Shipment": "#fdf0d8", "Part": "#fdf0d8", "Model": "#e4eefc", "Plant": "#dcecf9", "Lot": "#eddff7",
               "ProductionOrder": "#dcecf9", "CustomerOrder": "#e3f3e8", "Dealer": "#fbe9d6", "Customer": "#e3f3e8",
               "Vehicle": "#e3f3e8", "Supplier": "#fdf0d8"}

st.set_page_config(page_title="Wacky Wheels Control Tower", page_icon="🚦", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown("""
<style>
html, body, [class*="css"] { font-family: Inter, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
[data-testid="stToolbar"], [data-testid="stDecoration"], footer { display: none !important; }
header[data-testid="stHeader"] { background: transparent; height: 2.2rem; }
.block-container { padding: 3rem 2.2rem 3rem; max-width: 1600px; }
.topbar { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:14px 20px;
  background:#1c232b; color:#fff; border-radius:14px; margin-bottom:16px; }
.topbar .brand { font-size:21px; font-weight:800; letter-spacing:-.5px; }
.topbar .brand span { color:#ff5c6c; }
.topbar .sub { font-size:12px; color:#aab4c0; margin-top:2px; }
.chip { display:inline-block; font-size:11px; font-weight:600; padding:4px 10px; border-radius:20px;
  background:#2c3641; color:#d6dde5; margin-left:6px; }
.kpis { display:grid; grid-template-columns:repeat(6,1fr); gap:12px; margin-bottom:18px; }
.kpi { background:#fff; border:1px solid #e3e6ea; border-radius:12px; padding:14px 16px; }
.kpi .v { font-size:30px; font-weight:750; line-height:1.05; letter-spacing:-1px; }
.kpi .l { font-size:11px; color:#667085; text-transform:uppercase; letter-spacing:.8px; margin-top:5px; font-weight:600; }
.kpi.good .v { color:#1d7a55; } .kpi.warn .v { color:#b25e00; } .kpi.mute .v { color:#667085; }
.badge { display:inline-block; font-size:11px; font-weight:700; padding:3px 9px; border-radius:6px; margin-right:5px; }
.card { background:#fff; border:1px solid #e3e6ea; border-radius:12px; padding:16px 18px; margin-bottom:12px; }
.card h4 { margin:0 0 8px; font-size:12px; text-transform:uppercase; letter-spacing:1px; color:#667085; font-weight:700; }
.msg { font-size:15px; line-height:1.55; border-left:4px solid #c82132; background:#fff; }
.verdict { font-size:14px; line-height:1.55; }
.verdict.act { border-left:4px solid #1d7a55; } .verdict.esc { border-left:4px solid #c82132; }
.verdict.none { border-left:4px solid #98a2b3; }
.stepper { display:flex; gap:8px; margin:4px 0 14px; }
.step { flex:1; background:#fff; border:1px solid #e3e6ea; border-radius:10px; padding:10px 12px; }
.step .n { font-size:10px; color:#98a2b3; font-weight:700; letter-spacing:1px; }
.step .t { font-size:14px; font-weight:700; margin-top:1px; }
.step .d { font-size:12px; color:#667085; margin-top:2px; }
.step.done { border-color:#b7e0cc; background:#f2faf6; } .step.done .n { color:#1d7a55; }
.step.skip { opacity:.55; } .step.stop { border-color:#f2bcc3; background:#fdf3f4; } .step.stop .n { color:#c82132; }
.out { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:10px; margin-bottom:14px; }
.out div { background:#fff; border:1px solid #e3e6ea; border-radius:10px; padding:10px 12px; }
.out b { display:block; font-size:22px; letter-spacing:-.5px; } .out span { font-size:11px; color:#667085; }
.tl { border-left:2px solid #e3e6ea; margin-left:8px; padding-left:16px; }
.tl .it { position:relative; padding:0 0 12px; font-size:13px; line-height:1.5; }
.tl .it::before { content:""; position:absolute; left:-22px; top:5px; width:10px; height:10px; border-radius:50%;
  background:var(--c,#98a2b3); border:2px solid #fff; box-shadow:0 0 0 1px #d0d5dd; }
.tl .ag { font-weight:700; color:var(--c,#1c232b); } .tl .st { color:#667085; font-style:italic; margin:0 4px; }
.feedrow { font-size:12px; color:#667085; margin:-6px 0 14px 2px; line-height:1.45; }
div[data-testid="stButton"] > button { width:100%; text-align:left; justify-content:flex-start; border-radius:10px;
  border:1px solid #e3e6ea; background:#fff; padding:.55rem .8rem; font-weight:600; }
div[data-testid="stButton"] > button[kind="primary"] { background:#fdf3f4; border-color:#c82132; color:#1c232b; }
button[data-baseweb="tab"] { font-weight:600; }
</style>
""", unsafe_allow_html=True)


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
    return po[po.build_date >= "2027-03-08"]


def badges(cats) -> str:
    out = ""
    for c in cats:
        lab, fg, bg = CAT.get(c, (c, "#333", "#eee"))
        out += f'<span class="badge" style="color:{fg};background:{bg}">{html.escape(lab)}</span>'
    return out


def esc(x) -> str:
    return html.escape(str(x))


def counts(t: dict) -> Counter:
    return Counter(r["tool"] for r in t["executed"] if r.get("ok") and r["tool"] in WRITE)


runs = sorted([p.name for p in RUNS.glob("*") if (p / "traces").exists()]) if RUNS.exists() else []
if not runs:
    st.error("No runs found. Run `python -m control_tower.run --twin --out runs/offline` first.")
    st.stop()
with st.sidebar:
    st.header("Run")
    run = st.selectbox("Run folder", runs, index=runs.index("final") if "final" in runs else 0)
traces, log, summary, onto = load_run(run)
llm = summary.get("llm")
model_chip = f"{llm['model']} · {llm['backend']}" if llm else "rule reader (no LLM)"

st.markdown(f"""
<div class="topbar"><div><div class="brand">Wacky Wheels<span>.</span> Control Tower</div>
<div class="sub">Today is Mon 2027-03-08 · every event is handled in its own copy of the world · every plan is proven
on a digital twin before it touches the live systems</div></div>
<div><span class="chip">run: {esc(run)}</span><span class="chip">reader: {esc(model_chip)}</span>
<span class="chip">transfer: {esc(summary.get('settings', {}).get('transfer_anchor', '?'))}</span></div></div>
""", unsafe_allow_html=True)

n_inc = sum(len(t["incidents"]) for t in traces.values())
n_esc = sum(bool(t["escalation"]) for t in traces.values())
n_noise = sum(t["category"] == ["noise"] for t in traces.values())
n_fail = sum(not r["ok"] for r in log)
n_writes = sum(1 for r in log if r["tool"] in WRITE and r["ok"])
st.markdown(f"""
<div class="kpis">
<div class="kpi"><div class="v">{len(traces)}</div><div class="l">Events in feed</div></div>
<div class="kpi"><div class="v">{n_inc}</div><div class="l">Incidents handled</div></div>
<div class="kpi warn"><div class="v">{n_esc}</div><div class="l">Escalated to a human</div></div>
<div class="kpi mute"><div class="v">{n_noise}</div><div class="l">Ignored as noise</div></div>
<div class="kpi"><div class="v">{n_writes}</div><div class="l">Corrective actions</div></div>
<div class="kpi {'good' if n_fail == 0 else 'warn'}"><div class="v">{n_fail}</div><div class="l">Failed calls</div></div>
</div>""", unsafe_allow_html=True)

tab_main, tab_onto, tab_audit = st.tabs(["Control tower", "Ontology", "Audit log"])

# =============================================================================== control tower
with tab_main:
    ids = list(traces)
    if "sel" not in st.session_state or st.session_state.sel not in ids:
        st.session_state.sel = ids[0]
    feed, detail = st.columns([2, 5], gap="large")

    with feed:
        st.markdown("##### Event feed")
        box = st.container(height=760, border=False)
        for eid in ids:
            t = traces[eid]
            label = " + ".join(CAT.get(c, (c,))[0] for c in t["category"])
            if box.button(f"{eid} · {label}", key=f"b_{eid}", type="primary" if eid == st.session_state.sel else "secondary"):
                st.session_state.sel = eid
                st.rerun()
            snippet = t["event"]["text"][:92].replace("\n", " ") + ("…" if len(t["event"]["text"]) > 92 else "")
            box.markdown(f'<div class="feedrow">{esc(t["event"].get("received_at", "")[11:16])} · '
                         f'{esc(t["event"].get("source", ""))} · <b>{sum(counts(t).values())}</b> actions<br>'
                         f'{esc(snippet)}</div>', unsafe_allow_html=True)

    with detail:
        eid = st.session_state.sel
        t = traces[eid]
        acted = bool(t["incidents"])
        st.markdown(f'<div style="margin-bottom:8px">{badges(t["category"])} '
                    f'<span style="color:#667085;font-size:13px">{esc(eid)} · {esc(t["event"].get("source", ""))} · '
                    f'{esc(t["event"].get("received_at", ""))}</span></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="card msg"><h4>Incoming message</h4>{esc(t["event"]["text"])}</div>', unsafe_allow_html=True)
        tone = "act" if acted and not t["escalation"] else ("esc" if t["escalation"] else "none")
        head = {"act": "Decision · act within policy", "esc": "Decision · escalate to a human",
                "none": "Decision · no action"}[tone]
        st.markdown(f'<div class="card verdict {tone}"><h4>{head}</h4>{esc(t["summary"])}</div>', unsafe_allow_html=True)

        # ---- pipeline stepper
        v = t["verdict"]
        readers = Counter(r["reading"]["source"].split(":")[0] for r in v["readings"])
        dr = t["dry_run"]
        proof = f"{sum(c['ok'] for c in dr['checks'])}/{len(dr['checks'])} checks" if dr else "—"
        n_w = sum(counts(t).values())
        steps = [("1 · READ", "Understand", f"{'+'.join(sorted(readers))} reader" + ("s" if len(readers) > 1 else ""), "done"),
                 ("2 · GROUND", "Match to records",
                  f"{len(t['incidents'])} incident(s) bound" if acted else ("noise" if t["category"] == ["noise"] else "nothing specific"),
                  "done" if acted else "stop"),
                 ("3 · PLAN", "Apply handbook", f"{len(t['plan'])} planned calls" if t["plan"] else "no plan", "done" if t["plan"] else "skip"),
                 ("4 · PROVE", "Dry run on twin", proof, "done" if dr and dr["ok"] else "skip"),
                 ("5 · EXECUTE", "Live calls", f"{n_w} writes" + (" · 1 escalation" if t["escalation"] else ""),
                  "done" if n_w else ("stop" if t["escalation"] else "skip"))]
        st.markdown('<div class="stepper">' + "".join(
            f'<div class="step {s}"><div class="n">{a}</div><div class="t">{b}</div><div class="d">{esc(c)}</div></div>'
            for a, b, c, s in steps) + "</div>", unsafe_allow_html=True)

        # ---- outcome cards
        c = counts(t)
        owners = c["crm.notify_customer"]
        cards = [("Orders moved", c["mes.reschedule"] + c["mes.transfer"]), ("Transferred", c["mes.transfer"]),
                 ("Dealer notices", c["dealer.notify"]), ("Loaners", c["crm.assign_loaner"]),
                 ("Stop-sales", c["dealer.stop_sale"]), ("Owners contacted", owners), ("Lots held", c["quality.hold_lot"])]
        cards = [(a, b) for a, b in cards if b]
        if cards:
            st.markdown('<div class="out">' + "".join(f"<div><b>{b}</b><span>{a}</span></div>" for a, b in cards) + "</div>",
                        unsafe_allow_html=True)

        names = ["Graph path", "Actions taken", "Reasoning & audit"] + (["Schedule impact"] if t["moves"] else []) \
            + (["Proof"] if dr else []) + ["How it was read"]
        tabs = dict(zip(names, st.tabs(names)))

        # ---- graph path
        with tabs["Graph path"]:
            if not t["incidents"]:
                reason = (v["noise_reasons"] or v["escalations"] or ["no operational entity found"])[0]
                st.info(f"No graph traversal: {reason}")
            for inc in t["incidents"]:
                edges = inc["evidence_edges"]
                nodes_by_cls = defaultdict(set)
                for a, _, b in edges:
                    nodes_by_cls[a.split(":")[0]].add(a)
                    nodes_by_cls[b.split(":")[0]].add(b)
                ex = inc["example_path"]
                st.markdown(f"**{esc(inc['id'])}** &nbsp; `{' → '.join(inc['path_schema'])}`", unsafe_allow_html=True)
                dot = ['digraph G { rankdir=LR; bgcolor="transparent"; nodesep=0.35; ranksep=0.55; '
                       'node [shape=box, style="rounded,filled", color="#b8c2cc", fontname=Helvetica, fontsize=11, margin="0.14,0.08"]; '
                       'edge [color="#7b8794", fontsize=9, fontname=Helvetica, fontcolor="#52606d"];']
                for n in ex:
                    cls = n.split(":")[0]
                    more = len(nodes_by_cls.get(cls, ())) - 1
                    label = n.replace(":", "\\n") + (f"\\n(+{more} more)" if more > 0 else "")
                    dot.append(f'"{n}" [label="{label}", fillcolor="{CLASS_COLOR.get(cls, "#eee")}"];')
                rel = {(a, b): r for a, r, b in edges}
                for a, b in zip(ex, ex[1:]):
                    dot.append(f'"{a}" -> "{b}" [label="{rel.get((a, b)) or rel.get((b, a), "")}"];')
                dot.append("}")
                st.graphviz_chart("\n".join(dot), **STRETCH)
                m1, m2, m3 = st.columns(3)
                m1.metric("Production orders", len(inc["affected_production_orders"]))
                m2.metric("Customer orders" if nodes_by_cls.get("CustomerOrder") else "Vehicles",
                          len(nodes_by_cls.get("CustomerOrder", ())) or inc["vehicles"])
                m3.metric("Dealers reached", len(nodes_by_cls.get("Dealer", ())))
                with st.expander("Grounding checks and every evidence edge"):
                    st.markdown("\n".join(f"- {x}" for x in inc["grounding_checks"]))
                    st.dataframe(pd.DataFrame(edges, columns=["from", "relation", "to"]), hide_index=True, **STRETCH)

        # ---- actions
        with tabs["Actions taken"]:
            if not t["executed"]:
                st.info("No tool calls — " + ((v["noise_reasons"] or ["nothing to do"])[0]))
            else:
                by_agent = defaultdict(Counter)
                for r in t["executed"]:
                    if r.get("ok") and r["tool"] in WRITE:
                        by_agent[r.get("agent", "?")][r["tool"]] += 1
                cols = st.columns(max(1, len(by_agent)))
                for col, (ag, cn) in zip(cols, by_agent.items()):
                    col.markdown(f'<div class="card"><h4 style="color:{AGENT_COLOR.get(ag, "#667085")}">{esc(ag)}</h4>'
                                 + "".join(f"<div style='font-size:13px'><b>{n}</b> × {esc(tool)}</div>" for tool, n in cn.items())
                                 + "</div>", unsafe_allow_html=True)
                acts = pd.DataFrame([{"agent": r.get("agent"), "tool": r["tool"],
                                      "ok": "✔" if r.get("ok") else ("skipped" if r.get("skipped") else "✖"),
                                      "target": next(iter(r["args"].values())) if r["args"] else "", "why": r.get("why", "")}
                                     for r in t["executed"]])
                st.dataframe(acts, hide_index=True, height=360, **STRETCH)

        # ---- reasoning & audit
        with tabs["Reasoning & audit"]:
            items = "".join(
                f'<div class="it" style="--c:{AGENT_COLOR.get(a["agent"], "#98a2b3")}"><span class="ag">{esc(a["agent"])}</span>'
                f'<span class="st">{esc(a["step"])}</span>{esc(a["detail"][:600])}</div>' for a in t["audit"])
            st.markdown(f'<div class="card"><h4>Audit trail</h4><div class="tl">{items}</div></div>', unsafe_allow_html=True)

        # ---- schedule
        if t["moves"]:
            with tabs["Schedule impact"]:
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
                heat = base.mark_rect(cornerRadius=3, stroke="#ffffff", strokeWidth=2).encode(
                    color=alt.Color("used:Q", title="slots used (of 5)", scale=alt.Scale(domain=[0, 5], range=SEQ)),
                    tooltip=["plant", "date", alt.Tooltip("used", title="slots used"), alt.Tooltip("moved_in", title="orders moved in"),
                             alt.Tooltip("blocked", title="status")])
                txt = base.mark_text(fontSize=10).encode(
                    text=alt.Text("label:N"), color=alt.condition("datum.used >= 4", alt.value("#ffffff"), alt.value("#0b0b0b"))
                ).transform_calculate(label="datum.blocked ? 'down' : (datum.moved_in > 0 ? '+' + datum.moved_in : '')")
                st.altair_chart((heat + txt).properties(height=40 * len(plants) + 60), **STRETCH)
                st.caption("Colour = slots used out of 5 per plant and day. 'down' = disrupted day; '+n' = orders moved in.")
                st.dataframe(pd.DataFrame([{"order": m["po"], "model": m["model"], "from": " ".join(m["from"]),
                                            "to": " ".join(m["to"]), "type": m["type"], "why": m["why"]} for m in t["moves"]]),
                             hide_index=True, height=300, **STRETCH)

        # ---- proof
        if dr:
            with tabs["Proof"]:
                st.caption("The plan is replayed on a digital twin and checked against an independent, table-only oracle "
                           "before any live call. Any failing check withholds the plan.")
                st.dataframe(pd.DataFrame(dr["checks"]).assign(ok=lambda d: d.ok.map({True: "✔ pass", False: "✖ fail"})),
                             hide_index=True, **STRETCH)

        # ---- how it was read
        with tabs["How it was read"]:
            st.markdown(f"*Date convention:* {v['convention_note']}")
            for r in v["readings"]:
                rd = r["reading"]
                st.markdown(f"- **[{rd['source']}]** reads *{rd['kind']}* → status **{r['status']}**  \n"
                            f"  plants={rd['plants']} parts={rd['parts']} suppliers={rd['suppliers']} "
                            f"shipments={rd['shipments']} lots={rd['lots']}")
                for why in r["reasons"]:
                    st.markdown(f"    - {why}")
            for g in v["incidents"]:
                st.markdown(f"**Grounded {g['kind']}** — " + "; ".join(g["checks"]))
            for e in v["escalations"]:
                st.markdown(f"**Escalation reason:** {e}")

# =============================================================================== ontology
with tab_onto:
    if onto:
        dot = ['digraph O { rankdir=LR; bgcolor="transparent"; nodesep=0.4; ranksep=0.7; node [shape=box, style="rounded,filled", '
               'color="#b8c2cc", fontname=Helvetica, margin="0.16,0.09"]; edge [color="#7b8794", fontname=Helvetica, fontsize=9];']
        for cls in onto.get("classes", {}):
            dot.append(f'"{cls}" [fillcolor="{CLASS_COLOR.get(cls, "#eee")}"];')
        for a, r, b in onto["relations"]:
            style = ", style=dashed, color=\"#c82132\", fontcolor=\"#c82132\"" if r in onto.get("inferred", {}) else ""
            dot.append(f'"{a}" -> "{b}" [label="{r}"{style}];')
        dot.append("}")
        st.graphviz_chart("\n".join(dot), **STRETCH)
        st.caption("Dashed red = inferred relation. " + "; ".join(f"{k_}: {v_}" for k_, v_ in onto.get("inferred", {}).items()))
        s = onto.get("stats", {})
        st.markdown(f"**{s.get('nodes'):,} nodes · {s.get('edges'):,} edges**")
        c1, c2 = st.columns(2)
        c1.dataframe(pd.DataFrame(s.get("nodes_by_class", {}).items(), columns=["class", "nodes"]), hide_index=True, **STRETCH)
        c2.dataframe(pd.DataFrame(s.get("edges_by_relation", {}).items(), columns=["relation", "edges"]), hide_index=True, **STRETCH)

# =============================================================================== audit log
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
        st.dataframe(df, hide_index=True, height=560, **STRETCH)
        st.caption(f"{len(df)} rows from {run}/action_log.jsonl — the file submitted for replay.")
