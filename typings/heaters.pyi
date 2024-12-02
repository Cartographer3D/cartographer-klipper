# https://github.com/Klipper3d/klipper/blob/master/klippy/extras/heaters.py
from typing import TypedDict

class _Status(TypedDict):
    temperature: float
    target: float
    power: float

class Heater:
    pass
    def get_status(self, eventtime: float) -> _Status:
        pass

class PrinterHeaters:
    available_sensors: list[str]
