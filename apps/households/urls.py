from django.urls import path

from . import views

app_name = "households"

urlpatterns = [
    path("heimili/nytt/", views.HouseholdCreateView.as_view(), name="create"),
    path("bod/<str:token>/", views.InviteAcceptView.as_view(), name="invite_accept"),
    path("h/<slug:slug>/stillingar/", views.SettingsView.as_view(), name="settings"),
    path("h/<slug:slug>/hver-er-eg/", views.ClaimPersonView.as_view(), name="claim_person"),
    path("h/<slug:slug>/folk/<int:pk>/bod/", views.PersonInviteCreateView.as_view(), name="person_invite"),
    path(
        "h/<slug:slug>/folk/<int:pk>/bod/afturkalla/",
        views.PersonInviteRevokeView.as_view(),
        name="person_invite_revoke",
    ),
    path("h/<slug:slug>/stillingar/nafn/", views.RenameView.as_view(), name="rename"),
    path("h/<slug:slug>/stillingar/bod/", views.InviteCreateView.as_view(), name="invite_create"),
    path(
        "h/<slug:slug>/stillingar/bod/<int:pk>/afturkalla/",
        views.InviteRevokeView.as_view(),
        name="invite_revoke",
    ),
    path(
        "h/<slug:slug>/stillingar/medlimir/<int:pk>/hlutverk/",
        views.MemberRoleView.as_view(),
        name="member_role",
    ),
    path(
        "h/<slug:slug>/stillingar/medlimir/<int:pk>/a-listanum/",
        views.MemberPersonView.as_view(),
        name="member_person",
    ),
    path(
        "h/<slug:slug>/stillingar/medlimir/<int:pk>/fjarlaegja/",
        views.MemberRemoveView.as_view(),
        name="member_remove",
    ),
    path("h/<slug:slug>/stillingar/yfirgefa/", views.LeaveView.as_view(), name="leave"),
    path("h/<slug:slug>/stillingar/eyda/", views.DeleteView.as_view(), name="delete"),
]
