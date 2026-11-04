# RS485 环境监测网关（ESP32 + MicroPython + EC800）

按 `网关上传json.txt` 的约定实现：

- 1 路空气温湿度传感器（RS485 / Modbus RTU）
- 1 路七合一土壤传感器（RS485 / Modbus RTU）
- EC800 4G 模块 GNSS 定位
- ST7789 SPI 彩屏本地显示
- 每 10 分钟 HTTP POST 一次 JSON
- 开发环境：Thonny + ESP32 MicroPython

```
                 ┌──────────────┐
  空气温湿度 ────┤              │
  七合一土壤 ────┤ RS485/Modbus ├── ESP32 ── SPI ── ST7789 LCD
                 └──────────────┘    │
                                     ├── UART1 ── EC800 (AT + GNSS)
                                     └── WiFi / EC800 ── HTTP POST JSON
```

## 1. 目录结构

```
demo1/
├── gateway/
│   ├── main.py              主程序（采集、显示、定时上报）
│   ├── config.py            全部配置：引脚、WiFi、服务器、寄存器表
│   └── lib/
│       ├── modbus.py        RS485 半双工收发
│       ├── modbus_codec.py  CRC16、组帧、解帧（纯逻辑，可 PC 测试）
│       ├── sensors.py       空气温湿度 / 七合一土壤驱动
│       ├── ec800.py         EC800 AT 驱动：开机、驻网、GPS、QHTTPPOST
│       ├── gpsutil.py       QGPSLOC 解析、UTC→时间戳
│       ├── payload.py       按文档组装上报 JSON（纯逻辑，可 PC 测试）
│       ├── http_client.py   WiFi 下的极简 HTTP POST 客户端
│       ├── st7789.py        ST7789 最小驱动（内置 8x8 字库）
│       └── ui.py            屏幕布局与行级刷新
├── tools/
│   ├── test_server.py       PC 端 JSON 接收/校验服务器
│   └── selftest.py          PC 端自检（CRC、GPS、JSON 结构）
├── sample_payload.json      自检生成的标准上报样例
└── 网关上传json.txt          原始需求文档
```

## 2. 硬件接线（默认配置）

### ESP32 ↔ RS485 模块（MAX3485 / SP3485，3.3V）

| ESP32 | RS485 模块 | 说明 |
|---|---|---|
| GPIO17 | DI | 发送 |
| GPIO16 | RO | 接收 |
| GPIO4 | DE + RE（并接） | 方向控制，高电平发送 |
| 3V3 / GND | VCC / GND | 若模块是 5V 供电，注意 A/B 电平与共地 |

两路传感器都挂在同一对 A/B 上，靠 Modbus 从站地址区分（空气=1，土壤=2）。
总线两端各 120Ω 终端电阻，传感器用 12V 单独供电，并和 ESP32 共地。

### ESP32 ↔ EC800

| ESP32 | EC800 | 说明 |
|---|---|---|
| GPIO25 (TX) | RXD | 交叉连接 |
| GPIO26 (RX) | TXD | 交叉连接 |
| GPIO27 | PWRKEY | 低脉冲 700ms 开机；常电模块可设为 None |
| GPIO32 | RESET | 可选 |
| GND | GND | 必须共地 |

注意：

- EC800 峰值电流可达 2A，必须用独立 3.8V/4V 电源，不能从 ESP32 的 3V3 取电。
- 部分 EC800 模块的 UART 是 1.8V 电平，需电平转换；带 3.3V 电平的底板可直接连。
- 首次冷启动 + 搜星建议在室外或窗边，室内可能几分钟都定不到位。

### ESP32 ↔ ST7789（240×320）

| ESP32 | ST7789 | 说明 |
|---|---|---|
| GPIO18 | SCLK | SPI 时钟 |
| GPIO23 | MOSI | SPI 数据 |
| GPIO5 | CS | 片选 |
| GPIO21 | DC | 数据/命令 |
| GPIO22 | RST | 复位 |
| GPIO15 | BL | 背光，高电平亮 |
| 3V3 / GND | VCC / GND | 按屏幕额定电压 |

## 3. 默认 Modbus 寄存器表

空气温湿度（从站 1，功能码 0x03）：

| 寄存器 | 含义 | 换算 |
|---|---|---|
| 0x0000 | 空气温度 | 有符号 /10 ℃ |
| 0x0001 | 空气湿度 | /10 %RH |

