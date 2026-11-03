from django.urls import path

from apps.households.views import home

from . import views

urlpatterns = [
    path("", home, name="home"),
    path("healthz", views.healthz, name="healthz"),
]
