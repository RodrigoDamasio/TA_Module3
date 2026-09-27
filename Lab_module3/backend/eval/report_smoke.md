# Evaluation report — `gemini-3.5-flash-lite`, prompt v2, set `smoke`

Deterministic scoring (BACKEND_PLAN §12.3); the generated code is never executed.

- Jobs completed: **1/1** ✅
- Migrated files parse + compile: **1/1** ✅
- Routes preserved (web pairs): **1/1** ✅
- Source-framework imports / Py2 idioms gone: **1/1** ✅
- Undefined names (F821): **0** ✅
- LLM calls per job (avg, incl. cached): **6.0** (target ≤ 12) ✅
- Real LLM calls in the last run: **3** (cache hits cost 0)

| Case | Status | Success | Compiles | Routes | Framework gone | F821 | Confidence | Steps | Real calls (cached) | Tokens in / out |
|---|---|---|---|---|---|---|---|---|---|---|
| flask_todo | ran | ✅ | ✅ | 5/5 routes | ✅ | 0 | 10 | 2 | 3 (3) | 13135 / 2228 |
