# https://github.com/Klipper3d/klipper/blob/master/klippy/gcode.py
from typing import Callable, NamedTuple, overload

class CommandError(Exception):
    pass

class GCodeCommand:
    error: type[CommandError]
    class sentinel:
        pass

    def respond_raw(self, msg: str) -> None:
        pass
    def respond_info(self, msg: str, log: bool = True) -> None:
        pass
    def get_command_parameters(self) -> dict[str, str]:
        pass

    @overload
    def get(
        self,
        name: str,
        default: str | type[sentinel] = sentinel,
    ) -> str:
        pass
    @overload
    def get(
        self,
        name: str,
        default: None,
    ) -> str | None:
        pass

    @overload
    def get_int(
        self,
        name: str,
        default: int | type[sentinel] = sentinel,
        minval: int | None = None,
        maxval: int | None = None,
    ) -> int:
        pass
    @overload
    def get_int(
        self,
        name: str,
        default: None,
        minval: int | None = None,
        maxval: int | None = None,
    ) -> int | None:
        pass

    @overload
    def get_float(
        self,
        name: str,
        default: float | type[sentinel] = sentinel,
        minval: float | None = None,
        maxval: float | None = None,
        above: float | None = None,
        below: float | None = None,
    ) -> float:
        pass
    @overload
    def get_float(
        self,
        name: str,
        default: None,
        minval: float | None = None,
        maxval: float | None = None,
        above: float | None = None,
        below: float | None = None,
    ) -> float | None:
        pass

class Coord(NamedTuple):
    x: float
    y: float
    z: float
    e: float

class GCodeDispatch:
    error: type[CommandError]
    Coord: type[Coord]

    def respond_raw(self, msg: str) -> None:
        pass
    def respond_info(self, msg: str, log: bool = True) -> None:
        pass

    def run_script_from_command(self, script: str) -> None:
        pass

    @overload
    def register_command(
        self,
        cmd: str,
        func: Callable[[GCodeCommand], None],
        when_not_ready: bool = False,
        desc: str | None = None,
    ) -> None:
        pass
    @overload
    def register_command(
        self,
        cmd: str,
        func: None,
        when_not_ready: bool = False,
        desc: str | None = None,
    ) -> Callable[[GCodeCommand], None]:
        pass

    def create_gcode_command(
        self,
        command: str,
        commandline: str,
        params: dict[str, str],
    ) -> GCodeCommand:
        pass
