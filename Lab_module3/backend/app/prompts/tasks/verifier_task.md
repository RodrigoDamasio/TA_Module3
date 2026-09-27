Verify the migration.

# Automatic checks (already run by code — authoritative)
{checks}

# Plan as executed
{plan}

# Source files
{numbered_sources}

# Migrated files
{numbered_migrated}

# Checklist (answer each in your reasoning)
1. Is every source behavior present in the migrated code (routes, inputs, outputs,
   status codes, error cases)?
2. Are there bugs introduced by the migration (wrong types, missing awaits, lost
   validation, changed defaults)?
3. Are target-framework idioms used correctly?
4. What edge cases are not handled?

Rate confidence 1-10 and give a verdict (pass/fail). If confidence < 7, list concrete
issues (severity, file, line, message). Do not repeat failed automatic checks as new
issues — reference them.
