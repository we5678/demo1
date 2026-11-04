# -*- coding: utf-8 -*-
"""
极简 HTTP/1.1 POST 客户端（基于 socket，不依赖 urequests）。

支持 http:// 和 https://；https 不校验证书，适合现场联调。
"""

import socket

try:
    import ssl
except ImportError:
    ssl = None


def _parse_url(url):
    if url.startswith("https://"):
        scheme = "https"
        rest = url[8:]
        default_port = 443
    elif url.startswith("http://"):
        scheme = "http"
        rest = url[7:]
        default_port = 80
    else:
        raise ValueError("URL must start with http:// or https://")

    slash = rest.find("/")
    if slash < 0:
        hostport = rest
        path = "/"
    else:
        hostport = rest[:slash]
        path = rest[slash:]

    colon = hostport.find(":")
    if colon >= 0:
        host = hostport[:colon]
        port = int(hostport[colon + 1:])
    else:
        host = hostport
        port = default_port

    return scheme, host, port, path, hostport


def _wrap_ssl(sock, host):
    if ssl is None:
        raise OSError("ssl module not available")
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        try:
            ctx.verify_mode = ssl.CERT_NONE
        except Exception:
            pass
        return ctx.wrap_socket(sock, server_hostname=host)
    except Exception:
        return ssl.wrap_socket(sock, server_hostname=host)


def post(url, body, timeout=15, extra_headers=None, max_response=2048):
    """
    POST 一段数据，返回 (status_code, response_text)。

    body 可以是 str 或 bytes；默认 Content-Type: application/json。
    """
    scheme, host, port, path, hostport = _parse_url(url)
    if isinstance(body, str):
        body = body.encode()

    addr = socket.getaddrinfo(host, port)[0][-1]
    sock = socket.socket()
    sock.settimeout(timeout)

    try:
        sock.connect(addr)
    except OSError:
        sock.close()
        raise

    if scheme == "https":
        sock = _wrap_ssl(sock, host)

    if port in (80, 443):
        host_header = host
    else:
        host_header = hostport

    head = (
        "POST %s HTTP/1.1\r\n"
        "Host: %s\r\n"
        "Connection: close\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: %d\r\n"
    ) % (path, host_header, len(body))

    if extra_headers:
        for key in extra_headers:
            head += "%s: %s\r\n" % (key, extra_headers[key])

    head += "\r\n"

    sock.send(head.encode() + body)

    data = b""
    while len(data) < max_response:
        try:
            chunk = sock.recv(512)
        except OSError:
            break
        if not chunk:
            break
        data += chunk

    try:
        sock.close()
    except Exception:
        pass

    status = 0
    nl = data.find(b"\r\n")
    first_line = data[:nl] if nl > 0 else data[:64]
    parts = first_line.split(b" ")
    if len(parts) >= 2:
        try:
            status = int(parts[1].decode())
        except Exception:
            status = 0

    sep = data.find(b"\r\n\r\n")
    text_bytes = data[sep + 4:] if sep >= 0 else b""
    try:
        text = text_bytes.decode()
    except Exception:
        text = repr(text_bytes)

    return status, text
