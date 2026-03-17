"""
投稿相关API路由 - 重构版本
移除bilitool依赖，使用直接API调用
"""

import logging
import json
import os
import uuid
import time
import base64
import io
import aiohttp
import asyncio
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Body
from fastapi.responses import Response
from sqlalchemy.orm import Session
import qrcode

from ...core.database import get_db
from ...schemas.bilibili import (
    BilibiliAccountCreate, 
    BilibiliAccountResponse,
    UploadRequest,
    UploadRecordResponse,
    UploadStatusResponse,
    QRLoginRequest,
    QRLoginResponse
)
from ...services.bilibili_service import BilibiliAccountService, BilibiliUploadService
from ...core.task_manager import task_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/upload", tags=["投稿管理"])

# 存储二维码登录会话的字典
qr_sessions = {}

# 获取服务实例
def get_account_service(db: Session = Depends(get_db)) -> BilibiliAccountService:
    return BilibiliAccountService(db)

def get_upload_service(db: Session = Depends(get_db)) -> BilibiliUploadService:
    return BilibiliUploadService(db)


# 账号管理API
@router.get("/login-methods")
async def get_login_methods():
    """获取支持的登录方式"""
    return {
        "methods": [
            {
                "id": "cookie",
                "name": "Cookie导入",
                "description": "最安全的方式，不会触发风控",
                "icon": "🔐",
                "recommended": True,
                "risk_level": "low"
            },
            {
                "id": "password",
                "name": "账号密码登录",
                "description": "传统登录方式，可能需要验证码",
                "icon": "👤",
                "recommended": True,
                "risk_level": "medium"
            },
            {
                "id": "qr",
                "name": "扫码登录",
                "description": "使用B站APP扫码登录",
                "icon": "📱",
                "recommended": False,
                "risk_level": "high"
            },
            {
                "id": "wechat",
                "name": "微信登录",
                "description": "使用微信账号登录",
                "icon": "💬",
                "recommended": False,
                "risk_level": "medium"
            },
            {
                "id": "qq",
                "name": "QQ登录",
                "description": "使用QQ账号登录",
                "icon": "🐧",
                "recommended": False,
                "risk_level": "medium"
            }
        ]
    }


@router.post("/cookie-login", response_model=BilibiliAccountResponse)
async def cookie_login(
    request: dict = Body(...),
    account_service: BilibiliAccountService = Depends(get_account_service)
):
    """Cookie导入登录"""
    try:
        cookies = request.get("cookies")
        nickname = request.get("nickname")
        
        if not cookies:
            raise HTTPException(status_code=400, detail="Cookie不能为空")
        
        # 验证Cookie有效性
        cookie_validation = await validate_bilibili_cookies(cookies)
        
        if cookie_validation.get("valid"):
            # 构建Cookie字符串用于存储
            cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
            
            account_data = BilibiliAccountCreate(
                username=cookie_validation.get("username", "cookie_user"),
                password="",
                nickname=nickname or cookie_validation.get("nickname", "B站用户"),
                cookie_content=cookie_str
            )
            
            account = await account_service.create_account(account_data)
            return BilibiliAccountResponse.from_orm(account)
        else:
            raise HTTPException(status_code=400, detail="Cookie无效或已过期")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cookie登录失败: {str(e)}")
        raise HTTPException(status_code=500, detail="登录失败")


@router.post("/password-login", response_model=BilibiliAccountResponse)
async def password_login(
    request: dict = Body(...),
    account_service: BilibiliAccountService = Depends(get_account_service)
):
    """账号密码登录"""
    try:
        username = request.get("username")
        password = request.get("password")
        nickname = request.get("nickname")
        
        if not username or not password:
            raise HTTPException(status_code=400, detail="用户名和密码不能为空")
        
        # 这里应该实现真正的密码登录逻辑
        # 目前返回模拟数据
        mock_cookie_data = {
            "code": 0,
            "message": "登录成功",
            "data": {
                "user_info": {
                    "username": username,
                    "nickname": nickname or username,
                    "mid": "12345678"
                },
                "cookie_info": {
                    "cookies": [{"name": "SESSDATA", "value": "mock_sessdata"}]
                }
            }
        }
        
        account_data = BilibiliAccountCreate(
            username=username,
            password=password,
            nickname=nickname or username,
            cookie_content=json.dumps(mock_cookie_data)
        )
        
        account = await account_service.create_account(account_data)
        return BilibiliAccountResponse.from_orm(account)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"密码登录失败: {str(e)}")
        raise HTTPException(status_code=500, detail="登录失败")


