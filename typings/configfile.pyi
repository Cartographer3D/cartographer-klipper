import configparser
from typing import final, overload

from klippy import Printer

error = configparser.Error

@final
class sentinel:
    pass

@final
class ConfigWrapper:
    error = configparser.Error
    printer: Printer
    def get_printer(self) -> Printer:
        pass
    def get_name(self) -> str:
        pass
    def getsection(self, section: str) -> ConfigWrapper:
        pass
    def has_section(self, section: str) -> bool:
        pass
    def get_prefix_sections(self, prefix: str) -> list[ConfigWrapper]:
        pass
    def deprecate(self, option: str, value: str | None = None) -> None:
        pass

    @overload
    def get(
        self,
        option: str,
        default: str | type[sentinel] = sentinel,
        note_valid: bool = True,
    ) -> str:
        pass
    @overload
    def get(
        self,
        option: str,
        default: None,
        note_valid: bool = True,
    ) -> str | None:
        pass

    @overload
    def getint(
        self,
        option: str,
        default: int | type[sentinel] = sentinel,
        minval: int | None = None,
        maxval: int | None = None,
        note_valid: bool = True,
    ) -> int:
        pass
    @overload
    def getint(
        self,
        option: str,
        default: None,
        minval: int | None = None,
        maxval: int | None = None,
        note_valid: bool = True,
    ) -> int | None:
        pass

    @overload
    def getfloat(
        self,
        option: str,
        default: float | type[sentinel] = sentinel,
        minval: float | None = None,
        maxval: float | None = None,
        above: float | None = None,
        below: float | None = None,
        note_valid: bool = True,
    ) -> float:
        pass
    @overload
    def getfloat(
        self,
        option: str,
        default: None,
        minval: float | None = None,
        maxval: float | None = None,
        above: float | None = None,
        below: float | None = None,
        note_valid: bool = True,
    ) -> float | None:
        pass

    @overload
    def getboolean(
        self,
        option: str,
        default: bool | type[sentinel] = sentinel,
        note_valid: bool = True,
    ) -> bool:
        pass
    @overload
    def getboolean(
        self,
        option: str,
        default: None,
        note_valid: bool = True,
    ) -> bool | None:
        pass

    @overload
    def getchoice(
        self,
        option: str,
        choices: dict[str, str],
        default: str | type[sentinel] = sentinel,
        note_valid: bool = True,
    ) -> str:
        pass
    @overload
    def getchoice(
        self,
        option: str,
        choices: dict[str, str],
        default: str | None,
        note_valid: bool = True,
    ) -> str | None:
        pass

    @overload
    def getintlist(
        self,
        option: str,
        default: list[int] | type[sentinel] = sentinel,
        sep: str = ",",
        count: int | None = None,
        note_valid: bool = True,
    ) -> list[int]:
        pass

    @overload
    def getintlist(
        self,
        option: str,
        default: None,
        sep: str = ",",
        count: int | None = None,
        note_valid: bool = True,
    ) -> list[int] | None:
        pass

    @overload
    def getfloatlist(
        self,
        option: str,
        default: list[float] | type[sentinel] = sentinel,
        sep: str = ",",
        count: int | None = None,
        note_valid: bool = True,
    ) -> list[float]:
        pass
    @overload
    def getfloatlist(
        self,
        option: str,
        default: None,
        sep: str = ",",
        count: int | None = None,
        note_valid: bool = True,
    ) -> list[float] | None:
        pass

@final
class PrinterConfig:
    def get_printer(self) -> Printer:
        pass
    def deprecate(self, option: str, value: str | None = None) -> None:
        pass
    def set(self, section: str, option: str, value: object) -> None:
        pass
    def remove_section(self, section: str) -> None:
        pass
