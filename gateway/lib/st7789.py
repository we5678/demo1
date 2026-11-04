# -*- coding: utf-8 -*-
"""
ST7789 SPI 彩屏最小驱动（240x320），只实现本项目用到的功能：
初始化、填充、矩形、单行文字（8x8 字库放大）。

不依赖第三方库，只用 MicroPython 自带的 framebuf。
"""

import time
import framebuf
from machine import Pin, SPI

# 常用 16 位颜色（RGB565）
BLACK = 0x0000
WHITE = 0xFFFF
RED = 0xF800
GREEN = 0x07E0
BLUE = 0x001F
CYAN = 0x07FF
YELLOW = 0xFFE0
ORANGE = 0xFD20
GRAY = 0x8410

# 240x320 面板通用初始化序列
_INIT_TABLE = (
    (0x3A, b"\x55"),                          # COLMOD: 16bit/pixel
    (0xB2, b"\x0C\x0C\x00\x33\x33"),          # PORCTRL
    (0xB7, b"\x35"),                          # GCTRL
    (0xBB, b"\x19"),                          # VCOMS
    (0xC0, b"\x2C"),                          # LCMCTRL
    (0xC2, b"\x01"),                          # VDVVRHEN
    (0xC3, b"\x12"),                          # VRHS
    (0xC4, b"\x20"),                          # VDVS
    (0xC6, b"\x0F"),                          # FRCTRL2
    (0xD0, b"\xA4\xA1"),                      # PWCTRL1
    (0xE0, b"\xD0\x04\x0D\x11\x13\x2B\x3F\x54\x4C\x18\x0D\x0B\x1F\x23"),  # PVGAMCTRL
    (0xE1, b"\xD0\x04\x0C\x11\x13\x2C\x3F\x44\x51\x2F\x1F\x1F\x20\x23"),  # NVGAMCTRL
)


class ST7789:
    def __init__(self, spi_id, sck, mosi, cs, dc, rst, bl,
                 width=240, height=320, baudrate=40000000,
                 rotation=0, invert=True, bgr=False):
        self.base_width = width
        self.base_height = height
        self.width = width
        self.height = height
        self.invert = invert
        self.bgr = bgr

        self.cs = Pin(cs, Pin.OUT, value=1)
        self.dc = Pin(dc, Pin.OUT, value=1)
        self.rst = Pin(rst, Pin.OUT, value=1) if rst is not None else None
        self.bl = Pin(bl, Pin.OUT, value=1) if bl is not None else None

        self.spi = SPI(
            spi_id,
            baudrate=baudrate,
            polarity=0,
            phase=0,
            sck=Pin(sck),
            mosi=Pin(mosi),
        )

        self._reset()
        self._init_panel()
        self.set_rotation(rotation)
        self.fill(BLACK)

    # ---------------- 底层 ----------------

    def _reset(self):
        if self.rst is not None:
            self.rst.value(0)
            time.sleep_ms(20)
            self.rst.value(1)
            time.sleep_ms(120)

    def _write(self, data, is_data):
        self.dc.value(1 if is_data else 0)
        self.cs.value(0)
        self.spi.write(data)
        self.cs.value(1)

    def _cmd(self, cmd, data=None):
        self._write(bytes((cmd,)), False)
        if data:
            self._write(data, True)

    def _init_panel(self):
        self._cmd(0x01)                 # SWRESET
        time.sleep_ms(150)
        self._cmd(0x11)                 # SLPOUT
        time.sleep_ms(120)

        for cmd, data in _INIT_TABLE:
            self._cmd(cmd, data)

        if self.invert:
            self._cmd(0x21)             # INVON
        self._cmd(0x13)                 # NORON
        self._cmd(0x29)                 # DISPON
        time.sleep_ms(20)

    def set_rotation(self, rotation):
        rotation &= 0x03
        if rotation == 0:
            madctl = 0x00
            w, h = self.base_width, self.base_height
        elif rotation == 1:
            madctl = 0x60
            w, h = self.base_height, self.base_width
        elif rotation == 2:
            madctl = 0xC0
            w, h = self.base_width, self.base_height
        else:
            madctl = 0xA0
            w, h = self.base_height, self.base_width

        if self.bgr:
            madctl |= 0x08

        self._cmd(0x36, bytes((madctl,)))
        self.width = w
        self.height = h

    def set_window(self, x0, y0, x1, y1):
        self._cmd(0x2A, bytes((
            (x0 >> 8) & 0xFF, x0 & 0xFF,
            (x1 >> 8) & 0xFF, x1 & 0xFF,
        )))
        self._cmd(0x2B, bytes((
            (y0 >> 8) & 0xFF, y0 & 0xFF,
            (y1 >> 8) & 0xFF, y1 & 0xFF,
        )))
        self._cmd(0x2C)

    # ---------------- 绘图 ----------------

    def fill_rect(self, x, y, w, h, color):
        if w <= 0 or h <= 0:
            return
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.width - 1, x + w - 1)
        y1 = min(self.height - 1, y + h - 1)
        if x1 < x0 or y1 < y0:
            return

        self.set_window(x0, y0, x1, y1)
        self.dc.value(1)
        self.cs.value(0)

        hi = (color >> 8) & 0xFF
        lo = color & 0xFF
        line = bytearray((x1 - x0 + 1) * 2)
        for i in range(0, len(line), 2):
            line[i] = hi
            line[i + 1] = lo

        for _ in range(y1 - y0 + 1):
            self.spi.write(line)

        self.cs.value(1)

    def fill(self, color):
        self.fill_rect(0, 0, self.width, self.height, color)

    def line_text(self, y, text, fg=WHITE, bg=BLACK, scale=2):
        """
        在 y 处画一行文字，行高 8*scale 像素。

        内置 8x8 字库，scale=2 时每个字符 16x16 像素，
        240 宽的屏幕每行最多 15 个字符。
        """
        if scale < 1:
            scale = 1
        sw = self.width // scale
        if len(text) > sw:
            text = text[:sw]

        # 先用 RGB565 小画布把这一行文字画出来
        buf = bytearray(sw * 8 * 2)
        fb = framebuf.FrameBuffer(buf, sw, 8, framebuf.RGB565)
        fb.fill(BLACK)
        fb.text(text, 0, 0, WHITE)

        self.set_window(0, y, self.width - 1, y + 8 * scale - 1)
        self.dc.value(1)
        self.cs.value(0)

        fg_hi = (fg >> 8) & 0xFF
        fg_lo = fg & 0xFF
        bg_hi = (bg >> 8) & 0xFF
        bg_lo = bg & 0xFF

        row = bytearray(self.width * 2)
        for sy in range(8):
            i = 0
            for sx in range(sw):
                if fb.pixel(sx, sy):
                    for _ in range(scale):
                        row[i] = fg_hi
                        row[i + 1] = fg_lo
                        i += 2
                else:
                    for _ in range(scale):
                        row[i] = bg_hi
                        row[i + 1] = bg_lo
                        i += 2
            for _ in range(scale):
                self.spi.write(row)

        self.cs.value(1)
