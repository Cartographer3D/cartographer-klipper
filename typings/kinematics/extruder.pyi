from typing import final
from heater import Heater

@final
class Extruder:
    def get_name(self) -> str:
        pass
    def get_heater(self) -> Heater:
        pass
