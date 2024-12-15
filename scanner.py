# IDM, Cartographer 3D, and OpenBedScanner Script v3.0.0 w/ Temperature Compensation and Cartgorapher Survey
#
# To buy affordable bed scanners, check out https://cartographer3d.com
#
# Based on the outstanding work from the Beacon3D Team, with modifications made by the Cartographer and IDM team.
#
# Copyright (C) 2023-2024 Cartographer3D <cartographer3d.com>
# Copyright (C) 2020-2023 Matt Baker <baker.matt.j@gmail.com>
# Copyright (C) 2020-2023 Lasse Dalegaard <dalegaard@gmail.com>
# Copyright (C) 2023 Beacon <beacon3d.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import copy
import importlib
import logging
import math
import multiprocessing
import os
import queue
import random
import struct
import threading
import time
import traceback
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Optional, TypedDict, final

import chelper
import msgproto
import numpy as np
import pins
from clocksync import SecondarySync
from configfile import ConfigWrapper
from gcode import GCodeCommand
from klippy import Printer
from mcu import MCU, MCU_trsync
from stepper import MCU_stepper
from webhooks import WebRequest

from . import (
    bed_mesh,
    manual_probe,
    probe,
    temperature_sensor,
    thermistor,
)

DOCS_TOUCH_CALIBRATION = "https://docs.cartographer3d.com/cartographer-probe/installation-and-setup/installation/touch-based-calibration"
DOCS_SCAN_CALIBRATION = "https://docs.cartographer3d.com/cartographer-probe/installation-and-setup/installation/scan-based-calibration"

STREAM_BUFFER_LIMIT_DEFAULT = 100
STREAM_TIMEOUT = 2.0


THRESHOLD_MIN_LIMIT = 750
THRESHOLD_SCALING_FACTOR = 0.25
THRESHOLD_ROUNDING_BASE = 250
THRESHOLD_INCREMENT_MULTIPLIER = 5
THRESHOLD_STEP_MULTIPLIER = 10
# Require a qualified threshold to pass at 0.66 of the QUALIFY_SAMPLES
THRESHOLD_ACCEPTANCE_FACTOR = 0.66


class TriggerMethod(IntEnum):
    SCAN = 0
    TOUCH = 1


@dataclass
class ThresholdResults:
    max_value: float
    min_value: float
    range_value: float
    avg_value: float
    median: float
    sigma: float
    in_range: int
    early: int
    late: int
    nb_samples: int


def format_macro(macro: str) -> str:
    return f'<a class="command">{macro}</a>'


@final
class BedLeveling:
    def __init__(self, printer: Printer):
        self._printer = printer

    def get_bed_leveling_command(self) -> Optional[str]:
        qgl = self._printer.lookup_object("quad_gantry_level", None)
        if qgl is not None:
            return "QUAD_GANTRY_LEVEL"

        z_tilt = self._printer.lookup_object("z_tilt", None)
        if z_tilt is not None:
            return "Z_TILT_ADJUST"

    def requires_bed_leveling(self):
        curtime = self._printer.get_reactor().monotonic()

        qgl = self._printer.lookup_object("quad_gantry_level", None)
        if qgl is not None:
            return not qgl.get_status(curtime).get("applied", False)

        z_tilt = self._printer.lookup_object("z_tilt", None)
        if z_tilt is not None:
            return not z_tilt.get_status(curtime).get("applied", False)

        # We cannot do it automatically
        # TODO: Check the bed to see if it is within "tolerance",
        # if not, request that the user levels the bed.
        return False