七合一土壤（从站 2，一次读 0x0000~0x0006）：

| 寄存器 | 含义 | 换算 |
|---|---|---|
| 0x0000 | 土壤水分 | /10 %RH |
| 0x0001 | 土壤温度 | 有符号 /10 ℃ |
| 0x0002 | 电导率 | /1000，单位 dS/m |
| 0x0003 | pH | /10 |
| 0x0004 | 氮 | 原值 mg/kg |
| 0x0005 | 磷 | 原值 mg/kg |
| 0x0006 | 钾 | 原值 mg/kg |

不同厂家的寄存器顺序、数据类型、缩放系数可能不同。拿到手册后只改
`gateway/config.py` 里的 `AIR_FIELDS` / `SOIL_FIELDS` 即可，不用动代码。

## 4. 上报 JSON 说明

`sample_payload.json` 是自检生成的完整样例。关键点：

- `timestamp`：Unix 毫秒时间戳，优先取 GPS 的 UTC 时间，无定位时取 ESP32 时钟（WiFi 模式下会用 NTP 校准）。
- `gateway.unique_code`：`GW-8F3A9C2B`，与 `config.py` 一致。
- `gateway.sensor_count`：固定 2。
- 传感器 `unique_code`：网关唯一码 + `-0001` / `-0002`。
- `data` 固定保留 9 个字段，没采到的填 `null`，符合文档“没有可以为空”的要求。
- 空气传感器 `type` 使用文档给出的枚举 `temperature_humidity_npk`；
  土壤传感器使用 `npk`。如果服务器要求别的枚举，改 `config.py` 即可。

> 原文档示例中的注释和全角冒号不是合法 JSON，程序输出的是标准 JSON。

## 5. Thonny 部署步骤

1. 打开 Thonny → `运行` → `配置解释器` → 选择 `MicroPython (ESP32)`，选对 COM 口。
2. 如果板子还没有 MicroPython 固件，用该窗口里的“安装或更新 MicroPython”刷入 ESP32 固件。
3. 修改 `gateway/config.py`：
   - `WIFI_SSID` / `WIFI_PASSWORD`（只支持 2.4GHz）
   - `UPLOAD_URL` 改成 PC 的局域网地址
   - 按实际接线改引脚
4. 上传文件到设备（Thonny 右下角“文件”面板 → 右键 Upload）：
   - `gateway/config.py` → `/config.py`
   - `gateway/main.py` → `/main.py`
   - `gateway/lib/*.py` → `/lib/`（设备上没有 `lib` 目录就先新建）
5. 按 Ctrl+D 软重启，`main.py` 会自动运行并开机自启。
6. 串口 REPL 里会打印 `[GW] ...` 日志；屏幕同步刷新。

注意：不要把整个 `gateway` 目录原样传上去——`main.py` 用的是扁平 import
（`from modbus import ...`），要求 `lib` 下的文件直接位于 `/lib/`。

## 6. PC 端联调

### 6.1 启动测试服务器

```powershell
E:\Thonny\python.exe E:\MyCode\demo1\tools\test_server.py
```

启动后会打印本机可用地址，例如：

```
ESP32 可用地址: http://192.168.1.100:8000/api/v1/gateway/upload
```

首次运行 Windows 防火墙会弹窗，**允许专用网络**。收不到数据时先查防火墙。

### 6.2 设备配置

```python
UPLOAD_TRANSPORT = "wifi"
UPLOAD_URL = "http://192.168.1.100:8000/api/v1/gateway/upload"
```

ESP32 和 PC 必须在同一个 2.4GHz 局域网。

### 6.3 用 EC800 上传

把 `UPLOAD_TRANSPORT` 改成 `"ec800"`。此时必须满足：

- 服务器有公网可达地址（4G 网络访问不到你 PC 的 192.168.x.x）
- SIM 卡已开通数据，APN 正确（移动 `CMNET` / 联通 `UNINET` / 电信 `CTNET`）
- 已激活 PDP：代码里会自动执行 `AT+QICSGP` + `AT+QIACT=1`

## 7. PC 端自检

不需要开发板：

```powershell
E:\Thonny\python.exe E:\MyCode\demo1\tools\selftest.py
```

覆盖内容：

- Modbus CRC 已知向量（`01 03 00 00 00 0A → C5 CD`）
- 0x03 响应解帧、异常码、CRC 错误
- 有符号 16 位（负温度）
- `+QGPSLOC` 经纬度与 UTC 时间戳
- 上报 JSON 的字段、类型、唯一码、9 项 data

