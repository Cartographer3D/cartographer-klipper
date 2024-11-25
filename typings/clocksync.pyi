from typing import final
from reactor import Reactor

@final
class ClockSync:
    pass

@final
class SecondarySync:
    def __init__(self, reactor: Reactor, main_sync: ClockSync) -> None:
        pass