@final
class Scanner:
    def __init__(self, config: ConfigWrapper):
        self.printer: Printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.bed_level = BedLeveling(self.printer)
        self.name = config.get_name()
        self.sensor = config.get("sensor")
        self.sensor_alt = config.get("sensor_alt", None)
        self.last_z_result = 0.0

        if not self.sensor and not self.sensor_alt:
            raise self.printer.command_error(
                "Please set at least one sensor type (sensor or sensor_alt) in printer.cfg"
            )

        self.speed = config.getfloat("speed", 5, above=0.0)
        self.lift_speed = config.getfloat("lift_speed", self.speed, above=0.0)
        self.backlash_comp = config.getfloat("backlash_comp", 0.5)

        temp_sensor_override = config.get("temp_sensor_override", None)
        if temp_sensor_override is not None:
            self.thermistor_override: Optional[
                temperature_sensor.PrinterSensorGeneric
            ] = config.printer.load_object(
                config, "temperature_sensor " + temp_sensor_override
            )
        else:
            self.thermistor_override = None

        self.model_temp_warning_disable = config.getint("model_temp_warning_disable", 0)
        self.probe_speed: float = config.getfloat("probe_speed", self.speed)

        if config.has_section("bed_mesh"):
            mesh_config = config.getsection("bed_mesh")
            zero_reference_position = mesh_config.get("zero_reference_position", None)
            if zero_reference_position is not None:
                manual_location = config.get("scanner_touch_location", None)
                if manual_location is not None:
                    manual_location = manual_location.split(",")
                    if manual_location:
                        self.touch_location = manual_location
                else:
                    self.touch_location = zero_reference_position.split(",")
            else:
                stepper_x = config.getsection("stepper_x")
                use_x = stepper_x.getfloat("position_max") / 2
                stepper_y = config.getsection("stepper_y")
                use_y = stepper_y.getfloat("position_max") / 2
                raise self.printer.command_error(
                    f"Please update your [bed_mesh] section to include zero_reference_position: {use_x:.2f},{use_y:.2f} in printer.cfg.\nPlease read the manual"
                )

        atypes = {"median": "median", "average": "average"}
        self.samples_config = {
            "samples": config.getfloat("samples", 5, above=0.0),
            "retract_dist": config.getfloat("samples_retract_dist", 5, above=0.0),
            "tolerance": config.getfloat("samples_tolerance", 0.2, minval=0.0),
            "tolerance_retries": config.getint(
                "samples_tolerance_retries", 4, minval=0
            ),
            "result": config.getchoice("samples_result", atypes, "median"),
        }

        self.offset = {
            "x": config.getfloat("x_offset", 0.0),
            "y": config.getfloat("y_offset", 0.0),
        }

        if config.has_section("safe_z_home"):
            z_home_config = config.getsection("safe_z_home")
            if z_home_config.get("z_hop", None) is not None:
                self.z_hop_dist = z_home_config.getfloat("z_hop")
            else:
                self.z_hop_dist = config.getfloat("z_hop_dist", 5.0, above=0.0)
            if z_home_config.get("speed", None) is not None:
                self.z_hop_speed = z_home_config.getfloat("speed")
            else:
                self.z_hop_speed = config.getfloat("z_hop_speed", 5.0, above=0.0)
        else:
            self.z_hop_dist = config.getfloat("z_hop_dist", 5.0, above=0.0)
            self.z_hop_speed = config.getfloat("z_hop_speed", 5.0, above=0.0)

        self.calibration_method = config.get(
            "mode", config.get("calibration_method", "scan")
        )
        config.deprecate("calibration_method")

        self.trigger_method = TriggerMethod.SCAN

        self.trigger_distance = config.getfloat("trigger_distance", 2.0)
        self.trigger_dive_threshold = config.getfloat("trigger_dive_threshold", 1.5)
        self.trigger_hysteresis = config.getfloat("trigger_hysteresis", 0.006)
        self.z_settling_time = config.getint("z_settling_time", 5, minval=0)

        max_speed_value = config.getfloat(
            "scanner_touch_max_speed", 10, above=0, maxval=30
        )
        ## NEW VARIABLES HERE
        self.scanner_touch_config = {
            "accel": config.getfloat("scanner_touch_accel", 100, above=0, minval=100),
            "max_speed": max_speed_value,
            "speed": config.getfloat("scanner_touch_speed", 3, maxval=max_speed_value),
            "retract_dist": config.getfloat("scanner_touch_retract_dist", 2, minval=1),
            "retract_speed": config.getfloat(
                "scanner_touch_retract_speed", 10, minval=1
            ),
            "sample_count": config.getfloat("scanner_touch_sample_count", 3, minval=1),
            "tolerance": config.getfloat("scanner_touch_tolerance", 0.01, above=0.0),
            "max_retries": config.getint("scanner_touch_max_retries", 10, minval=0),
            "move_speed": config.getfloat("scanner_touch_move_speed", 50, minval=1),
            "calibrate": config.getfloat("scanner_touch_calibrate", 0),
            "z_offset": config.getfloat("scanner_touch_z_offset", 0.05),
            "threshold": config.getint("scanner_touch_threshold", 2500),
            "max_temp": config.getfloat("scanner_touch_max_temp", 150),
            "fuzzy_touch": config.getfloat("scanner_touch_fuzzy_touch", 0, maxval=10),
        }
        self.gcode = self.printer.lookup_object("gcode")

        self.probe_calibrate_z = 0.0

        if config.getint("detect_threshold_z", None) is not None:
            raise self.printer.command_error(
                "Please change detect_threshold_z to scanner_touch_threshold in printer.cfg"
            )
        self.detect_threshold_z = self.scanner_touch_config["threshold"]
        self.previous_probe_success = None

        self.cal_config = {
            "nozzle_z": config.getfloat("cal_nozzle_z", 0.1),
            "floor": config.getfloat("cal_floor", 0.1),
            "ceil": config.getfloat("cal_ceil", 5.0),
            "speed": config.getfloat("cal_speed", 1.0, minval=1, maxval=5),
            "move_speed": config.getfloat("cal_move_speed", 10.0, minval=1),
        }
        # Load models
        self.model = None
        self.models: dict[str, ScannerModel] = {}
        self.model_temp_builder = ScannerTempModelBuilder.load(config)
        self.model_temp = None
        self.fmin = None
        self.default_model_name = config.get("default_model_name", "default")
        self.model_manager = ModelManager(self)

        # Temperature sensor integration
        self.last_temp = 0
        self.measured_min = 99999999.0
        self.measured_max = 0.0

        self.last_sample = None
        self.last_received_sample = None
        self.hardware_failure = None

        self.mesh_helper = ScannerMeshHelper.create(self, config)

        self._stream_en = 0
        self._stream_timeout_timer = self.reactor.register_timer(self._stream_timeout)
        self._stream_callbacks = {}
        self._stream_latency_requests = {}
        self._stream_buffer = []
        self._stream_buffer_limit = STREAM_BUFFER_LIMIT_DEFAULT
        self._stream_buffer_limit_new = self._stream_buffer_limit
        self._stream_samples_queue = queue.Queue()
        self._stream_flush_event = threading.Event()
        self._log_stream = None
        self._data_filter = AlphaBetaFilter(
            config.getfloat("filter_alpha", 0.5),
            config.getfloat("filter_beta", 0.000001),
        )
        self.trapq = None
        self._last_trapq_move = None
        self.mod_axis_twist_comp: Optional[Callable[[list[float]], float]] = None
        self.raw_axis_twist_comp = None

        mainsync = self.printer.lookup_object("mcu")._clocksync
        mcu = config.get("mcu", None)
        if mcu is None:
            self._mcu: MCU = MCU(config, SecondarySync(self.reactor, mainsync))
            self.printer.add_object("mcu " + self.name, self._mcu)
        else:
            if mcu == "mcu":
                self._mcu = self.printer.lookup_object("mcu")
            else:
                self._mcu = self.printer.lookup_object("mcu " + mcu)
        self.cmd_queue = self._mcu.alloc_command_queue()
        self.mcu_probe = ScannerEndstopWrapper(self)

        self.results = []

        # Register z_virtual_endstop
        self.printer.lookup_object("pins").register_chip("probe", self)
        # Register event handlers
        self.printer.register_event_handler("klippy:connect", self._handle_connect)
        self.printer.register_event_handler(
            "klippy:mcu_identify", self._handle_mcu_identify
        )
        self._mcu.register_config_callback(self._build_config)
        self._mcu.register_response(
            self._handle_scanner_data, self.sensor.lower() + "_data"
        )
        # Register webhooks
        webhooks = self.printer.lookup_object("webhooks")
        self._api_dump_helper = APIDumpHelper(self)
        webhooks.register_endpoint("scanner/status", self._handle_req_status)
        webhooks.register_endpoint("scanner/dump", self._handle_req_dump)

        # Register gcode commands
        self.gcode = self.printer.lookup_object("gcode")
        for sensor in [self.sensor, self.sensor_alt]:
            if sensor:  # Ensure the sensor is not None
                sensor_name = sensor.upper()
                self.sensor_name = sensor_name
                self.gcode.register_command(
                    sensor_name + "_STREAM",
                    self.cmd_SCANNER_STREAM,
                    desc=self.cmd_SCANNER_STREAM_help,
                )
                self.gcode.register_command(
                    sensor_name + "_QUERY",
                    self.cmd_SCANNER_QUERY,
                    desc=self.cmd_SCANNER_QUERY_help,
                )
                self.gcode.register_command(
                    sensor_name + "_CALIBRATE",
                    self.cmd_SCANNER_CALIBRATE,
                    desc=self.cmd_SCANNER_CALIBRATE_help,
                )
                self.gcode.register_command(
                    sensor_name + "_THRESHOLD_SCAN",
                    self.cmd_SCANNER_THRESHOLD_SCAN,
                    desc=self.cmd_SCANNER_THRESHOLD_SCAN_help,
                )
                self.gcode.register_command(
                    sensor_name + "_ESTIMATE_BACKLASH",
                    self.cmd_SCANNER_ESTIMATE_BACKLASH,
                    desc=self.cmd_SCANNER_ESTIMATE_BACKLASH_help,
                )
                self.gcode.register_command(
                    sensor_name + "_TOUCH",
                    self.cmd_SCANNER_TOUCH,
                    desc=self.cmd_SCANNER_TOUCH_help,
                )
        self.gcode.register_command("PROBE", self.cmd_PROBE, desc=self.cmd_PROBE_help)
        self.gcode.register_command(
            "PROBE_ACCURACY", self.cmd_PROBE_ACCURACY, desc=self.cmd_PROBE_ACCURACY_help
        )
        self.gcode.register_command(
            "PROBE_SWITCH", self.cmd_PROBE_SWITCH, desc=self.cmd_PROBE_SWITCH_help
        )
        self.gcode.register_command(
            "Z_OFFSET_APPLY_PROBE",
            self.cmd_Z_OFFSET_APPLY_PROBE,
            desc=self.cmd_Z_OFFSET_APPLY_PROBE_help,
        )

    def validate_model_loaded(self, gcmd: GCodeCommand):
        if self.model is None:
            raise gcmd.error(
                f"No model currently selected - make sure you have run {format_macro('CARTOGRAPHER_CALIBRATE')} first."
                + f" Click <a href='{DOCS_TOUCH_CALIBRATION}'>HERE</a> for more information"
            )

        self.model.validate()

    cmd_SCANNER_CALIBRATE_help = "Calibrate scanner response curve"

    def cmd_SCANNER_CALIBRATE(self, gcmd: GCodeCommand):
        orig_params = gcmd.get_command_parameters()
        if self.calibration_method != "scan":
            cmd = self.sensor_name + "_TOUCH"
            params: dict[str, str] = {}
            if gcmd.get("METHOD", "None").lower() == "manual":
                params["METHOD"] = "manual"
            else:
                params["CALIBRATE"] = "1"

            params.update(orig_params)

            cmd = self.gcode.create_gcode_command(cmd, cmd, params)
            self.cmd_SCANNER_TOUCH(cmd)
        else:
            self.calibration_method = "scan"
            self._start_calibration(gcmd)

    def _get_common_variables(self, gcmd: GCodeCommand):
        return {
            "speed": gcmd.get_float(
                "SPEED",
                self.scanner_touch_config["speed"],
                above=0,
                maxval=self.scanner_touch_config["max_speed"],
            ),
            "move_speed": gcmd.get_float(
                "MOVEMENT_SPEED", self.scanner_touch_config["move_speed"], above=0
            ),
            "accel": gcmd.get_float(
                "ACCEL", self.scanner_touch_config["accel"], minval=1
            ),
            "retract_dist": gcmd.get_float(
                "RETRACT", self.scanner_touch_config["retract_dist"], minval=1
            ),
            "retract_speed": gcmd.get_float(
                "RETRACT_SPEED", self.scanner_touch_config["retract_speed"], minval=1
            ),
            "num_samples": gcmd.get_int(
                "SAMPLES", self.scanner_touch_config["sample_count"], minval=1
            ),
            "tolerance": round(
                gcmd.get_float(
                    "TOLERANCE",
                    float(self.scanner_touch_config["tolerance"]),
                    above=0.0,
                ),
                4,
            ),
            "target": gcmd.get_float(
                "TARGET", 0.015, above=0.0
            ),  # Default target to 0.015 if not defined
            "max_retries": gcmd.get_int(
                "RETRIES", self.scanner_touch_config["max_retries"], minval=0
            ),
            "touch_location_x": gcmd.get_float(
                "TOUCH_LOCATION_X", float(self.touch_location[0])
            ),
            "touch_location_y": gcmd.get_float(
                "TOUCH_LOCATION_Y", float(self.touch_location[1])
            ),
            "randomize": gcmd.get_float(
                "FUZZY_TOUCH", self.scanner_touch_config["fuzzy_touch"], maxval=10
            ),
            "verbose": gcmd.get_int("DEBUG", 0),
        }

    cmd_SCANNER_TOUCH_help = "Home in TOUCH mode"

    def cmd_SCANNER_TOUCH(self, gcmd: GCodeCommand):
        # Retrieve common variables
        vars = self._get_common_variables(gcmd)

        # Variables specific to the touch command
        test_threshold = gcmd.get_int("THRESHOLD", self.detect_threshold_z, minval=100)
        calibrate = gcmd.get_float("CALIBRATE", self.scanner_touch_config["calibrate"])
        manual_z_offset = gcmd.get_float(
            "Z_OFFSET", self.scanner_touch_config["z_offset"], minval=0
        )
        # Debugging information
        self.log_debug_info(
            vars["verbose"],
            gcmd,
            f"SPEED: {vars['speed']}",
            f"MOVEMENT_SPEED: {vars['move_speed']}",
            f"ACCEL: {vars['accel']}",
            f"RETRACT: {vars['retract_dist']}",
            f"RETRACT_SPEED: {vars['retract_speed']}",
            f"SAMPLES: {vars['num_samples']}",
            f"TOLERANCE: {vars['tolerance']}",
            f"RETRIES: {vars['max_retries']}",
            f"TOUCH_LOCATION_X: {vars['touch_location_x']}",
            f"TOUCH_LOCATION_Y: {vars['touch_location_y']}",
            f"THRESHOLD: {test_threshold}",
            f"Z_OFFSET: {manual_z_offset}",
            f"DEBUG: {vars['verbose']}",
            f"MOVE: {vars['randomize']}",
        )

        # Switch between Touch and Scan Probing
        if self.calibration_method == "touch":
            self.trigger_method = TriggerMethod.TOUCH
        else:
            self.trigger_method = TriggerMethod.SCAN
            self.calibration_method = "scan"
            if calibrate == 1 or gcmd.get("METHOD", "None").lower() == "manual":
                self._start_calibration(gcmd)
            return

        self.check_temp(gcmd)
        self.log_debug_info(
            vars["verbose"], gcmd, f"Trigger Method: {self.trigger_method}"
        )
        self.toolhead.wait_moves()

        curtime = self.printer.get_reactor().monotonic()
        kinematics = self.toolhead.get_kinematics()
        kin_status = kinematics.get_status(curtime)
        if "x" not in kin_status["homed_axes"] or "y" not in kin_status["homed_axes"]:
            self.trigger_method = TriggerMethod.SCAN
            raise gcmd.error("Must home X and Y axes first")

        self.previous_probe_success = 0
        self._zhop()
        self._move(
            [vars["touch_location_x"], vars["touch_location_y"], None],
            vars["move_speed"],
        )

        if gcmd.get("METHOD", "None").lower() == "manual":
            self._start_calibration(gcmd)
        else:
            gcmd.respond_info("Starting nozzle touch..")
            initial_position = self.toolhead.get_position()[:]
            homing_position = initial_position[:]
            z_min, z_max = kin_status["axis_minimum"][2], kin_status["axis_maximum"][2]

            self.log_debug_info(
                vars["verbose"],
                gcmd,
                f"Initial Pos: {initial_position} \nHoming Pos: {homing_position} \nZ MIN: {z_min} \nZ MAX: {z_max}",
            )

            initial_position[2] = z_max
            homing_position[2] = z_min
            self.log_debug_info(
                vars["verbose"],
                gcmd,
                f"new Initial Pos [Initial Z - Z Max]: {initial_position} \nnew Homing Pos [Homing Pos - Z Min]: {homing_position}",
            )

            max_accel = self.toolhead.get_status(curtime)["max_accel"]
            self.log_debug_info(
                vars["verbose"], gcmd, f"Current Accel: {int(max_accel)}"
            )

            if calibrate == 1:
                manual_z_offset = 0

            touch_settings = TouchSettings(
                initial_position,
                homing_position,
                vars["accel"],
                vars["speed"],
                vars["retract_dist"],
                vars["retract_speed"],
                vars["num_samples"],
                vars["tolerance"],
                vars["max_retries"],
                z_max,
                max_accel,
                test_threshold,
                manual_z_offset,
                vars["randomize"],
            )

            result = self.start_touch(gcmd, touch_settings, vars["verbose"])

            standard_deviation = result["standard_deviation"]
            final_position = result["final_position"]
            retries = result["retries"]
            success = result["success"]
            if success:
                self.log_debug_info(
                    vars["verbose"],
                    gcmd,
                    f"Touch procedure successful with {int(retries + 1)} attempts.",
                )
                self.log_debug_info(
                    vars["verbose"], gcmd, f"Final position: {final_position}"
                )
                self.log_debug_info(
                    vars["verbose"],
                    gcmd,
                    f"Standard Deviation: {standard_deviation:.4f}",
                )
                if calibrate == 1:
                    self._calibrate(
                        gcmd, final_position, final_position[2], True, True, False
                    )

            else:
                self.trigger_method = TriggerMethod.SCAN
                gcmd.respond_info("Touch procedure failed.")
            self._zhop()
            self.set_temp(gcmd)
            self.extruder_target = 0

    # Event handlers
    def start_touch(self, gcmd: GCodeCommand, touch_settings, verbose: bool):
        kinematics = self.toolhead.get_kinematics()
        initial_position = touch_settings.initial_position
        homing_position = touch_settings.homing_position
        accel = touch_settings.accel
        speed = touch_settings.speed
        retract_dist = touch_settings.retract_dist
        retract_speed = touch_settings.retract_speed
        num_samples = touch_settings.num_samples
        tolerance = touch_settings.tolerance
        max_retries = touch_settings.max_retries
        z_max = touch_settings.z_max
        max_accel = touch_settings.max_accel
        test_threshold = touch_settings.test_threshold
        manual_z_offset = touch_settings.manual_z_offset
        randomize = touch_settings.randomize

        original_threshold = self.detect_threshold_z
        try:
            self.detect_threshold_z = test_threshold
            # Set the initial position for the toolhead
            self.toolhead.set_position(initial_position, homing_axes=[2])

            retries = 0

            new_retry = False
            samples = []

            original_position = initial_position[:]

            while len(samples) < num_samples:
                if retries >= max_retries:
                    self.detect_threshold_z = original_threshold
                    self.trigger_method = TriggerMethod.SCAN
                    self._zhop()
                    raise gcmd.error(
                        f"Exceeded maximum attempts [{retries}/{int(max_retries)}]"
                    )
                if randomize > 0 and new_retry:
                    # Generate random offsets
                    x_offset = random.uniform(-randomize, randomize)
                    y_offset = random.uniform(-randomize, randomize)

                    # Adjust positiion
                    initial_position[0] = original_position[0] + x_offset
                    initial_position[1] = original_position[1] + y_offset

                    self.toolhead.move(initial_position, 20)

                    # Respond with the randomized movement info
                    gcmd.respond_info(
                        f"Moving touch location to (x: {initial_position[0]:.2f}, y: {initial_position[1]:.2f})"
                    )
                    new_retry = False

                self.toolhead.wait_moves()
                self.set_accel(accel)

                try:
                    probe_position = self.phoming.probing_move(
                        self.mcu_probe, homing_position, speed
                    )
                except self.printer.command_error as e:
                    if self.printer.is_shutdown():
                        self.detect_threshold_z = original_threshold
                        self.trigger_method = TriggerMethod.SCAN
                        raise self.printer.command_error(
                            "Touch procedure interrupted due to printer shutdown"
                        ) from e
                    raise
                finally:
                    self.set_accel(max_accel)

                retract_position = self.toolhead.get_position()[:]
                retract_position[2] = min(retract_position[2] + retract_dist, z_max)
                self.toolhead.move(retract_position, retract_speed)
                self.toolhead.dwell(1.0)

                samples.append(probe_position[2])
                self.log_debug_info(
                    verbose,
                    gcmd,
                    f"Touch {len(samples)} result: {probe_position[2]:.4f}",
                )

                average = np.median(samples)
                deviation = max(abs(sample - average) for sample in samples)

                deviation = round(deviation, 4)
                if deviation > tolerance:
                    self.log_debug_info(
                        verbose,
                        gcmd,
                        f"Deviation of {deviation:.4f} exceeds tolerance of {tolerance:.4f}",
                    )
                    gcmd.respond_info(
                        f"Attempt {retries + 1}/{max_retries} failed with deviation {deviation:.4f}."
                    )
                    retries += 1
                    new_retry = True
                    samples.clear()

                self.log_debug_info(
                    verbose,
                    gcmd,
                    f"Deviation: {deviation:.4f}\nNew Average: {average:.4f}\nTolerance: {tolerance:.4f}",
                )
            std_dev = np.std(samples)
            if retries < max_retries and std_dev <= tolerance:
                gcmd.respond_info(
                    f"Completed {len(samples)} touches with a standard deviation of {std_dev:.4f}"
                )
                position_difference = (
                    initial_position[2] - self.toolhead.get_position()[2]
                )
                adjusted_difference = initial_position[2] - np.mean(samples)
                self.log_debug_info(
                    verbose,
                    gcmd,
                    f"Position Difference: {position_difference:.4f}\nAdjusted Difference: {adjusted_difference:.4f}",
                )

                initial_position[2] = float(adjusted_difference - position_difference)
                formatted_position = [f"{coord:.2f}" for coord in initial_position]
                self.log_debug_info(
                    verbose, gcmd, f"Updated Initial Position: {formatted_position}"
                )
                if manual_z_offset > 0:
                    gcmd.respond_info(f"Offsetting by {manual_z_offset:.3f}")
                    initial_position[2] = initial_position[2] - manual_z_offset
                self.toolhead.set_position(initial_position)
                self.toolhead.wait_moves()
                self.toolhead.flush_step_generation()
                self.trigger_method = TriggerMethod.SCAN
                self.previous_probe_success = 1

                # Return relevant data
                self.detect_threshold_z = original_threshold
            return {
                "samples": samples,
                "standard_deviation": std_dev,
                "final_position": initial_position,
                "retries": retries,
                "success": self.previous_probe_success,
            }
        except self.printer.command_error:
            self.detect_threshold_z = original_threshold
            self.trigger_method = TriggerMethod.SCAN
            if hasattr(kinematics, "note_z_not_homed"):
                kinematics.note_z_not_homed()
            raise

    cmd_SCANNER_THRESHOLD_SCAN_help = "Scan THRESHOLD in TOUCH mode"

    def cmd_SCANNER_THRESHOLD_SCAN(self, gcmd: GCodeCommand):
        """Initiate threshold scanning to find the optimal threshold for accurate touch detection."""
        if self.calibration_method == "touch":
            self.trigger_method = TriggerMethod.TOUCH
        else:
            self.trigger_method = TriggerMethod.SCAN
            return

        # Retrieve common and specific threshold scan variables
        vars = self._get_common_variables(gcmd)

        # Retrieve STEP value once
        step = gcmd.get_int("STEP", 250)
        user_defined_min = gcmd.get_int("MIN", None, minval=0)

        if user_defined_min is None:
            threshold_min = max(
                THRESHOLD_MIN_LIMIT,
                round(
                    (self.detect_threshold_z * THRESHOLD_SCALING_FACTOR)
                    / THRESHOLD_ROUNDING_BASE
                )
                * THRESHOLD_ROUNDING_BASE,
            )
        else:
            threshold_min = user_defined_min

        has_increased_threshold_max = (
            False  # Flag to track if threshold_max has been increased
        )

        threshold_max = gcmd.get_int("MAX", None)
        if threshold_max is None:
            threshold_max = threshold_min + (THRESHOLD_STEP_MULTIPLIER * step)
        else:
            has_increased_threshold_max = True  # max limit is set, dont increase

        override = gcmd.get_int("OVERRIDE", 0)

        confirmation_retries = gcmd.get_int(
            "QUALIFY_SAMPLES", 5
        )  # Number of consistent retries for a good candidate
        repeat_attempts = gcmd.get_int(
            "VERIFY_SAMPLES", 3
        )  # Define repeat attempts for consistency check

        # Define what qualifies as a "good" result
        max_acceptable_retries = round(
            confirmation_retries * THRESHOLD_ACCEPTANCE_FACTOR
        )
        max_acceptable_std_dev = vars["target"]

        verbose = vars["verbose"]

        # Prepare to track results
        results = []

        # Proceed with threshold scanning
        self.check_temp(gcmd)
        self.toolhead.wait_moves()

        # Ensure XY homing
        curtime = self.printer.get_reactor().monotonic()
        kinematics = self.toolhead.get_kinematics()
        kin_status = kinematics.get_status(curtime)
        if (
            "x" not in kin_status["homed_axes"]
            or "y" not in kin_status["homed_axes"]
            or "z" not in kin_status["homed_axes"]
        ):
            self.trigger_method = TriggerMethod.SCAN
            raise gcmd.error("Must home all axes first")

        # Check if model is loaded
        self.validate_model_loaded(gcmd)

        # Check if bed leveling has been applied
        if self.bed_level.requires_bed_leveling():
            self.trigger_method = TriggerMethod.SCAN
            lines = ["Bed leveling required before threshold scan."]
            cmd = self.bed_level.get_bed_leveling_command()
            if cmd is not None:
                lines.append(f"Please run {format_macro(cmd)}")
            raise gcmd.error(" ".join(lines))

        self._zhop()
        self._move(
            [vars["touch_location_x"], vars["touch_location_y"], None],
            vars["move_speed"],
        )
        self.previous_probe_success = 0
        current_threshold = threshold_min

        start_position = kin_status["axis_maximum"][2]
        try:
            initial_position = self.toolhead.get_position()[:]
            homing_position = initial_position[:]
            initial_position[2], homing_position[2] = (
                start_position,
                kin_status["axis_minimum"][2],
            )
            max_accel = self.toolhead.get_status(curtime)["max_accel"]

            # Threshold scanning loop
            while current_threshold <= threshold_max:
                gcmd.respond_info(f"Testing Threshold value {current_threshold}...")
                self.detect_threshold_z = current_threshold

                touch_settings = TouchSettings(
                    initial_position,
                    homing_position,
                    vars["accel"],
                    vars["speed"],
                    vars["retract_dist"],
                    vars["retract_speed"],
                    vars["num_samples"],
                    vars["tolerance"],
                    confirmation_retries,
                    start_position,
                    max_accel,
                    current_threshold,
                    0,
                    vars["randomize"],
                )

                # Start threshold scan and evaluate results
                result = self.start_threshold_scan(gcmd, touch_settings, verbose)
                result["threshold"] = (
                    current_threshold  # Add threshold value to result for tracking
                )
                results.append(result)  # Append the result for later comparison

                if result["success"]:
                    # Check if this result meets "good" criteria
                    if result["retries"] <= max_acceptable_retries and (
                        result["standard_deviation"] is not None
                        and result["standard_deviation"] <= max_acceptable_std_dev
                    ):
                        # Increase threshold_max by 3 steps above the current threshold, only if it hasn't been increased before
                        if not has_increased_threshold_max:
                            threshold_max = (
                                current_threshold
                                + THRESHOLD_INCREMENT_MULTIPLIER * step
                            )
                            has_increased_threshold_max = (
                                True  # Set the flag to True after increasing
                            )
                        gcmd.respond_info(f"Good Threshold Found: {current_threshold}.")

                        # Run repeatability check with this threshold
                        consistent_results = True
                        repeat_result = {}
                        for attempt in range(repeat_attempts):
                            repeat_result = self.start_threshold_scan(
                                gcmd, touch_settings, verbose
                            )
                            if not repeat_result["success"] or (
                                repeat_result["standard_deviation"]
                                > max_acceptable_std_dev
                            ):
                                gcmd.respond_info(
                                    f"Qualify attempt {attempt + 1} failed for threshold {current_threshold}"
                                )
                                consistent_results = False
                                break
                            gcmd.respond_info(
                                f"Qualify attempt {attempt + 1} successful with std dev: {repeat_result['standard_deviation']:.5f}"
                            )

                        # Save only successful repeat attempts in results
                        result["consistent_results"] = (
                            consistent_results  # Mark if it passed repeatability checks
                        )
                        result["standard_deviation"] = (
                            repeat_result["standard_deviation"]
                            if consistent_results
                            else None
                        )
                        result["success"] = (
                            repeat_result["success"] if consistent_results else False
                        )
                        results.append(result)  # Append the result for later comparison
                        # If all repeat attempts succeeded, save the threshold
                        if consistent_results and override == 0:
                            best_threshold = current_threshold
                            self._save_threshold(best_threshold, vars["speed"])
                            break
                # Move to the next candidate if current threshold didn't succeed
                current_threshold += step

        finally:
            self._zhop()

            # In the finally block, filter for consistent results only
            consistent_results = [
                r for r in results if r.get("consistent_results", False)
            ]

            # Check if there are any results at all
            if not results or all(not r["success"] for r in results):
                # If no thresholds passed the scan at all
                gcmd.respond_info("No suitable threshold was found during the scan.")
                return  # Exit as there's no best threshold to save

            if consistent_results:
                # Find the best consistent result based on minimum retries and standard deviation
                best_result = min(
                    consistent_results,
                    key=lambda x: (
                        x["retries"],
                        x["standard_deviation"]
                        if x["standard_deviation"] is not None
                        else float("inf"),
                    ),
                )
                best_threshold = best_result["threshold"]
                optimal_found = True
            else:
                # Fallback if no consistent results were found, pick the best among all results
                best_result = min(
                    results,
                    key=lambda x: (
                        x["retries"],
                        x["standard_deviation"]
                        if x["standard_deviation"] is not None
                        else float("inf"),
                    ),
                )
                best_threshold = best_result["threshold"]
                optimal_found = False

            # Save and respond with the best threshold found
            self.detect_threshold_z = best_threshold
            self._save_threshold(best_threshold, vars["speed"])

            # Handle None for standard deviation by using a default message
            std_dev_display = (
                f"{best_result['standard_deviation']:.5f}"
                if best_result["standard_deviation"] is not None
                else "N/A"
            )

            # Inform the user about the result
            if optimal_found:
                gcmd.respond_info(
                    f"Optimal Threshold Determined: {best_threshold} with standard deviation of {std_dev_display}"
                )
            else:
                gcmd.respond_info(
                    f"No fully optimal threshold found. Best attempt: {best_threshold} with standard deviation of {std_dev_display}"
                )
            gcmd.respond_info(
                f"You can now {format_macro('SAVE_CONFIG')} to save your threshold."
            )

            self.trigger_method = TriggerMethod.SCAN

    def start_threshold_scan(self, gcmd: GCodeCommand, touch_settings, verbose: bool):
        kinematics = self.toolhead.get_kinematics()
        initial_position = touch_settings.initial_position
        homing_position = touch_settings.homing_position
        accel = touch_settings.accel
        speed = touch_settings.speed
        retract_dist = touch_settings.retract_dist
        retract_speed = touch_settings.retract_speed
        num_samples = touch_settings.num_samples
        tolerance = touch_settings.tolerance
        max_retries = touch_settings.max_retries
        z_max = touch_settings.z_max
        max_accel = touch_settings.max_accel
        test_threshold = touch_settings.test_threshold
        randomize = touch_settings.randomize
        try:
            self.detect_threshold_z = test_threshold
            # Set the initial position for the toolhead
            self.toolhead.set_position(initial_position, homing_axes=[2])

            retries = 0
            new_retry = False
            samples = []
            success = False

            original_position = initial_position[:]

            while len(samples) < num_samples:
                if retries >= max_retries:
                    break  # Exit the loop and move to the next threshold

                if randomize > 0 and new_retry:
                    # Generate random offsets
                    x_offset = random.uniform(-randomize, randomize)
                    y_offset = random.uniform(-randomize, randomize)

                    # Adjust positiion
                    initial_position[0] = original_position[0] + x_offset
                    initial_position[1] = original_position[1] + y_offset

                    self.toolhead.move(initial_position, 20)

                    # Respond with the randomized movement info
                    gcmd.respond_info(
                        f"Moving touch location to (x: {initial_position[0]:.2f}, y: {initial_position[1]:.2f})"
                    )
                    new_retry = False

                self.toolhead.wait_moves()
                self.set_accel(accel)

                try:
                    probe_position = self.phoming.probing_move(
                        self.mcu_probe, homing_position, speed
                    )
                except self.printer.command_error as e:
                    if self.printer.is_shutdown():
                        self.trigger_method = TriggerMethod.SCAN
                        raise self.printer.command_error(
                            "Touch procedure interrupted due to printer shutdown"
                        ) from e
                    raise
                finally:
                    self.set_accel(max_accel)

                retract_position = self.toolhead.get_position()[:]
                retract_position[2] = min(retract_position[2] + retract_dist, z_max)
                self.toolhead.move(retract_position, retract_speed)
                self.toolhead.dwell(1.0)

                samples.append(probe_position[2])
                self.log_debug_info(
                    verbose,
                    gcmd,
                    f"Touch {len(samples)} result: {probe_position[2]:.4f}",
                )

                average = np.median(samples)
                deviation = max(abs(sample - average) for sample in samples)
                deviation = round(deviation, 4)
                if deviation > tolerance:
                    self.log_debug_info(
                        verbose,
                        gcmd,
                        f"Deviation of {deviation:.4f} exceeds tolerance of {tolerance:.4f}",
                    )
                    gcmd.respond_info(
                        f"Attempt {retries + 1}/{max_retries} failed with deviation {deviation:.4f}."
                    )
                    retries += 1
                    new_retry = True
                    samples.clear()
                    # If successful, we continue gathering samples until num_samples is reached.

                self.log_debug_info(
                    verbose,
                    gcmd,
                    f"Deviation: {deviation:.4f}\nNew Average: {average:.4f}\nTolerance: {tolerance:.4f}",
                )

            std_dev = np.std(samples) if samples else None
            if len(samples) == num_samples:
                success = True
                position_difference = (
                    initial_position[2] - self.toolhead.get_position()[2]
                )
                adjusted_difference = initial_position[2] - np.median(samples)
                self.log_debug_info(
                    verbose,
                    gcmd,
                    f"Position Difference: {position_difference:.4f}\nAdjusted Difference: {adjusted_difference:.4f}",
                )
            else:
                std_dev = None
                success = False

            self.toolhead.wait_moves()
            self.toolhead.flush_step_generation()
            self.previous_probe_success = 1 if success else 0

            # Return relevant data
            return {
                "samples": samples,
                "standard_deviation": std_dev,
                "final_position": initial_position,
                "retries": retries,
                "success": success,
                "consistent_results": False,  # Default to False
            }
        except self.printer.command_error:
            self.trigger_method = TriggerMethod.SCAN
            if hasattr(kinematics, "note_z_not_homed"):
                kinematics.note_z_not_homed()
            raise

    def touch_probe(self, speed: float, skip: int = 0, verbose: bool = True):
        skipped_msg = ""
        toolhead = self.printer.lookup_object("toolhead")
        curtime = self.printer.get_reactor().monotonic()
        status = self.toolhead.get_kinematics().get_status(curtime)
        if "z" not in toolhead.get_status(curtime)["homed_axes"]:
            raise self.printer.command_error("Must home before probe")
        pos = toolhead.get_position()
        pos[2] = status["axis_minimum"][2]
        try:
            epos = self.phoming.probing_move(self.mcu_probe, pos, speed)
        except self.printer.command_error as e:
            reason = str(e)
            if "Timeout during endstop homing" in reason:
                reason += probe.HINT_TIMEOUT
            raise self.printer.command_error(reason)
        if verbose:
            if skip == 1:
                skipped_msg = " - SKIPPED - result not added"
            self.gcode.respond_info(
                "probe at %.3f,%.3f is z=%.6f %s"
                % (epos[0], epos[1], epos[2], skipped_msg)
            )
        return epos[:3]

    def _calc_median(self, positions: "list[list[float]]"):
        z_sorted = sorted(positions, key=(lambda p: p[2]))
        middle = len(positions) // 2
        if (len(positions) & 1) == 1:
            # odd number of samples
            return z_sorted[middle]
        # even number of samples
        return self._calc_mean(z_sorted[middle - 1 : middle + 1])

    def _calc_mean(self, positions: "list[list[float]]"):
        count = float(len(positions))
        return [sum([pos[i] for pos in positions]) / count for i in range(3)]

    def log_debug_info(self, verbose: bool, gcmd: GCodeCommand, *args: object):
        if verbose:
            for message in args:
                gcmd.respond_info(str(message))

    def check_temp(self, gcmd: GCodeCommand):
        hotend = self.toolhead.get_extruder()
        if hotend is not None:
            curtime = self.printer.get_reactor().monotonic()
            cur_temp = hotend.get_heater().get_status(curtime)["temperature"]
            self.extruder_target = hotend.get_heater().get_status(curtime)["target"]
            max_temp = self.scanner_touch_config["max_temp"]
            wait_temp = max_temp + 5
            if self.extruder_target > max_temp:
                gcmd.respond_info(
                    "Target hotend temperature %.1f exceeds maximum allowed temperature %.1f lowering to %.1f"
                    % (cur_temp, max_temp, max_temp)
                )
                cmd = "M104 S" + str(max_temp)
                self.gcode.run_script_from_command(cmd)
                cmd = f"TEMPERATURE_WAIT SENSOR=extruder MAXIMUM={wait_temp}"
                self.gcode.run_script_from_command(cmd)
            else:
                if cur_temp > wait_temp:
                    gcmd.respond_info(
                        "Extruder temperature %.1fC is still too high, waiting until below %.1fC"
                        % (cur_temp, wait_temp)
                    )
                    cmd = f"TEMPERATURE_WAIT SENSOR=extruder MAXIMUM={wait_temp}"
                    self.gcode.run_script_from_command(cmd)

    def set_temp(self, gcmd: GCodeCommand):
        hotend = self.toolhead.get_extruder()
        if hotend is not None:
            curtime = self.printer.get_reactor().monotonic()
            cur_temp = hotend.get_heater().get_status(curtime)["temperature"]
            if self.extruder_target > cur_temp:
                gcmd.respond_info("Heating hotend to %.1f" % (self.extruder_target))
                cmd = "M104 S" + str(self.extruder_target)
                self.gcode.run_script_from_command(cmd)
                cmd = "TEMPERATURE_WAIT SENSOR=extruder MINIMUM=" + str(
                    self.extruder_target
                )
                self.gcode.run_script_from_command(cmd)

    def set_accel(self, value: float):
        self.gcode.run_script_from_command("SET_VELOCITY_LIMIT ACCEL=%.3f" % (value,))

    def _zhop(self):
        if self.z_hop_dist != 0:
            curtime = self.printer.get_reactor().monotonic()
            kin = self.toolhead.get_kinematics()
            kin_status = kin.get_status(curtime)
            pos = self.toolhead.get_position()

            move = [None, None, self.z_hop_dist]
            if "z" not in kin_status["homed_axes"]:
                pos[2] = 0
                self.toolhead.set_position(pos, homing_axes=[2])
                self.toolhead.manual_move(move, self.z_hop_speed)
                self.toolhead.wait_moves()
                if hasattr(kin, "note_z_not_homed"):
                    kin.note_z_not_homed()
            elif pos[2] < self.z_hop_dist:
                self.toolhead.manual_move(move, self.z_hop_speed)
                self.toolhead.wait_moves()

    def _move(self, coord: "list[float | None]", speed: float):
        self.printer.lookup_object("toolhead").manual_move(coord, speed)

    def _handle_connect(self):
        self.phoming = self.printer.lookup_object("homing")
        axis_twist_comp = self.printer.lookup_object("axis_twist_compensation", None)
        if axis_twist_comp is not None:
            if hasattr(axis_twist_comp, "get_z_compensation_value"):
                self.mod_axis_twist_comp = axis_twist_comp.get_z_compensation_value
            else:

                def get_z_compensation_value(pos):
                    temp = list(pos)
                    axis_twist_comp._update_z_compensation_value(temp)
                    return temp[2] - pos[2]

                self.mod_axis_twist_comp = get_z_compensation_value
        # Ensure streaming mode is stopped
        self.scanner_stream_cmd.send([0])

        self.model_temp = self.model_temp_builder.build_with_base(self)
        if self.model_temp:
            self.fmin = self.model_temp.fmin
        self.model = self.models.get(self.default_model_name, None)
        if self.model:
            self._apply_threshold()

    def _handle_mcu_identify(self):
        try:
            if self._mcu._mcu_freq < 20000000:
                self.sensor_freq = self._mcu._mcu_freq
            elif self._mcu._mcu_freq < 100000000:
                self.sensor_freq = self._mcu._mcu_freq / 2
            else:
                self.sensor_freq = self._mcu._mcu_freq / 6
            self.inv_adc_max = 1.0 / self._mcu.get_constant_float("ADC_MAX")
            self.temp_smooth_count = self._mcu.get_constant_float(
                self.sensor.upper() + "_ADC_SMOOTH_COUNT"
            )
            self.thermistor = thermistor.Thermistor(10000.0, 0.0)
            self.thermistor.setup_coefficients_beta(25.0, 47000.0, 4041.0)

            self.toolhead = self.printer.lookup_object("toolhead")
            self.trapq = self.toolhead.get_trapq()
            self.fw_version = self._mcu.get_status()["mcu_version"]
        except msgproto.error as e:
            raise msgproto.error(
                f"Error during probe mcu identification, check connection:\n{e}"
            )

    def _build_config(self):
        self.scanner_stream_cmd = self._mcu.lookup_command(
            self.sensor.lower() + "_stream en=%u", cq=self.cmd_queue
        )
        self.scanner_set_threshold = self._mcu.lookup_command(
            self.sensor.lower() + "_set_threshold trigger=%u untrigger=%u",
            cq=self.cmd_queue,
        )
        self.scanner_home_cmd = self._mcu.lookup_command(
            self.sensor.lower()
            + "_home trsync_oid=%c trigger_reason=%c trigger_invert=%c threshold=%u trigger_method=%u",
            cq=self.cmd_queue,
        )
        self.scanner_stop_home = self._mcu.lookup_command(
            self.sensor.lower() + "_stop_home", cq=self.cmd_queue
        )
        self.scanner_base_read_cmd = self._mcu.lookup_query_command(
            self.sensor.lower() + "_base_read len=%c offset=%hu",
            self.sensor.lower() + "_base_data bytes=%*s offset=%hu",
            cq=self.cmd_queue,
        )

    def stats(self, eventtime):
        return False, "%s: coil_temp=%.1f refs=%s" % (
            self.name,
            self.last_temp,
            self._stream_en,
        )

    # Virtual endstop

    def setup_pin(self, pin_type, pin_params):
        if pin_type != "endstop" or pin_params["pin"] != "z_virtual_endstop":
            raise pins.error("Probe virtual endstop only useful as endstop pin")
        if pin_params["invert"] or pin_params["pullup"]:
            raise pins.error("Can not pullup/invert probe virtual endstop")
        return self.mcu_probe

    # Probe interface

    def multi_probe_begin(self):
        self._start_streaming()

    def multi_probe_end(self):
        self._stop_streaming()

    def get_offsets(self):
        return self.offset["x"], self.offset["y"], self.trigger_distance

    def get_lift_speed(self, gcmd: Optional[GCodeCommand] = None):
        if gcmd is not None:
            return gcmd.get_float("LIFT_SPEED", self.lift_speed, above=0.0)
        return self.lift_speed

    def get_samples(self, gcmd: Optional[GCodeCommand] = None):
        if gcmd is not None:
            return gcmd.get_int("SAMPLES", self.samples_config["samples"], minval=1)
        return self.samples_config["samples"]

    def get_sample_retract_dist(self, gcmd: Optional[GCodeCommand] = None):
        if gcmd is not None:
            return gcmd.get_float(
                "SAMPLE_RETRACT_DIST", self.samples_config["retract_dist"], above=0.0
            )
        return self.samples_config["retract_dist"]

    def get_samples_tolerance(self, gcmd: Optional[GCodeCommand] = None):
        if gcmd is not None:
            return gcmd.get_float(
                "SAMPLES_TOLERANCE", self.samples_config["tolerance"], minval=0.0
            )
        return self.samples_config["retract_dist"]

    def get_samples_tolerance_retries(self, gcmd: Optional[GCodeCommand] = None):
        if gcmd is not None:
            return gcmd.get_int(
                "SAMPLES_TOLERANCE_RETRIES",
                self.samples_config["tolerance_retries"],
                minval=0,
            )
        return self.samples_config["tolerance_retries"]

    def get_samples_result(self, gcmd: Optional[GCodeCommand] = None):
        if gcmd is not None:
            return gcmd.get("SAMPLES_RESULT", self.samples_config["result"])
        return self.samples_config["result"]

    def run_probe(self, gcmd: GCodeCommand):
        if self.model is None:
            raise self.printer.command_error("No Scanner model loaded")

        speed = gcmd.get_float("PROBE_SPEED", self.speed, above=0.0)
        skip_samples = gcmd.get_int("SKIP", 0)
        allow_faulty = gcmd.get_int("ALLOW_FAULTY_COORDINATE", 0) != 0
        toolhead = self.printer.lookup_object("toolhead")
        curtime = self.reactor.monotonic()
        if "z" not in toolhead.get_status(curtime)["homed_axes"]:
            raise self.printer.command_error("Must home before probe")

        self._start_streaming()
        try:
            epos = self._probe(speed, skip_samples, allow_faulty=allow_faulty)
            self.results.append(epos)
            return epos
        finally:
            self._stop_streaming()

    def _move_to_probing_height(self, speed: float):
        target = self.trigger_distance
        top = target + self.backlash_comp
        cur_z = self.toolhead.get_position()[2]
        if cur_z < top:
            self.toolhead.manual_move([None, None, top], speed)
        self.toolhead.manual_move([None, None, target], speed)
        self.toolhead.wait_moves()

    def _probing_move_to_probing_height(self, speed: float):
        curtime = self.reactor.monotonic()
        status = self.toolhead.get_kinematics().get_status(curtime)
        pos = self.toolhead.get_position()
        pos[2] = status["axis_minimum"][2]
        try:
            self.phoming.probing_move(self.mcu_probe, pos, speed)
            self._sample_printtime_sync(self.z_settling_time)
        except self.printer.command_error as e:
            reason = str(e)
            if "Timeout during probing move" in reason:
                reason += probe.HINT_TIMEOUT
            raise self.printer.command_error(reason)

    def _probe(
        self,
        speed: float,
        skip: int = 0,
        num_samples: int = 10,
        allow_faulty: bool = False,
        verbose: bool = True,
    ) -> "list[float]":
        skipped_msg = ""
        if self.trigger_method != TriggerMethod.SCAN:
            return self.touch_probe(speed, skip)
        target = self.trigger_distance
        tdt = self.trigger_dive_threshold
        (dist, samples) = self._sample(5, num_samples)
        self.toolhead.wait_moves()
        x, y = samples[0]["pos"][0:2]
        if self._is_faulty_coordinate(x, y, True):
            msg = "Probing within a faulty area"
            if not allow_faulty:
                raise self.printer.command_error(msg)
            else:
                self.gcode.respond_raw("!! " + msg + "\n")

        if dist > target + tdt:
            # If we are above the dive threshold right now, we'll need to
            # do probing move and then re-measure
            self._probing_move_to_probing_height(speed)
            (dist, samples) = self._sample(self.z_settling_time, num_samples)
        elif math.isinf(dist) and dist < 0:
            # We were below the valid range of the model
            msg = "Attempted to probe with Scanner below calibrated model range"
            raise self.printer.command_error(msg)
        elif self.toolhead.get_position()[2] < target - tdt:
            # We are below the probing target height, we'll move to the
            # correct height and take a new sample.
            self._move_to_probing_height(speed)
            (dist, samples) = self._sample(self.z_settling_time, num_samples)
        pos = samples[0]["pos"]
        if verbose:
            if skip == 1:
                skipped_msg = " - SKIPPED - result not added"
            self.gcode.respond_info(
                "probe at %.3f,%.3f,%.3f is z=%.6f %s"
                % (pos[0], pos[1], pos[2], dist, skipped_msg)
            )

        return [pos[0], pos[1], pos[2] + target - dist]

    # Calibration routines
    def _start_calibration(self, gcmd: GCodeCommand):
        nozzle_z = gcmd.get_float("NOZZLE_Z", self.cal_config["nozzle_z"])
        touch_location_x = gcmd.get_float(
            "TOUCH_LOCATION_X", float(self.touch_location[0])
        )
        touch_location_y = gcmd.get_float(
            "TOUCH_LOCATION_Y", float(self.touch_location[1])
        )
        if self.calibration_method == "touch":
            self.trigger_method = TriggerMethod.TOUCH
        allow_faulty = gcmd.get_int("ALLOW_FAULTY_COORDINATE", 0) != 0
        if (
            self.trigger_method != TriggerMethod.SCAN
            and gcmd.get("METHOD", "manual").lower() != "manual"
        ):
            self._move([touch_location_x, touch_location_y, None], 40)
            pos = self.toolhead.get_position()
            self.toolhead.wait_moves()
            curtime = self.printer.get_reactor().monotonic()
            status = self.toolhead.get_kinematics().get_status(curtime)
            pos[2] = status["axis_maximum"][2]
            self.toolhead.set_position(pos, homing_axes=(0, 1, 2))
            self.touch_probe(self.probe_speed)
            self.toolhead.set_position(pos)
            self._move([None, None, 0], self.lift_speed)
            kin = self.toolhead.get_kinematics()
            kin_spos = {
                s.get_name(): s.get_commanded_position() for s in kin.get_steppers()
            }
            kin_pos = kin.calc_position(kin_spos)
            if self._is_faulty_coordinate(kin_pos[0], kin_pos[1]):
                msg = "Calibrating within a faulty area"
                if not allow_faulty:
                    raise gcmd.error(msg)
                else:
                    gcmd.respond_raw("!! " + msg + "\n")
            self._calibrate(
                gcmd, kin_pos, nozzle_z, forced_z=False, touch=False, manual_mode=False
            )
            self.trigger_method = TriggerMethod.SCAN

        elif gcmd.get("SKIP_MANUAL_PROBE", None) is not None:
            kin = self.toolhead.get_kinematics()
            kin_spos = {
                s.get_name(): s.get_commanded_position() for s in kin.get_steppers()
            }
            kin_pos = kin.calc_position(kin_spos)
            if self._is_faulty_coordinate(kin_pos[0], kin_pos[1]):
                msg = "Calibrating within a faulty area"
                if not allow_faulty:
                    raise gcmd.error(msg)
                else:
                    gcmd.respond_raw("!! " + msg + "\n")
            self._calibrate(
                gcmd, kin_pos, nozzle_z, forced_z=False, touch=False, manual_mode=False
            )
        else:
            curtime = self.printer.get_reactor().monotonic()
            kin_status = self.toolhead.get_kinematics().get_status(curtime)
            if "xy" not in kin_status["homed_axes"]:
                raise self.printer.command_error("Must home X and Y before calibration")

            kin_pos = self.toolhead.get_position()
            if self._is_faulty_coordinate(kin_pos[0], kin_pos[1]):
                msg = "Calibrating within a faulty area"
                if not allow_faulty:
                    raise gcmd.error(msg)
                else:
                    gcmd.respond_raw("!! " + msg + "\n")

            forced_z = False
            if "z" not in kin_status["homed_axes"]:
                self.toolhead.get_last_move_time()
                pos = self.toolhead.get_position()
                pos[2] = (
                    kin_status["axis_maximum"][2]
                    - 2.0
                    - gcmd.get_float("CEIL", self.cal_config["ceil"])
                )
                self.toolhead.set_position(pos, homing_axes=[2])
                forced_z = True
            self._move([touch_location_x, touch_location_y, None], 40)
            self.toolhead.wait_moves()

            def cb(kin_pos):
                return self._calibrate(
                    gcmd,
                    kin_pos,
                    cal_nozzle_z=None,
                    forced_z=forced_z,
                    touch=False,
                    manual_mode=True,
                )

            manual_probe.ManualProbeHelper(self.printer, gcmd, cb)

    def _calibrate(
        self,
        gcmd: GCodeCommand,
        kin_pos,
        cal_nozzle_z: Optional[float] = None,
        forced_z=None,
        touch=False,
        manual_mode=False,
    ):
        if kin_pos is None:
            self.trigger_method = TriggerMethod.SCAN
            self._zhop()
            if forced_z:
                kin = self.toolhead.get_kinematics()
                if hasattr(kin, "note_z_not_homed"):
                    kin.note_z_not_homed()
            return
        gcmd.respond_info("Scanner calibration starting")
        cal_floor = gcmd.get_float("FLOOR", self.cal_config["floor"])
        cal_ceil = gcmd.get_float("CEIL", self.cal_config["ceil"])
        cal_speed = gcmd.get_float("SPEED", self.cal_config["speed"])
        move_speed = gcmd.get_float("MOVE_SPEED", self.cal_config["move_speed"])
        model_name = gcmd.get("MODEL_NAME", "default")

        toolhead = self.toolhead
        toolhead.wait_moves()

        if manual_mode:
            nozzle_z = gcmd.get_float("NOZZLE_Z", self.cal_config["nozzle_z"])
            cal_min_z = kin_pos[2] - nozzle_z + cal_floor
            cal_max_z = kin_pos[2] - nozzle_z + cal_ceil
        elif cal_nozzle_z is None:
            raise Exception(
                "A calculated nozzle Z position is required if not in manual mode,"
                + " this is an error in our code."
            )
        else:
            curpos = toolhead.get_position()
            curpos[2] = cal_nozzle_z
            toolhead.set_position(curpos)
            cal_min_z = cal_floor
            cal_max_z = cal_ceil

        # Move to probe coordinates and compensate for backlash
        curpos = toolhead.get_position()
        curpos[2] = cal_max_z + self.backlash_comp
        curpos[0] -= self.offset["x"]
        curpos[1] -= self.offset["y"]
        toolhead.manual_move(curpos, move_speed)  # Move up and over
        curpos[2] = cal_max_z
        toolhead.manual_move(curpos, move_speed)  # Move down
        toolhead.wait_moves()

        samples = []

        def cb(sample):
            samples.append(sample)

        try:
            self._start_streaming()
            self._sample_printtime_sync(50)
            with self.streaming_session(cb):
                self._sample_printtime_sync(50)
                toolhead.dwell(0.250)
                curpos[2] = cal_min_z
                toolhead.manual_move(curpos, cal_speed)
                toolhead.dwell(0.250)
                self._sample_printtime_sync(50)
        except Exception as e:
            print(f"Error encounted while calibrating: {e}")
            self.trigger_method = TriggerMethod.SCAN
            self._zhop()
        finally:
            self._stop_streaming()

        # Fit the sampled data
        z_offset = [
            s["pos"][2] - (cal_min_z if manual_mode else 0) + cal_floor for s in samples
        ]
        freq = [s["freq"] for s in samples]
        temp = [s["temp"] for s in samples]
        inv_freq = [1 / f for f in freq]
        poly = np.polynomial.Polynomial.fit(inv_freq, z_offset, 9)
        temp_median = median(temp)
        self.model = ScannerModel(
            model_name,
            self,
            poly,
            temp_median,
            min(z_offset),
            max(z_offset),
            self.calibration_method,
            0.0,
            self.fw_version,
        )
        self.models[self.model.name] = self.model
        self.model.save()
        self._apply_threshold()

        toolhead.get_last_move_time()
        pos = toolhead.get_position()
        pos[2] = cal_floor
        toolhead.set_position(pos)

        # Dump calibration curve
        fn = f"/tmp/scanner-calibrate-{time.strftime('%Y%m%d_%H%M%S')}.csv"
        with open(fn, "w") as f:
            f.write("freq,z,temp\n")
            for i in range(len(freq)):
                f.write(f"{freq[i]:.5f},{z_offset[i]:.5f},{temp[i]:.3f}\n")

        gcmd.respond_info(
            "Scanner calibrated at %.3f,%.3f from %.3f to %.3f, speed %.2f mm/s, temp %.2fC"
            % (pos[0], pos[1], cal_min_z, cal_max_z, cal_speed, temp_median)
        )
        self.trigger_method = TriggerMethod.SCAN
        self._zhop()

    # Internal

    def _update_thresholds(self, moving_up=False):
        self.trigger_freq = self.dist_to_freq(self.trigger_distance, self.last_temp)
        if self.trigger_freq is None:
            return
        self.untrigger_freq = self.trigger_freq * (1 - self.trigger_hysteresis)

    def _apply_threshold(self, moving_up=False):
        self._update_thresholds()
        trigger_c = int(self.freq_to_count(self.trigger_freq))
        untrigger_c = int(self.freq_to_count(self.untrigger_freq))
        self.scanner_set_threshold.send([trigger_c, untrigger_c])

    def register_model(self, name: str, model: "ScannerModel"):
        if name in self.models:
            raise self.printer.config_error(
                "Multiple Scanner models with same name '%s'" % (name,)
            )
        self.models[name] = model

    def _is_faulty_coordinate(self, x, y, add_offsets=False):
        if not self.mesh_helper:
            return False
        return self.mesh_helper._is_faulty_coordinate(x, y, add_offsets)

        # Streaming mode

    def _check_hardware(self, sample):
        if not self.hardware_failure:
            msg = None
            if sample["data"] == 0xFFFFFFF:
                msg = "coil is shorted or not connected"
            elif self.fmin is not None and sample["freq"] > 1.35 * self.fmin:
                msg = "coil expected max frequency exceeded"
            if msg:
                msg = "Scanner hardware issue: " + msg
                self.hardware_failure = msg
                logging.error(msg)
                if self._stream_en:
                    self.printer.invoke_shutdown(msg)
                else:
                    self.gcode.respond_raw("!! " + msg + "\n")
        elif self._stream_en:
            self.printer.invoke_shutdown(self.hardware_failure)

    def _enrich_sample_time(self, sample):
        clock = sample["clock"] = self._mcu.clock32_to_clock64(sample["clock"])
        sample["time"] = self._mcu.clock_to_print_time(clock)

    def _enrich_sample_temp(self, sample):
        if self.thermistor_override is None:
            temp_adc = sample["temp"] / self.temp_smooth_count * self.inv_adc_max
            sample["temp"] = self.thermistor.calc_temp(temp_adc)
        else:
            sample["temp"], _ = self.thermistor_override.get_temp(sample["time"])

    def _enrich_sample_freq(self, sample):
        sample["data_smooth"] = self._data_filter.value()
        sample["freq"] = self.count_to_freq(sample["data_smooth"])
        self._check_hardware(sample)

    def _enrich_sample(self, sample):
        sample["dist"] = self.freq_to_dist(sample["freq"], sample["temp"])
        pos, vel = self._get_trapq_position(sample["time"])

        if pos is None:
            return
        if sample["dist"] is not None and self.mod_axis_twist_comp is not None:
            sample["dist"] -= self.mod_axis_twist_comp(pos)
        sample["pos"] = pos
        sample["vel"] = vel

    def _start_streaming(self):
        if self._stream_en == 0:
            self.scanner_stream_cmd.send([1])
            curtime = self.reactor.monotonic()
            self.reactor.update_timer(
                self._stream_timeout_timer, curtime + STREAM_TIMEOUT
            )
        self._stream_en += 1
        self._data_filter.reset()
        self._stream_flush()

    def _stop_streaming(self):
        self._stream_en -= 1
        if self._stream_en == 0:
            self.reactor.update_timer(self._stream_timeout_timer, self.reactor.NEVER)
            self.scanner_stream_cmd.send([0])
        self._stream_flush()

    def _stream_timeout(self, _: float):
        if not self._stream_en:
            return self.reactor.NEVER
        msg = "Scanner sensor not receiving data"
        logging.error(msg)
        self.printer.invoke_shutdown(msg)
        return self.reactor.NEVER

    def request_stream_latency(self, latency):
        next_key = 0
        if self._stream_latency_requests:
            next_key = max(self._stream_latency_requests.keys()) + 1
        new_limit = STREAM_BUFFER_LIMIT_DEFAULT
        self._stream_latency_requests[next_key] = latency
        min_requested = min(self._stream_latency_requests.values())
        if min_requested < new_limit:
            new_limit = min_requested
        if new_limit < 1:
            new_limit = 1
        self._stream_buffer_limit_new = new_limit
        return next_key

    def drop_stream_latency_request(self, key):
        self._stream_latency_requests.pop(key, None)
        new_limit = STREAM_BUFFER_LIMIT_DEFAULT
        if self._stream_latency_requests:
            min_requested = min(self._stream_latency_requests.values())
            if min_requested < new_limit:
                new_limit = min_requested
        if new_limit < 1:
            new_limit = 1
        self._stream_buffer_limit_new = new_limit

    def streaming_session(self, callback, completion_callback=None, latency=None):
        return StreamingHelper(self, callback, completion_callback, latency)

    def _stream_flush(self):
        self._stream_flush_event.clear()
        while True:
            try:
                samples = self._stream_samples_queue.get_nowait()
                updated_timer = False
                last = None
                for sample in samples:
                    if not updated_timer:
                        curtime = self.reactor.monotonic()
                        self.reactor.update_timer(
                            self._stream_timeout_timer, curtime + STREAM_TIMEOUT
                        )
                        updated_timer = True

                    self._enrich_sample_time(sample)
                    self._enrich_sample_temp(sample)
                    temp = sample["temp"]
                    if self.model_temp is not None and not (-40 < temp < 180):
                        if self.model_temp_warning_disable != 1:
                            msg = (
                                "Scanner temperature sensor faulty(read %.2f C),"
                                " disabling temperaure compensation" % (temp,)
                            )
                            logging.error(msg)
                            self.gcode.respond_raw("!! " + msg + "\n")
                        self.model_temp = None

                    self.last_temp = temp
                    if temp:
                        self.measured_min = min(self.measured_min, temp)
                        self.measured_max = max(self.measured_max, temp)

                    self._data_filter.update(sample["time"], sample["data"])
                    self._enrich_sample_freq(sample)
                    self._enrich_sample(sample)

                    if len(self._stream_callbacks) > 0:
                        for cb in list(self._stream_callbacks.values()):
                            cb(sample)
                    last = sample
                if last is not None:
                    last = last.copy()
                    dist = last["dist"]
                    if dist is None or np.isinf(dist) or np.isnan(dist):
                        del last["dist"]
                    self.last_received_sample = last
            except queue.Empty:
                return

    def _stream_flush_schedule(self):
        force = self._stream_en == 0  # When streaming is disabled, let all through
        if self._stream_buffer_limit_new != self._stream_buffer_limit:
            force = True
            self._stream_buffer_limit = self._stream_buffer_limit_new
        if not force and len(self._stream_buffer) < self._stream_buffer_limit:
            return
        self._stream_samples_queue.put_nowait(self._stream_buffer)
        self._stream_buffer = []
        if self._stream_flush_event.is_set():
            return
        self._stream_flush_event.set()
        self.reactor.register_async_callback(lambda e: self._stream_flush())

    def _handle_scanner_data(self, params):
        if self.trapq is None:
            return

        self._stream_buffer.append(params.copy())
        self._stream_flush_schedule()

    def _get_trapq_position(
        self, print_time: float
    ) -> "tuple[list[float] | None, float | None]":
        ffi_main, ffi_lib = chelper.get_ffi()
        data = ffi_main.new("struct pull_move[1]")
        count = ffi_lib.trapq_extract_old(self.trapq, data, 1, 0.0, print_time)
        if not count:
            return None, None
        move = data[0]
        move_time = max(0.0, min(move.move_t, print_time - move.print_time))
        dist = (move.start_v + 0.5 * move.accel * move_time) * move_time
        pos = [
            move.start_x + move.x_r * dist,
            move.start_y + move.y_r * dist,
            move.start_z + move.z_r * dist,
        ]
        velocity = move.start_v + move.accel * move_time
        return pos, velocity

    def _sample_printtime_sync(self, skip=0, count=1):
        move_time = self.toolhead.get_last_move_time()
        settle_clock = self._mcu.print_time_to_clock(move_time)
        samples = []
        total = skip + count

        def cb(sample):
            if sample["clock"] >= settle_clock:
                samples.append(sample)
                if len(samples) >= total:
                    raise StopStreaming

        with self.streaming_session(cb, latency=skip + count) as ss:
            ss.wait()

        samples = samples[skip:]

        if count == 1:
            return samples[0]
        else:
            return samples

    def _sample(self, skip, count):
        samples = self._sample_printtime_sync(skip, count)
        return (median([s["dist"] for s in samples]), samples)

    def _sample_async(self):
        # TODO: This is only used to get one sample, let's make it clearer.
        count = 1
        samples = []

        def cb(sample):
            samples.append(sample)
            if len(samples) >= count:
                raise StopStreaming

        with self.streaming_session(cb, latency=count) as ss:
            ss.wait()

        return samples[0]

    def count_to_freq(self, count):
        return count * self.sensor_freq / (2**28)

    def freq_to_count(self, freq):
        return freq * (2**28) / self.sensor_freq

    def dist_to_freq(self, dist, temp):
        if self.model is None:
            return None
        return self.model.dist_to_freq(dist, temp)

    def freq_to_dist(self, freq, temp):
        if self.model is None:
            return None
        return self.model.freq_to_dist(freq, temp)

    def get_status(self, eventtime):
        model = None
        if self.model is not None:
            model = self.model.name
        return {
            "last_sample": self.last_sample,
            "last_received_sample": self.last_received_sample,
            "model": model,
        }

    # Webhook handlers

    def _handle_req_status(self, web_request: WebRequest):
        temp = None
        sample = self._sample_async()
        out = {
            "freq": sample["freq"],
            "dist": sample["dist"],
        }
        temp = sample["temp"]
        if temp is not None:
            out["temp"] = temp
        web_request.send(out)

    def _handle_req_dump(self, web_request: WebRequest):
        self._api_dump_helper.add_client(web_request)

    # GCode command handlers
    cmd_PROBE_SWITCH_help = "swith between scan and touch"

    def cmd_PROBE_SWITCH(self, gcmd: GCodeCommand):
        method = gcmd.get("MODE", "NONE").lower()
        if method == "scan":
            self.calibration_method = "scan"
            self.trigger_method = TriggerMethod.SCAN
            configfile = self.printer.lookup_object("configfile")
            configfile.set("scanner", "mode", "scan")
            gcmd.respond_info(
                f"Mode switched to SCAN. Please use {format_macro('SAVE_CONFIG')} to save this mode."
            )
        elif method == "touch":
            self.calibration_method = "touch"
            self.trigger_method = TriggerMethod.TOUCH
            configfile = self.printer.lookup_object("configfile")
            configfile.set("scanner", "mode", "touch")
            gcmd.respond_info(
                f"Mode switched to TOUCH. Please use {format_macro('SAVE_CONFIG')} to save this mode."
            )
        threshold = gcmd.get_int("THRESHOLD", self.detect_threshold_z)
        if self.detect_threshold_z != threshold:
            self.detect_threshold_z = threshold
            configfile = self.printer.lookup_object("configfile")
            configfile.set("scanner", "scanner_touch_threshold", threshold)
            gcmd.respond_info("Detect Threshold Changed %d" % (threshold))

    cmd_PROBE_help = "Probe Z-height at current XY position"

    def cmd_PROBE(self, gcmd: GCodeCommand):
        pos = self.run_probe(gcmd)
        gcmd.respond_info("Result is z=%.6f" % (pos[2],))
        self.last_z_result = pos[2]

    def _save_threshold(self, threshold: int, speed: float):
        configfile = self.printer.lookup_object("configfile")
        configfile.set("scanner", "scanner_touch_threshold", "%d" % int(threshold))
        configfile.set("scanner", "scanner_touch_speed", "%d" % int(speed))

    cmd_SCANNER_ESTIMATE_BACKLASH_help = "Estimate Z axis backlash"

    def cmd_SCANNER_ESTIMATE_BACKLASH(self, gcmd: GCodeCommand):
        # Get to correct Z height
        overrun = gcmd.get_float("OVERRUN", 1.0)
        speed = gcmd.get_float("PROBE_SPEED", self.speed, above=0.0)
        cur_z = self.toolhead.get_position()[2]
        self.toolhead.manual_move([None, None, cur_z + overrun], speed)
        _ = self.run_probe(gcmd)

        lift_speed = self.get_lift_speed(gcmd)
        target = gcmd.get_float("Z", self.trigger_distance)

        num_samples = gcmd.get_int("SAMPLES", 20)
        wait = self.z_settling_time

        samples_up = []
        samples_down = []

        next_dir = -1

        try:
            self._start_streaming()

            (cur_dist, _samples) = self._sample(wait, 10)
            pos = self.toolhead.get_position()
            missing = target - cur_dist
            target = pos[2] + missing
            gcmd.respond_info("Target kinematic Z is %.3f" % (target,))

            if target - overrun < 0:
                raise gcmd.error("Target minus overrun must exceed 0mm")

            while len(samples_up) + len(samples_down) < num_samples:
                liftpos = [None, None, target + overrun * next_dir]
                self.toolhead.manual_move(liftpos, lift_speed)
                liftpos = [None, None, target]
                self.toolhead.manual_move(liftpos, lift_speed)
                self.toolhead.wait_moves()
                (dist, _samples) = self._sample(wait, 10)
                {-1: samples_up, 1: samples_down}[next_dir].append(dist)
                next_dir = next_dir * -1

        finally:
            self._stop_streaming()

        res_up = median(samples_up)
        res_down = median(samples_down)

        gcmd.respond_info(
            "Median distance moving up %.5f, down %.5f, "
            "delta %.5f over %d samples"
            % (res_up, res_down, res_down - res_up, num_samples)
        )

    cmd_SCANNER_QUERY_help = "Take a sample from the sensor"

    def cmd_SCANNER_QUERY(self, gcmd: GCodeCommand):
        sample = self._sample_async()
        last_value = sample["freq"]
        dist = sample["dist"]
        temp = sample["temp"]
        self.last_sample = {
            "time": sample["time"],
            "value": last_value,
            "temp": temp,
            "dist": None if dist is None or np.isinf(dist) or np.isnan(dist) else dist,
        }
        if dist is None:
            gcmd.respond_info(
                "Last reading: %.2fHz, %.2fC, no model"
                % (
                    last_value,
                    temp,
                )
            )
        else:
            gcmd.respond_info(
                "Last reading: %.2fHz, %.2fC, %.5fmm" % (last_value, temp, dist)
            )

    cmd_SCANNER_STREAM_help = "Enable Scanner Streaming"

    def cmd_SCANNER_STREAM(self, gcmd: GCodeCommand):
        if self._log_stream is not None:
            self._log_stream.stop()
            self._log_stream = None
            gcmd.respond_info("Scanner Streaming disabled")
        else:
            f = None
            completion_cb = None
            fn = os.path.join("/tmp", gcmd.get("FILENAME"))
            f = open(fn, "w")

            def close_file():
                f.close()

            completion_cb = close_file
            f.write("time,data,data_smooth,freq,dist,temp,pos_x,pos_y,pos_z,vel\n")

            def cb(sample):
                pos = sample.get("pos", None)
                obj = "%.4f,%d,%.2f,%.5f,%.5f,%.2f,%s,%s,%s,%s\n" % (
                    sample["time"],
                    sample["data"],
                    sample["data_smooth"],
                    sample["freq"],
                    sample["dist"],
                    sample["temp"],
                    "%.3f" % (pos[0],) if pos is not None else "",
                    "%.3f" % (pos[1],) if pos is not None else "",
                    "%.3f" % (pos[2],) if pos is not None else "",
                    "%.3f" % (sample["vel"],) if "vel" in sample else "",
                )
                f.write(obj)

            self._log_stream = self.streaming_session(cb, completion_cb)
            gcmd.respond_info("Scanner Streaming enabled")

    cmd_PROBE_ACCURACY_help = "Probe Z-height accuracy at current XY position"

    def cmd_PROBE_ACCURACY(self, gcmd: GCodeCommand):
        speed = gcmd.get_float("PROBE_SPEED", self.probe_speed, above=0.0)
        lift_speed = self.get_lift_speed(gcmd)
        sample_count = gcmd.get_int("SAMPLES", 10, minval=1)
        skip_samples = gcmd.get_int("SKIP", 0)
        sample_retract_dist = self.get_sample_retract_dist(gcmd)
        allow_faulty = gcmd.get_int("ALLOW_FAULTY_COORDINATE", 0) != 0
        pos = self.toolhead.get_position()
        gcmd.respond_info(
            "PROBE_ACCURACY at X:%.3f Y:%.3f Z:%.3f"
            " (samples=%d sample_retract_dist=%.3f"
            " speed=%.1f lift_speed=%.1f skip=%d)\n"
            % (
                pos[0],
                pos[1],
                pos[2],
                sample_count,
                sample_retract_dist,
                speed,
                lift_speed,
                skip_samples,
            )
        )

        result = self._probe_accuracy_check(
            speed,
            skip_samples,
            sample_count,
            sample_retract_dist,
            allow_faulty,
            lift_speed,
        )

        gcmd.respond_info(
            "probe accuracy results: maximum %.6f, minimum %.6f, range %.6f, "
            "average %.6f, median %.6f, standard deviation %.6f"
            % (
                result.max_value,
                result.min_value,
                result.range_value,
                result.avg_value,
                result.median,
                result.sigma,
            )
        )

    def _probe_accuracy_check(
        self,
        speed,
        skip_samples,
        sample_count,
        sample_retract_dist,
        allow_faulty,
        lift_speed,
        verbose=True,
        abort_range=float("inf"),
    ):
        pos = self.toolhead.get_position()

        start_height = self.trigger_distance + sample_retract_dist
        liftpos = [None, None, start_height]
        cur_range_value = 0
        positions: list[list[float]] = []
        if self.trigger_method == TriggerMethod.SCAN:
            self.toolhead.manual_move(liftpos, lift_speed)
            self.multi_probe_begin()
            while (len(positions) < sample_count) and (cur_range_value < abort_range):
                if len(positions) < skip_samples:
                    pos = self._probe(
                        speed, skip=1, allow_faulty=allow_faulty, verbose=verbose
                    )  # Pass skip=1 if sample is skipped
                else:
                    pos = self._probe(
                        speed, skip=0, allow_faulty=allow_faulty, verbose=verbose
                    )  # Normal probe
                positions.append(pos)
                self.toolhead.manual_move(liftpos, lift_speed)
                cur_zs = [p[2] for p in positions[skip_samples:]]
                cur_range_value = max(cur_zs) - min(cur_zs) if cur_zs else 0
            self.multi_probe_end()
        else:
            while (len(positions) < sample_count) and (cur_range_value < abort_range):
                try:
                    if len(positions) < skip_samples:
                        pos = self.touch_probe(
                            speed, skip=1, verbose=verbose
                        )  # Pass skip=1 if sample is skipped
                    else:
                        pos = self.touch_probe(
                            speed, skip=0, verbose=verbose
                        )  # Normal probe
                except Exception as e:
                    toolhead = self.printer.lookup_object("toolhead")
                    curtime = self.printer.get_reactor().monotonic()
                    if "z" not in toolhead.get_status(curtime)["homed_axes"]:
                        raise e
                    else:
                        pos = [float("inf"), float("inf"), float("inf")]
                self.toolhead.manual_move(liftpos, lift_speed)
                positions.append(pos)
                cur_zs = [p[2] for p in positions[skip_samples:]]
                cur_range_value = max(cur_zs) - min(cur_zs) if cur_zs else 0
        zs = [p[2] for p in positions[skip_samples:]]
        if not zs:
            return ThresholdResults(
                max_value=math.inf,
                min_value=-math.inf,
                range_value=math.inf,
                avg_value=math.inf,
                median=math.inf,
                sigma=math.inf,
                in_range=0,
                early=0,
                late=0,
                nb_samples=0,
            )

        max_value = max(zs)
        min_value = min(zs)
        range_value = max_value - min_value
        avg_value = sum(zs) / len(positions)
        median_ = median(zs)

        in_range = 0
        early = 0
        late = 0

        for sampl in zs:
            if abs(median_ - sampl) < 0.05:
                in_range += 1
            elif sampl > median_:
                early += 1
            else:
                late += 1

        deviation_sum = 0
        for i in range(len(zs)):
            deviation_sum += pow(zs[i] - avg_value, 2)
        sigma = math.sqrt(deviation_sum / len(zs))

        return ThresholdResults(
            max_value=max_value,
            min_value=min_value,
            range_value=range_value,
            avg_value=avg_value,
            median=median_,
            sigma=sigma,
            in_range=in_range,
            early=early,
            late=late,
            nb_samples=len(zs),
        )

    cmd_Z_OFFSET_APPLY_PROBE_help = "Adjust the probe's z_offset"

    def cmd_Z_OFFSET_APPLY_PROBE(self, gcmd: GCodeCommand):
        gcode_move = self.printer.lookup_object("gcode_move")
        offset = gcode_move.get_status()["homing_origin"].z
        if offset == 0:
            self.gcode.respond_info("Nothing to do: Z Offset is 0")
            return

        if not self.model:
            raise self.gcode.error("You must calibrate your model first.")

        if self.calibration_method == "touch":
            newoffset = self.scanner_touch_config["z_offset"]
            newoffset += offset
            if newoffset < 0:
                self.scanner_touch_config["z_offset"] = 0
                configfile = self.printer.lookup_object("configfile")
                configfile.set("scanner", "scanner_touch_z_offset", "%.3f" % 0)
                gcmd.respond_info(
                    f"Touch offset attempted to update to {newoffset:.3f}.\n"
                    "However it cannot be less than 0. So its been set to 0.\n"
                    "Please check your printers calibration and try again."
                )
                return

            else:
                # We use the model code to save the new offset, but we can't actually
                # apply that offset yet because the gcode_offset is still in effect.
                # If the user continues to do stuff after this, the newly set model
                # offset would compound with the gcode offset. To ensure this doesn't
                # happen, we revert to the old model offset afterwards.
                # Really, the user should just be calling `SAVE_CONFIG` now.
                self.scanner_touch_config["z_offset"] = newoffset
                configfile = self.printer.lookup_object("configfile")
                configfile.set(
                    "scanner",
                    "scanner_touch_z_offset",
                    "%.3f" % self.scanner_touch_config["z_offset"],
                )
                gcmd.respond_info(
                    f"Touch offset has been updated by {offset:.3f} to {self.scanner_touch_config['z_offset']:.3f}.\n"
                    f"You must run the {format_macro('SAVE_CONFIG')} command now to update the\n"
                    "printer config file and restart the printer."
                )
        else:
            self.model.offset += offset
            self.model.save(False)
            gcmd.respond_info(
                f"Scanner model offset has been updated to {self.model.offset:.3f}.\n"
                f"You must run the {format_macro('SAVE_CONFIG')} command now to update the\n"
                "printer config file and restart the printer."
            )