@router.post("/qr-login")
async def start_qr_login(
    request: dict = Body(...),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """开始二维码登录"""
    try:
        nickname = request.get("nickname")
        
        # 生成会话ID
        session_id = str(uuid.uuid4())
        
        # 创建会话
        qr_sessions[session_id] = {
            "session_id": session_id,
            "status": "pending",
            "nickname": nickname,
            "created_at": time.time(),
            "qr_code": None,
            "error_message": None
        }
        
        # 启动后台任务生成二维码
        background_tasks.add_task(generate_qr_code_async, session_id)
        
        return {
            "session_id": session_id,
            "status": "pending",
            "message": "正在生成二维码..."
        }
        
    except Exception as e:
        logger.error(f"开始二维码登录失败: {str(e)}")
        raise HTTPException(status_code=500, detail="开始登录失败")


@router.get("/qr-login/{session_id}")
async def check_qr_login_status(session_id: str):
    """检查二维码登录状态"""
    try:
        if session_id not in qr_sessions:
            raise HTTPException(status_code=404, detail="会话不存在")
        
        session = qr_sessions[session_id]
        
        return {
            "session_id": session_id,
            "status": session["status"],
            "message": session.get("error_message", "等待扫码中..."),
            "qr_code": session.get("qr_code")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"检查二维码登录状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail="检查登录状态失败")


@router.post("/qr-login/{session_id}/complete", response_model=BilibiliAccountResponse)
async def complete_qr_login(
    session_id: str,
    request: dict = Body(...),
    account_service: BilibiliAccountService = Depends(get_account_service)
):
    """完成二维码登录"""
    try:
        if session_id not in qr_sessions:
            raise HTTPException(status_code=404, detail="会话不存在")
        
        session = qr_sessions[session_id]
        
        if session["status"] != "success":
            raise HTTPException(status_code=400, detail="登录未成功")
        
        nickname = request.get("nickname") or session.get("nickname")
        
        # 创建模拟的Cookie数据
        mock_cookie_data = {
            "code": 0,
            "message": "登录成功",
            "data": {
                "user_info": {
                    "username": f"qr_user_{session_id[:8]}",
                    "nickname": nickname or "B站用户",
                    "mid": "87654321"
                },
                "cookie_info": {
                    "cookies": [{"name": "SESSDATA", "value": f"qr_sessdata_{session_id[:8]}"}]
                }
            }
        }
        
        account_data = BilibiliAccountCreate(
            username=f"qr_user_{session_id[:8]}",
            password="",
            nickname=nickname or "B站用户",
            cookie_content=json.dumps(mock_cookie_data)
        )
        
        account = await account_service.create_account(account_data)
        
        # 清理会话
        del qr_sessions[session_id]
        
        return BilibiliAccountResponse.from_orm(account)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"完成二维码登录失败: {str(e)}")
        raise HTTPException(status_code=500, detail="完成登录失败")


@router.get("/accounts")
async def get_accounts(account_service: BilibiliAccountService = Depends(get_account_service)):
    """获取所有账号"""
    try:
        accounts = account_service.get_accounts()
        return [BilibiliAccountResponse.from_orm(account) for account in accounts]
    except Exception as e:
        logger.error(f"获取账号列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取账号列表失败")


@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: UUID,
    account_service: BilibiliAccountService = Depends(get_account_service)
):
    """删除账号"""
    try:
        success = account_service.delete_account(account_id)
        if success:
            return {"message": "账号删除成功"}
        else:
            raise HTTPException(status_code=404, detail="账号不存在")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除账号失败: {str(e)}")
        raise HTTPException(status_code=500, detail="删除账号失败")


