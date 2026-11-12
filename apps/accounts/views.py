from allauth.account.utils import get_next_redirect_url
from allauth.account.views import SignupView as AllauthSignupView

from .forms import joins_by_invite


class SignupView(AllauthSignupView):
    """Nýskráning; heimilisreiturinn hverfur þegar notandinn er á leið að þiggja boð."""

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["joining"] = joins_by_invite(get_next_redirect_url(self.request))
        return kwargs


signup = SignupView.as_view()
