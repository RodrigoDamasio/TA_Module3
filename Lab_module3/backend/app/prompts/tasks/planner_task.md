Create the migration plan.

# Source files
{source_files}

# Routes that must exist after the migration
{routes}

# Analysis
{analysis}

# Lessons from past {pair} migrations (episodic memory)
{episodes}

# Reviewer feedback on the previous plan (only when replanning)
{feedback}

# Rules
- At most {max_steps} steps. Each step is independently verifiable: it produces or updates
  specific target files that must parse and compile on their own.
- depends_on lists only earlier step ids. Steps that do not depend on each other may run
  in parallel — therefore two independent steps must NEVER write the same target file.
- Every source file appears in at least one step's source_files; every route above
  appears in some step's description.
- complexity: low (mechanical renames), medium (API shape changes), high (behavior with
  no direct equivalent).
- target_files are Python files with explicit names (e.g. "main.py", "routers/users.py").

# Example (format only — {example_pair})
{plan_example}

Before answering, check: ids unique · no cycles · no shared target file between
independent steps · all files and routes covered · at most {max_steps} steps.
