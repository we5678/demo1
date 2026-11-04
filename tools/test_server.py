#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PC 端本地接收服务器，用来验证 ESP32 的上报 JSON。

运行：
    E:\\Thonny\\python.exe E:\\MyCode\\demo1\\tools\\test_server.py
    E:\\Thonny\\python.exe ...\\test_server.py --port 8000 --dir received

然后把 gateway/config.py 改成：
    UPLOAD_TRANSPORT = "wifi"
    UPLOAD_URL = "http://<本机局域网IP>:8000/api/v1/gateway/upload"

Windows 防火墙首次会弹窗，记得允许“专用网络”。
"""

import argparse
import json
import os
import socket
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATA_KEYS = (
    "soil_temperature",
    "soil_humidity",
    "nitrogen",
    "phosphorus",
    "potassium",
    "ph",
    "salinity",
    "air_temperature",
    "air_humidity",
)


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate(payload):
    """按《网关上传json.txt》校验，返回错误列表（空表示通过）。"""
    errors = []

    if not isinstance(payload, dict):
        return ["根节点必须是 JSON 对象"]

    ts = payload.get("timestamp")
    if not isinstance(ts, int) or isinstance(ts, bool) or ts <= 0:
        errors.append("timestamp 必须是正整数（毫秒时间戳）")

    gw = payload.get("gateway")
    if not isinstance(gw, dict):
        errors.append("缺少 gateway 对象")
        gw = {}

    for key in ("gateway_id", "unique_code"):
        value = gw.get(key)
        if not isinstance(value, str) or not value:
            errors.append("gateway.%s 必须是非空字符串" % key)

    sensor_count = gw.get("sensor_count")
    if not isinstance(sensor_count, int) or isinstance(sensor_count, bool):
        errors.append("gateway.sensor_count 必须是整数")

    loc = gw.get("location")
    if not isinstance(loc, dict):
        errors.append("缺少 gateway.location 对象")
    else:
        lat = loc.get("latitude")
        lon = loc.get("longitude")
        if not is_number(lat) or not -90 <= lat <= 90:
            errors.append("gateway.location.latitude 不合法")
        if not is_number(lon) or not -180 <= lon <= 180:
            errors.append("gateway.location.longitude 不合法")

    sensors = payload.get("sensors")
    if not isinstance(sensors, list) or not sensors:
        errors.append("sensors 必须是非空数组")
        return errors

    if sensor_count != len(sensors):
        errors.append("sensor_count=%s 与 sensors 数量 %d 不一致"
                      % (sensor_count, len(sensors)))

    unique = gw.get("unique_code") or ""
    for i, sensor in enumerate(sensors):
        tag = "sensors[%d]" % i
        if not isinstance(sensor, dict):
            errors.append("%s 必须是对象" % tag)
            continue
        for key in ("sensor_id", "unique_code", "type", "type_name"):
            if not isinstance(sensor.get(key), str) or not sensor.get(key):
                errors.append("%s.%s 必须是非空字符串" % (tag, key))
        code = sensor.get("unique_code") or ""
        if unique and not code.startswith(unique + "-"):
            errors.append("%s.unique_code 应以 '%s-' 开头" % (tag, unique))

        data = sensor.get("data")
        if not isinstance(data, dict):
            errors.append("%s.data 必须是对象" % tag)
            continue
        unknown = [k for k in data if k not in DATA_KEYS]
        if unknown:
            errors.append("%s.data 含未知字段: %s" % (tag, ", ".join(unknown)))
        for key, value in data.items():
            if value is not None and not is_number(value):
                errors.append("%s.data.%s 必须是数值或 null" % (tag, key))

    return errors


class Handler(BaseHTTPRequestHandler):
    server_version = "GatewayTestServer/1.0"

    def _json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") in ("/health", "/"):
            self._json(200, {"ok": True, "service": "gateway-test-server"})
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        client = self.client_address[0]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""

        print("\n[%s] POST %s from %s (%d bytes)"
              % (datetime.now().strftime("%H:%M:%S"), self.path, client, len(raw)))

        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            print("  JSON 解析失败: %s" % exc)
            self._json(400, {"ok": False, "errors": ["JSON 解析失败: %s" % exc]})
            return

        errors = validate(payload)
        if errors:
            print("  校验失败:")
            for err in errors:
                print("    - %s" % err)
            self._json(400, {"ok": False, "errors": errors})
            return

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_ip = client.replace(":", "_")
        name = "%s-%s.json" % (stamp, safe_ip)
        path = os.path.join(self.server.output_dir, name)
        with open(path, "wb") as f:
            f.write(raw if raw else json.dumps(payload, ensure_ascii=False).encode("utf-8"))

        print("  校验通过，已保存: %s" % path)
        print(json.dumps(payload, ensure_ascii=False, indent=2))

        self._json(200, {"ok": True, "saved": name})

    def log_message(self, fmt, *args):
        # 安静模式：只打印我们自己的日志
        pass


def local_ips():
    ips = set()
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None):
            ip = info[4][0]
            if "." in ip:
                ips.add(ip)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return sorted(ips)


def main():
    parser = argparse.ArgumentParser(description="网关上报 JSON 本地测试服务器")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--dir",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "received"),
    )
    args = parser.parse_args()

    os.makedirs(args.dir, exist_ok=True)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.output_dir = args.dir

    print("=" * 60)
    print("网关测试服务器已启动")
    print("监听: http://%s:%d" % (args.host, args.port))
    for ip in local_ips():
        print("  ESP32 可用地址: http://%s:%d/api/v1/gateway/upload" % (ip, args.port))
    print("保存目录: %s" % args.dir)
    print("Ctrl+C 停止")
    print("=" * 60)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        server.server_close()


if __name__ == "__main__":
    main()
