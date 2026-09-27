# Evaluation report — `gemini-3.5-flash-lite`, prompt v2, set `full`

Deterministic scoring (BACKEND_PLAN §12.3); the generated code is never executed.

- Jobs completed: **4/4** ✅
- Migrated files parse + compile: **4/4** ✅
- Routes preserved (web pairs): **3/3** ✅
- Source-framework imports / Py2 idioms gone: **4/4** ✅
- Undefined names (F821): **0** ✅
- LLM calls per job (avg, incl. cached): **5.8** (target ≤ 12) ✅
- Real LLM calls in the last run: **0** (cache hits cost 0)

| Case | Status | Success | Compiles | Routes | Framework gone | F821 | Confidence | Steps | Real calls (cached) | Tokens in / out |
|---|---|---|---|---|---|---|---|---|---|---|
| flask_todo | ran | ✅ | ✅ | 5/5 routes | ✅ | 0 | 10 | 2 | 0 (6) | 13135 / 2228 |
| express_users | ran | ✅ | ✅ | 4/4 routes | ✅ | 0 | 10 | 2 | 0 (6) | 12487 / 1929 |
| django_articles | ran | ✅ | ✅ | 3/3 routes | ✅ | 0 | 10 | 1 | 0 (5) | 8555 / 1644 |
| py2_report | ran | ✅ | ✅ | n/a | ✅ | 0 | 10 | 2 | 0 (6) | 9337 / 1689 |
