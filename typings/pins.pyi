# https://github.com/Klipper3d/klipper/blob/master/klippy/pins.py

class error(Exception):
    pass

class PrinterPins:
    error: type[error]

    # TODO: Can we require a type / interface for `chip`?
    def register_chip(self, chip_name: str, chip: object) -> None:
        pass
