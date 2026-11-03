from django.urls import path

from . import views

app_name = "gifts"

urlpatterns = [
    path("h/<slug:slug>/", views.GiftListView.as_view(), name="list"),
]
