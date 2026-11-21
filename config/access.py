"""Server-side access policy for the shared staff application."""

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseNotAllowed
from django.utils.cache import add_never_cache_headers
from django.utils.deprecation import MiddlewareMixin


PUBLIC_VIEWS = frozenset({
    'staff_login', 'staff_logout',
    'club:sports_directory', 'club:sport_detail', 'club:public_plans',
    'club:public_availability', 'club:search_suggestions', 'club:help_bot_faq',
})

STAFF_PERMISSIONS = {
    'dashboard': ('club.view_member', 'club.view_booking', 'commerce.view_sale'),
    'staff_home': (),
    'club:index': ('club.view_member',),
    'club:member_list': ('club.view_member',),
    'club:member_create': ('club.view_member', 'club.add_member'),
    'club:member_edit': ('club.view_member', 'club.change_member'),
    'club:member_change_plan': ('club.view_member', 'club.change_member', 'club.add_memberplanchange'),
    'club:plan_list': ('club.view_membershipplan',),
    'club:plan_create': ('club.view_membershipplan', 'club.add_membershipplan'),
    'club:plan_edit': ('club.view_membershipplan', 'club.change_membershipplan'),
    'club:plan_toggle_active': ('club.view_membershipplan', 'club.change_membershipplan'),
    'club:booking_list': ('club.view_booking',),
    'club:booking_create': ('club.view_booking', 'club.add_booking', 'club.view_member'),
    'club:booking_detail': ('club.view_booking',),
    'club:booking_cancel': ('club.view_booking', 'club.change_booking'),
    'club:booking_receipt': ('club.view_booking',),
    'club:booking_export_csv': ('club.view_booking',),
    'club:booking_export_csv_alias': ('club.view_booking',),
    'club:api_calculate_price': ('club.view_booking', 'club.view_member'),
    'commerce:index': ('commerce.view_sale', 'commerce.add_sale', 'commerce.view_product'),
    'commerce:shop': ('commerce.view_sale', 'commerce.add_sale', 'commerce.view_product'),
    'commerce:guest_counter': ('commerce.view_sale', 'commerce.add_sale', 'commerce.view_product'),
    'commerce:member_counter': ('commerce.view_sale', 'commerce.add_sale', 'commerce.view_product'),
    'commerce:sale_create': ('commerce.view_sale', 'commerce.add_sale'),
    'commerce:member_sale_create': ('commerce.view_sale', 'commerce.add_sale'),
    'commerce:sale_detail': ('commerce.view_sale',),
    'commerce:sale_receipt': ('commerce.view_sale',),
    'commerce:sale_complete': ('commerce.view_sale', 'commerce.change_sale'),
    'commerce:sale_cancel': ('commerce.view_sale', 'commerce.change_sale'),
}

POST_PERMISSIONS = {
    'club:booking_detail': ('club.add_bookingparticipant',),
}

POST_ONLY = frozenset({
    'club:booking_cancel', 'club:plan_toggle_active', 'commerce:sale_create',
    'commerce:member_sale_create', 'commerce:sale_complete', 'commerce:sale_cancel',
})


def can_access(user, view_name, *, method='GET'):
    if not (user.is_authenticated and user.is_active and user.is_staff):
        return False
    if view_name not in STAFF_PERMISSIONS:
        return False
    permissions = STAFF_PERMISSIONS[view_name]
    if method == 'POST':
        permissions += POST_PERMISSIONS.get(view_name, ())
    return user.has_perms(permissions)


class StaffAccessMiddleware(MiddlewareMixin):
    """Protect all resolved application views; unknown views fail closed.

    Public visitors never reach staff views or queries. Django admin retains
    its own active-staff/model permission enforcement. CSRF remains independent.
    """
    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if match.namespace == 'admin':
            return None
        if view_func.__module__ in {'django.contrib.staticfiles.views', 'django.views.static'} and view_func.__name__ == 'serve':
            return None
        name = match.view_name
        if name in PUBLIC_VIEWS:
            if name not in {'staff_login', 'staff_logout'} and request.method not in {'GET', 'HEAD'}:
                return HttpResponseNotAllowed(['GET', 'HEAD'])
            return None
        request._staff_private_response = True
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        if not can_access(user, name, method=request.method):
            raise PermissionDenied('Your staff account does not have access to this screen.')
        if name in POST_ONLY and request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])
        return None

    def process_response(self, request, response):
        if getattr(request, '_staff_private_response', False) or (
            getattr(request, 'resolver_match', None) and request.resolver_match.view_name in {'staff_login', 'staff_logout'}
        ):
            add_never_cache_headers(response)
        return response
