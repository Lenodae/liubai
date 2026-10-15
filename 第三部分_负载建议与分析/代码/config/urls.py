from django.urls import path

from execution.views import deepseek_settings, workspace
from load_analysis.views import endpoint
from tasks import views

urlpatterns = [
    path("api/load/<str:operation>", endpoint),
    path("api/settings/deepseek", deepseek_settings),
    path("api/tasks/<uuid:task_id>/workspace", workspace),
    path("", views.home),
    path("api/me", views.me),
    path("api/auth/register", views.register),
    path("api/auth/login", views.sign_in),
    path("api/auth/logout", views.sign_out),
    path("api/tasks", views.collection),
    path("api/tasks/<uuid:task_id>", views.detail),
    path("api/tasks/<uuid:task_id>/events", views.events),
    path("api/tasks/<uuid:task_id>/lifecycle", views.lifecycle),
]
