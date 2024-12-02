from typing import final

@final
class PrinterSensorGeneric:
    def get_temp(self, eventtime: float) -> tuple[float, float]:
        pass
