from django.http import JsonResponse

from tasks.services import ApiError, owned_task
from tasks.views import api, payload

from . import settings_service
from .serialization import view
from .services import mutate


@api(("GET", "POST"))
def deepseek_settings(request):
    try:
        result = (
            settings_service.verify_and_save(request.user.pk, payload(request))
            if request.method == "POST"
            else settings_service.status(request.user.pk)
        )
    except OSError:
        raise ApiError("本机配置无法读取，请检查目录权限。", 503) from None
    return JsonResponse(result)


@api(("GET", "POST"))
def workspace(request, task_id):
    if request.method == "POST":
        result = mutate(
            request.user.pk, task_id, payload(request), request.headers.get("Idempotency-Key", "")
        )
    else:
        result = view(owned_task(request.user.pk, task_id))
    return JsonResponse(result)
