# https://github.com/Klipper3d/klipper/blob/master/klippy/toolhead.py
from typing import Sequence, TypedDict

import gcode
from kinematics.extruder import Extruder
from kinematics.none import NoneKinematics

class _KinematicsStatus(TypedDict):
    homed_axes: str
    axis_minimum: float
    axis_maximum: float

class _Status(_KinematicsStatus):
    print_time: float
    stalls: int
    estimated_print_time: float
    extruder: str
    position: gcode.Coord
    max_velocity: float
    max_accel: float
    minimum_cruise_ratio: float
    square_corner_velocity: float
    pass

type _Pos = list[float]

class ToolHead:
    Coord: type[gcode.Coord]
    def get_kinematics(self) -> NoneKinematics:
        pass
    def get_extruder(self) -> Extruder:
        pass
    def get_status(self, eventtime: float) -> _Status:
        pass
    def get_position(self) -> _Pos:
        pass
    def set_position(self, newpos: _Pos, homing_axes: Sequence[int | str] = ()) -> None:
        pass
    def move(self, newpos: _Pos, speed: float) -> None:
        pass
    def wait_moves(self) -> None:
        pass
    def dwell(self, delay: float) -> None:
        pass
    def flush_step_generation(self) -> None:
        pass
    def manual_move(self, coord: _Pos | list[float | None], speed: float) -> None:
        pass
    def get_trapq(self) -> str:
        pass
    def get_last_move_time(self) -> float:
        pass
