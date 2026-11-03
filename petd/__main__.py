"""python -m petd"""
import argparse
import logging
import sys

import uvicorn

from . import config as config_mod
from .server import create_app


def main(argv=None):
    ap = argparse.ArgumentParser(prog="petd", description="AI agent 桌面宠物服务端")
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--no-gateway", action="store_true", help="不连 gateway（离线自测）")
    ap.add_argument("--log-level", default="info")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-5s %(name)s %(message)s")

    cfg = config_mod.load(args.config)
    host = args.host or cfg["server"]["host"]
    port = args.port or cfg["server"]["port"]

    if host in ("0.0.0.0", "::"):
        if config_mod.admin_password():
            print("[petd] 监听 %s —— 后台已启用口令保护。" % host)
        else:
            print("[petd] 监听 %s —— 后台未设口令：能连到这个端口的人都能查看状态、修改配置，请勿暴露到公网。" % host)
    else:
        print("[petd] 监听 %s:%d" % (host, port))
    print("[petd] 控制台 http://%s:%d/admin/" % (host, port))

    app = create_app(cfg, start_gateway=not args.no_gateway, port=port)
    uvicorn.run(app, host=host, port=port, log_level=args.log_level,
                ws_ping_interval=20, ws_ping_timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
