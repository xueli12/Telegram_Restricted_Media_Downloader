# coding=UTF-8
# Author:Gentlesprite
# Software:PyCharm
# Time:2024/9/5 19:08
# File:main.py
import os
import sys
import asyncio
from contextlib import asynccontextmanager

from module.enums import ENVIRON, MODE
from module.util import check_environ
from module.web import Web
from module.parser import PARSE_ARGS
from module.downloader import TelegramRestrictedMediaDownloader


if __name__ == '__main__':
    check_environ()
    if os.environ.get(ENVIRON.TRMD_WEB_PORT) and os.environ.get(ENVIRON.TRMD_WEB_PID) is None:
        web = Web(__file__)
        if PARSE_ARGS.mode == MODE.SESSION:
            web.run_session()
        else:
            web.run_once()
    else:
        trmd = TelegramRestrictedMediaDownloader()
        
        # 如果启用了 API 参数，则启动 REST API 服务
        if hasattr(PARSE_ARGS, 'api') and PARSE_ARGS.api:
            from module.api import TRMDAPI
            
            api_port = PARSE_ARGS.api_port if hasattr(PARSE_ARGS, 'api_port') and PARSE_ARGS.api_port else 8080
            api = TRMDAPI(downloader=trmd, host='0.0.0.0', port=api_port)
            
            print(f'REST API 已启动，访问地址：http://0.0.0.0:{api_port}')
            print(f'API 文档地址：http://0.0.0.0:{api_port}/docs')
            
            # 使用 asyncio.run 运行 API，确保共享同一个事件循环
            try:
                asyncio.run(api.serve_async())
            except KeyboardInterrupt:
                print('API 服务已停止')
        else:
            trmd.run()
