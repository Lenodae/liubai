from django.http import JsonResponse

from tasks.services import owned_task
from tasks.views import api, payload

from .serialization import view
from .services import mutate


@api(("GET", "POST"))
def workspace(request, task_id):
    if request.method == "POST":
        result = mutate(
            request.user.pk, task_id, payload(request), request.headers.get("Idempotency-Key", "")
        )
    else:
        result = view(owned_task(request.user.pk, task_id))
    return JsonResponse(result)
