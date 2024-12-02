# https://github.com/Klipper3d/klipper/blob/master/klippy/klippy.py
from typing import Callable, Literal, TypeVar, overload

import configfile
from bed_mesh import BedMesh
from configfile import ConfigWrapper, PrinterConfig, sentinel
from gcode import CommandError, GCodeDispatch
from gcode_move import GCodeMove
from heaters import PrinterHeaters
from homing import PrinterHoming
from mcu import MCU
from pins import PrinterPins
from reactor import Reactor
from toolhead import ToolHead
from webhooks import WebHooks
from axis_twist_compensation import AxisTwistCompensation

from scanner import Scanner

T = TypeVar("T")

class Printer:
    config_error: type[configfile.error]
    command_error: type[CommandError]
    def add_object(self, name: str, obj: object) -> None:
        pass
    @overload
    def load_object(
        self,
        config: ConfigWrapper,
        section: Literal["bed_mesh"],
    ) -> BedMesh:
        pass
    @overload
    def load_object(
        self,
        config: ConfigWrapper,
        section: Literal["heaters"],
    ) -> PrinterHeaters:
        pass
    @overload
    def load_object(
        self,
        config: ConfigWrapper,
        section: str,
        default: T | type[sentinel] = sentinel,
    ) -> T:
        pass

    def is_shutdown(self) -> bool:
        pass
    def invoke_shutdown(self, msg: str) -> None:
        pass
    def get_reactor(self) -> Reactor:
        pass
    def register_event_handler(self, event: str, callback: Callable[..., None]) -> None:
        pass

    @overload
    def lookup_object(
        self, name: Literal["axis_twist_compensation"], default: None
    ) -> AxisTwistCompensation | None:
        pass
    @overload
    def lookup_object(self, name: Literal["configfile"]) -> PrinterConfig:
        pass
    @overload
    def lookup_object(self, name: Literal["gcode"]) -> GCodeDispatch:
        pass
    @overload
    def lookup_object(self, name: Literal["gcode_move"]) -> GCodeMove:
        pass
    @overload
    def lookup_object(self, name: Literal["homing"]) -> PrinterHoming:
        pass
    @overload
    def lookup_object(self, name: Literal["mcu"]) -> MCU:
        pass
    @overload
    def lookup_object(self, name: Literal["pins"]) -> PrinterPins:
        pass
    @overload
    def lookup_object(self, name: Literal["scanner"]) -> Scanner:
        pass
    @overload
    def lookup_object(self, name: Literal["toolhead"]) -> ToolHead:
        pass
    @overload
    def lookup_object(self, name: Literal["webhooks"]) -> WebHooks:
        pass
    @overload
    def lookup_object(self, name: str, default: T | type[sentinel] = sentinel) -> T:
        pass
