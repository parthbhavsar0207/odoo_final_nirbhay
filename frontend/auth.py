"""Use Django password hashing, sessions and safe login redirects."""

from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, resolve_url
from django.urls import Resolver404, resolve
from django.views.decorators.http import require_safe

from config.access import PUBLIC_VIEWS, can_access


class StaffAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise ValidationError(self.error_messages['invalid_login'], code='invalid_login', params={'username': self.username_field.verbose_name})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-input'


class StaffLoginView(LoginView):
    authentication_form = StaffAuthenticationForm
    template_name = 'registration/login.html'
    extra_context = {'page_title': 'Staff sign in'}

    def get_success_url(self):
        target = self.get_redirect_url()
        if target:
            try:
                match = resolve(unquote(urlsplit(target).path))
            except Resolver404:
                pass
            else:
                if match.view_name in PUBLIC_VIEWS or match.namespace == 'admin' or can_access(self.request.user, match.view_name):
                    return target
        return resolve_url(settings.LOGIN_REDIRECT_URL)


class StaffLogoutView(LogoutView):
    next_page = 'staff_login'


@require_safe
def staff_home(request):
    for name in ('dashboard', 'commerce:guest_counter', 'club:member_list', 'club:booking_list', 'club:plan_list'):
        if can_access(request.user, name):
            return redirect(name)
    raise PermissionDenied('Ask the owner to assign your staff role.')
