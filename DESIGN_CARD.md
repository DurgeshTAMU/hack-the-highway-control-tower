# Design card — "Ground, Compile, Prove" control tower

**Idea in one line.** The LLM reads; the knowledge graph decides which reading is real; the handbook is
compiled into an exact plan; the plan is proven on a digital twin before a single live call is made.

## Architecture

```
event text ─► Coordinator ─┬─ LLM reader (local SLM, JSON-constrained) ─┐
                           └─ rule reader (lexical, free)               ├─► readings
                                                                         ▼
                          Grounder: expand each reading into hypotheses (ids × date conventions),
                          keep only those that bind to real records in the KG
                                     │ unique binding → act   │ none / conflicting → escalate   │ no ops entity → noise
                                     ▼
          ┌──────────────── policy compiler (one shared slot + loaner ledger per event) ────────────────┐
          │ SupplyChainPlanner: mes.get_schedule / reschedule / transfer (earliest feasible slot)       │
          │ DealerNetwork:      dealer.notify (one per dealer, only its orders) / dealer.stop_sale       │
          │ CustomerCareQuality: crm.loaner_availability / assign_loaner (tier→date→id) / notify_customer │
          │                      / quality.hold_lot                                                      │
          └──────────────────────────────────────────────────────────────────────────────────────────────┘
                                     ▼
          Prove: dry-run on the provided enterprise model (local twin) + 13 invariants checked against an
          independent table-only oracle → only then execute live; failures → re-read + retry once → escalate
```

**Ontology.** 11 classes (Supplier, Part, Model, Plant, Shipment, Lot, ProductionOrder, CustomerOrder,
Customer, Dealer, Vehicle), 17 relations, one inferred (`Lot -INSTALLED_IN-> ProductionOrder` via plant,
build window and BOM). ~17k nodes / 28k edges. Every impact set is a traversal that records the edges it
walked; those edges are the cited graph path.

## LLM versus code

| Concern | Who | Why |
|---|---|---|
| Split a digest, classify, pick out names and date phrases | LLM (+ rule reader as second opinion) | language |
| Names → ids, phrases → dates | code (aliases.csv + table names; calendar) | SLMs mis-do calendar math and invent ids |
| Which reading is real | knowledge graph | existence + consistency is checkable |
| Who is affected, where orders go, who gets a loaner | code (policy-as-code) | exact rules, scored by exact replay |
| Dealer / owner message text | templates | cheaper, deterministic; LLM optional |

**Data-grounded date reading.** "Next Friday" on a Monday is genuinely ambiguous (Mar 12 or Mar 19). The
grounder tries both conventions per message and keeps the one under which *every* incident binds. In the
morning digest, "next Monday → next Friday" only has a real shipment (SH-0190, ETA Mar 15) if "next" means
next week; the same convention then fixes the outage window to Mar 19–22 (6 affected orders, not 21).

## Guardrails

- No operational entity → noise, zero calls. Hedged wording → escalate with what is missing, zero writes.
- Supplier/part/plant/date must agree with a record (e.g. "Quanta chip at Jackson" is refused: Jackson's chip lots are Kestrel's).
- A quality window must line up with lot boundaries; a new ETA must be after the original.
- Two readers that bind to different records → conflict → escalate, no writes.
- Plan is withheld unless the dry run passes every invariant: exactly the affected orders moved; no move into a disrupted
  day; same-plant moves at/after restart; transfers only when the home plant is full; capacity never exceeded; one notice
  per dealer listing exactly its affected orders; loaners equal the policy-priority winners per pool; lots/stop-sale/owners
  exact; ≥ 3 kinds of action.
- Live failure on a move → re-read the schedule, take the next free slot once; otherwise escalate. Transport errors retry
  with backoff; tool errors are never blindly retried.

## Evaluation (this package, 15 events)

| | Result |
|---|---|
| Categories | 1 compound (outage + delay), 3 delays, 3 outages, 3 quality holds, 3 noise, 2 unconfirmed |
| Live run | 879 calls, **0 failed**, 2 escalations (rumors only), 0 writes on noise/rumors |
| Replay of `action_log.jsonl` on a fresh world | 15/15 events pass all invariants |
| Tests | 27 passing, incl. unseen paraphrases, the organisers' explainer phrasings, open-start outages, unnumbered compounds, guardrail refusals, failed-call recovery, LLM contract, reader conflict |
| Runtime | ~15 s end-to-end on a laptop CPU (KG build ~4 s) |

**Model cited:** `qwen2.5:1.5b` (Qwen2.5 1.5B Instruct, ~1 GB, Q4) served locally by Ollama on a MacBook (Apple silicon, CPU/GPU
shared memory, no cloud). The final run (`runs/final`) made 15 LLM calls, 6,423 tokens, 26 s of model time, 27 s end to end,
0 failed tool calls. The rule reader runs alongside as a second opinion. The 1.5B model sometimes misclassifies a sentence
(e.g. calls a supplier delay a quality hold); the grounder overrules a failed LLM reading when another reader already grounded
that sentence, so such slips cause no extra action or escalation. Categories, bindings and all 879 logged calls are the same
with and without the LLM.

## Assumptions we made (the handbook is silent)

1. Transfer day: the order's original date (`CT_TRANSFER_ANCHOR=original_date`; alternatives: `disruption_start`,
   `today`, `restart`). The receiving plant builds on the day already promised, so customers lose no time and nothing is
   built earlier than planned. All options pass the 13 checks; only the build date of 5 orders (E-09, E-11) changes
   (e.g. E-09: Mar 31 instead of Mar 29).
2. When slots are scarce, affected orders are placed in original (date, id) order.
3. "next <weekday>" defaults to that day next week when the data cannot tell (E-04); the alternative is logged.
4. One loaner per customer even if they have several affected orders.

## What we would improve

LLM-written dealer messages behind a validator; a confidence score that routes borderline reads to a human
before execution; learning the date convention per source; graph DB export (Neo4j) for ad-hoc queries.
