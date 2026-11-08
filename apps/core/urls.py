from django.urls import path

from apps.households.views import home

from . import views

urlpatterns = [
    path("", home, name="home"),
    path("healthz", views.healthz, name="healthz"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
]