class TouchSettings:
    def __init__(
        self,
        initial_position,
        homing_position,
        accel,
        speed,
        retract_dist,
        retract_speed,
        num_samples,
        tolerance,
        max_retries,
        z_max,
        max_accel,
        test_threshold,
        manual_z_offset,
        randomize,
    ):
        self.initial_position = initial_position
        self.homing_position = homing_position
        self.accel = accel
        self.speed = speed
        self.retract_dist = retract_dist
        self.retract_speed = retract_speed
        self.num_samples = num_samples
        self.tolerance = tolerance
        self.max_retries = max_retries
        self.z_max = z_max
        self.max_accel = max_accel
        self.test_threshold = test_threshold
        self.manual_z_offset = manual_z_offset
        self.randomize = randomize


@final
class ScannerModel:
    _CONFIG_FW_VERSION = "model_fw_version"

    @staticmethod
    def load(name: str, config: ConfigWrapper, scanner: Scanner):
        coef = config.getfloatlist("model_coef")
        temp = config.getfloat("model_temp")
        domain = config.getfloatlist("model_domain", count=2)
        [min_z, max_z] = config.getfloatlist("model_range", count=2)
        offset = config.getfloat("model_offset", 0.0)
        mode = config.get("model_mode", "unknown")
        fw_version = config.get(ScannerModel._CONFIG_FW_VERSION, "UNKNOWN")
        poly = np.polynomial.Polynomial(coef, domain)
        return ScannerModel(
            name, scanner, poly, temp, min_z, max_z, mode, offset, fw_version
        )

    def __init__(
        self,
        name: str,
        scanner: Scanner,
        poly: np.polynomial.Polynomial,
        temp: float,
        min_z: float,
        max_z: float,
        mode: str,
        offset: float,
        fw_version: str,
    ):
        self.name = name
        self.scanner = scanner
        self.poly = poly
        self.min_z = min_z
        self.max_z = max_z
        self.temp = temp
        self.offset = offset
        self.mode = mode
        self.fw_version = fw_version

    def save(self, show_message: bool = True):
        configfile = self.scanner.printer.lookup_object("configfile")
        section = "scanner model " + self.name
        configfile.set(section, "model_coef", ",\n  ".join(map(str, self.poly.coef)))
        configfile.set(section, "model_domain", ",".join(map(str, self.poly.domain)))
        configfile.set(section, "model_range", "%f,%f" % (self.min_z, self.max_z))
        configfile.set(section, "model_temp", "%f" % (self.temp))
        configfile.set(section, "model_offset", "%.5f" % (self.offset,))
        configfile.set(section, "model_mode", "%s" % (self.scanner.calibration_method))
        configfile.set(section, ScannerModel._CONFIG_FW_VERSION, self.fw_version)
        if show_message:
            self.scanner.gcode.respond_info(
                "Scanner calibration for model '%s' has "
                f"been updated\nfor the current session. The {format_macro('SAVE_CONFIG')} "
                "command will\nupdate the printer config file and restart "
                "the printer." % (self.name,)
            )

    def validate(self) -> None:
        url = DOCS_TOUCH_CALIBRATION
        if self.scanner.calibration_method == "scan":
            url = DOCS_SCAN_CALIBRATION
        cur_fw = self.scanner.fw_version
        if cur_fw != self.fw_version:
            raise self.scanner.printer.command_error(
                f"Scanner model '{self.name}' was created with firmware version '{self.fw_version}',"
                + f"current firmware version is '{cur_fw}'."
                + " Please recalibrate your threshold and model."
                + f" Click <a href='{url}'>HERE</a> for more information"
            )
        if self.mode != self.scanner.calibration_method:
            raise self.scanner.printer.command_error(
                f"Scanner model '{self.name}' was created for '{self.mode}'."
                + f" Please create a new model for use with '{self.scanner.calibration_method}'."
                + f" Click <a href='{url}'>HERE</a> for more information"
            )

    def freq_to_dist_raw(self, freq):
        [begin, end] = self.poly.domain
        invfreq = 1 / freq
        if invfreq > end:
            return float("inf")
        elif invfreq < begin:
            return float("-inf")
        else:
            return float(self.poly(invfreq) - self.offset)

    def freq_to_dist(self, freq, temp):
        if self.temp is not None and self.scanner.model_temp is not None:
            freq = self.scanner.model_temp.compensate(freq, temp, self.temp)
        return self.freq_to_dist_raw(freq)

    def dist_to_freq_raw(self, dist, max_e=0.00000001):
        if dist < self.min_z or dist > self.max_z:
            msg = (
                "Attempted to map out-of-range distance %f, valid range "
                "[%.3f, %.3f]" % (dist, self.min_z, self.max_z)
            )
            raise self.scanner.printer.command_error(msg)
        dist += self.offset
        [begin, end] = self.poly.domain
        for _ in range(0, 50):
            f = (end + begin) / 2
            v = self.poly(f)
            if abs(v - dist) < max_e:
                return float(1.0 / f)
            elif v < dist:
                begin = f
            else:
                end = f
        raise self.scanner.printer.command_error("Scanner model convergence error")

    def dist_to_freq(self, dist, temp, max_e=0.00000001):
        freq = self.dist_to_freq_raw(dist, max_e)
        if self.temp is not None and self.scanner.model_temp is not None:
            freq = self.scanner.model_temp.compensate(freq, self.temp, temp)
        return freq


