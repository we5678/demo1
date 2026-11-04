# -*- coding: utf-8 -*-
"""
EC800 4G Cat.1 模块驱动（AT 指令）：

- 上电 / 初始化 / 驻网 / APN 激活
- GNSS 定位读取（AT+QGPSLOC）
- HTTP POST 上报（AT+QHTTPPOST）

AT 手册参考 Quectel EC800 系列《AT 命令手册》里的 QGPS / QHTTP 章节。
"""

import time
from machine import UART, Pin

from gpsutil import parse_qgpsloc


class EC800Error(Exception):
    pass


class EC800:
    def __init__(self, uart_id, tx_pin, rx_pin, baudrate=115200,
                 pwrkey_pin=None, reset_pin=None, rxbuf=2048):
        self.uart = UART(
            uart_id,
            baudrate=baudrate,
            tx=Pin(tx_pin),
            rx=Pin(rx_pin),
            timeout=100,
            rxbuf=rxbuf,
        )
        self.pwrkey = None
        if pwrkey_pin is not None:
            self.pwrkey = Pin(pwrkey_pin, Pin.OUT, value=1)
        self.reset_pin = None
        if reset_pin is not None:
            self.reset_pin = Pin(reset_pin, Pin.OUT, value=1)

    # ---------------- 底层 AT 收发 ----------------

    def _drain(self):
        while self.uart.any():
            self.uart.read()

    def _read_until(self, tokens, timeout_ms):
        buf = ""
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)

        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            n = self.uart.any()
            if n:
                chunk = self.uart.read(n)
                if chunk:
                    try:
                        buf += chunk.decode()
                    except Exception:
                        buf += "".join(chr(b) for b in chunk)
                    for token in tokens:
                        if token in buf:
                            return token, buf
            else:
                time.sleep_ms(20)

        return None, buf

    def at(self, cmd, timeout_ms=2000):
        """发一条 AT 指令，成功返回整段响应，失败抛 EC800Error。"""
        self._drain()
        self.uart.write((cmd + "\r\n").encode())

        token, buf = self._read_until(["OK", "ERROR", "+CME ERROR"], timeout_ms)
        if token is None:
            raise EC800Error("AT timeout: %s" % cmd)
        if token != "OK":
            raise EC800Error("AT failed: %s (%s)" % (cmd, buf.strip()[-100:]))
        return buf

    # ---------------- 电源与网络 ----------------

    def power_on(self, timeout_s=20):
        """PWRKEY 低脉冲开机，然后反复 AT 探测。模块常电时直接探测。"""
        if self.pwrkey is not None:
            self.pwrkey.value(0)
            time.sleep_ms(700)
            self.pwrkey.value(1)

        deadline = time.ticks_add(time.ticks_ms(), timeout_s * 1000)
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            try:
                self.at("AT", 1000)
                return True
            except EC800Error:
                time.sleep_ms(1000)
        return False

    def reset(self):
        if self.reset_pin is None:
            return
        self.reset_pin.value(0)
        time.sleep_ms(300)
        self.reset_pin.value(1)
        time.sleep_ms(3000)

    def init(self, apn, timeout_s=60):
        self.at("AT")
        self.at("ATE0", 1000)
        self.at("AT+CMEE=1", 1000)

        resp = self.at("AT+CPIN?", 3000)
        if "READY" not in resp:
            raise EC800Error("SIM not ready: %s" % resp.strip()[-80:])

        if not self.wait_registration(timeout_s):
            raise EC800Error("network registration timeout")

        self.at('AT+QICSGP=1,1,"%s","","",1' % apn, 5000)
        try:
            self.at("AT+QIACT=1", 90000)
        except EC800Error:
            # 已经激活时部分固件会直接返回 ERROR，忽略即可
            pass

    def wait_registration(self, timeout_s=60):
        deadline = time.ticks_add(time.ticks_ms(), timeout_s * 1000)
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            try:
                resp = self.at("AT+CEREG?", 3000)
            except EC800Error:
                resp = ""
            # +CEREG: 0,1 本地网 / 0,5 漫游网
            if ",1" in resp or ",5" in resp:
                return True
            time.sleep_ms(2000)
        return False

    def csq(self):
        """返回信号强度 0-31 的整数，失败返回 None。"""
        try:
            resp = self.at("AT+CSQ", 2000)
        except EC800Error:
            return None
        for line in resp.replace("\r", "").split("\n"):
            if line.startswith("+CSQ:"):
                try:
                    return int(line.split(":", 1)[1].split(",")[0])
                except ValueError:
                    return None
        return None

    # ---------------- GNSS ----------------

    def gps_start(self):
        try:
            self.at("AT+QGPS=1", 5000)
        except EC800Error:
            # 已经打开时会报 ERROR 504，忽略
            pass

    def gps_stop(self):
        try:
            self.at("AT+QGPSEND", 5000)
        except EC800Error:
            pass

    def gps_locate(self):
        """返回定位 dict（见 gpsutil.parse_qgpsloc），无定位返回 None。"""
        try:
            resp = self.at("AT+QGPSLOC=2", 5000)
        except EC800Error:
            return None
        return parse_qgpsloc(resp)

    # ---------------- HTTP POST ----------------

    def http_post(self, url, body, timeout_ms=90000):
        """
        用 AT+QHTTPPOST 发 JSON。

        返回 {"err": int, "status": int, "raw": str}
        err=0 表示模块侧成功，status 是服务器 HTTP 状态码。
        """
        if isinstance(body, str):
            body = body.encode()
        url_b = url.encode()

        self.at('AT+QHTTPCFG="contextid",1', 3000)

        # 1) 下发 URL：AT+QHTTPURL=<len>,<timeout> -> CONNECT -> 发送 URL 字节
        self._drain()
        self.uart.write(("AT+QHTTPURL=%d,80\r\n" % len(url_b)).encode())
        token, _ = self._read_until(["CONNECT", "ERROR"], 10000)
        if token != "CONNECT":
            raise EC800Error("QHTTPURL: no CONNECT prompt")

        self.uart.write(url_b)
        token, buf = self._read_until(["OK", "ERROR"], 10000)
        if token != "OK":
            raise EC800Error("QHTTPURL failed: %s" % buf.strip()[-100:])

        # 2) 发 POST：AT+QHTTPPOST=<len>,<cmd_timeout>,<rsp_timeout> -> CONNECT -> body
        self._drain()
        self.uart.write(("AT+QHTTPPOST=%d,80,80\r\n" % len(body)).encode())
        token, _ = self._read_until(["CONNECT", "ERROR"], 10000)
        if token != "CONNECT":
            raise EC800Error("QHTTPPOST: no CONNECT prompt")

        self.uart.write(body)

        token, buf = self._read_until(["+QHTTPPOST:", "ERROR"], timeout_ms)
        if token != "+QHTTPPOST:":
            raise EC800Error("QHTTPPOST no result: %s" % buf.strip()[-100:])

        # 状态行可能被拆成两次到达，继续读到尾部 OK
        _, tail = self._read_until(["OK", "ERROR"], 5000)
        buf += tail

        err = -1
        status = 0
        for line in buf.replace("\r", "").split("\n"):
            if line.startswith("+QHTTPPOST:"):
                parts = line.split(":", 1)[1].split(",")
                try:
                    err = int(parts[0])
                    status = int(parts[1])
                except (ValueError, IndexError):
                    pass

        return {"err": err, "status": status, "raw": buf}
