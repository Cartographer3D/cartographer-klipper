from typing_extensions import deprecated

class AxisTwistCompensation:
    @deprecated("private method")
    def _update_z_compensation_value(self, pos: list[float]) -> None:
        pass

    @deprecated("removed from klipper")
    def get_z_compensation_value(self, pos: list[float]) -> float:
        pass