@final
class ScannerTempModelBuilder:
    _DEFAULTS: "dict[str, Optional[float]]" = {
        "a_a": None,
        "a_b": None,
        "b_a": None,
        "b_b": None,
        "fmin": None,
        "fmin_temp": None,
    }

    @staticmethod
    def load(config: ConfigWrapper):
        return ScannerTempModelBuilder(config)

    def __init__(self, config: ConfigWrapper):
        self.parameters = ScannerTempModelBuilder._DEFAULTS.copy()
        for key in self.parameters.keys():
            param = config.getfloat("tc_" + key, None)
            if param is not None:
                self.parameters[key] = param

    def build(self):
        if self.parameters["fmin"] is None or self.parameters["fmin_temp"] is None:
            return None
        logging.info("scanner: built tempco model %s", self.parameters)
        return ScannerTempModel(**self.parameters)

    def build_with_base(self, scanner: Scanner):
        base_data = scanner.scanner_base_read_cmd.send([6, 0])
        (f_count, adc_count) = struct.unpack("<IH", base_data["bytes"])
        if f_count < 0xFFFFFFFF and adc_count < 0xFFFF:
            if self.parameters["fmin"] is None:
                self.parameters["fmin"] = scanner.count_to_freq(f_count)
                logging.info(
                    "scanner: loaded fmin=%.2f from base", self.parameters["fmin"]
                )
            if self.parameters["fmin_temp"] is None:
                temp_adc = (
                    float(adc_count) / scanner.temp_smooth_count * scanner.inv_adc_max
                )
                self.parameters["fmin_temp"] = scanner.thermistor.calc_temp(temp_adc)
                logging.info(
                    "scanner: loaded fmin_temp=%.2f from base",
                    self.parameters["fmin_temp"],
                )
        else:
            logging.info("scanner: fmin parameters not found in base")
        return self.build()


