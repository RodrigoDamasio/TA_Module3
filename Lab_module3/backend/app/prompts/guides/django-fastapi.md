| Django                                     | FastAPI                                        |
|--------------------------------------------|------------------------------------------------|
| urls.py path("articles/<int:pk>/", view)   | @app.get("/articles/{pk}") + pk: int           |
| def view(request): ...                     | def view(...): with typed parameters           |
| if request.method != "POST": 405           | use the matching decorator (@app.post)          |
| json.loads(request.body)                   | a Pydantic model parameter                     |
| JsonResponse(obj)                          | return obj                                     |
| JsonResponse(obj, status=201)              | status_code=201 on the decorator               |
| JsonResponse({"error": ...}, status=404)   | raise HTTPException(status_code=404, detail=...) |
| @csrf_exempt                               | remove (not needed for a JSON API)             |
| method not fixed by urls.py                | choose from the view: reads → GET, creates → POST |
