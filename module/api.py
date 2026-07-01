# coding=UTF-8
# Author:Gentlesprite
# Software:PyCharm
# Time:2026/03/30
# File:api.py
"""
REST API 模块 - 提供 HTTP 接口供其他程序调用 TRMD 功能
"""
import os
import sys
import asyncio
import uuid
from typing import Optional, List, Dict, Any, Union
from datetime import datetime

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from uvicorn import Config, Server

from module import log, console
from module.language import _t
from module.enums import KeyWord, DownloadStatus, UploadStatus
from module.task import DownloadTask, UploadTask


class DownloadRequest(BaseModel):
    """下载请求模型"""
    links: List[str] = Field(..., description="Telegram 消息链接列表")
    start_id: Optional[int] = Field(None, description="起始消息 ID (范围下载)")
    end_id: Optional[int] = Field(None, description="结束消息 ID (范围下载)")
    with_upload: bool = Field(False, description="下载完成后是否上传")
    upload_chat_id: Optional[Union[str, int]] = Field(None, description="上传目标频道 ID")
    delete_after_upload: bool = Field(False, description="上传后是否删除本地文件")


class UploadRequest(BaseModel):
    """上传请求模型"""
    file_paths: List[str] = Field(..., description="要上传的文件路径列表")
    chat_id: Union[str, int] = Field(..., description="目标频道 ID")
    delete_after_upload: bool = Field(False, description="上传后是否删除本地文件")
    send_as_media_group: bool = Field(True, description="是否作为媒体组发送")


class TaskResponse(BaseModel):
    """任务响应模型"""
    task_id: str
    status: str
    message: str
    created_at: str


class TaskStatusResponse(BaseModel):
    """任务状态响应模型"""
    task_id: str
    status: str
    progress: Optional[float] = None
    file_name: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str
    updated_at: str


class DownloadTaskInfo(BaseModel):
    """下载任务信息"""
    link: str
    link_type: Optional[str]
    member_num: int
    complete_num: int
    file_names: List[str]
    error_msg: Dict[str, Any]
    status: str


class UploadTaskInfo(BaseModel):
    """上传任务信息"""
    file_path: str
    file_name: str
    file_size: int
    chat_id: Union[str, int, None]
    status: str
    error_msg: Optional[str] = None
    progress: float = 0.0


class ConfigResponse(BaseModel):
    """配置响应模型"""
    api_id: Optional[str]
    bot_token: Optional[str]
    save_directory: str
    temp_directory: str
    max_download_task: int
    max_upload_task: int
    enable_proxy: bool
    download_type: List[str]


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    version: str
    is_running: bool
    active_download_tasks: int
    active_upload_tasks: int


