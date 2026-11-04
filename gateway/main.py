# -*- coding: utf-8 -*-
"""
网关主程序

流程：
  1. 初始化 LCD / EC800 / RS485 / WiFi
  2. 每 30 秒采集一次两路 RS485 传感器并刷新 LCD
  3. 每 10 分钟读取 EC800 GPS，组装 JSON 并 HTTP POST 上报
  4. 上报失败不退出，下一周期继续重试
"""

import sys
import time
import gc
import json
import network

import config
from modbus import ModbusRTU
from sensors import AirTHSensor, Soil7in1
from ec800 import EC800
import http_client
from payload import build_payload
from st7789 import ST7789
from ui import UI

META = {
    "gateway_id": config.GATEWAY_ID,
    "gateway_unique": config.GATEWAY_UNIQUE_CODE,
    "air_id": config.AIR_SENSOR_ID,
    "air_type": config.AIR_SENSOR_TYPE,
    "air_type_name": config.AIR_SENSOR_TYPE_NAME,
    "soil_id": config.SOIL_SENSOR_ID,
    "soil_type": config.SOIL_SENSOR_TYPE,
    "soil_type_name": config.SOIL_SENSOR_TYPE_NAME,
}

STATE = {
    "air": None,
    "soil": None,
    "fix": None,
    "lat": 0.0,
    "lon": 0.0,
    "net": "--",
    "upload": "WAIT",
    "last_up": None,
    "countdown": "NEXT:--:--",
    "ec800_ok": False,
}

LCD = None
UI_OBJ = None
BUS = None
AIR = None
SOIL = None
EC800_MOD = None
WLAN = None


def log(*args):
    print("[GW]", *args)


def now_epoch_ms():
    """
    取当前 Unix 毫秒时间。

    MicroPython 的裸机端口 time.time() 通常是从 2000-01-01 起算的秒数，
    这里按数值大小自动区分 2000 纪元与 1970 纪元。
    """
    t = time.time()
    if t < 1200000000:
        t += 946684800
    return int(t * 1000)


# ============================================================
# WiFi
# ============================================================

def setup_wifi():
    global WLAN
    try:
        wlan = network.WLAN(network.STA_IF)
        if not wlan.active():
            wlan.active(True)
        if wlan.isconnected():
            WLAN = wlan
            return wlan

        log("WiFi connecting:", config.WIFI_SSID)
        wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)

        deadline = time.ticks_add(time.ticks_ms(), config.WIFI_TIMEOUT_S * 1000)
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            if wlan.isconnected():
                break
            time.sleep_ms(500)

        if not wlan.isconnected():
            log("WiFi failed, status =", wlan.status())
            return None

        log("WiFi ok:", wlan.ifconfig())

        # 用 NTP 校准 ESP32 时钟，GPS 无定位时 timestamp 也不至于回到 2000 年
        try:
            import ntptime
            ntptime.settime()
            log("NTP synced")
        except Exception as exc:
            log("NTP failed:", exc)

        WLAN = wlan
        return wlan
    except Exception as exc:
        sys.print_exception(exc)
        return None


def net_text():
    if config.UPLOAD_TRANSPORT == "wifi":
        if WLAN is not None and WLAN.isconnected():
            try:
                return "WIFI %d" % WLAN.status("rssi")
            except Exception:
                return "WIFI OK"
        return "WIFI OFF"

    if EC800_MOD is not None and STATE["ec800_ok"]:
        csq = EC800_MOD.csq()
        if csq is None:
            return "4G --"
        return "4G CSQ%d" % csq
    return "4G OFF"


# ============================================================
# 硬件初始化
# ============================================================

def init_ec800():
    global EC800_MOD
    try:
        EC800_MOD = EC800(
            config.EC800_UART_ID,
            config.EC800_TX_PIN,
            config.EC800_RX_PIN,
            config.EC800_BAUDRATE,
            config.EC800_PWRKEY_PIN,
            config.EC800_RESET_PIN,
            config.EC800_RXBUF,
        )
    except Exception as exc:
        log("EC800 UART init failed:", exc)
        return

    UI_OBJ.boot("4G power on...")
    if not EC800_MOD.power_on(20):
        log("EC800 not responding")
        return
    STATE["ec800_ok"] = True

    UI_OBJ.boot("4G init...")
    try:
        EC800_MOD.init(config.EC800_APN, 60)
        EC800_MOD.gps_start()
        log("EC800 ready, APN =", config.EC800_APN)
    except Exception as exc:
        log("EC800 init incomplete:", exc)


