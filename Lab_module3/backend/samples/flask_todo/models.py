"""In-memory storage for todos."""
from dataclasses import dataclass, asdict


@dataclass
class Todo:
    title: str
    done: bool = False
    id: int = 0

    def to_dict(self):
        return asdict(self)


class TodoStore:
    def __init__(self):
        self._items = {}
        self._next_id = 1

    def all(self):
        return list(self._items.values())

    def get(self, todo_id):
        return self._items.get(todo_id)

    def add(self, todo):
        todo.id = self._next_id
        self._items[todo.id] = todo
        self._next_id += 1
        return todo

    def remove(self, todo_id):
        return self._items.pop(todo_id, None) is not None
