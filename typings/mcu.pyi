from clocksync import SecondarySync

class MCU:
    _mcu_freq = 42
    def __init__(self, _, sync: SecondarySync):
        pass
    def alloc_command_queue(self):
        pass
    def register_config_callback(self, _):
        pass
    def register_response(self, _, __):
        pass
    def get_constants(self):
        pass
    def lookup_command(self, msgformat, cq=None):
        pass
    def lookup_query_command(self, _, __, cq=None):
        pass
    def clock32_to_clock64(self, _):
        pass
    def clock_to_print_time(self, _):
        pass
    def print_time_to_clock(self, _):
        pass
    def get_printer(self):
        pass

class MCU_trsync:
    REASON_ENDSTOP_HIT = 1
    REASON_HOST_REQUEST = 2
    REASON_PAST_END_TIME = 3
    REASON_COMMS_TIMEOUT = 4

    _mcu: MCU
    def __init__(self, _, __):
        pass
    def get_oid(self):
        pass
    def get_mcu(self):
        pass
    def add_stepper(self, stepper):
        pass
    def get_steppers(self) -> list:
        pass
    def start(self, print_time, report_offset, trigger_completion, expire_timeout):
        pass
    def stop(self):
        pass
    def set_home_end_time(self, home_end_time):
        pass
