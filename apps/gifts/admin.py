from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline

from apps.core.money import format_kr

from .models import Gift, Idea, IdeaGiver, Location, Person, Season, Store


@admin.register(Person)
class PersonAdmin(ModelAdmin):
    list_display = ["name", "group", "household", "birthday", "give_christmas"]
    list_filter = ["household", "group", "give_christmas"]
    search_fields = ["name"]


@admin.register(Location)
class LocationAdmin(ModelAdmin):
    list_display = ["name", "household"]
    list_filter = ["household"]
    search_fields = ["name"]


@admin.register(Store)
class StoreAdmin(ModelAdmin):
    list_display = ["name", "household"]
    list_filter = ["household"]
    search_fields = ["name"]
    filter_horizontal = ["locations"]


@admin.register(Season)
class SeasonAdmin(ModelAdmin):
    list_display = ["household", "year", "budget"]
    list_filter = ["household"]


class IdeaInline(TabularInline):
    model = Idea
    extra = 0
    fields = ["text", "store", "price", "picked", "for_other", "position"]
    autocomplete_fields = ["store"]


@admin.register(Gift)
class GiftAdmin(ModelAdmin):
    list_display = ["person", "season", "plan", "bought", "price_display", "deleted_at"]
    list_filter = ["season__household", "season__year", "bought"]
    search_fields = ["person__name", "ideas__text"]
    autocomplete_fields = ["person"]
    inlines = [IdeaInline]

    @admin.display(description=_("raunverð"))
    def price_display(self, obj):
        return format_kr(obj.actual_price) if obj.actual_price is not None else "—"


class IdeaGiverInline(TabularInline):
    model = IdeaGiver
    extra = 0
    autocomplete_fields = ["person"]


@admin.register(Idea)
class IdeaAdmin(ModelAdmin):
    list_display = ["text", "gift", "price", "picked", "for_other"]
    list_filter = ["picked", "for_other", "gift__season__year"]
    search_fields = ["text", "gift__person__name"]
    autocomplete_fields = ["gift", "store", "reserved_by"]
    inlines = [IdeaGiverInline]
