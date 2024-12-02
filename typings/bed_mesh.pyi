# Types for https://github.com/Klipper3d/klipper/blob/master/klippy/extras/bed_mesh.py
from typing import Literal, TypedDict

class BedMeshError(Exception):
    pass

class _Params(TypedDict):
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    x_count: int
    y_count: int
    mesh_x_pps: int
    mesh_y_pps: int
    algo: Literal["lagrange", "bicubic", "direct"]
    tension: float

class ZMesh:
    def __init__(self, params: _Params, name: str | None) -> None:
        pass
    def build_mesh(self, z_matrix: list[list[float]]) -> None:
        pass

class BedMeshCalibrate:
    mesh_config: _Params

class BedMesh:
    bmc: BedMeshCalibrate
    def set_mesh(self, mesh: ZMesh) -> None:
        pass
    def save_profile(self, prof_name: str) -> None:
        pass
