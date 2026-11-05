from django.core.management.base import BaseCommand

from apps.gifts.services.birthdays import send_reminders


class Command(BaseCommand):
    help = "Sendir afmælisáminningar í tölvupósti (keyrt daglega)."

    def handle(self, **options):
        self.stdout.write(f"Sendi {send_reminders()} afmælisáminningar.")
