#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SubWatch 示例后端（可选）
------------------------
纯标准库实现的演示服务，提供前端需要的三个接口 + 静态文件托管。
无需任何第三方依赖，直接运行即可预览完整效果（含延迟测试与测速）：

    python3 api/demo_server.py
    # 然后浏览器打开 http://127.0.0.1:8899/

接口契约（对接自己的后端时按此实现即可）：
    GET  /subinfo-api/api/subinfo            订阅流量 / 节点 / 到期信息
    POST /subinfo-api/api/refresh            触发一次流量同步
    GET  /subinfo-api/api/ping               节点 TCP 连通性探测（可缓存 10~15s）
    GET  /subinfo-api/api/speedtest?size=N   返回 N 字节下载流（用于测带宽）
"""
import http.server
import json
import os
import socketserver
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(os.environ.get("PORT", "8899"))
HOST = os.environ.get("HOST", "127.0.0.1")
API_PREFIX = "/subinfo-api"

GB = 1024 ** 3


def fmt_bytes(b):
    units = ["B", "KB", "MB", "GB", "TB"]
    i, v = 0, float(b)
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    return ("%.0f " if i == 0 else "%.2f ") % v + units[i]


def build_subinfo():
    """构造示例订阅数据（真实场景请替换为读取订阅文件 / 上游 API）"""
    now = int(time.time())
    upload = 5.08 * GB
    download = 10.39 * GB
    total = 1024 * GB
    used = upload + download
    expire = now + 25 * 86400 + 7 * 3600
    return {
        "ok": True,
        "subscription_url": "https://example.com/sub/demo-token.yaml",
        "upload": int(upload),
        "download": int(download),
        "total": total,
        "expire": expire,
        "updated_at": now - 38,
        "used": int(used),
        "used_percent": round(used / total * 100, 2),
        "days_left": (expire - now) // 86400,
        "fmt": {
            "upload": fmt_bytes(upload),
            "download": fmt_bytes(download),
            "total": fmt_bytes(total),
            "used": fmt_bytes(used),
        },
        "nodes": {
            "count": 3,
            "proxies": [
                {"name": "Demo-HK-01", "type": "hysteria2", "server": "192.0.2.11", "port": 443},
                {"name": "Demo-SG-02", "type": "vless", "server": "192.0.2.12", "port": 8443},
                {"name": "Demo-JP-03", "type": "trojan", "server": "192.0.2.13", "port": 443},
            ],
        },
        "refreshing": False,
        "last_refresh": {"started_at": now - 45, "finished_at": now - 42, "ok": True},
        "server_time": now,
    }


def build_ping():
    """示例延迟数据（真实场景：对节点 server:port 做 TCP connect 计时）"""
    return {
        "nodes": [
            {"name": "Demo-HK-01", "tcp_ms": 86},
            {"name": "Demo-SG-02", "tcp_ms": 142},
            {"name": "Demo-JP-03", "tcp_ms": 213},
        ]
    }


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    # ---------- 工具 ----------
    def _json(self, obj, code=200, extra_headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _stream(self, size):
        """流式吐出 size 字节，用于前端测带宽"""
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        # 关掉 nginx 缓冲：X-Accel-Buffering: no
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        chunk = b"\0" * (64 * 1024)
        sent = 0
        try:
            while sent < size:
                n = min(len(chunk), size - sent)
                self.wfile.write(chunk[:n])
                sent += n
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---------- 路由 ----------
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        if path == API_PREFIX + "/api/subinfo":
            return self._json(build_subinfo())
        if path == API_PREFIX + "/api/ping":
            return self._json(build_ping(), extra_headers={"Cache-Control": "max-age=10"})
        if path == API_PREFIX + "/api/speedtest":
            size = int((query.get("size") or ["20971520"])[0])
            return self._stream(max(1024, min(size, 200 * 1024 * 1024)))

        if path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == API_PREFIX + "/api/refresh":
            time.sleep(0.6)  # 模拟拉取耗时
            return self._json({"ok": True, "refreshing": False, "message": "示例后端：同步完成"})
        return self._json({"ok": False, "message": "not found"}, code=404)

    def log_message(self, fmt, *args):
        # 只打印 API 请求，静态资源日志静音
        line = fmt % args
        if API_PREFIX in line:
            print("[demo] " + line)


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    print(f"SubWatch 示例服务已启动 → http://{HOST}:{PORT}/")
    print(f"静态根目录: {ROOT}")
    print("按 Ctrl+C 停止\n")
    with ThreadingServer((HOST, PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止")
