import factory

from apps.accounts.models import User
from apps.gifts.models import Gift, Idea, IdeaGiver, Person, Season, Store
from apps.households.models import Household, Membership


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"notandi{n}@example.com")


class HouseholdFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Household

    name = factory.Sequence(lambda n: f"Heimili {n}")
    slug = factory.Sequence(lambda n: f"heimili-{n}")


class MembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Membership

    user = factory.SubFactory(UserFactory)
    household = factory.SubFactory(HouseholdFactory)


class PersonFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Person

    household = factory.SubFactory(HouseholdFactory)
    name = factory.Sequence(lambda n: f"Manneskja {n}")


class StoreFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Store

    household = factory.SubFactory(HouseholdFactory)
    name = factory.Sequence(lambda n: f"Búð {n}")


class SeasonFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Season

    household = factory.SubFactory(HouseholdFactory)
    year = 2026
    budget = 160000


class GiftFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Gift

    season = factory.SubFactory(SeasonFactory)
    person = factory.SubFactory(PersonFactory, household=factory.SelfAttribute("..season.household"))


class IdeaFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Idea

    gift = factory.SubFactory(GiftFactory)
    text = factory.Sequence(lambda n: f"hugmynd {n}")


def giver(idea, person, **kwargs) -> IdeaGiver:
    return IdeaGiver.objects.create(idea=idea, person=person, **kwargs)
