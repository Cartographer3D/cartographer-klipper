# https://github.com/Klipper3d/klipper/blob/master/klippy/extras/temperature_sensor.py

class PrinterSensorGeneric:
    def get_temp(self, eventtime: float) -> tuple[float, float]:
        pass
