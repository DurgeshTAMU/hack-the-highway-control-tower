# Control tower — how to run

Requirements: Python 3.11, `networkx`, `streamlit`, `altair`, `pandas`, `pytest`. No cloud, no GPU.

```bash
# 1. company systems (fresh world; refuses to overwrite an existing log)
python enterprise_server.py --data data --events data/events.json --out runs/run1 --port 8000

# 2. agents (second terminal)
python -m control_tower.run --server http://127.0.0.1:8000 --out runs/run1

# 3. check the submission exactly as a judge would: replay the log on a fresh world
python -m control_tower.replay runs/run1

# 4. control-tower view
streamlit run control_tower/app.py

# offline (no server): execute on the local twin
python -m control_tower.run --twin --out runs/offline

# tests
python -m pytest tests -q
```

Optional local LLM reader (the rule reader stays on as a second opinion):

```bash
ollama pull qwen2.5:7b-instruct
CT_LLM=ollama CT_LLM_MODEL=qwen2.5:7b-instruct python -m control_tower.run --server http://127.0.0.1:8000 --out runs/run2
# any OpenAI-compatible local server: CT_LLM=openai CT_LLM_URL=http://127.0.0.1:8080/v1 CT_LLM_MODEL=<name>
```

## Outputs in `runs/<run>/`

| File | What |
|---|---|
| `action_log.jsonl` | written by the server; the file to submit |
| `traces/E-xx.json` | per event: both readings, grounding hypotheses and verdict, graph path + evidence edges, plan, dry-run proof, executed calls, audit trail, summary |
| `ontology/ontology.json`, `ontology.mmd`, `knowledge_graph.graphml` | ontology export and the full graph |
| `run_summary.json` | per-event stats, model used, machine info |

## Code map (`control_tower/`)

| Module | Role |
|---|---|
| `kg.py` | ontology + knowledge graph (networkx), including the inferred `Lot -INSTALLED_IN-> ProductionOrder` |
| `nlp.py` | date phrases → candidate dates; names → ids; rule reader |
| `llm.py` | LLM reader (Ollama / OpenAI-compatible, JSON schema); returns surface strings only |
| `ground.py` | hypothesis expansion and grounding against the KG; noise / escalate / act decision |
| `impact.py` | traversals that compute affected sets and record the graph path |
| `agents.py` | Coordinator + SupplyChainPlanner + DealerNetwork + CustomerCareQuality |
| `verify.py` | table-only oracle and the 13 invariants |
| `pipeline.py` | understand → ground → compile → prove → execute → explain |
| `clients.py` | HTTP client and the in-process twin (the provided `enterprise.py`, unmodified) |
| `replay.py` | judge-style replay of an action log |
| `app.py` | Streamlit control-tower view |