class ScannerTempModel:
    def __init__(self, a_a, a_b, b_a, b_b, fmin, fmin_temp):
        self.a_a = a_a
        self.a_b = a_b
        self.b_a = b_a
        self.b_b = b_b
        self.fmin = fmin
        self.fmin_temp = fmin_temp

    def param_linear(self, x, a, b):
        return a * x + b

    def compensate(self, freq, temp_source, temp_target, tctl=None):
        if self.a_a is None or self.a_b is None or self.b_a is None or self.b_b is None:
            return freq
        A = (
            4 * (temp_source * self.a_a) ** 2
            + 4 * temp_source * self.a_a * self.b_a
            + self.b_a**2
            + 4 * self.a_a
        )
        B = (
            8 * temp_source**2 * self.a_a * self.a_b
            + 4 * temp_source * (self.a_a * self.b_b + self.a_b * self.b_a)
            + 2 * self.b_a * self.b_b
            + 4 * self.a_b
            - 4 * (freq - self.fmin) * self.a_a
        )
        C = (
            4 * (temp_source * self.a_b) ** 2
            + 4 * temp_source * self.a_b * self.b_b
            + self.b_b**2
            - 4 * (freq - self.fmin) * self.a_b
        )
        if B**2 - 4 * A * C < 0:
            param_c = (
                freq
                - self.param_linear(freq - self.fmin, self.a_a, self.a_b)
                * temp_source**2
                - self.param_linear(freq - self.fmin, self.b_a, self.b_b) * temp_source
            )
            return (
                self.param_linear(freq - self.fmin, self.a_a, self.a_b) * temp_target**2
                + self.param_linear(freq - self.fmin, self.b_a, self.b_b) * temp_target
                + param_c
            )
        ax = (np.sqrt(B**2 - 4 * A * C) - B) / 2 / A
        param_a = self.param_linear(ax, self.a_a, self.a_b)
        param_b = self.param_linear(ax, self.b_a, self.b_b)
        return param_a * (temp_target + param_b / 2 / param_a) ** 2 + ax + self.fmin


