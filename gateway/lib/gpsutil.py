# -*- coding: utf-8 -*-
"""
GPS 数据解析与时间换算，纯 Python，不依赖 machine。

EC800 的 AT+QGPSLOC 返回格式（Quectel 系列通用）：

    +QGPSLOC: <UTC>,<latitude>,<longitude>,<HDOP>,<altitude>,<fix>,
              <COG>,<spkm>,<spkn>,<date>

示例：
    +QGPSLOC: 061234.0,39.90923,116.397428,1.2,45.0,3,0.0,0.0,0.0,030120

其中 latitude/longitude 已经是十进制度，不需要 NMEA 的 ddmm.mmmm 换算。
date 为 ddmmyy，UTC 时间为 UTC。
"""


def days_from_civil(y, m, d):
    """公历日期 -> 1970-01-01 起的天数（Howard Hinnant 算法，适用于 1583 年以后）。"""
    y -= 1 if m <= 2 else 0
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def utc_epoch_ms(y, mo, d, hh, mm, ss):
    """UTC 年月日时分秒 -> Unix 毫秒时间戳（ss 可以为小数）。"""
    days = days_from_civil(y, mo, d)
    seconds = days * 86400 + hh * 3600 + mm * 60 + ss
    return int(seconds * 1000)


def parse_qgpsloc(text):
    """
    从 AT 响应文本中解析 +QGPSLOC 行，返回 dict 或 None。

    返回：{"lat": float, "lon": float, "fix": int, "hdop": float,
           "alt": float, "epoch_ms": int}
    """
    line = None
    for raw in text.replace("\r", "").split("\n"):
        if raw.startswith("+QGPSLOC:"):
            line = raw
    if line is None:
        return None

    parts = line.split(":", 1)[1].strip().split(",")
    if len(parts) < 10:
        return None

    try:
        utc = parts[0].strip()          # hhmmss.s
        lat = float(parts[1])
        lon = float(parts[2])
        hdop = float(parts[3])
        alt = float(parts[4])
        fix = int(float(parts[5]))
        date = parts[9].strip()         # ddmmyy

        hh = int(utc[0:2])
        mm = int(utc[2:4])
        ss = float(utc[4:])

        d = int(date[0:2])
        mo = int(date[2:4])
        y = 2000 + int(date[4:6])

        epoch_ms = utc_epoch_ms(y, mo, d, hh, mm, ss)
    except (ValueError, IndexError):
        return None

    return {
        "lat": lat,
        "lon": lon,
        "fix": fix,
        "hdop": hdop,
        "alt": alt,
        "epoch_ms": epoch_ms,
    }


def fmt_hhmm(epoch_ms, tz_offset_min=0):
    """Unix 毫秒 -> 本地 HH:MM 字符串。"""
    if not epoch_ms:
        return "--:--"
    secs = epoch_ms // 1000 + tz_offset_min * 60
    return "%02d:%02d" % ((secs // 3600) % 24, (secs // 60) % 60)
