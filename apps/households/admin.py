from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import Household, Membership


class MembershipInline(TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ["user"]


@admin.register(Household)
class HouseholdAdmin(ModelAdmin):
    list_display = ["name", "slug", "created_at"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ["name"]}
    inlines = [MembershipInline]
