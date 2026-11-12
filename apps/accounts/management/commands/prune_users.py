from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Eyðir aðgöngum sem voru aldrei notaðir (t.d. frá tíma innskráningar með kóða)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=2, help="Aldur aðgangs í dögum (sjálfgefið 2)")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, days, dry_run, **options):
        stale = User.objects.filter(
            last_login__isnull=True,
            is_staff=False,
            date_joined__lt=timezone.now() - timedelta(days=days),
            memberships__isnull=True,
        )
        count = stale.count()
        if not dry_run:
            stale.delete()
        verb = "Myndi eyða" if dry_run else "Eyddi"
        self.stdout.write(f"{verb} {count} ónotuðum aðgöngum.")
