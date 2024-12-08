from typing import TypedDict

class _Object(TypedDict):
    name: str
    center: list[float]
    polygon: list[list[float]]

class _Status(TypedDict):
    objects: list[_Object]
    excluded_objects: list[_Object]
    current_object: _Object | None

class ExcludeObject:
    def get_status(self) -> _Status:
        pass
