# -*- coding: utf-8 -*-
"""
Modbus RTU 纯逻辑：CRC16、组帧、解帧。

不依赖 machine 模块，所以可以直接在 PC 上跑单元测试（见 tools/selftest.py）。
"""


def crc16(data):
    """Modbus RTU CRC16（多项式 0xA001，初值 0xFFFF）。"""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def build_read_request(slave, start_reg, count):
    """组 0x03 读保持寄存器请求帧，返回 bytes。"""
    frame = bytearray((
        slave & 0xFF,
        0x03,
        (start_reg >> 8) & 0xFF,
        start_reg & 0xFF,
        (count >> 8) & 0xFF,
        count & 0xFF,
    ))
    c = crc16(frame)
    frame.append(c & 0xFF)
    frame.append((c >> 8) & 0xFF)
    return bytes(frame)


def check_crc(frame):
    """校验整帧（最后两字节是低前高后的 CRC）。"""
    if len(frame) < 4:
        return False
    calc = crc16(frame[:-2])
    got = frame[-2] | (frame[-1] << 8)
    return calc == got


def parse_read_response(frame, slave, count):
    """解析 0x03 响应，返回寄存器整数列表；出错抛 ValueError。"""
    if len(frame) < 5:
        raise ValueError("response too short: %d bytes" % len(frame))
    if frame[0] != slave:
        raise ValueError("slave mismatch: got %d, want %d" % (frame[0], slave))
    if frame[1] == 0x83:
        raise ValueError("modbus exception code %d" % frame[2])
    if frame[1] != 0x03:
        raise ValueError("unexpected function code 0x%02X" % frame[1])
    if frame[2] != count * 2:
        raise ValueError("byte count %d != %d" % (frame[2], count * 2))
    if not check_crc(frame):
        raise ValueError("crc error")

    regs = []
    for i in range(count):
        hi = frame[3 + i * 2]
        lo = frame[4 + i * 2]
        regs.append((hi << 8) | lo)
    return regs


def to_signed16(value):
    """无符号 16 位转有符号（负温度等）。"""
    value &= 0xFFFF
    if value & 0x8000:
        return value - 0x10000
    return value
