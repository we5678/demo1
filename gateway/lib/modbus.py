# -*- coding: utf-8 -*-
"""
RS485 Modbus RTU 主站（只实现 0x03 读保持寄存器）。
"""

import time
from machine import UART, Pin

from modbus_codec import build_read_request, parse_read_response


class ModbusError(Exception):
    pass


class ModbusRTU:
    def __init__(self, uart_id, tx_pin, rx_pin, de_pin, baudrate=9600,
                 timeout_ms=300, retries=3):
        self.baudrate = baudrate
        self.timeout_ms = timeout_ms
        self.retries = retries
        self.uart = UART(
            uart_id,
            baudrate=baudrate,
            tx=Pin(tx_pin),
            rx=Pin(rx_pin),
            timeout=50,
        )
        self.de = None
        if de_pin is not None:
            self.de = Pin(de_pin, Pin.OUT, value=0)
        time.sleep_ms(20)

    def _flush(self):
        while self.uart.any():
            self.uart.read()

    def _send_and_receive(self, frame, expected):
        self._flush()

        if self.de is not None:
            self.de.value(1)
            time.sleep_ms(2)

        self.uart.write(frame)

        # 等最后一个字节真正发完再放开 485 总线
        tx_ms = int(len(frame) * 10 * 1000 / self.baudrate) + 2
        time.sleep_ms(tx_ms)

        if self.de is not None:
            self.de.value(0)

        buf = bytearray()
        deadline = time.ticks_add(time.ticks_ms(), self.timeout_ms)
        while len(buf) < expected:
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                break
            chunk = self.uart.read(expected - len(buf))
            if chunk:
                buf.extend(chunk)

        return bytes(buf)

    def read_holding(self, slave, start_reg, count):
        """读 count 个保持寄存器，返回整数列表；失败抛 ModbusError。"""
        expected = 5 + 2 * count
        last_error = "no response"

        for _ in range(self.retries):
            frame = build_read_request(slave, start_reg, count)
            resp = self._send_and_receive(frame, expected)

            if len(resp) == 0:
                last_error = "timeout (slave %d)" % slave
            else:
                try:
                    return parse_read_response(resp[:expected], slave, count)
                except ValueError as exc:
                    last_error = str(exc)

            time.sleep_ms(60)

        raise ModbusError("slave %d: %s" % (slave, last_error))
