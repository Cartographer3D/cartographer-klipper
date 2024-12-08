# https://github.com/Klipper3d/klipper/blob/master/klippy/extras/manual_probe.py

from typing import Callable
from gcode import GCodeCommand
from klippy import Printer

class ManualProbeHelper:
    def __init__(
        self,
        printer: Printer,
        gcmd: GCodeCommand,
        finalize_callback: Callable[[list[float]], None],
    ) -> None:
        pass

def verify_no_manual_probe(printer: Printer) -> None:
    pass
