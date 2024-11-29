from typing import Callable, Literal, TypeVar, final, overload

import configfile
import gcode
from configfile import ConfigWrapper, PrinterConfig, sentinel
from mcu import MCU
from reactor import Reactor
from toolhead import ToolHead

from scanner import Scanner

T = TypeVar("T")

@final
class Printer:
    config_error = configfile.error
    command_error = gcode.CommandError
    def add_object(self, name: str, obj: object) -> None:
        pass
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
    def lookup_object(self, name: Literal["configfile"]) -> PrinterConfig:
        pass
    @overload
    def lookup_object(self, name: Literal["mcu"]) -> MCU:
        pass
    @overload
    def lookup_object(self, name: Literal["scanner"]) -> Scanner:
        pass
    @overload
    def lookup_object(self, name: Literal["toolhead"]) -> ToolHead:
        pass
    @overload
    def lookup_object(self, name: str, default: T | type[sentinel] = sentinel) -> T:
        pass
