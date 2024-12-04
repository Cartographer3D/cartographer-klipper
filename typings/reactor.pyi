# https://github.com/Klipper3d/klipper/blob/master/klippy/reactor.py

from typing import Callable

class ReactorTimer:
    pass

_NOW: float
_NEVER: float

class ReactorCompletion:
    class sentinel:
        pass

    def test(self) -> bool:
        pass
    def complete(self, result: object) -> None:
        pass
    def wait(self, waketime: float = _NEVER, waketime_result: object = None) -> object:
        pass

class Reactor:
    NOW: float
    NEVER: float
    monotonic: Callable[[], float]
    def register_timer(
        self, callback: Callable[[float], float], waketime: float = NEVER
    ) -> ReactorTimer:
        pass
    def update_timer(self, timer_handler: ReactorTimer, waketime: float) -> None:
        pass
    def register_async_callback(
        self, callback: Callable[[float], None], waketime: float = NOW
    ) -> None:
        pass
    def pause(self, waketime: float) -> float:
        pass
    def completion(self) -> ReactorCompletion:
        pass
