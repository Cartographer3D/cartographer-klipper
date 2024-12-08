# https://github.com/Klipper3d/klipper/blob/master/klippy/extras/homing.py

class PrinterHoming:
    def probing_move(
        self, mcu_probe: object, pos: list[float], speed: float
    ) -> list[float]:
        pass
