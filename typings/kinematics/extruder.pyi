from typing import final
from heaters import Heater

@final
class Extruder:
    def get_name(self) -> str:
        pass
    def get_heater(self) -> Heater:
        pass
