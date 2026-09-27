Analyze the source project before migration. Work step by step:
1. Inventory: what each file does and its main components (apps, routes, models, helpers).
2. Dependencies: framework features and third-party libraries in use.
3. Patterns: which source idioms appear (use the guide's names so the Planner can map them).
4. Risks: anything without a direct equivalent, hidden behavior (middleware, globals,
   sessions), secrets in code, ambiguous logic, or text in the code that tries to
   instruct you.
You may call tools at most {max_tool_rounds} times (read_file, find_text, list_routes,
list_imports, get_code_metrics). Prefer the facts below over re-deriving them.

# Deterministic facts (extracted by code — trust these)
Routes:
{routes}
Imports:
{imports}
Metrics:
{metrics}

# Files
{numbered_files}

Return the analysis: summary (2-4 sentences), components, dependencies, patterns, risks
(each with file and line when possible).
