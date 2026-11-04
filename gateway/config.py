# -*- coding: utf-8 -*-
"""
网关全局配置

现场部署时主要改这个文件。改完后要把本文件重新上传到设备根目录 /config.py。
"""

# ============================================================
# 1. 设备标识（对应网关上传json.txt 里的 gateway 块）
# ============================================================
GATEWAY_ID = "GW-2026-0001"           # 网关业务标识，可自定义
GATEWAY_UNIQUE_CODE = "GW-8F3A9C2B"   # 网关唯一码（出厂 SN，全局唯一）

# 传感器业务标识与类型枚举（type 字段必须和服务器约定一致）
AIR_SENSOR_ID = "S-TH-0001"
AIR_SENSOR_TYPE = "temperature_humidity_npk"   # 文档中“温湿度”对应的枚举
AIR_SENSOR_TYPE_NAME = "温湿度传感器"

SOIL_SENSOR_ID = "S-NPK-0001"
SOIL_SENSOR_TYPE = "npk"
SOIL_SENSOR_TYPE_NAME = "七合一土壤传感器"

# ============================================================
# 2. 上报（HTTP POST + 周期）
# ============================================================
# "wifi"  : 走 ESP32 WiFi 上传，适合局域网联调
# "ec800" : 走 EC800 的 AT+QHTTPPOST 上传，需要服务器有公网地址
UPLOAD_TRANSPORT = "wifi"

# 本机测试服务器地址示例：http://192.168.1.100:8000/api/v1/gateway/upload
UPLOAD_URL = "http://192.168.1.100:8000/api/v1/gateway/upload"

UPLOAD_INTERVAL_MS = 10 * 60 * 1000    # 10 分钟上报一次
SAMPLE_INTERVAL_MS = 30 * 1000         # 30 秒采集一次并刷新 LCD
HTTP_TIMEOUT_S = 15

# ============================================================
# 3. WiFi（仅 UPLOAD_TRANSPORT = "wifi" 时使用）
# ============================================================
WIFI_SSID = "YOUR_WIFI_SSID"          # ESP32 只支持 2.4GHz
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
WIFI_TIMEOUT_S = 20

# ============================================================
# 4. RS485 / Modbus RTU（两路传感器挂在同一条 485 总线上）
# ============================================================
RS485_UART_ID = 2
RS485_TX_PIN = 17          # ESP32 TX -> MAX3485 DI
RS485_RX_PIN = 16          # ESP32 RX <- MAX3485 RO
RS485_DE_PIN = 4           # DE/RE 并接后接此脚；自动收发模块填 None
RS485_BAUDRATE = 9600
RS485_TIMEOUT_MS = 300
RS485_RETRIES = 3

# ---- 空气温湿度传感器（从站 1）----
AIR_SLAVE = 1
AIR_START_REG = 0x0000
# (字段名, 缩放系数, 是否按有符号 16 位解析)
AIR_FIELDS = [
    ("air_temperature", 10.0, True),    # 0x0000 温度 ×0.1
    ("air_humidity",    10.0, False),   # 0x0001 湿度 ×0.1
]

# ---- 七合一土壤传感器（从站 2）----
SOIL_SLAVE = 2
SOIL_START_REG = 0x0000     # 一次性读 7 个寄存器
# (字段名, 缩放系数, 是否按有符号 16 位解析)
SOIL_FIELDS = [
    ("soil_humidity",    10.0,   False),   # 0x0000 水分 %RH ×0.1
    ("soil_temperature", 10.0,   True),    # 0x0001 温度 ℃ ×0.1
    ("salinity",         1000.0, False),   # 0x0002 电导率 µS/cm -> dS/m
    ("ph",               10.0,   False),   # 0x0003 pH ×0.1
    ("nitrogen",         1.0,    False),   # 0x0004 氮 mg/kg
    ("phosphorus",       1.0,    False),   # 0x0005 磷 mg/kg
    ("potassium",        1.0,    False),   # 0x0006 钾 mg/kg
]
# 注意：七合一传感器的寄存器顺序和缩放系数各厂家不同，
# 拿到手册后按实际值改上面的表即可，不用改代码。

# ============================================================
# 5. EC800 4G 模块（AT 指令，串口 1）
# ============================================================
EC800_UART_ID = 1
EC800_TX_PIN = 25          # ESP32 TX -> 模块 RX
EC800_RX_PIN = 26          # ESP32 RX <- 模块 TX
EC800_BAUDRATE = 115200
EC800_PWRKEY_PIN = 27      # 低电平脉冲开机；模块常电/自动开机时填 None
EC800_RESET_PIN = 32       # 可填 None
EC800_APN = "CMNET"        # 移动 CMNET / 联通 UNINET / 电信 CTNET
EC800_RXBUF = 2048
GPS_TIMEOUT_S = 90         # 冷启动定位最长等待（代码里按次轮询，不会真的阻塞这么久）

# ============================================================
# 6. ST7789 SPI 彩屏（240x320）
# ============================================================
LCD_WIDTH = 240
LCD_HEIGHT = 320
LCD_SPI_ID = 2             # ESP32 的 VSPI
LCD_SCK_PIN = 18
LCD_MOSI_PIN = 23
LCD_CS_PIN = 5
LCD_DC_PIN = 21
LCD_RST_PIN = 22
LCD_BL_PIN = 15            # 背光，高电平点亮；不控制背光可填 None
LCD_BAUDRATE = 40000000
LCD_ROTATION = 0           # 0/2 竖屏，1/3 横屏
LCD_INVERT = True          # 颜色发白/反色时切换
LCD_BGR = False            # 红蓝颠倒时改为 True

# ============================================================
# 7. 显示
# ============================================================
LOCAL_TZ_OFFSET_MIN = 480  # 东八区 UTC+8，用于 LCD 上的时间显示
