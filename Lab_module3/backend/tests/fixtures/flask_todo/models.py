from dataclasses import asdict, dataclass


@dataclass
class Todo:
    title: str
    done: bool = False
    id: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class TodoStore:
    def __init__(self) -> None:
        self._items: dict[int, Todo] = {}
        self._next_id = 1

    def all(self) -> list[Todo]:
        return list(self._items.values())

    def get(self, todo_id: int) -> Todo | None:
        return self._items.get(todo_id)

    def add(self, todo: Todo) -> Todo:
        todo.id = self._next_id
        self._items[todo.id] = todo
        self._next_id += 1
        return todo

    def remove(self, todo_id: int) -> bool:
        return self._items.pop(todo_id, None) is not None
