# -*- coding: utf-8 -*-
"""
LCD 界面：按行显示空气/土壤数据、GPS、网络与上报状态。

采用“行缓存 + 变化才重绘”，避免整屏刷新造成闪烁。
"""

from gpsutil import fmt_hhmm

BLACK = 0x0000
WHITE = 0xFFFF
RED = 0xF800
GREEN = 0x07E0
CYAN = 0x07FF
YELLOW = 0xFFE0
ORANGE = 0xFD20
GRAY = 0x8410

# 行号 -> y 坐标 = 行号 * 16
LINE_HEIGHT = 16


class UI:
    def __init__(self, lcd, tz_offset_min=480):
        self.lcd = lcd
        self.tz = tz_offset_min
        self.cache = {}

        lcd.fill(BLACK)
        lcd.fill_rect(0, 18, lcd.width, 2, 0x0410)   # 标题下分隔线
        self._draw(0, "SOIL GATEWAY", CYAN)
        self._draw(2, "AIR", GREEN)
        self._draw(4, "SOIL", GREEN)
        self._draw(8, "GPS", GREEN)

    # ---------------- 基础 ----------------

    def _draw(self, idx, text, color=WHITE):
        if len(text) > 15:
            text = text[:15]
        key = "%d|%s" % (color, text)
        if self.cache.get(idx) == key:
            return
        self.cache[idx] = key
        self.lcd.line_text(idx * LINE_HEIGHT, text, color, BLACK, 2)

    def boot(self, msg):
        self._draw(5, "BOOT", YELLOW)
        self._draw(6, msg, WHITE)

    @staticmethod
    def _num(value, fmt, unit=""):
        if value is None:
            return "--" + unit
        try:
            return (fmt % value) + unit
        except Exception:
            return "--" + unit

    # ---------------- 刷新 ----------------

    def update(self, state):
        air = state.get("air") or {}
        soil = state.get("soil") or {}
        fix = state.get("fix")

        # 空气温湿度（一行最多 15 字符，这里用紧凑写法）
        t = self._num(air.get("air_temperature"), "%.1f", "C")
        h = self._num(air.get("air_humidity"), "%.1f", "%")
        self._draw(3, "T%s H%s" % (t, h))

        # 土壤温湿度
        t = self._num(soil.get("soil_temperature"), "%.1f", "C")
        h = self._num(soil.get("soil_humidity"), "%.1f", "%")
        self._draw(5, "T%s H%s" % (t, h))

        # 电导率 / pH
        ec = self._num(soil.get("salinity"), "%.2f")
        ph = self._num(soil.get("ph"), "%.1f")
        self._draw(6, "EC:%s pH:%s" % (ec, ph))

        # 氮磷钾
        n = self._num(soil.get("nitrogen"), "%.0f")
        p = self._num(soil.get("phosphorus"), "%.0f")
        k = self._num(soil.get("potassium"), "%.0f")
        self._draw(7, "NPK %s/%s/%s" % (n, p, k))

        # GPS
        if fix:
            lat_t = "%.5f" % state.get("lat", 0.0)
            lon_t = "%.5f" % state.get("lon", 0.0)
            mode = fix.get("fix", 0)
            fix_t = "3D" if mode >= 2 else ("2D" if mode == 1 else "NO")
        else:
            lat_t = "--"
            lon_t = "--"
            fix_t = "NO"
        self._draw(9, "LAT:%s" % lat_t)
        self._draw(10, "LON:%s" % lon_t)
        self._draw(11, "FIX:%s" % fix_t)

        # 网络
        net = state.get("net", "--")
        self._draw(12, "NET:%s" % net)

        # 上报状态
        last = state.get("last_up")
        time_text = fmt_hhmm(last, self.tz) if last else "--:--"
        status = state.get("upload", "WAIT")
        if status == "OK":
            color = GREEN
        elif status == "FAIL":
            color = RED
        else:
            color = YELLOW
        self._draw(13, "UP:%s %s" % (time_text, status), color)

        # 距下次上报倒计时
        self._draw(14, state.get("countdown", "NEXT:--:--"), WHITE)