@final
class ModelManager:
    def __init__(self, scanner: Scanner):
        self.scanner = scanner
        self.gcode = scanner.printer.lookup_object("gcode")

        for sensor in [scanner.sensor, scanner.sensor_alt]:
            if sensor:  # Ensure the sensor is not None
                sensor_name = sensor.upper()
                self.gcode.register_command(
                    sensor_name + "_MODEL_SELECT",
                    self.cmd_SCANNER_MODEL_SELECT,
                    desc=self.cmd_SCANNER_MODEL_SELECT_help,
                )
                self.gcode.register_command(
                    sensor_name + "_MODEL_SAVE",
                    self.cmd_SCANNER_MODEL_SAVE,
                    desc=self.cmd_SCANNER_MODEL_SAVE_help,
                )
                self.gcode.register_command(
                    sensor_name + "_MODEL_REMOVE",
                    self.cmd_SCANNER_MODEL_REMOVE,
                    desc=self.cmd_SCANNER_MODEL_REMOVE_help,
                )
                self.gcode.register_command(
                    sensor_name + "_MODEL_LIST",
                    self.cmd_SCANNER_MODEL_LIST,
                    desc=self.cmd_SCANNER_MODEL_LIST_help,
                )

    cmd_SCANNER_MODEL_SELECT_help = "Load named scanner model"

    def cmd_SCANNER_MODEL_SELECT(self, gcmd: GCodeCommand):
        name = gcmd.get("NAME")
        model = self.scanner.models.get(name, None)
        if model is None:
            raise gcmd.error("Unknown model '%s'" % (name,))
        self.scanner.model = model
        gcmd.respond_info("Selected Scanner model '%s'" % (name,))

    cmd_SCANNER_MODEL_SAVE_help = "Save current scanner model"

    def cmd_SCANNER_MODEL_SAVE(self, gcmd: GCodeCommand):
        model = self.scanner.model
        if model is None:
            raise gcmd.error(
                "No model currently selected - make sure you have run CARTOGRAPHER_CALIBRATE first"
            )
        oldname = model.name
        name = gcmd.get("NAME", oldname)
        if name != oldname:
            model = copy.copy(model)
        model.name = name
        model.save()
        if name != oldname:
            self.scanner.models[name] = model

    cmd_SCANNER_MODEL_REMOVE_help = "Remove saved scanner model"

    def cmd_SCANNER_MODEL_REMOVE(self, gcmd: GCodeCommand):
        name = gcmd.get("NAME")
        model = self.scanner.models.get(name, None)
        if model is None:
            raise gcmd.error(f"Unknown model '{name}'")
        configfile = self.scanner.printer.lookup_object("configfile")
        section = "scanner model " + model.name
        configfile.remove_section(section)
        _ = self.scanner.models.pop(name)
        gcmd.respond_info(
            f"Model '{name}' was removed for the current session.\n"
            + f"Run {format_macro('SAVE_CONFIG')} to update the printer configuration"
            + "and restart Klipper."
        )
        if self.scanner.model == model:
            self.scanner.model = None

    cmd_SCANNER_MODEL_LIST_help = "Remove saved scanner model"

    def cmd_SCANNER_MODEL_LIST(self, gcmd: GCodeCommand):
        if not self.scanner.models:
            gcmd.respond_info("No Scanner models loaded")
            return
        gcmd.respond_info("List of loaded Scanner models:")
        current_model = self.scanner.model
        for _name, model in sorted(self.scanner.models.items()):
            if model == current_model:
                gcmd.respond_info("- %s [active]" % (model.name,))
            else:
                gcmd.respond_info("- %s" % (model.name,))


class AlphaBetaFilter:
    def __init__(self, alpha, beta):
        self.alpha = alpha
        self.beta = beta
        self.reset()

    def reset(self):
        self.xl = None
        self.vl = 0
        self.tl = None

    def update(self, time, measurement):
        if self.xl is None:
            self.xl = measurement
        if self.tl is not None:
            dt = time - self.tl
        else:
            dt = 0
        self.tl = time
        xk = self.xl + self.vl * dt
        vk = self.vl
        rk = measurement - xk
        xk = xk + self.alpha * rk
        if dt > 0:
            vk = vk + self.beta / dt * rk
        self.xl = xk
        self.vl = vk
        return xk

    def value(self):
        return self.xl


class StreamingHelper:
    def __init__(self, scanner, callback, completion_callback, latency):
        self.scanner = scanner
        self.cb = callback
        self.completion_cb = completion_callback
        self.completion = self.scanner.reactor.completion()

        self.latency_key = None
        if latency is not None:
            self.latency_key = self.scanner.request_stream_latency(latency)

        self.scanner._stream_callbacks[self] = self._handle
        self.scanner._start_streaming()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def _handle(self, sample):
        try:
            self.cb(sample)
        except StopStreaming:
            self.completion.complete(())

    def stop(self):
        if self not in self.scanner._stream_callbacks:
            return
        del self.scanner._stream_callbacks[self]
        self.scanner._stop_streaming()
        if self.latency_key is not None:
            self.scanner.drop_stream_latency_request(self.latency_key)
        if self.completion_cb is not None:
            self.completion_cb()

    def wait(self):
        self.completion.wait()
        self.stop()


class StopStreaming(Exception):
    pass


class APIDumpHelper:
    def __init__(self, scanner):
        self.scanner = scanner
        self.clients = {}
        self.stream = None
        self.buffer = []
        self.fields = ["dist", "temp", "pos", "freq", "vel", "time"]

    def _start_stop(self):
        if not self.stream and self.clients:
            self.stream = self.scanner.streaming_session(self._cb)
        elif self.stream is not None and not self.clients:
            self.stream.stop()
            self.stream = None

    def _cb(self, sample):
        tmp = [sample.get(key, None) for key in self.fields]
        self.buffer.append(tmp)
        if len(self.buffer) > 50:
            self._update_clients()

    def _update_clients(self):
        for cconn, template in list(self.clients.items()):
            if cconn.is_closed():
                del self.clients[cconn]
                self._start_stop()
                continue
            tmp = dict(template)
            tmp["params"] = self.buffer
            cconn.send(tmp)
        self.buffer = []

    def add_client(self, web_request: WebRequest):
        cconn = web_request.get_client_connection()
        template = web_request.get_dict("response_template", {})
        self.clients[cconn] = template
        self._start_stop()
        web_request.send({"header": self.fields})


class _ProbeStatus(TypedDict):
    name: str
    # last_query: int  # TODO: Support this
    last_z_result: float


@final
class ScannerWrapper:
    def __init__(self, scanner: Scanner):
        self.scanner = scanner

    def get_status(self, _eventtime: float) -> _ProbeStatus:
        return _ProbeStatus(
            name=self.scanner.name,
            last_z_result=self.scanner.last_z_result,
        )

    def multi_probe_begin(self):
        return self.scanner.multi_probe_begin()

    def multi_probe_end(self):
        return self.scanner.multi_probe_end()

    def get_offsets(self):
        return self.scanner.get_offsets()

    def get_lift_speed(self, gcmd: Optional[GCodeCommand] = None):
        return self.scanner.get_lift_speed(gcmd)

    def run_probe(self, gcmd: GCodeCommand):
        return self.scanner.run_probe(gcmd)

    def probe_prepare(self, hmove):
        pass

    def probe_finish(self, hmove):
        pass

    def get_probe_params(self, gcmd: Optional[GCodeCommand] = None):
        return {
            "probe_speed": self.scanner.probe_speed,
            "lift_speed": self.scanner.lift_speed,
        }

    def start_probe_session(self, gcmd: GCodeCommand):
        self.multi_probe_begin()
        self.scanner.results = []
        return self

    def end_probe_session(self):
        self.scanner.results = []
        self.multi_probe_end()

    def pull_probed_results(self):
        res = self.scanner.results
        self.scanner.results = []
        return res


