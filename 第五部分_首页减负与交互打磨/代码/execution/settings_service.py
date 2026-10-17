"""Authenticated local settings: verify once, then atomically save a private file."""

import fcntl
import hashlib
import json
import os
import re
import ssl
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import certifi
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from tasks.services import ApiError

from .provider import configuration
from .validation import fields


def config_path():
    return settings.BASE_DIR / ".local/deepseek.json"


def stored():
    try:
        raw = config_path().read_bytes()
    except FileNotFoundError:
        raw = b""
    revision = hashlib.sha256(raw).hexdigest()
    try:
        value = json.loads(raw)
    except ValueError:
        value = {}
    return value if isinstance(value, dict) else {}, revision


def can_manage(user_id):
    return user_id == get_user_model().objects.order_by("pk").values_list("pk", flat=True).first()


def status(user_id):
    config = configuration()
    value, revision = stored()
    environment = bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_MODEL"))
    return {
        "configured": bool(config["key"]),
        "model": config["model"],
        "verified_at": None if environment else value.get("verified_at"),
        "revision": revision,
        "can_manage": can_manage(user_id),
        "managed_by_env": environment,
    }


def verify_connection(key, model):
    request = urllib.request.Request(
        "https://api.deepseek.com/models", headers={"Authorization": "Bearer " + key}
    )
    try:
        with urllib.request.urlopen(
            request, context=ssl.create_default_context(cafile=certifi.where()), timeout=20
        ) as response:
            raw = response.read(262145)
        if len(raw) > 262144:
            raise ValueError("oversized response")
        data = json.loads(raw)["data"]
        if not isinstance(data, list) or not all(
            isinstance(item, dict) and isinstance(item.get("id"), str) for item in data
        ):
            raise ValueError("invalid model list")
        if model not in {item["id"] for item in data}:
            raise ApiError("密钥可连接，但指定模型不可用，请核对模型名称。")
    except urllib.error.HTTPError as exc:
        message = (
            "密钥无效或无权限，请检查 API Key"
            if exc.code in (401, 403)
            else "请求频率受限，请稍后验证"
            if exc.code == 429
            else "服务暂时不可用，请稍后验证"
        )
        raise ApiError(f"DeepSeek {message}。", 400 if exc.code in (401, 403) else 502) from None
    except OSError as exc:
        reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
        message = (
            "HTTPS 证书校验失败，请检查本机证书或代理"
            if isinstance(reason, ssl.SSLCertVerificationError)
            else "连接超时，请稍后验证"
            if isinstance(reason, TimeoutError)
            else "网络连接失败，请检查网络或代理"
        )
        raise ApiError(f"DeepSeek {message}。", 502) from None
    except (ValueError, KeyError, TypeError):
        raise ApiError("DeepSeek 模型列表响应格式异常，请稍后验证。", 502) from None


def save_config(value):
    directory = config_path().parent
    fd, name = tempfile.mkstemp(prefix="deepseek-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w") as out:
            os.fchmod(out.fileno(), 0o600)
            json.dump(value, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, config_path())
    finally:
        Path(name).unlink(missing_ok=True)


def verify_and_save(user_id, data):
    if not can_manage(user_id):
        raise ApiError("本机 DeepSeek 设置仅允许最早创建的账号管理。", 403)
    fields(data, ["api_key", "model", "revision"])
    key, model = data.get("api_key", ""), data.get("model")
    if not isinstance(key, str) or len(key) > 512 or any(not 33 <= ord(c) <= 126 for c in key):
        raise ApiError("API Key 格式不正确，请去除空格和换行。")
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", model):
        raise ApiError("请填写有效的模型名称。")
    try:
        directory = config_path().parent
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.chmod(0o700)
        with (directory / "deepseek-settings.lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ApiError("正在验证另一次请求，请稍后重新打开设置。", 409) from None
            current = status(user_id)
            if data.get("revision") != current["revision"]:
                raise ApiError("配置已更新，请重新打开设置后验证。", 409)
            if current["managed_by_env"] and (key or model != current["model"]):
                raise ApiError("当前使用环境变量配置，网页只能验证现有配置。", 409)
            key = key or configuration()["key"]
            if not key:
                raise ApiError("请先填写 API Key。")
            verify_connection(key, model)
            if stored()[1] != current["revision"]:
                raise ApiError("验证期间配置已改变，请重新打开设置。", 409)
            verified_at = timezone.now().isoformat()
            if not current["managed_by_env"]:
                save_config({"api_key": key, "model": model, "verified_at": verified_at})
            return {**status(user_id), "verified_at": verified_at}
    except OSError:
        raise ApiError("本机配置读取或保存失败，原配置未被替换，请检查目录权限。", 503) from None
