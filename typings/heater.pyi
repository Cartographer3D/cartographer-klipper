from typing import TypedDict, final

class _Status(TypedDict):
    temperature: float
    target: float
    power: float

@final
class Heater:
    pass
    def get_status(self, eventtime: float) -> _Status:
        pass
