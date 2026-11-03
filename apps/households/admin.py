from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import Household, Invite, Membership


class MembershipInline(TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ["user"]


class InviteInline(TabularInline):
    model = Invite
    extra = 0
    fields = ["created_by", "created_at", "expires_at", "accepted_by", "accepted_at"]
    readonly_fields = fields


@admin.register(Household)
class HouseholdAdmin(ModelAdmin):
    list_display = ["name", "slug", "created_at"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ["name"]}
    inlines = [MembershipInline, InviteInline]
