from django.urls import path

from . import views

app_name = "wishlists"

urlpatterns = [
    path("o/<str:token>/", views.PublicWishlistView.as_view(), name="public"),
    path("o/<str:token>/<int:idea_id>/taka-fra/", views.ReserveView.as_view(), name="reserve"),
    path("o/<str:token>/<int:idea_id>/haetta-vid/", views.CancelView.as_view(), name="cancel"),
    path("o/<str:token>/fylgja/", views.FollowView.as_view(), name="follow"),
    path("o/<str:token>/fylgja/byrja/", views.FollowStartView.as_view(), name="follow_start"),
    # Óskalisti heimilis: allt heimilisfólkið á einni síðu
    path("f/<str:token>/", views.HouseholdWishlistView.as_view(), name="household"),
    path(
        "f/<str:token>/<int:idea_id>/taka-fra/",
        views.HouseholdReserveView.as_view(),
        name="household_reserve",
    ),
    path(
        "f/<str:token>/<int:idea_id>/haetta-vid/",
        views.HouseholdCancelView.as_view(),
        name="household_cancel",
    ),
    path("f/<str:token>/fylgja/", views.HouseholdFollowView.as_view(), name="household_follow"),
    path(
        "f/<str:token>/fylgja/byrja/", views.HouseholdFollowStartView.as_view(), name="household_follow_start"
    ),
    path("h/<slug:slug>/oskalisti-heimilis/", views.HouseholdShareView.as_view(), name="household_share"),
    path(
        "h/<slug:slug>/oskalisti-heimilis/nyr/",
        views.HouseholdShareCreateView.as_view(),
        name="household_share_create",
    ),
    path(
        "h/<slug:slug>/oskalisti-heimilis/loka/",
        views.HouseholdShareRevokeView.as_view(),
        name="household_share_revoke",
    ),
    path("h/<slug:slug>/fylgir/<int:pk>/haetta/", views.UnfollowFamilyView.as_view(), name="unfollow_family"),
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
