import configparser
from typing import Callable, TypeVar, final

from configfile import ConfigWrapper, sentinel
import configfile
import gcode
from reactor import Reactor

T = TypeVar("T")

@final
class Printer:
    config_error = configfile.error
    command_error = gcode.CommandError
    def add_object(self, name: str, obj: object) -> None:
        pass
    def lookup_object(self, name: str, default: T | type[sentinel] = sentinel) -> T:
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
    def register_event_handler(self, event: str, callback: Callable[[], None]) -> None:
        pass
