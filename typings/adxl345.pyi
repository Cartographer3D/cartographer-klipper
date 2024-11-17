# ADXL345 registers
REG_DEVID = 0x00
REG_BW_RATE = 0x2C
REG_POWER_CTL = 0x2D
REG_DATA_FORMAT = 0x31
REG_FIFO_CTL = 0x38
REG_MOD_READ = 0x80
REG_MOD_MULTI = 0x40

FREEFALL_ACCEL = 9.80665 * 1000.0

class ADXL345:
    def __init__(self, config):
        pass
    def set_reg(self, reg, val, minclock=0):
        pass
