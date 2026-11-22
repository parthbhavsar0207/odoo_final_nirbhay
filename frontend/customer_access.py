"""Protect portal-owned records even through legacy demo detail/payment URLs."""
from django.http import Http404, HttpResponse
from django.db import DatabaseError
from club.models import Booking
from commerce.models import Sale


def may_access_customer_record(request, target):
    if not target.customer_id:
        return True  # Existing anonymous staff demo records retain their contract.
    user = request.user
    return user.is_authenticated and user.is_active and (user.is_staff or user.pk == target.customer_id)


class CustomerRecordAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if not match or 'pk' not in view_kwargs:
            return None
        namespace, name = match.namespace, match.url_name
        model = None
        if namespace == 'commerce' and name in {'sale_detail', 'sale_receipt', 'sale_complete', 'sale_cancel'}:
            model = Sale
        elif namespace == 'club' and name in {'booking_detail', 'booking_receipt', 'booking_cancel'}:
            model = Booking
        elif namespace == 'commerce' and name in {
            'demo_payment', 'demo_payment_submit', 'razorpay_payment',
            'razorpay_order_create', 'razorpay_payment_verify',
        }:
            model = {'sale': Sale, 'booking': Booking}.get(view_kwargs.get('kind'))
        if model is not None:
            try:
                target = model.objects.filter(pk=view_kwargs['pk']).only('customer_id').first()
            except DatabaseError:
                return HttpResponse('Transaction unavailable. Please retry later.', status=503)
            if target and not may_access_customer_record(request, target):
                raise Http404('Transaction does not exist.')
            # Customer cancellations/roster edits use the narrower portal policy.
            # A generic legacy completion or mutation cannot bypass that policy.
            if target and target.customer_id and not request.user.is_staff:
                if (namespace == 'commerce' and name in {'sale_complete', 'sale_cancel'}) or (
                    namespace == 'club' and (name == 'booking_cancel' or (name == 'booking_detail' and request.method == 'POST'))
                ):
                    raise Http404('Use your account transaction actions.')
        return None