def init_hardware():
    global LCD, UI_OBJ, BUS, AIR, SOIL

    LCD = ST7789(
        config.LCD_SPI_ID,
        config.LCD_SCK_PIN,
        config.LCD_MOSI_PIN,
        config.LCD_CS_PIN,
        config.LCD_DC_PIN,
        config.LCD_RST_PIN,
        config.LCD_BL_PIN,
        config.LCD_WIDTH,
        config.LCD_HEIGHT,
        config.LCD_BAUDRATE,
        config.LCD_ROTATION,
        config.LCD_INVERT,
        config.LCD_BGR,
    )
    UI_OBJ = UI(LCD, config.LOCAL_TZ_OFFSET_MIN)
    UI_OBJ.boot("LCD OK")
    log("LCD ready")

    init_ec800()

    UI_OBJ.boot("RS485 init...")
    BUS = ModbusRTU(
        config.RS485_UART_ID,
        config.RS485_TX_PIN,
        config.RS485_RX_PIN,
        config.RS485_DE_PIN,
        config.RS485_BAUDRATE,
        config.RS485_TIMEOUT_MS,
        config.RS485_RETRIES,
    )
    AIR = AirTHSensor(BUS, config.AIR_SLAVE, config.AIR_START_REG, config.AIR_FIELDS)
    SOIL = Soil7in1(BUS, config.SOIL_SLAVE, config.SOIL_START_REG, config.SOIL_FIELDS)
    log("RS485 ready")

    if config.UPLOAD_TRANSPORT == "wifi":
        UI_OBJ.boot("WiFi init...")
        setup_wifi()


# ============================================================
# 采集与上报
# ============================================================

def poll_gps():
    if EC800_MOD is None or not STATE.get("ec800_ok"):
        return
    try:
        fix = EC800_MOD.gps_locate()
    except Exception as exc:
        log("GPS error:", exc)
        return

    if fix:
        STATE["fix"] = fix
        STATE["lat"] = fix["lat"]
        STATE["lon"] = fix["lon"]
        log("GPS fix:", fix["lat"], fix["lon"], fix["epoch_ms"])


def sample_sensors():
    if AIR is not None:
        try:
            STATE["air"] = AIR.read()
        except Exception as exc:
            log("air read failed:", exc)
            STATE["air"] = None

    if SOIL is not None:
        try:
            STATE["soil"] = SOIL.read()
        except Exception as exc:
            log("soil read failed:", exc)
            STATE["soil"] = None

    poll_gps()


def do_upload():
    global WLAN

    STATE["upload"] = "BUSY"
    UI_OBJ.update(STATE)

    fix = STATE.get("fix")
    if fix:
        timestamp = fix["epoch_ms"]
    else:
        timestamp = now_epoch_ms()

    payload = build_payload(
        META,
        timestamp,
        STATE.get("lat", 0.0),
        STATE.get("lon", 0.0),
        STATE.get("air"),
        STATE.get("soil"),
    )
    body = json.dumps(payload)
    log("POST", body)

    ok = False
    detail = ""
    try:
        if config.UPLOAD_TRANSPORT == "wifi":
            if WLAN is None or not WLAN.isconnected():
                setup_wifi()
            status, text = http_client.post(
                config.UPLOAD_URL,
                body,
                timeout=config.HTTP_TIMEOUT_S,
            )
            detail = "HTTP %s" % status
            ok = 200 <= status < 300
        else:
            if EC800_MOD is None or not STATE.get("ec800_ok"):
                raise Exception("EC800 not ready")
            result = EC800_MOD.http_post(config.UPLOAD_URL, body)
            detail = "err=%d http=%d" % (result["err"], result["status"])
            ok = result["err"] == 0 and 200 <= result["status"] < 300
    except Exception as exc:
        sys.print_exception(exc)
        detail = "exception"

    log("upload", "OK" if ok else "FAIL", detail)
    STATE["last_up"] = now_epoch_ms()
    STATE["upload"] = "OK" if ok else "FAIL"

    gc.collect()
    UI_OBJ.update(STATE)


# ============================================================
# 主循环
# ============================================================

def main():
    log("gateway boot")
    init_hardware()

    UI_OBJ.boot("sampling...")
    sample_sensors()
    STATE["net"] = net_text()
    UI_OBJ.update(STATE)

    next_sample = time.ticks_add(time.ticks_ms(), config.SAMPLE_INTERVAL_MS)
    next_upload = time.ticks_ms()          # 首次立即上报
    last_ui = time.ticks_ms()

    while True:
        now = time.ticks_ms()

        if time.ticks_diff(now, next_sample) >= 0:
            sample_sensors()
            STATE["net"] = net_text()
            UI_OBJ.update(STATE)
            next_sample = time.ticks_add(time.ticks_ms(), config.SAMPLE_INTERVAL_MS)

        if time.ticks_diff(now, next_upload) >= 0:
            do_upload()
            next_upload = time.ticks_add(time.ticks_ms(), config.UPLOAD_INTERVAL_MS)

        now = time.ticks_ms()
        if time.ticks_diff(now, last_ui) >= 1000:
            remain = time.ticks_diff(next_upload, now)
            if remain < 0:
                remain = 0
            STATE["countdown"] = "NEXT:%02d:%02d" % (
                remain // 60000,
                (remain // 1000) % 60,
            )
            UI_OBJ.update(STATE)
            last_ui = now

        time.sleep_ms(100)


try:
    main()
except Exception as exc:
    # 不自动重启，方便在 Thonny 里直接看到错误
    sys.print_exception(exc)
    log("fatal error, stopped")