@final
class ScannerTempWrapper:
    def __init__(self, scanner: Scanner):
        self.scanner = scanner

    def get_temp(self, eventtime: float):
        return self.scanner.last_temp, 0

    def get_status(self, eventtime: float):
        return {
            "temperature": round(self.scanner.last_temp, 2),
            "measured_min_temp": round(self.scanner.measured_min, 2),
            "measured_max_temp": round(self.scanner.measured_max, 2),
        }


TRSYNC_TIMEOUT = 0.025
TRSYNC_SINGLE_MCU_TIMEOUT = 0.250


@final
class ScannerEndstopWrapper:
    def __init__(self, scanner: Scanner):
        self.scanner = scanner
        self._mcu = scanner._mcu

        ffi_main, ffi_lib = chelper.get_ffi()
        self._trdispatch = ffi_main.gc(ffi_lib.trdispatch_alloc(), ffi_lib.free)
        self._trsyncs = [MCU_trsync(self.scanner._mcu, self._trdispatch)]

        printer = self.scanner.printer
        printer.register_event_handler("klippy:mcu_identify", self._handle_mcu_identify)
        printer.register_event_handler(
            "homing:home_rails_begin", self._handle_home_rails_begin
        )
        printer.register_event_handler(
            "homing:home_rails_end", self._handle_home_rails_end
        )
        printer.register_event_handler(
            "homing:homing_move_begin", self._handle_homing_move_begin
        )
        self.z_homed = False
        self.is_homing = False

    def _handle_mcu_identify(self):
        self.toolhead = self.scanner.printer.lookup_object("toolhead")
        kin = self.toolhead.get_kinematics()
        for stepper in kin.get_steppers():
            if stepper.is_active_axis("z"):
                self.add_stepper(stepper)

    def _handle_home_rails_begin(self, homing_state, rails):
        self.is_homing = False

    def _handle_home_rails_end(self, homing_state, rails):
        if (
            self.scanner.model is None
            and self.scanner.trigger_method == TriggerMethod.SCAN
        ):
            return

        if not self.is_homing:
            return

        if 2 not in homing_state.get_axes():
            return

        # After homing Z we perform a measurement and adjust the toolhead
        # kinematic position.
        if self.scanner.trigger_method != TriggerMethod.SCAN:
            homing_state.set_homed_position([None, None, 0])
            return
        (dist, samples) = self.scanner._sample(self.scanner.z_settling_time, 10)
        if math.isinf(dist):
            logging.error("Post-homing adjustment measured samples %s", samples)
            raise self.scanner.printer.command_error(
                "Toolhead stopped below model range"
            )
        homing_state.set_homed_position([None, None, dist])

    def _handle_homing_move_begin(self, hmove):
        if self.scanner.mcu_probe in hmove.get_mcu_endstops():
            etrsync = self._trsyncs[0]
            if self.scanner.trigger_method == TriggerMethod.TOUCH:
                self.scanner.scanner_home_cmd.send(
                    [
                        etrsync.get_oid(),
                        etrsync.REASON_ENDSTOP_HIT,
                        0,
                        self.scanner.detect_threshold_z,
                        self.scanner.trigger_method,
                    ]
                )

    def get_mcu(self):
        return self._mcu

    def add_stepper(self, stepper: MCU_stepper):
        trsyncs = {trsync.get_mcu(): trsync for trsync in self._trsyncs}
        stepper_mcu = stepper.get_mcu()
        trsync = trsyncs.get(stepper_mcu)
        if trsync is None:
            trsync = MCU_trsync(stepper_mcu, self._trdispatch)
            self._trsyncs.append(trsync)
        trsync.add_stepper(stepper)
        # Check for unsupported multi-mcu shared stepper rails, duplicated
        # from MCU_endstop
        sname = stepper.get_name()
        if sname.startswith("stepper_"):
            for ot in self._trsyncs:
                for s in ot.get_steppers():
                    if ot is not trsync and s.get_name().startswith(sname[:9]):
                        cerror = self._mcu.get_printer().config_error
                        raise cerror(
                            "Multi-mcu homing not supported on multi-mcu shared axis"
                        )

    def get_steppers(self):
        return [s for trsync in self._trsyncs for s in trsync.get_steppers()]

    def home_start(
        self, print_time, sample_time, sample_count, rest_time, triggered=True
    ):
        if self.scanner.model is not None:
            self.scanner.model.validate()
        if (
            self.scanner.model is None
            and self.scanner.trigger_method == TriggerMethod.SCAN
        ):
            raise self.scanner.printer.command_error("No Scanner model loaded")

        self.is_homing = True
        if self.scanner.trigger_method == TriggerMethod.SCAN:
            self.scanner._apply_threshold()
            self.scanner._sample_async()
        clock = self._mcu.print_time_to_clock(print_time)
        rest_ticks = self._mcu.print_time_to_clock(print_time + rest_time) - clock
        self._rest_ticks = rest_ticks
        reactor = self._mcu.get_printer().get_reactor()
        self._trigger_completion = reactor.completion()
        expire_timeout = TRSYNC_TIMEOUT
        if len(self._trsyncs) == 1:
            expire_timeout = TRSYNC_SINGLE_MCU_TIMEOUT
        for i, trsync in enumerate(self._trsyncs):
            try:
                trsync.start(print_time, self._trigger_completion, expire_timeout)  # pyright: ignore [reportCallIssue]
            except TypeError:
                offset = float(i) / len(self._trsyncs)
                trsync.start(
                    print_time, offset, self._trigger_completion, expire_timeout
                )
        etrsync = self._trsyncs[0]
        ffi_main, ffi_lib = chelper.get_ffi()
        ffi_lib.trdispatch_start(self._trdispatch, etrsync.REASON_HOST_REQUEST)

        if self.scanner.trigger_method != TriggerMethod.SCAN:
            return self._trigger_completion

        self.scanner.scanner_home_cmd.send(
            [
                etrsync.get_oid(),
                etrsync.REASON_ENDSTOP_HIT,
                0,
                self.scanner.detect_threshold_z,
                self.scanner.trigger_method,
            ]
        )
        return self._trigger_completion

    def home_wait(self, home_end_time):
        etrsync = self._trsyncs[0]
        etrsync.set_home_end_time(home_end_time)
        if self._mcu.is_fileoutput():
            self._trigger_completion.complete(True)
        _ = self._trigger_completion.wait()
        self.scanner.scanner_stop_home.send()
        ffi_main, ffi_lib = chelper.get_ffi()
        ffi_lib.trdispatch_stop(self._trdispatch)
        res = [trsync.stop() for trsync in self._trsyncs]
        if any([r == etrsync.REASON_COMMS_TIMEOUT for r in res]):
            raise self.scanner.printer.command_error(
                "Communication timeout during homing"
            )
        if res[0] != etrsync.REASON_ENDSTOP_HIT:
            return 0.0
        if self._mcu.is_fileoutput():
            return home_end_time
        return home_end_time

    def query_endstop(self, print_time):
        if self.scanner.model is None:
            return 1
        sample = self.scanner._sample_async()
        if self.scanner.trigger_freq <= sample["freq"]:
            return 1
        else:
            return 0

    def get_position_endstop(self):
        return self.scanner.trigger_distance


