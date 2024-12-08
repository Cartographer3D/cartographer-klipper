from typing import TypedDict
from gcode import Coord

class _Status(TypedDict):
    speed_factor: float
    speed: float
    extrude_factor: float
    absolute_coordinates: bool
    absolute_extrude: bool
    homing_origin: Coord
    position: Coord
    gcode_position: Coord

class GCodeMove:
    coord: type[Coord]
    def get_status(self) -> _Status:
        pass
