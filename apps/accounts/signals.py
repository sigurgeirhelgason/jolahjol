from allauth.account.models import EmailAddress
from allauth.account.signals import password_reset
from django.dispatch import receiver


@receiver(password_reset)
def verify_email_on_password_reset(sender, request, user, **kwargs):
    """Hlekkur úr pósti sannar að notandinn á netfangið.

    Nýskráning staðfestir ekki netfang (enginn póstur), og allauth þurrkar út lykilorð óstaðfests
    aðgangs þegar komið er inn með Google á sama netfangi. Eftir endurstillingu á það ekki við lengur.
    """
    EmailAddress.objects.filter(user=user, email__iexact=user.email).update(verified=True)
