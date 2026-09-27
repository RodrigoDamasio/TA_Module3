from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from models import Todo, TodoStore

app = FastAPI()
store = TodoStore()


class TodoIn(BaseModel):
    title: str


class TodoUpdate(BaseModel):
    title: str | None = None
    done: bool | None = None


@app.get("/todos")
def list_todos(done: str | None = None) -> list[dict]:
    todos = store.all()
    if done is not None:
        todos = [t for t in todos if t.done == (done == "true")]
    return [t.to_dict() for t in todos]


@app.post("/todos", status_code=201)
def create_todo(body: TodoIn) -> dict:
    return store.add(Todo(title=body.title)).to_dict()


@app.get("/todos/{todo_id}")
def get_todo(todo_id: int) -> dict:
    todo = store.get(todo_id)
    if todo is None:
        raise HTTPException(status_code=404)
    return todo.to_dict()


@app.put("/todos/{todo_id}")
def update_todo(todo_id: int, body: TodoUpdate) -> dict:
    todo = store.get(todo_id)
    if todo is None:
        raise HTTPException(status_code=404)
    if body.title is not None:
        todo.title = body.title
    if body.done is not None:
        todo.done = body.done
    return todo.to_dict()


@app.delete("/todos/{todo_id}", status_code=204)
def delete_todo(todo_id: int) -> Response:
    if not store.remove(todo_id):
        raise HTTPException(status_code=404)
    return Response(status_code=204)