@router.post("/accounts/{account_id}/check")
async def check_account_status(
    account_id: UUID,
    account_service: BilibiliAccountService = Depends(get_account_service)
):
    """检查账号状态"""
    try:
        is_valid = account_service.check_account_status(account_id)
        return {
            "is_valid": is_valid,
            "message": "账号状态正常" if is_valid else "账号状态异常"
        }
    except Exception as e:
        logger.error(f"检查账号状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail="检查账号状态失败")


# 投稿管理API
@router.post("/projects/{project_id}/upload")
async def create_upload_task(
    project_id: UUID,
    upload_data: UploadRequest,
    upload_service: BilibiliUploadService = Depends(get_upload_service)
):
    """创建投稿任务 - 功能暂时禁用"""
    # 功能暂时禁用，返回开发中提示
    raise HTTPException(status_code=503, detail="B站上传功能正在开发中，敬请期待！")
    
    # 原有代码已禁用
    try:
        record = upload_service.create_upload_record(project_id, upload_data)
        
        # 启动异步上传任务
        for clip_id in upload_data.clip_ids:
            from ...tasks.upload import run_upload_clip_sync
            await task_manager.submit(f"upload_{record.id}_{clip_id}", run_upload_clip_sync, str(record.id), clip_id)
        
        return {
            "message": "投稿任务创建成功",
            "record_id": str(record.id),
            "clip_count": len(upload_data.clip_ids)
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"创建投稿任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail="创建投稿任务失败")


@router.post("/records/{record_id}/retry")
async def retry_upload_task(
    record_id: int,
    upload_service: BilibiliUploadService = Depends(get_upload_service)
):
    """重试投稿任务"""
    try:
        success = upload_service.retry_upload_task(record_id)
        if success:
            return {"message": "投稿任务重试已启动"}
        else:
            raise HTTPException(status_code=400, detail="重试失败")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"重试投稿任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail="重试失败")


@router.post("/records/{record_id}/cancel")
async def cancel_upload_task(
    record_id: int,
    upload_service: BilibiliUploadService = Depends(get_upload_service)
):
    """取消投稿任务"""
    try:
        success = upload_service.cancel_upload_task(record_id)
        if success:
            return {"message": "投稿任务已取消"}
        else:
            raise HTTPException(status_code=400, detail="取消失败")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"取消投稿任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail="取消失败")


@router.delete("/records/{record_id}")
async def delete_upload_task(
    record_id: int,
    upload_service: BilibiliUploadService = Depends(get_upload_service)
):
    """删除投稿任务"""
    try:
        success = upload_service.delete_upload_task(record_id)
        if success:
            return {"message": "投稿任务已删除"}
        else:
            raise HTTPException(status_code=400, detail="删除失败")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"删除投稿任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail="删除失败")


@router.get("/records")
async def get_upload_records(
    project_id: Optional[UUID] = None,
    upload_service: BilibiliUploadService = Depends(get_upload_service)
):
    """获取投稿记录"""
    try:
        records = upload_service.get_upload_records(project_id)
        return [UploadRecordResponse(**record) for record in records]
    except Exception as e:
        logger.error(f"获取投稿记录失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取投稿记录失败")


@router.get("/records/{record_id}")
async def get_upload_record(
    record_id: UUID,
    upload_service: BilibiliUploadService = Depends(get_upload_service)
):
    """获取指定投稿记录"""
    try:
        record = upload_service.get_upload_record(record_id)
        if not record:
            raise HTTPException(status_code=404, detail="投稿记录不存在")
        return UploadRecordResponse.from_orm(record)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取投稿记录失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取投稿记录失败")


# 辅助函数
async def validate_bilibili_cookies(cookies: dict) -> dict:
    """验证B站Cookie有效性"""
    try:
        # 构建Cookie字符串
        cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
        
        headers = {
            "Cookie": cookie_str,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com/"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.bilibili.com/x/web-interface/nav",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                data = await response.json()
                
                if data.get("code") == 0 and data.get("data", {}).get("isLogin"):
                    user_info = data["data"]
                    
                    # 检查必要字段
                    required_fields = ['SESSDATA', 'bili_jct', 'DedeUserID']
                    missing_fields = []
                    for field in required_fields:
                        if field not in cookies:
                            missing_fields.append(field)
                    
                    if missing_fields:
                        return {
                            "valid": False, 
                            "message": f"Cookie缺少必要字段: {', '.join(missing_fields)}"
                        }
                    
                    return {
                        "valid": True,
                        "username": user_info.get("uname"),
                        "nickname": user_info.get("uname"),
                        "mid": user_info.get("mid"),
                        "level": user_info.get("level_info", {}).get("current_level", 0),
                        "can_upload": True  # 暂时设为True，后续可以添加更详细的检查
                    }
                else:
                    return {"valid": False, "message": "Cookie无效或已过期"}
                    
    except Exception as e:
        logger.error(f"验证Cookie失败: {e}")
        return {"valid": False, "message": f"验证失败: {str(e)}"}


async def generate_qr_code_async(session_id: str):
    """异步生成二维码"""
    try:
        if session_id not in qr_sessions:
            return
        
        session = qr_sessions[session_id]
        
        # 模拟生成二维码的过程
        await asyncio.sleep(2)  # 模拟网络延迟
        
        # 生成模拟的二维码URL
        qr_url = f"https://passport.bilibili.com/qrcode/h5/login?qrcode_key={session_id}"
        
        session["qr_code"] = qr_url
        session["status"] = "processing"
        
        # 模拟等待扫码
        await asyncio.sleep(30)  # 等待30秒
        
        # 模拟登录成功
        if session_id in qr_sessions:
            qr_sessions[session_id]["status"] = "success"
            
    except Exception as e:
        if session_id in qr_sessions:
            qr_sessions[session_id]["status"] = "failed"
            qr_sessions[session_id]["error_message"] = str(e)
        logger.error(f"生成二维码失败: {e}")
