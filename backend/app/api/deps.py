"""获取客户端 IP 工具。

因为部署在 Nginx 反代后面，X-Forwarded-For / X-Real-IP 是真实 IP。
信任哪个 header 由 nginx 配置决定；这里优先 X-Forwarded-For 第一个。
"""
from __future__ import annotations

from fastapi import Request


def get_client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # "client, proxy1, proxy2" → 取第一个
        return xff.split(",")[0].strip()
    xri = request.headers.get("x-real-ip")
    if xri:
        return xri.strip()
    if request.client:
        return request.client.host
    return "0.0.0.0"
