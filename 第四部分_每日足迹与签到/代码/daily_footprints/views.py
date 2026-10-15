from django.http import JsonResponse

from execution import validation as v
from tasks.services import ApiError
from tasks.views import api, payload

from . import reading, writing


@api(("GET", "POST"))
def endpoint(request, operation):
    if operation not in ("calendar", "day", "mark"):
        raise ApiError("没有这个足迹入口。", 404)
    if request.method != ("POST" if operation == "mark" else "GET"):
        raise ApiError("不支持此操作。", 405)
    if operation == "mark":
        result = writing.mark(
            request.user.pk, payload(request), request.headers.get("Idempotency-Key", "")
        )
    else:
        v.fields(request.GET, ["view", "year"] if operation == "calendar" else ["date"])
        result = (reading.calendar if operation == "calendar" else reading.detail)(
            request.user.pk, request.GET
        )
    return JsonResponse(result)
