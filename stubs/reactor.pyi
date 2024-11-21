from typing import Callable, final

@final
class ReactorTimer:
    pass

@final
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
