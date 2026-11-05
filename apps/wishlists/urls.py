from django.urls import path

from . import views

app_name = "wishlists"

urlpatterns = [
    path("o/<str:token>/", views.PublicWishlistView.as_view(), name="public"),
    path("o/<str:token>/<int:idea_id>/taka-fra/", views.ReserveView.as_view(), name="reserve"),
    path("o/<str:token>/<int:idea_id>/haetta-vid/", views.CancelView.as_view(), name="cancel"),
    path("h/<slug:slug>/folk/<int:pk>/oskalisti/", views.ShareCreateView.as_view(), name="share_create"),
    path(
        "h/<slug:slug>/folk/<int:pk>/oskalisti/afturkalla/",
        views.ShareRevokeView.as_view(),
        name="share_revoke",
    ),
]
