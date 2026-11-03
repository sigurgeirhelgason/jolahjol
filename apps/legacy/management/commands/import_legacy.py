import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from apps.accounts.models import User
from apps.households.models import Household, Membership
from apps.legacy.importer import LegacyImporter, clear_household


class Command(BaseCommand):
    help = "Flytur inn JSON-afrit úr gamla gjafalistanum (Sækja afrit (JSON))."

    def add_arguments(self, parser):
        parser.add_argument("path", type=Path)
        parser.add_argument("--household", required=True, help="Slóð (slug) heimilisins")
        parser.add_argument(
            "--create", metavar="NAFN", help="Stofna heimilið með þessu nafni ef það er ekki til"
        )
        parser.add_argument("--owner", metavar="NETFANG", help="Gera notanda að eiganda heimilisins")
        parser.add_argument("--replace", action="store_true", help="Hreinsa gjafagögn heimilisins fyrst")

    @transaction.atomic
    def handle(self, path, household, create, owner, replace, **options):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CommandError(f"Gat ekki lesið {path}: {exc}") from exc

        home = Household.objects.filter(slug=household).first()
        if home is None:
            if not create:
                raise CommandError(f"Heimilið „{household}“ er ekki til. Notaðu --create „Nafn“.")
            home = Household.objects.create(name=create, slug=slugify(household))
        if owner:
            user, _ = User.objects.get_or_create(email=owner.lower())
            Membership.objects.update_or_create(
                user=user, household=home, defaults={"role": Membership.Role.OWNER}
            )
        if replace:
            clear_household(home)
        elif home.seasons.exists():
            raise CommandError("Heimilið á þegar gögn. Notaðu --replace til að skipta þeim út.")

        try:
            report = LegacyImporter(home, data).run()
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        out = self.stdout
        out.write(self.style.SUCCESS(f"Flutt inn í „{home.name}“ ({home.slug})"))
        out.write(f"  Ár: {report.seasons}  Gjafir: {report.gifts}  Hugmyndir: {report.ideas}")
        out.write(f"  Einstaklingar: {report.people}  Búðir: {report.stores}")
        if report.skipped_gifts:
            out.write(f"  Ónefndum línum sleppt: {report.skipped_gifts}")
        for name in report.merged_gifts:
            out.write(self.style.WARNING(f"  Tvær gjafir sameinaðar: {name}"))
        if report.new_givers:
            out.write("  Gefendur sem urðu til (sameinaðu eða endurnefndu ef þarf):")
            for name in report.new_givers:
                out.write(f"    – {name}")
