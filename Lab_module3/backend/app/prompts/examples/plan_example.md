{"steps": [
  {"id": 1, "title": "Create app and models", "description": "Create main.py with FastAPI() and Pydantic models for the request bodies.", "depends_on": [], "complexity": "low", "source_files": ["app.py"], "target_files": ["main.py"]},
  {"id": 2, "title": "Migrate item routes", "description": "Move GET /items and POST /items to routers/items.py with an APIRouter.", "depends_on": [], "complexity": "medium", "source_files": ["app.py"], "target_files": ["routers/items.py"]},
  {"id": 3, "title": "Wire routers", "description": "Include routers/items.py in main.py; keep GET /health in main.py.", "depends_on": [1, 2], "complexity": "low", "source_files": ["app.py"], "target_files": ["main.py"]}
]}
