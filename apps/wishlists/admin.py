from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import WishlistShare, WishRequest


@admin.register(WishlistShare)
class WishlistShareAdmin(ModelAdmin):
    list_display = ["person", "created_by", "created_at", "revoked_at"]
    list_filter = ["revoked_at"]
    autocomplete_fields = ["person"]
    readonly_fields = ["token"]


@admin.register(WishRequest)
class WishRequestAdmin(ModelAdmin):
    list_display = ["person", "created_by", "created_at", "expires_at", "revoked_at"]
    autocomplete_fields = ["person"]
    readonly_fields = ["token"]