class TRMDTaskManager:
    """TRMD 任务管理器 - 管理通过 API 创建的任务"""
    
    TASKS: Dict[str, Dict[str, Any]] = {}
    
    @classmethod
    def create_task(cls, task_type: str, **kwargs) -> str:
        """创建新任务"""
        task_id = str(uuid.uuid4())
        cls.TASKS[task_id] = {
            'task_type': task_type,
            'status': 'pending',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
            'data': kwargs,
            'error_message': None,
            'progress': 0.0
        }
        log.info(f'创建 API 任务:{task_id},类型:{task_type}')
        return task_id
    
    @classmethod
    def update_task(cls, task_id: str, **kwargs) -> bool:
        """更新任务状态"""
        if task_id not in cls.TASKS:
            return False
        cls.TASKS[task_id]['updated_at'] = datetime.now().isoformat()
        for key, value in kwargs.items():
            if key in cls.TASKS[task_id]:
                cls.TASKS[task_id][key] = value
        return True
    
    @classmethod
    def get_task(cls, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务信息"""
        return cls.TASKS.get(task_id)
    
    @classmethod
    def delete_task(cls, task_id: str) -> bool:
        """删除任务"""
        if task_id in cls.TASKS:
            del cls.TASKS[task_id]
            log.info(f'删除任务:{task_id}')
            return True
        return False
    
    @classmethod
    def list_tasks(cls, task_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出所有任务"""
        if task_type:
            return [task for task in cls.TASKS.values() if task['task_type'] == task_type]
        return list(cls.TASKS.values())


class TRMDAPI:
    """TRMD REST API 服务类"""
    
    def __init__(self, downloader=None, host: str = '0.0.0.0', port: int = 8080):
        self.host = host
        self.port = port
        self.downloader = downloader
        self.app = FastAPI(
            title='TRMD REST API',
            description='Telegram Restricted Media Downloader REST API 接口',
            version='1.0.0'
        )
        self.server: Optional[Server] = None
        self._setup_app()
    
    def _setup_app(self):
        """配置 FastAPI 应用"""
        # CORS 中间件
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=['*'],
            allow_credentials=True,
            allow_methods=['*'],
            allow_headers=['*'],
        )
        
        # 注册路由
        self._register_routes()
    
    def _register_routes(self):
        """注册 API 路由"""
        
        @self.app.get('/', response_model=HealthResponse, tags=['系统'])
        async def root():
            """API 根路径 - 健康检查"""
            active_downloads = len([t for t in DownloadTask.LINK_INFO.values()])
            active_uploads = len(UploadTask.TASKS)
            return HealthResponse(
                status='healthy',
                version='1.0.0',
                is_running=self.downloader.is_running if self.downloader else False,
                active_download_tasks=active_downloads,
                active_upload_tasks=active_uploads
            )
        
        @self.app.get('/health', response_model=HealthResponse, tags=['系统'])
        async def health_check():
            """健康检查接口"""
            active_downloads = len([t for t in DownloadTask.LINK_INFO.values()])
            active_uploads = len(UploadTask.TASKS)
            return HealthResponse(
                status='healthy',
                version='1.0.0',
                is_running=self.downloader.is_running if self.downloader else False,
                active_download_tasks=active_downloads,
                active_upload_tasks=active_uploads
            )
        
        @self.app.post('/download', response_model=TaskResponse, tags=['下载'])
        async def create_download_task(request: DownloadRequest, background_tasks: BackgroundTasks):
            """
            创建下载任务
            
            - **links**: Telegram 消息链接列表
            - **start_id**: 起始消息 ID (可选，用于范围下载)
            - **end_id**: 结束消息 ID (可选，用于范围下载)
            - **with_upload**: 下载完成后是否上传
            - **upload_chat_id**: 上传目标频道 ID
            - **delete_after_upload**: 上传后是否删除本地文件
            """
            if not self.downloader or not self.downloader.is_running:
                raise HTTPException(status_code=503, detail='下载器未运行')
            
            if not request.links:
                raise HTTPException(status_code=400, detail='链接列表不能为空')
            
            task_id = TRMDTaskManager.create_task(
                task_type='download',
                links=request.links,
                start_id=request.start_id,
                end_id=request.end_id
            )
            
            async def process_download():
                try:
                    for link in request.links:
                        # 处理范围下载
                        if request.start_id and request.end_id:
                            for msg_id in range(request.start_id, request.end_id + 1):
                                full_link = f'{link}/{msg_id}?single'
                                await self._execute_download(full_link, request, task_id)
                        else:
                            await self._execute_download(link, request, task_id)
                    
                    TRMDTaskManager.update_task(
                        task_id=task_id,
                        status='completed',
                        progress=100.0
                    )
                except Exception as e:
                    log.error(f'下载任务失败:{task_id},原因:{e}')
                    TRMDTaskManager.update_task(
                        task_id=task_id,
                        status='failed',
                        error_message=str(e)
                    )
            
            background_tasks.add_task(process_download)
            
            return TaskResponse(
                task_id=task_id,
                status='pending',
                message='下载任务已创建',
                created_at=datetime.now().isoformat()
            )
        
        @self.app.post('/upload', response_model=TaskResponse, tags=['上传'])
        async def create_upload_task(request: UploadRequest, background_tasks: BackgroundTasks):
            """
            创建上传任务
            
            - **file_paths**: 要上传的文件路径列表
            - **chat_id**: 目标频道 ID
            - **delete_after_upload**: 上传后是否删除本地文件
            - **send_as_media_group**: 是否作为媒体组发送
            """
            if not self.downloader or not self.downloader.is_running:
                raise HTTPException(status_code=503, detail='下载器未运行')
            
            if not request.file_paths:
                raise HTTPException(status_code=400, detail='文件路径列表不能为空')
            
            # 验证文件是否存在
            for file_path in request.file_paths:
                if not os.path.exists(file_path):
                    raise HTTPException(status_code=400, detail=f'文件不存在:{file_path}')
            
            task_id = TRMDTaskManager.create_task(
                task_type='upload',
                file_paths=request.file_paths,
                chat_id=request.chat_id,
                delete_after_upload=request.delete_after_upload
            )
            
            async def process_upload():
                try:
                    if self.downloader.uploader:
                        for file_path in request.file_paths:
                            upload_task = UploadTask(
                                chat_id=request.chat_id,
                                file_path=file_path,
                                file_id=0,
                                file_size=os.path.getsize(file_path),
                                file_part=[],
                                status=UploadStatus.PENDING,
                                with_delete=request.delete_after_upload,
                                send_as_media_group=request.send_as_media_group
                            )
                            await self.downloader.uploader.create_upload_task(
                                link=file_path,
                                upload_task=upload_task
                            )
                        
                        TRMDTaskManager.update_task(
                            task_id=task_id,
                            status='completed',
                            progress=100.0
                        )
                    else:
                        raise Exception('上传器未初始化')
                except Exception as e:
                    log.error(f'上传任务失败:{task_id},原因:{e}')
                    TRMDTaskManager.update_task(
                        task_id=task_id,
                        status='failed',
                        error_message=str(e)
                    )
            
            background_tasks.add_task(process_upload)
            
            return TaskResponse(
                task_id=task_id,
                status='pending',
                message='上传任务已创建',
                created_at=datetime.now().isoformat()
            )
        
        @self.app.get('/tasks', tags=['任务管理'])
        async def list_tasks(
            task_type: Optional[str] = Query(None, description='任务类型:download|upload'),
            status: Optional[str] = Query(None, description='任务状态')
        ):
            """列出所有任务"""
            tasks = TRMDTaskManager.list_tasks(task_type)
            if status:
                tasks = [t for t in tasks if t['status'] == status]
            return {'tasks': tasks}
        
        @self.app.get('/tasks/{task_id}', response_model=TaskStatusResponse, tags=['任务管理'])
        async def get_task_status(task_id: str):
            """获取任务状态"""
            task = TRMDTaskManager.get_task(task_id)
            if not task:
                raise HTTPException(status_code=404, detail='任务不存在')
            
            return TaskStatusResponse(
                task_id=task_id,
                status=task['status'],
                progress=task.get('progress'),
                error_message=task.get('error_message'),
                created_at=task['created_at'],
                updated_at=task['updated_at']
            )
        
        @self.app.delete('/tasks/{task_id}', tags=['任务管理'])
        async def cancel_task(task_id: str):
            """取消/删除任务"""
            if not TRMDTaskManager.delete_task(task_id):
                raise HTTPException(status_code=404, detail='任务不存在')
            return {'message': '任务已取消'}
        
        @self.app.get('/downloads', tags=['下载'])
        async def list_download_tasks():
            """列出所有下载任务"""
            downloads = []
            for link, info in DownloadTask.LINK_INFO.items():
                downloads.append(DownloadTaskInfo(
                    link=link,
                    link_type=info.get('link_type'),
                    member_num=info.get('member_num', 0),
                    complete_num=info.get('complete_num', 0),
                    file_names=list(info.get('file_name', set())),
                    error_msg=info.get('error_msg', {}),
                    status='completed' if link in DownloadTask.COMPLETE_LINK else 'downloading'
                ))
            return {'downloads': downloads}
        
        @self.app.get('/uploads', tags=['上传'])
        async def list_upload_tasks():
            """列出所有上传任务"""
            uploads = []
            for task in UploadTask.TASKS:
                progress = (len(task.file_part) / task.file_total_parts * 100) if task.file_total_parts > 0 else 0
                uploads.append(UploadTaskInfo(
                    file_path=task.file_path,
                    file_name=task.file_name,
                    file_size=task.file_size,
                    chat_id=task.chat_id,
                    status=task.status,
                    error_msg=task.error_msg,
                    progress=progress
                ))
            return {'uploads': uploads}
        
        @self.app.get('/config', response_model=ConfigResponse, tags=['配置'])
        async def get_config():
            """获取当前配置"""
            if not self.downloader or not self.downloader.app:
                raise HTTPException(status_code=503, detail='下载器未初始化')
            
            app = self.downloader.app
            return ConfigResponse(
                api_id=app.api_id,
                bot_token=app.bot_token,
                save_directory=app.save_directory,
                temp_directory=app.temp_directory,
                max_download_task=app.max_download_task,
                max_upload_task=app.max_upload_task,
                enable_proxy=app.enable_proxy,
                download_type=app.download_type
            )
        
        @self.app.get('/stats', tags=['统计'])
        async def get_stats():
            """获取统计信息"""
            from module.stdio import MetaData
            
            stats = {
                'download': {
                    'total': 0,
                    'success': 0,
                    'failure': 0,
                    'skip': 0
                },
                'upload': {
                    'total': 0,
                    'success': 0,
                    'failure': 0
                }
            }
            
            # 从 DownloadTask 获取统计
            for link, info in DownloadTask.LINK_INFO.items():
                stats['download']['total'] += info.get('member_num', 0)
                stats['download']['success'] += info.get('complete_num', 0)
            
            # 从 UploadTask 获取统计
            for task in UploadTask.TASKS:
                stats['upload']['total'] += 1
                if task.status == UploadStatus.SUCCESS:
                    stats['upload']['success'] += 1
                elif task.status == UploadStatus.FAILURE:
                    stats['upload']['failure'] += 1
            
            return stats
    
    async def _execute_download(self, link: str, request: DownloadRequest, task_id: str):
        """执行单个下载任务"""
        try:
            # 构造消息对象
            from pyrogram.types import Message
            message = Message(
                id=0,
                date=datetime.now(),
                chat=None,
                text=f'/download {link}'
            )
            
            # 准备上传参数
            with_upload = None
            if request.with_upload and request.upload_chat_id:
                with_upload = {
                    'link': request.upload_chat_id,
                    'file_name': None,
                    'with_delete': request.delete_after_upload,
                    'send_as_media_group': True
                }
            
            # 调用下载器的方法
            await self.downloader.get_download_link_from_bot(
                client=self.downloader.app.client,
                message=message,
                with_upload=with_upload
            )
            
            TRMDTaskManager.update_task(
                task_id=task_id,
                status='running',
                progress=50.0
            )
        except Exception as e:
            log.error(f'执行下载失败:{link},原因:{e}')
            raise
    
    def run(self):
        """启动 API 服务器"""
        config = Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level='info'
        )
        self.server = Server(config=config)
        
        log.info(f'TRMD REST API 启动在 http://{self.host}:{self.port}')
        log.info(f'API 文档地址：http://{self.host}:{self.port}/docs')
        
        # 在非主线程中运行需要创建新的事件循环
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.server.serve())
        except KeyboardInterrupt:
            log.info('API 服务已停止')
    
    async def serve_async(self):
        """异步启动 API 服务器"""
        config = Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level='info'
        )
        self.server = Server(config=config)
        
        log.info(f'TRMD REST API 启动在 http://{self.host}:{self.port}')
        log.info(f'API 文档地址：http://{self.host}:{self.port}/docs')
        
        await self.server.serve()
