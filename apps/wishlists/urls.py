from django.urls import path

from . import views

app_name = "wishlists"

urlpatterns = [
    path("o/<str:token>/", views.PublicWishlistView.as_view(), name="public"),
    path("o/<str:token>/<int:idea_id>/taka-fra/", views.ReserveView.as_view(), name="reserve"),
    path("o/<str:token>/<int:idea_id>/haetta-vid/", views.CancelView.as_view(), name="cancel"),
    path("o/<str:token>/fylgja/", views.FollowView.as_view(), name="follow"),
    path("o/<str:token>/fylgja/byrja/", views.FollowStartView.as_view(), name="follow_start"),
    path("oskir/<str:token>/", views.WishRequestView.as_view(), name="request"),
    path("oskir/<str:token>/<int:idea_id>/", views.WishEditView.as_view(), name="request_edit"),
    path("oskir/<str:token>/<int:idea_id>/bud/", views.WishStoreView.as_view(), name="request_store"),
    path("oskir/<str:token>/<int:idea_id>/eyda/", views.WishDeleteView.as_view(), name="request_delete"),
    path("h/<slug:slug>/folk/<int:pk>/oskabeidni/", views.RequestCreateView.as_view(), name="request_create"),
    path(
        "h/<slug:slug>/folk/<int:pk>/oskabeidni/loka/",
        views.RequestRevokeView.as_view(),
        name="request_revoke",
    ),
    path("h/<slug:slug>/folk/<int:pk>/fylgja/haetta/", views.UnfollowView.as_view(), name="unfollow"),
    path("h/<slug:slug>/folk/<int:pk>/oskalisti/", views.ShareCreateView.as_view(), name="share_create"),
    path(
        "h/<slug:slug>/folk/<int:pk>/oskalisti/afturkalla/",
        views.ShareRevokeView.as_view(),
        name="share_revoke",
    ),
]
