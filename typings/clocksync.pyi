# https://github.com/Klipper3d/klipper/blob/master/klippy/clocksync.py
from reactor import Reactor

class ClockSync:
    def print_time_to_clock(self, print_time: float) -> int:
        pass
    def clock_to_print_time(self, clock: int) -> float:
        pass
    def clock32_to_clock64(self, clock32: int) -> int:
        pass

class SecondarySync(ClockSync):
    def __init__(self, reactor: Reactor, main_sync: ClockSync) -> None:
        pass
