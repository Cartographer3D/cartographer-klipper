# https://github.com/Klipper3d/klipper/blob/master/klippy/webhooks.py#L303
from collections.abc import Callable
from typing import Any, overload
import gcode

class WebRequestError(gcode.CommandError):
    def __init__(self, message: str) -> None:
        pass

class ClientConnection:
    pass

class Sentinel:
    pass

class WebRequest:
    error: type[WebRequestError]

    def send(self, data: object) -> None:
        pass

    def get_client_connection(self) -> ClientConnection:
        pass

    @overload
    def get_dict(
        self, item: str, default: dict[str, Any] | type[Sentinel] = Sentinel
    ) -> dict[str, Any]:
        pass
    @overload
    def get_dict(self, item: str, default: None) -> dict[str, Any] | None:
        pass

class WebHooks:
    def register_endpoint(
        self, path: str, callback: Callable[[WebRequest], None]
    ) -> None:
        pass
