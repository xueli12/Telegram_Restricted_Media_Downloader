# coding=UTF-8
# Author:Gentlesprite
# Software:PyCharm
# Time:2024/9/5 19:08
# File:main.py
import os
import sys

from module.enums import ENVIRON, MODE
from module.util import check_environ
from module.web import Web
from module.parser import PARSE_ARGS
from module.downloader import TelegramRestrictedMediaDownloader


def run_with_api(trmd):
    """在后台启动 REST API 服务"""
    from module.api import TRMDAPI
    
    api = TRMDAPI(downloader=trmd, host='0.0.0.0', port=8080)
    
    # 在新线程中运行 API 服务器，避免阻塞主线程
    import threading
    api_thread = threading.Thread(target=api.run, daemon=True)
    api_thread.start()
    
    return api


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
            api_port = PARSE_ARGS.api_port if hasattr(PARSE_ARGS, 'api_port') and PARSE_ARGS.api_port else 8080
            api = run_with_api(trmd)
            print(f'REST API 已启动，访问地址：http://0.0.0.0:{api_port}')
            print(f'API 文档地址：http://0.0.0.0:{api_port}/docs')
        
        trmd.run()
