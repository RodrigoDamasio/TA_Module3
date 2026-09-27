Execute step {step_id} of {step_count}: {step_title}
{step_description}

# Project context (analysis summary)
{analysis}

# Routes of the whole project (all must exist once every step is done)
{routes}

# Files this step reads (source)
{numbered_sources}

# Current content of the files this step writes (from earlier steps; empty if new)
{current_targets}

# Rules
- Write ONLY these files: {target_files}. Return each one complete (full content, not a diff).
- Keep every route your source files handle, with the same method and path.
- Use the guide's target idioms; import only what you use; no source-framework imports.
- If something cannot be migrated faithfully, keep the closest behavior and explain it in notes.
{retry_block}
