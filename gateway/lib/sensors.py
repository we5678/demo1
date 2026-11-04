# -*- coding: utf-8 -*-
"""
两路 RS485 传感器驱动：空气温湿度 + 七合一土壤。
寄存器表和缩放系数全部来自 config.py。
"""

from modbus_codec import to_signed16


class SensorReadError(Exception):
    pass


def _in_range(value, low, high):
    return value is not None and low <= value <= high


class AirTHSensor:
    def __init__(self, bus, slave, start_reg, fields):
        self.bus = bus
        self.slave = slave
        self.start_reg = start_reg
        self.fields = fields

    def read(self):
        regs = self.bus.read_holding(self.slave, self.start_reg, len(self.fields))
        out = {}

        for i in range(len(self.fields)):
            name, scale, signed = self.fields[i]
            raw = regs[i]
            if signed:
                raw = to_signed16(raw)
            out[name] = raw / scale

        # 合理性检查，超出量程按无效处理
        if not _in_range(out.get("air_temperature"), -40.0, 85.0):
            out["air_temperature"] = None
        if not _in_range(out.get("air_humidity"), 0.0, 100.0):
            out["air_humidity"] = None

        if out.get("air_temperature") is None and out.get("air_humidity") is None:
            raise SensorReadError("air sensor values out of range: %s" % out)

        return out


class Soil7in1:
    def __init__(self, bus, slave, start_reg, fields):
        self.bus = bus
        self.slave = slave
        self.start_reg = start_reg
        self.fields = fields

    def read(self):
        regs = self.bus.read_holding(self.slave, self.start_reg, len(self.fields))
        out = {}

        for i in range(len(self.fields)):
            name, scale, signed = self.fields[i]
            raw = regs[i]
            if signed:
                raw = to_signed16(raw)
            out[name] = raw / scale

        # 量程检查（按常见七合一传感器）
        limits = {
            "soil_temperature": (-40.0, 85.0),
            "soil_humidity": (0.0, 100.0),
            "salinity": (0.0, 20.0),        # dS/m
            "ph": (0.0, 14.0),
            "nitrogen": (0.0, 2000.0),
            "phosphorus": (0.0, 2000.0),
            "potassium": (0.0, 2000.0),
        }
        for name in limits:
            if name in out and not _in_range(out[name], limits[name][0], limits[name][1]):
                out[name] = None

        valid = 0
        for name in out:
            if out[name] is not None:
                valid += 1
        if valid == 0:
            raise SensorReadError("soil sensor all values invalid: %s" % out)

        return out
