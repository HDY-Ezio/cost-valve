"""
节能阀 - 许可证验证模块
启动时校验授权，未授权则拒绝启动服务
"""
import hashlib
import os
import logging
import socket
import uuid as uuid_module
from datetime import datetime

logger = logging.getLogger(__name__)


def _get_machine_fingerprint() -> str:
    """获取机器指纹（基于MAC地址+主机名）"""
    try:
        mac = uuid_module.getnode()
        mac_str = ':'.join(['{:02x}'.format((mac >> (8 * i)) & 0xff) for i in range(5, -1, -1)])
    except Exception:
        mac_str = "unknown"
    hostname = socket.gethostname()
    raw = f"{mac_str}:{hostname}:cost-valve"
    return hashlib.sha256(raw.encode()).hexdigest()[:16].upper()


def generate_license_key(expiry: str = "20991231") -> str:
    """
    为当前机器生成许可证密钥（管理员工具）
    :param expiry: 到期日期 YYYYMMDD
    :return: 许可证密钥
    """
    machine_fp = _get_machine_fingerprint()
    raw = f"{machine_fp}:{expiry}:xingmu2026"
    sig = hashlib.sha256(raw.encode()).hexdigest()[:12].upper()
    return f"JNV-{machine_fp}-{expiry}-{sig}"


def validate_license() -> bool:
    """
    验证许可证
    :return: 是否通过验证
    """
    license_key = os.environ.get("LICENSE_KEY", "")
    
    # 开发模式：无许可证时跳过验证
    if not license_key:
        if os.getenv("APP_DEBUG", "false").lower() == "true":
            logger.warning("⚠️  开发模式：未配置许可证，跳过验证")
            return True
        else:
            logger.error("❌ 未配置许可证！请设置 LICENSE_KEY 环境变量")
            return False
    
    # 解析许可证
    parts = license_key.split("-")
    if len(parts) != 4 or parts[0] != "JNV":
        logger.error("❌ 许可证格式错误")
        return False
    
    machine_fp, expiry, sig = parts[1], parts[2], parts[3]
    
    # 检查机器指纹
    current_fp = _get_machine_fingerprint()
    if machine_fp != current_fp:
        logger.error(f"❌ 许可证与当前机器不匹配！期望: {machine_fp}, 当前: {current_fp}")
        return False
    
    # 检查有效期
    try:
        exp_date = datetime.strptime(expiry, "%Y%m%d")
        if exp_date < datetime.now():
            logger.error(f"❌ 许可证已过期！到期日: {expiry}")
            return False
    except ValueError:
        logger.error("❌ 许可证日期格式错误")
        return False
    
    # 验证签名
    raw = f"{machine_fp}:{expiry}:xingmu2026"
    expected_sig = hashlib.sha256(raw.encode()).hexdigest()[:12].upper()
    if sig != expected_sig:
        logger.error("❌ 许可证签名无效！")
        return False
    
    logger.info(f"✅ 许可证验证通过 | 到期: {expiry}")
    return True


def get_license_info() -> dict:
    """获取许可证信息（用于管理接口）"""
    license_key = os.environ.get("LICENSE_KEY", "")
    current_fp = _get_machine_fingerprint()
    
    if not license_key:
        return {"status": "未配置", "machine_fp": current_fp}
    
    parts = license_key.split("-")
    if len(parts) != 4:
        return {"status": "格式错误", "machine_fp": current_fp}
    
    machine_fp, expiry = parts[1], parts[2]
    try:
        exp_date = datetime.strptime(expiry, "%Y%m%d")
        valid = exp_date >= datetime.now() and machine_fp == current_fp
        return {
            "status": "有效" if valid else "无效/过期",
            "machine_fp": machine_fp,
            "expiry": expiry,
            "machine_match": machine_fp == current_fp
        }
    except Exception:
        return {"status": "解析失败", "machine_fp": current_fp}