@final
class ScannerMeshHelper:
    @staticmethod
    def create(
        scanner: Scanner, config: ConfigWrapper
    ) -> Optional["ScannerMeshHelper"]:
        if config.has_section("bed_mesh"):
            mesh_config = config.getsection("bed_mesh")
            if mesh_config.get("mesh_radius", None) is not None:
                return None  # Use normal bed meshing for round beds
            return ScannerMeshHelper(scanner, config, mesh_config)
        else:
            return None

    def __init__(
        self,
        scanner: Scanner,
        config: ConfigWrapper,
        mesh_config: ConfigWrapper,
    ):
        self.scanner = scanner
        self.scipy = None
        self.mesh_config = mesh_config
        self.bm = self.scanner.printer.load_object(mesh_config, "bed_mesh")

        self.speed = mesh_config.getfloat("speed", 50.0, above=0.0, note_valid=False)
        self.def_min_x, self.def_min_y = mesh_config.getfloatlist(
            "mesh_min", count=2, note_valid=False
        )
        self.def_max_x, self.def_max_y = mesh_config.getfloatlist(
            "mesh_max", count=2, note_valid=False
        )
        self.def_res_x, self.def_res_y = mesh_config.getintlist(
            "probe_count", count=2, note_valid=False
        )
        self.rri = mesh_config.getint(
            "relative_reference_index", None, note_valid=False
        )
        self.zero_ref_pos = mesh_config.getfloatlist(
            "zero_reference_position", None, count=2
        )
        self.zero_ref_pos_cluster_size = config.getfloat(
            "zero_reference_cluster_size", 1, minval=0
        )
        self.dir = config.getchoice(
            "mesh_main_direction", {"x": "x", "X": "x", "y": "y", "Y": "y"}, "x"
        )
        self.overscan = config.getfloat("mesh_overscan", -1, minval=0)
        self.cluster_size = config.getfloat("mesh_cluster_size", 1, minval=0)
        self.runs = config.getint("mesh_runs", 1, minval=1)
        self.adaptive_margin = mesh_config.getfloat(
            "adaptive_margin", 0, note_valid=False
        )

        if self.zero_ref_pos is not None and self.rri is not None:
            logging.info(
                "Scanner: both 'zero_reference_position' and "
                "'relative_reference_index' options are specified. The"
                " former will be used"
            )

        self.faulty_region_ = []
        self.faulty_regions = []
        for i in list(range(1, 100, 1)):
            start = mesh_config.getfloatlist(
                "faulty_region_%d_min" % (i,), None, count=2
            )
            if start is None:
                break
            end = mesh_config.getfloatlist("faulty_region_%d_max" % (i,), count=2)
            x_min = min(start[0], end[0])
            x_max = max(start[0], end[0])
            y_min = min(start[1], end[1])
            y_max = max(start[1], end[1])
            self.faulty_regions.append(Region(x_min, x_max, y_min, y_max))
            self.faulty_region_.append([x_min, y_min, x_max, y_max])
        self.faulty_region_ = np.array(self.faulty_region_).T
        self.exclude_object = None
        self.scanner.printer.register_event_handler(
            "klippy:connect", self._handle_connect
        )

        self.gcode = self.scanner.printer.lookup_object("gcode")
        self.prev_gcmd = self.gcode.register_command("BED_MESH_CALIBRATE", None)
        self.gcode.register_command(
            "BED_MESH_CALIBRATE",
            self.cmd_BED_MESH_CALIBRATE,
            desc=self.cmd_BED_MESH_CALIBRATE_help,
        )

        if self.overscan < 0:
            printer = self.scanner.printer
            printer.register_event_handler(
                "klippy:mcu_identify", self._handle_mcu_identify
            )

    cmd_BED_MESH_CALIBRATE_help = "Perform Mesh Bed Leveling"

    def cmd_BED_MESH_CALIBRATE(self, gcmd: GCodeCommand):
        method = gcmd.get("METHOD", "scanner").lower()
        if method == "scanner":
            self.calibrate(gcmd)
        else:
            self.prev_gcmd(gcmd)

    def _handle_connect(self):
        self.exclude_object = self.scanner.printer.lookup_object("exclude_object", None)

    def _handle_mcu_identify(self):
        # Auto determine a safe overscan amount
        toolhead = self.scanner.printer.lookup_object("toolhead")
        curtime = self.scanner.reactor.monotonic()
        status = toolhead.get_kinematics().get_status(curtime)
        xo = self.scanner.offset["x"]
        yo = self.scanner.offset["y"]
        settings = {
            "x": {
                "range": [self.def_min_x - xo, self.def_max_x - xo],
                "machine": [status["axis_minimum"][0], status["axis_maximum"][0]],
                "count": self.def_res_y,
            },
            "y": {
                "range": [self.def_min_y - yo, self.def_max_y - yo],
                "machine": [status["axis_minimum"][1], status["axis_maximum"][1]],
                "count": self.def_res_x,
            },
        }[self.dir]

        r = settings["range"]
        m = settings["machine"]
        space = (r[1] - r[0]) / (float(settings["count"] - 1))
        self.overscan = min(
            [
                max(0, r[0] - m[0]),
                max(0, m[1] - r[1]),
                space + 2.0,  # A half circle with 2mm lead in/out
            ]
        )

    def _generate_path(self):
        xo = self.scanner.offset["x"]
        yo = self.scanner.offset["y"]
        settings = {
            "x": {
                "range_aligned": [self.min_x - xo, self.max_x - xo],
                "range_perpendicular": [self.min_y - yo, self.max_y - yo],
                "count": self.res_y,
                "swap_coord": False,
            },
            "y": {
                "range_aligned": [self.min_y - yo, self.max_y - yo],
                "range_perpendicular": [self.min_x - xo, self.max_x - xo],
                "count": self.res_x,
                "swap_coord": True,
            },
        }[self.dir]

        # We build the path in "normalized" coordinates and then simply
        # swap x and y at the end if we need to
        begin_a, end_a = settings["range_aligned"]
        begin_p, end_p = settings["range_perpendicular"]
        swap_coord = settings["swap_coord"]
        step = (end_p - begin_p) / (float(settings["count"] - 1))
        points = []
        corner_radius = min(step / 2, self.overscan)
        for i in range(0, settings["count"]):
            pos_p = begin_p + step * i
            even = i % 2 == 0  # If even we are going "right", else "left'
            pa = (begin_a, pos_p) if even else (end_a, pos_p)
            pb = (end_a, pos_p) if even else (begin_a, pos_p)

            l = (pa, pb)

            if len(points) > 0 and corner_radius > 0:
                # We need to insert an overscan corner. Basically we insert
                # a rounded rectangle to smooth out the transition and retain
                # as much speed as we can.
                #
                #  ---|---<
                # /
                # |
                # \
                #  ---|--->
                #
                # We just need to draw the two 90 degree arcs. They contain
                # the endpoints of the lines connecting everything.
                if even:
                    center = begin_a - self.overscan + corner_radius
                    points += arc_points(
                        center, pos_p - step + corner_radius, corner_radius, -90, -90
                    )
                    points += arc_points(
                        center, pos_p - corner_radius, corner_radius, -180, -90
                    )
                else:
                    center = end_a + self.overscan - corner_radius
                    points += arc_points(
                        center, pos_p - step + corner_radius, corner_radius, -90, 90
                    )
                    points += arc_points(
                        center, pos_p - corner_radius, corner_radius, 0, 90
                    )

            points.append(l[0])
            points.append(l[1])

        if swap_coord:
            for i in range(len(points)):
                (x, y) = points[i]
                points[i] = (y, x)

        return points

    def calibrate(self, gcmd: GCodeCommand):
        self.min_x, self.min_y = coord_fallback(
            gcmd,
            "MESH_MIN",
            convert_float,
            self.def_min_x,
            self.def_min_y,
            lambda v, d: max(v, d),
        )
        self.max_x, self.max_y = coord_fallback(
            gcmd,
            "MESH_MAX",
            convert_float,
            self.def_max_x,
            self.def_max_y,
            lambda v, d: min(v, d),
        )
        self.res_x, self.res_y = coord_fallback(
            gcmd,
            "PROBE_COUNT",
            int,
            self.def_res_x,
            self.def_res_y,
            lambda v, _d: max(v, 3),
        )
        self.profile_name = gcmd.get("PROFILE", "default")

        if self.min_x > self.max_x:
            self.min_x, self.max_x = (
                max(self.max_x, self.def_min_x),
                min(self.min_x, self.def_max_x),
            )
        if self.min_y > self.max_y:
            self.min_y, self.max_y = (
                max(self.max_y, self.def_min_y),
                min(self.min_y, self.def_max_y),
            )

        # If the user gave RRI _on gcode_ then use it, else use zero_ref_pos
        # if we have it, and finally use config RRI if we have it.
        rri = gcmd.get_int("RELATIVE_REFERENCE_INDEX", None)
        if rri is not None:
            self.zero_ref_mode = ("rri", rri)
        elif self.zero_ref_pos is not None:
            self.zero_ref_mode = ("pos", self.zero_ref_pos)
            self.zero_ref_val = None
            self.zero_ref_bin = []
        elif self.rri is not None:
            self.zero_ref_mode = ("rri", self.rri)
        else:
            self.zero_ref_mode = None

        # If the user requested adaptive meshing, try to shrink the values we just configured
        if gcmd.get_int("ADAPTIVE", 0):
            self._shrink_to_excluded_objects(gcmd)

        self.step_x = (self.max_x - self.min_x) / (self.res_x - 1)
        self.step_y = (self.max_y - self.min_y) / (self.res_y - 1)

        self.toolhead = self.scanner.toolhead
        path = self._generate_path()

        probe_speed = gcmd.get_float("PROBE_SPEED", self.scanner.speed, above=0.0)
        self.scanner._move_to_probing_height(probe_speed)

        speed = gcmd.get_float("SPEED", self.speed, above=0.0)
        runs = gcmd.get_int("RUNS", self.runs, minval=1)

        try:
            self.scanner._start_streaming()

            # Move to first location
            (x, y) = path[0]
            self.toolhead.manual_move([x, y, None], speed)
            self.toolhead.wait_moves()

            self.scanner._sample_printtime_sync(5)
            clusters = self._sample_mesh(gcmd, path, speed, runs)

            if self.zero_ref_mode and self.zero_ref_mode[0] == "pos":
                # If we didn't collect anything, hop over to the zero point
                # and sample. Otherwise, grab the median of what we collected.
                if len(self.zero_ref_bin) == 0:
                    self._collect_zero_ref(speed, self.zero_ref_mode[1])
                else:
                    self.zero_ref_val = median(self.zero_ref_bin)

        finally:
            self.scanner._stop_streaming()

        matrix = self._process_clusters(clusters, gcmd)
        self._apply_mesh(matrix, gcmd)

    def _shrink_to_excluded_objects(self, gcmd: GCodeCommand):
        if self.exclude_object is None:
            gcmd.respond_info(
                "Requested adaptive mesh, but [exclude_object] is not enabled. Ignoring."
            )
            return

        objects = self.exclude_object.get_status().get("objects", [])
        margin = gcmd.get_float("ADAPTIVE_MARGIN", self.adaptive_margin)

        bound_min_x, bound_max_x = None, None
        bound_min_y, bound_max_y = None, None

        for obj in objects:
            for point in obj["polygon"]:
                bound_min_x = opt_min(bound_min_x, point[0])
                bound_max_x = opt_max(bound_max_x, point[0])
                bound_min_y = opt_min(bound_min_y, point[1])
                bound_max_y = opt_max(bound_max_y, point[1])
        if (
            bound_min_x is None
            or bound_max_x is None
            or bound_min_y is None
            or bound_max_y is None
        ):
            gcmd.respond_info(
                "Requested adaptive mesh, but no oobjects defined. Ignoring."
            )
            return

        bound_min_x -= margin
        bound_max_x += margin
        bound_min_y -= margin
        bound_max_y += margin

        # Calculate original step size and apply the new bounds
        orig_span_x = self.max_x - self.min_x
        orig_span_y = self.max_y - self.min_y

        if bound_min_x >= self.min_x:
            self.min_x = bound_min_x
        if bound_max_x <= self.max_x:
            self.max_x = bound_max_x
        if bound_min_y >= self.min_y:
            self.min_y = bound_min_y
        if bound_max_y <= self.max_y:
            self.max_y = bound_max_y

        # Update resolution to retain approximately the same step size as before
        self.res_x = math.ceil(self.res_x * (self.max_x - self.min_x) / orig_span_x)
        self.res_y = math.ceil(self.res_y * (self.max_y - self.min_y) / orig_span_y)
        # Guard against bicubic interpolation with 3 points on one axis
        min_res = 3
        if max(self.res_x, self.res_y) > 6 and min(self.res_x, self.res_y) < 4:
            min_res = 4
        self.res_x = max(self.res_x, min_res)
        self.res_y = max(self.res_y, min_res)

        self.profile_name = None

    def _fly_path(self, path, speed, runs):
        # Run through the path
        for i in range(runs):
            p = path if i % 2 == 0 else reversed(path)
            for x, y in p:
                self.toolhead.manual_move([x, y, None], speed)
        self.toolhead.dwell(0.251)
        self.toolhead.wait_moves()

    def _collect_zero_ref(self, speed, coord):
        xo, yo = self.scanner.offset["x"], self.scanner.offset["y"]
        (x, y) = coord
        self.toolhead.manual_move([x - xo, y - yo, None], speed)
        (dist, _samples) = self.scanner._sample(50, 10)
        self.zero_ref_val = dist

    def _is_valid_position(self, x, y):
        return self.min_x <= x <= self.max_x and self.min_y <= y <= self.min_y

    def _is_faulty_coordinate(self, x, y, add_offsets=False):
        if add_offsets:
            xo, yo = self.scanner.offset["x"], self.scanner.offset["y"]
            x += xo
            y += yo
        for r in self.faulty_regions:
            if r.is_point_within(x, y):
                return True
        return False

    def _sample_mesh(self, gcmd: GCodeCommand, path, speed, runs):
        cs = gcmd.get_float("CLUSTER_SIZE", self.cluster_size, minval=0.0)
        zcs = self.zero_ref_pos_cluster_size
        if not (self.zero_ref_mode and self.zero_ref_mode[0] == "pos"):
            zcs = 0

        min_x, min_y = self.min_x, self.min_y
        xo, yo = self.scanner.offset["x"], self.scanner.offset["y"]

        clusters = {}
        total_samples = [0]
        invalid_samples = [0]

        def cb(sample):
            total_samples[0] += 1
            d = sample["dist"]
            (x, y, z) = sample["pos"]
            x += xo
            y += yo

            if d is None or math.isinf(d):
                if self._is_valid_position(x, y):
                    invalid_samples[0] += 1
                return

            # Calculate coordinate of the cluster we are in
            xi = int(round((x - min_x) / self.step_x))
            yi = int(round((y - min_y) / self.step_y))
            if xi < 0 or self.res_x <= xi or yi < 0 or self.res_y <= yi:
                return

            # If there's a cluster size limit, apply it here
            if cs > 0:
                xf = xi * self.step_x + min_x
                yf = yi * self.step_y + min_y
                dx = x - xf
                dy = y - yf
                dist = math.sqrt(dx * dx + dy * dy)
                if dist > cs:
                    return

            # If we are looking for a zero reference, check if we
            # are close enough and if so, add to the bin.
            if zcs > 0:
                # TODO: These can be None?
                dx = x - self.zero_ref_mode[1][0]  # pyright: ignore[reportOptionalSubscript,reportIndexIssue]
                dy = y - self.zero_ref_mode[1][1]  # pyright: ignore[reportOptionalSubscript,reportIndexIssue]
                dist = math.sqrt(dx * dx + dy * dy)
                if dist <= zcs:
                    self.zero_ref_bin.append(d)

            k = (xi, yi)

            if k not in clusters:
                clusters[k] = []
            clusters[k].append(d)

        with self.scanner.streaming_session(cb):
            self._fly_path(path, speed, runs)

        gcmd.respond_info(
            "Sampled %d total points over %d runs" % (total_samples[0], runs)
        )
        if invalid_samples[0]:
            gcmd.respond_info(
                "!! Encountered %d invalid samples!" % (invalid_samples[0],)
            )
        gcmd.respond_info("Samples binned in %d clusters" % (len(clusters),))

        return clusters

    def _process_clusters(self, raw_clusters, gcmd: GCodeCommand):
        parent_conn, child_conn = multiprocessing.Pipe()
        dump_file = gcmd.get("FILENAME", None)

        def do():
            try:
                child_conn.send(
                    (
                        False,
                        self._do_process_clusters(raw_clusters, dump_file),
                    )
                )
            except Exception:
                child_conn.send((True, traceback.format_exc()))
            finally:
                child_conn.close()

        child = multiprocessing.Process(target=do)
        child.daemon = True
        child.start()
        reactor = self.scanner.reactor
        eventtime = reactor.monotonic()
        while child.is_alive():
            eventtime = reactor.pause(eventtime + 0.1)
        is_err, result = parent_conn.recv()
        child.join()
        parent_conn.close()
        if is_err:
            raise Exception("Error processing mesh: %s" % (result,))
        else:
            is_inner_err, inner_result = result
            if is_inner_err:
                raise gcmd.error(inner_result)
            else:
                return inner_result

    def _do_process_clusters(self, raw_clusters, dump_file):
        if dump_file:
            with open(dump_file, "w") as f:
                f.write("x,y,xp,xy,dist\n")
                for yi in range(self.res_y):
                    for xi in range(self.res_x):
                        cluster = raw_clusters.get((xi, yi), [])
                        xp = xi * self.step_x + self.min_x
                        yp = yi * self.step_y + self.min_y
                        for dist in cluster:
                            f.write("%d,%d,%f,%f,%f\n" % (xi, yi, xp, yp, dist))

        mask = self._generate_fault_mask()
        matrix, faulty_regions = self._generate_matrix(raw_clusters, mask)
        if len(faulty_regions) > 0:
            (error, interpolator_or_msg) = self._load_interpolator()
            if error:
                return (True, interpolator_or_msg)
            matrix = self._interpolate_faulty(
                matrix, faulty_regions, interpolator_or_msg
            )
        err = self._check_matrix(matrix)
        if err is not None:
            return (True, err)
        return (False, self._finalize_matrix(matrix))

    def _generate_fault_mask(self):
        if len(self.faulty_regions) == 0:
            return None
        mask = np.full((self.res_y, self.res_x), True)
        for r in self.faulty_regions:
            r_xmin = max(0, int(math.ceil((r.x_min - self.min_x) / self.step_x)))
            r_ymin = max(0, int(math.ceil((r.y_min - self.min_y) / self.step_y)))
            r_xmax = min(
                self.res_x - 1, int(math.floor((r.x_max - self.min_x) / self.step_x))
            )
            r_ymax = min(
                self.res_y - 1, int(math.floor((r.y_max - self.min_y) / self.step_y))
            )
            for y in range(r_ymin, r_ymax + 1):
                for x in range(r_xmin, r_xmax + 1):
                    mask[(y, x)] = False
        return mask

    def _generate_matrix(self, raw_clusters, mask):
        faulty_indexes = []
        matrix = np.empty((self.res_y, self.res_x))
        for (x, y), values in raw_clusters.items():
            if mask is None or mask[(y, x)]:
                matrix[(y, x)] = self.scanner.trigger_distance - median(values)
            else:
                matrix[(y, x)] = np.nan
                faulty_indexes.append((y, x))
        return matrix, faulty_indexes

    def _load_interpolator(self):
        if not self.scipy:
            try:
                self.scipy = importlib.import_module("scipy")
            except ImportError:
                msg = (
                    "Could not load `scipy`. To install it, simply re-run "
                    "the Scanner `install.sh` script. This module is required "
                    "when using faulty regions when bed meshing."
                )
                return (True, msg)
        if hasattr(self.scipy.interpolate, "RBFInterpolator"):
            # TODO: We should not reference self in a callback and make assumptions
            def rbf_interp(points, values, faulty):
                return self.scipy.interpolate.RBFInterpolator(points, values, 64)(  # pyright: ignore[reportOptionalMemberAccess]
                    faulty
                )

            return (False, rbf_interp)
        else:

            def linear_interp(points, values, faulty):
                return self.scipy.interpolate.griddata(  # pyright: ignore[reportOptionalMemberAccess]
                    points, values, faulty, method="linear"
                )

            return (False, linear_interp)

    def _interpolate_faulty(self, matrix, faulty_indexes, interpolator):
        ys, xs = np.mgrid[0 : matrix.shape[0], 0 : matrix.shape[1]]
        points = np.array([ys.flatten(), xs.flatten()]).T
        values = matrix.reshape(-1)
        good = ~np.isnan(values)
        fixed = interpolator(points[good], values[good], faulty_indexes)
        matrix[tuple(np.array(faulty_indexes).T)] = fixed
        return matrix

    def _check_matrix(self, matrix):
        empty_clusters = []
        for yi in range(self.res_y):
            for xi in range(self.res_x):
                if np.isnan(matrix[(yi, xi)]):
                    xc = xi * self.step_x + self.min_x
                    yc = yi * self.step_y + self.min_y
                    empty_clusters.append("  (%.3f,%.3f)[%d,%d]" % (xc, yc, xi, yi))
        if empty_clusters:
            err = (
                "Empty clusters found\n"
                "Try increasing mesh cluster_size or slowing down.\n"
                "The following clusters were empty:\n"
            ) + "\n".join(empty_clusters)
            return err
        else:
            return None

    def _finalize_matrix(self, matrix):
        z_offset = None
        if self.zero_ref_mode and self.zero_ref_mode[0] == "rri":
            rri = self.zero_ref_mode[1]
            if rri < 0 or rri >= self.res_x * self.res_y:
                rri = None
            if rri is not None:
                rri_x = rri % self.res_x
                rri_y = int(math.floor(rri / self.res_x))
                z_offset = matrix[rri_y][rri_x]
        elif (
            self.zero_ref_mode
            and self.zero_ref_mode[0] == "pos"
            and self.zero_ref_val is not None
        ):
            z_offset = self.scanner.trigger_distance - self.zero_ref_val

        if z_offset is not None:
            matrix = matrix - z_offset
        return matrix.tolist()

    def _apply_mesh(self, matrix, gcmd: GCodeCommand):
        params = self.bm.bmc.mesh_config
        params["min_x"] = self.min_x
        params["max_x"] = self.max_x
        params["min_y"] = self.min_y
        params["max_y"] = self.max_y
        params["x_count"] = self.res_x
        params["y_count"] = self.res_y
        try:
            mesh = bed_mesh.ZMesh(params)  # pyright: ignore [reportCallIssue]
        except TypeError:
            mesh = bed_mesh.ZMesh(params, self.profile_name)
        try:
            mesh.build_mesh(matrix)
        except bed_mesh.BedMeshError as e:
            raise self.gcode.error(str(e))
        self.bm.set_mesh(mesh)
        self.gcode.respond_info("Mesh calibration complete")
        if self.profile_name is not None:
            self.bm.save_profile(self.profile_name)


class Region:
    def __init__(self, x_min, x_max, y_min, y_max):
        self.x_min = x_min
        self.x_max = x_max
        self.y_min = y_min
        self.y_max = y_max

    def is_point_within(self, x, y):
        return (x > self.x_min and x < self.x_max) and (
            y > self.y_min and y < self.y_max
        )


def arc_points(cx, cy, r, start_angle, span):
    # Angle delta is determined by a max deviation(md) from 0.1mm:
    #   r * versin(d_a) < md
    #   versin(d_a) < md/r
    #   d_a < arcversin(md/r)
    #   d_a < arccos(1-md/r)
    # We then determine how many of these we can fit in exactly
    # 90 degrees(rounding up) and then determining the exact
    # delta angle.
    start_angle = start_angle / 180.0 * math.pi
    span = span / 180.0 * math.pi
    d_a = math.acos(1 - 0.1 / r)
    cnt = int(math.ceil(abs(span) / d_a))
    d_a = span / float(cnt)

    points = []
    for i in range(cnt + 1):
        ang = start_angle + d_a * float(i)
        x = cx + math.cos(ang) * r
        y = cy + math.sin(ang) * r
        points.append((x, y))

    return points


def convert_float(data) -> float:
    toFloat = float(data)
    if np.isinf(toFloat) or np.isnan(toFloat):
        raise ValueError(
            f'Convert error when trying to convert string "{data}" into float'
        )
    return toFloat


def coord_fallback(
    gcmd: GCodeCommand, name: str, parse, def_x, def_y, map=lambda v, d: v
):
    param = gcmd.get(name, None)
    if param is not None:
        try:
            x, y = [parse(p.strip()) for p in param.split(",", 1)]
            return map(x, def_x), map(y, def_y)
        except ValueError:
            raise gcmd.error("Unable to parse parameter '%s'" % (name,))
    else:
        return def_x, def_y


def median(samples):
    return float(np.median(samples))


def opt_min(a, b):
    if a is None:
        return b
    return min(a, b)


def opt_max(a, b):
    if a is None:
        return b
    return max(a, b)


def load_config(config: ConfigWrapper):
    scanner = Scanner(config)

    config.get_printer().add_object("probe", ScannerWrapper(scanner))
    temp = ScannerTempWrapper(scanner)
    if scanner.sensor == "cartographer":
        config.get_printer().add_object("temperature_sensor cartographer_coil", temp)
        pheaters = scanner.printer.load_object(config, "heaters")
        pheaters.available_sensors.append("temperature_sensor cartographer_coil")
    elif scanner.sensor == "idm":
        config.get_printer().add_object("temperature_sensor idm_coil", temp)
        pheaters = scanner.printer.load_object(config, "heaters")
        pheaters.available_sensors.append("temperature_sensor idm_coil")
    elif scanner.sensor == "eddy":
        config.get_printer().add_object("temperature_sensor eddy_coil", temp)
        pheaters = scanner.printer.load_object(config, "heaters")
        pheaters.available_sensors.append("temperature_sensor Eddy_coil")
    else:
        config.get_printer().add_object("temperature_sensor scanner_coil", temp)
        pheaters = scanner.printer.load_object(config, "heaters")
        pheaters.available_sensors.append("temperature_sensor scanner_coil")
    return scanner


def load_config_prefix(config: ConfigWrapper):
    scanner = config.get_printer().lookup_object("scanner")
    name = config.get_name()
    if name.startswith("scanner model "):
        name = name[14:]
        model = ScannerModel.load(name, config, scanner)
        scanner.register_model(name, model)
        return model
    else:
        raise config.error("Unknown scanner config directive '%s'" % (name[7:],))
