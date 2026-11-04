from django.urls import path

from . import views

app_name = "gifts"

urlpatterns = [
    path("h/<slug:slug>/", views.SeasonRedirectView.as_view(), name="list"),
    path("h/<slug:slug>/nytt-ar/", views.NewSeasonView.as_view(), name="new_season"),
    path("h/<slug:slug>/folk/leit/", views.PeopleSearchView.as_view(), name="people_search"),
    path("h/<slug:slug>/<int:year>/", views.GiftListView.as_view(), name="season"),
    path("h/<slug:slug>/<int:year>/vidmid/", views.BudgetView.as_view(), name="budget"),
    path("h/<slug:slug>/<int:year>/opna/", views.UnlockView.as_view(), name="unlock"),
    path("h/<slug:slug>/<int:year>/ny-gjof/", views.GiftDialogView.as_view(), name="gift_new"),
    path("h/<slug:slug>/<int:year>/nyr-adili/", views.PersonNewView.as_view(), name="person_new"),
    path("h/<slug:slug>/gjafir/<int:pk>/", views.GiftDialogView.as_view(), name="gift_edit"),
    path("h/<slug:slug>/gjafir/<int:pk>/keypt/", views.GiftBoughtView.as_view(), name="bought"),
    path("h/<slug:slug>/gjafir/<int:pk>/verd/", views.GiftPriceView.as_view(), name="price"),
    path("h/<slug:slug>/gjafir/<int:pk>/aaetlun/", views.GiftPlanView.as_view(), name="plan"),
    path("h/<slug:slug>/gjafir/<int:pk>/hugmyndir/", views.IdeaAddView.as_view(), name="idea_add"),
    path("h/<slug:slug>/gjafir/<int:pk>/eyda/", views.GiftDeleteView.as_view(), name="delete"),
    path("h/<slug:slug>/gjafir/<int:pk>/endurheimta/", views.GiftRestoreView.as_view(), name="restore"),
    path("h/<slug:slug>/hugmyndir/<int:pk>/", views.IdeaDialogView.as_view(), name="idea"),
    path("h/<slug:slug>/hugmyndir/<int:pk>/eyda/", views.IdeaRemoveView.as_view(), name="idea_remove"),
]
