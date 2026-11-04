#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PC 端自检：不需要开发板，验证 Modbus 组帧/解帧、GPS 解析、上报 JSON 结构。

运行：
    E:\\Thonny\\python.exe E:\\MyCode\\demo1\\tools\\selftest.py
"""

import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.abspath(os.path.join(HERE, "..", "gateway", "lib"))
sys.path.insert(0, LIB)

import modbus_codec as mc          # noqa: E402
import gpsutil                     # noqa: E402
import payload as payload_mod      # noqa: E402

failures = []


def check(name, condition, detail=""):
    if condition:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s  %s" % (name, detail))
        failures.append(name)


print("== 1. Modbus CRC / 组帧 ==")
req = mc.build_read_request(1, 0x0000, 10)
check("读 10 个寄存器组帧", req.hex().upper() == "01030000000AC5CD", req.hex())
req = mc.build_read_request(1, 0x0000, 1)
check("读 1 个寄存器组帧", req.hex().upper() == "010300000001840A", req.hex())

print("== 2. Modbus 响应解帧 ==")
frame = bytearray((1, 0x03, 0x04, 0x00, 0xFA, 0x01, 0x2C))
crc = mc.crc16(frame)
frame.append(crc & 0xFF)
frame.append((crc >> 8) & 0xFF)
regs = mc.parse_read_response(bytes(frame), 1, 2)
check("解析寄存器值", regs == [250, 300], str(regs))
check("有符号数 -100", mc.to_signed16(0xFF9C) == -100)
check("有符号数 100", mc.to_signed16(0x0064) == 100)

# 故意改坏 CRC，必须报错
bad = bytearray(frame)
bad[-1] ^= 0xFF
try:
    mc.parse_read_response(bytes(bad), 1, 2)
    check("CRC 错误被拒绝", False, "没有抛异常")
except ValueError:
    check("CRC 错误被拒绝", True)

print("== 3. GPS 解析（AT+QGPSLOC）==")
text = (
    "+QGPSLOC: 061234.0,39.90923,116.397428,1.2,45.0,3,0.0,0.0,0.0,030120\r\n"
    "\r\nOK\r\n"
)
fix = gpsutil.parse_qgpsloc(text)
expected_ms = int(
    datetime.datetime(2020, 1, 3, 6, 12, 34, tzinfo=datetime.timezone.utc).timestamp() * 1000
)
check("纬度", fix is not None and abs(fix["lat"] - 39.90923) < 1e-9, str(fix))
check("经度", fix is not None and abs(fix["lon"] - 116.397428) < 1e-9, str(fix))
check("定位模式", fix is not None and fix["fix"] == 3, str(fix))
check("时间戳", fix is not None and fix["epoch_ms"] == expected_ms,
      "%s != %s" % (fix and fix["epoch_ms"], expected_ms))
check("无定位返回 None", gpsutil.parse_qgpsloc("+CME ERROR: 516\r\n") is None)

print("== 4. 上报 JSON 结构 ==")
meta = {
    "gateway_id": "GW-2026-0001",
    "gateway_unique": "GW-8F3A9C2B",
    "air_id": "S-TH-0001",
    "air_type": "temperature_humidity_npk",
    "air_type_name": "温湿度传感器",
    "soil_id": "S-NPK-0001",
    "soil_type": "npk",
    "soil_type_name": "七合一土壤传感器",
}
air = {"air_temperature": 26.34, "air_humidity": 65.12}
soil = {
    "soil_temperature": 24.85,
    "soil_humidity": 68.2,
    "nitrogen": 45.3,
    "phosphorus": 22.1,
    "potassium": 33.7,
    "ph": 6.84,
    "salinity": 1.234,
}
out = payload_mod.build_payload(meta, expected_ms, 39.90923, 116.397428, air, soil)

check("timestamp 为整数", isinstance(out["timestamp"], int) and out["timestamp"] == expected_ms)
gw = out["gateway"]
check("gateway 字段", gw["gateway_id"] == "GW-2026-0001"
      and gw["unique_code"] == "GW-8F3A9C2B"
      and gw["sensor_count"] == 2)
check("location 为数值", isinstance(gw["location"]["latitude"], float)
      and isinstance(gw["location"]["longitude"], float))

sensors = out["sensors"]
check("两个传感器", len(sensors) == 2, str(len(sensors)))
check("传感器唯一码", sensors[0]["unique_code"] == "GW-8F3A9C2B-0001"
      and sensors[1]["unique_code"] == "GW-8F3A9C2B-0002")
check("类型枚举", sensors[0]["type"] == "temperature_humidity_npk"
      and sensors[1]["type"] == "npk")
check("每路 9 项数据", all(len(s["data"]) == 9 for s in sensors))
check("空气数据只有空气项",
      sensors[0]["data"]["air_temperature"] == 26.3
      and sensors[0]["data"]["air_humidity"] == 65.1
      and sensors[0]["data"]["soil_temperature"] is None)
check("土壤数据完整",
      sensors[1]["data"]["soil_temperature"] == 24.9
      and sensors[1]["data"]["ph"] == 6.8
      and sensors[1]["data"]["salinity"] == 1.23
      and sensors[1]["data"]["air_temperature"] is None)

sample_path = os.path.abspath(os.path.join(HERE, "..", "sample_payload.json"))
with open(sample_path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("\n示例数据已写入: %s" % sample_path)
print(json.dumps(out, ensure_ascii=False, indent=2))

print("")
if failures:
    print("FAILED: %d 项" % len(failures))
    sys.exit(1)
print("ALL PASSED")
