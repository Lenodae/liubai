from django.http import JsonResponse

from tasks.services import ApiError
from tasks.views import api, payload

from . import services, workspace


@api(("GET", "POST"))
def endpoint(request, operation):
    uid = request.user.pk
    if request.method == "GET":
        week, mode = workspace.scope(request.GET)
        if operation == "workspace":
            result = workspace.build(uid, week, mode)
        elif operation == "history":
            result = services.history(uid, week, mode)
        elif operation == "deadlines":
            from .deadlines import get

            result = get(uid, week, mode)
        else:
            raise ApiError("此接口不支持读取。", 405)
    elif operation == "preview":
        result = services.preview(uid, payload(request))
    else:
        result = services.mutate(
            uid, operation, payload(request), request.headers.get("Idempotency-Key", "")
        )
    return JsonResponse(result)
