"""Todo API (Flask)."""
from flask import Flask, abort, jsonify, request

from models import Todo, TodoStore

app = Flask(__name__)
store = TodoStore()


@app.route("/todos", methods=["GET"])
def list_todos():
    done = request.args.get("done")
    todos = store.all()
    if done is not None:
        todos = [t for t in todos if t.done == (done == "true")]
    return jsonify([t.to_dict() for t in todos])


@app.route("/todos", methods=["POST"])
def create_todo():
    data = request.get_json()
    if not data or not data.get("title"):
        abort(400)
    todo = store.add(Todo(title=data["title"]))
    return jsonify(todo.to_dict()), 201


@app.route("/todos/<int:todo_id>", methods=["GET"])
def get_todo(todo_id):
    todo = store.get(todo_id)
    if todo is None:
        abort(404)
    return jsonify(todo.to_dict())


@app.route("/todos/<int:todo_id>", methods=["PUT"])
def update_todo(todo_id):
    todo = store.get(todo_id)
    if todo is None:
        abort(404)
    data = request.get_json() or {}
    todo.title = data.get("title", todo.title)
    todo.done = bool(data.get("done", todo.done))
    return jsonify(todo.to_dict())


@app.route("/todos/<int:todo_id>", methods=["DELETE"])
def delete_todo(todo_id):
    if not store.remove(todo_id):
        abort(404)
    return "", 204


if __name__ == "__main__":
    app.run(debug=True)
