import json
import re
import uuid
from functools import wraps
from typing import Any, Callable, cast

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import RequestDataTooBig, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from .models import STATUSES
from .services import (
    ApiError,
    create_task,
    owned_task,
    owned_tasks,
    serialize_events,
    serialize_task,
    update_task,
)


def api(methods: tuple[str, ...], *, public: bool = False) -> Callable[..., Any]:
    def decorate(fn: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @wraps(fn)
        def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            try:
                if request.method not in methods:
                    raise ApiError("不支持此操作。", 405)
                if not public and not request.user.is_authenticated:
                    raise ApiError("登录已失效，请重新登录。", 401)
                expected_user = request.headers.get("X-Workspace-User")
                if not public and expected_user and expected_user != str(request.user.pk):
                    raise ApiError("账号已在其他页面切换，请重新登录。", 401)
                response = fn(request, *args, **kwargs)
            except ApiError as exc:
                response = JsonResponse({"error": exc.message}, status=exc.status)
            response["Cache-Control"] = "no-store"
            return response

        return wrapped

    return decorate


def payload(request: HttpRequest) -> dict[str, Any]:
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError, RequestDataTooBig, RecursionError) as exc:
        raise ApiError("请求内容不是有效 JSON，或内容过大。") from exc
    if not isinstance(data, dict):
        raise ApiError("请求内容必须是一个对象。")
    return data


def user_data(request: HttpRequest) -> dict[str, Any]:
    return {"id": request.user.pk, "username": request.user.get_username()}


def credentials(request: HttpRequest) -> tuple[str, str]:
    data = payload(request)
    if set(data) != {"username", "password"}:
        raise ApiError("请填写用户名和密码。")
    name, password = data["username"], data["password"]
    if not isinstance(name, str) or not isinstance(password, str) or len(password) > 256:
        raise ApiError("用户名或密码格式不正确。")
    name = name.strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{3,32}", name):
        raise ApiError("用户名使用 3–32 位英文字母、数字或下划线。")
    return name, password


def throttle_key(request: HttpRequest, category: str) -> str:
    return f"{category}:{request.META.get('REMOTE_ADDR', 'unknown')}"


def check_limit(key: str, limit: int) -> None:
    if cache.get(key, 0) >= limit:
        raise ApiError("尝试次数过多，请 15 分钟后再试。", 429)


def count_attempt(key: str) -> None:
    if not cache.add(key, 1, timeout=900):
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=900)


@ensure_csrf_cookie
def home(request: HttpRequest) -> HttpResponse:
    response = render(request, "index.html")
    response["Cache-Control"] = "no-store"
    return response


def csrf_failure(request: HttpRequest, reason: str = "") -> JsonResponse:
    return JsonResponse(
        {"error": "页面安全凭据已失效，请刷新后重试。未保存的输入请先复制保留。"}, status=403
    )


@api(("GET",))
def me(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"user": user_data(request)})


@api(("POST",), public=True)
def register(request: HttpRequest) -> JsonResponse:
    key = throttle_key(request, "register")
    check_limit(key, 20)
    count_attempt(key)
    name, password = credentials(request)
    users = get_user_model()
    candidate = users(username=name)
    try:
        validate_password(password, candidate)
    except ValidationError as exc:
        raise ApiError(" ".join(exc.messages)) from exc
    try:
        with transaction.atomic():
            user = users.objects.create_user(username=name, password=password)
    except IntegrityError as exc:
        raise ApiError("这个用户名已被使用，请换一个。") from exc
    login(request, user)
    return JsonResponse({"user": user_data(request)}, status=201)


@api(("POST",), public=True)
def sign_in(request: HttpRequest) -> JsonResponse:
    key = throttle_key(request, "login")
    check_limit(key, 5)
    name, password = credentials(request)
    user = authenticate(request, username=name, password=password)
    if user is None:
        count_attempt(key)
        raise ApiError("用户名或密码不正确。", 401)
    login(request, user)
    cache.delete(key)
    return JsonResponse({"user": user_data(request)})


@api(("POST",))
def sign_out(request: HttpRequest) -> JsonResponse:
    logout(request)
    return JsonResponse({"ok": True})


@api(("GET", "POST"))
def collection(request: HttpRequest) -> JsonResponse:
    uid = cast(int, request.user.pk)
    if request.method == "POST":
        task, created = create_task(
            uid, payload(request), request.headers.get("Idempotency-Key", "")
        )
        return JsonResponse({"task": serialize_task(task)}, status=201 if created else 200)
    tasks = owned_tasks(uid)
    counts = {state: 0 for state in STATUSES}
    counts.update(
        {row["status"]: row["n"] for row in tasks.values("status").annotate(n=Count("id"))}
    )
    trash = owned_tasks(uid, include_deleted=True).filter(deleted_at__isnull=False)
    counts["trash"] = trash.count()
    state = request.GET.get("status", "")
    if state == "trash":
        tasks = trash
    elif state == "history":
        tasks = tasks.filter(status__in=["completed", "abandoned"])
    elif state:
        if state not in STATUSES:
            raise ApiError("未知的任务区域。")
        tasks = tasks.filter(status=state)
    query = request.GET.get("q", "").strip()[:120]
    if query:
        tasks = tasks.filter(title__icontains=query)
    tasks = tasks.prefetch_related("steps__depends")
    return JsonResponse({"tasks": [serialize_task(task) for task in tasks], "counts": counts})


@api(("GET", "PATCH"))
def detail(request: HttpRequest, task_id: uuid.UUID) -> JsonResponse:
    uid = cast(int, request.user.pk)
    task = (
        update_task(uid, task_id, payload(request))
        if request.method == "PATCH"
        else owned_task(uid, task_id)
    )
    return JsonResponse({"task": serialize_task(task), "events": serialize_events(task)})


@api(("GET",))
def events(request: HttpRequest, task_id: uuid.UUID) -> JsonResponse:
    task = owned_task(cast(int, request.user.pk), task_id)
    return JsonResponse({"events": serialize_events(task)})


@api(("POST",))
def lifecycle(request: HttpRequest, task_id: uuid.UUID) -> JsonResponse:
    from .lifecycle import mutate

    return JsonResponse(
        mutate(
            cast(int, request.user.pk),
            task_id,
            payload(request),
            request.headers.get("Idempotency-Key", ""),
        )
    )