本工程已跑过，结果 `ALL PASSED`，并生成 `sample_payload.json`。

## 8. 关键配置项

| 配置 | 默认值 | 说明 |
|---|---|---|
| `UPLOAD_TRANSPORT` | `"wifi"` | `"wifi"` 或 `"ec800"` |
| `UPLOAD_URL` | 示例地址 | 完整 URL，含路径 |
| `UPLOAD_INTERVAL_MS` | 600000 | 10 分钟上报周期 |
| `SAMPLE_INTERVAL_MS` | 30000 | 30 秒采集/刷新周期 |
| `RS485_*` | UART2 / 17 / 16 / 4 | 波特率默认 9600 |
| `AIR_FIELDS` / `SOIL_FIELDS` | 见上表 | 字段名、缩放、符号 |
| `EC800_PWRKEY_PIN` | 27 | 常电模块填 `None` |
| `LCD_INVERT` | `True` | 反色屏幕切换 |
| `LCD_BGR` | `False` | 红蓝颠倒时改 `True` |

## 9. 屏幕布局

```
SOIL GATEWAY
AIR
T26.3C H65.1%
SOIL
T24.8C H68.2%
EC:1.20 pH:6.8
NPK 45/22/34
GPS
LAT:39.90923
LON:116.39743
FIX:3D
NET:WIFI -58
UP:16:30 OK
NEXT:09:59
```

屏幕只用内置 8x8 ASCII 字库（2 倍放大），所以标签是英文；中文只出现在上报 JSON 里。

## 10. 常见问题

**LCD 白屏/黑屏**
- 先确认背光脚有电；`LCD_BL_PIN` 接错或屏幕需要 PWM 亮度时先直接给 3.3V。
- 确认 `LCD_RST_PIN`、`LCD_DC_PIN`、SPI 引脚与 config 一致。
- 颜色发白：切换 `LCD_INVERT`；红蓝颠倒：切换 `LCD_BGR`。

**RS485 读不到数据**
- A/B 接反是最常见原因，先对调试试。
- 确认传感器供电（多数是 12V）并与 ESP32 共地。
- 确认从站地址：空气 1、土壤 2；用 USB-RS485 工具扫一遍总线更直接。
- 自动收发模块要把 `RS485_DE_PIN` 设为 `None`；手动方向模块不能悬空。
- 长距离/多设备时检查 120Ω 终端电阻和 9600 波特率。

**EC800 不开机**
- PWRKEY 是低电平脉冲开机；如果底板有电源开关或自动开机电路，把 `EC800_PWRKEY_PIN` 设为 `None`。
- 用独立电源，检查模块是否真的上电（部分模块有 NET/STATUS 指示灯）。

**GPS 一直无定位**
- 天线要朝上、尽量室外；冷启动可能 1~3 分钟。
- `AT+QGPS=1` 之后用 `AT+QGPSLOC=2` 轮询，无定位时模块返回 `+CME ERROR: 516`，程序会显示 `FIX:NO`。

**上报一直 FAIL**
- WiFi 模式：先看屏幕 `NET:`；确认 2.4GHz、密码、防火墙、URL 路径。
- EC800 模式：确认已驻网、`AT+QIACT?` 有激活的 PDP、服务器有公网地址。
- 看 Thonny REPL 里的 `[GW] upload FAIL ...` 和异常堆栈。

**timestamp 是 2000 年**
- 没有 GPS 定位且 WiFi 模式下 NTP 失败时会这样。接好 GPS 天线，或让 ESP32 能访问 NTP。

## 11. 已验证 / 未验证

已验证（PC 端，使用 Thonny 自带 Python 3.14）：

- 全部源文件语法检查通过
- Modbus 组帧/解帧、CRC、有符号数自检通过
- GPS 解析与时间戳自检通过
- 上报 JSON 结构与字段自检通过
- 本地测试服务器能接收样例 JSON 并返回 200；非法数据返回 400

未验证（需要实物）：

- RS485 实际总线收发（寄存器表按通用默认值，需按传感器手册校准）
- EC800 实际 AT 交互、驻网、GNSS 定位、QHTTPPOST
- ST7789 实际显示效果（引脚与初始化序列按 240×320 通用方案）

接上硬件后，先看 REPL 日志，再逐项对照第 10 节排查。
