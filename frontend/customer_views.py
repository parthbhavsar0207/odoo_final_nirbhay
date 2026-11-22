"""Customer browsing and account-bound activity in the existing Django project."""
import logging
from datetime import datetime
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_POST, require_safe
from club.availability import availability_date, availability_grid
from club.models import Court, MembershipPlan, Booking
from commerce.models import Product, Sale
from commerce.views import _product_initial
from .customer_forms import CustomerRegistrationForm, CustomerSaleForm, CustomerBookingForm
from .customer_services import account_for, create_customer_sale, create_customer_booking, cancel_customer_sale, cancel_customer_booking
from .models import CustomerAccount

logger = logging.getLogger(__name__)
customer_login = login_required(login_url='customer:login')


@require_safe
def home(request):
    return render(request, 'customer/home.html', {
        'courts': Court.objects.filter(active=True)[:4],
        'products': Product.objects.filter(is_active=True)[:4],
        'plans': MembershipPlan.objects.filter(active=True),
    })


@require_safe
def plans(request):
    return render(request, 'customer/plans.html', {'plans': MembershipPlan.objects.filter(active=True)})


@require_safe
def courts(request):
    today = timezone.localdate()
    selected = availability_date(request.GET.get('date'), fallback=today)
    selected_court = request.GET.get('court')
    courts_query = Court.objects.filter(active=True)
    if selected_court:
        if not selected_court.isascii() or not selected_court.isdigit() or len(selected_court) > 19:
            raise Http404('Court does not exist.')
        court_id = int(selected_court)
        if not 1 <= court_id <= 9223372036854775807:
            raise Http404('Court does not exist.')
        get_object_or_404(courts_query, pk=court_id)
        courts_query = courts_query.filter(pk=court_id)
    hours, rows, count = availability_grid(courts_query, selected)
    for row in rows:
        for label, slot in row['slots']:
            start = timezone.make_aware(datetime.combine(selected, datetime.strptime(label, '%H:%M').time()))
            if start <= timezone.now():
                slot['status'] = 'past'
    return render(request, 'customer/courts.html', {
        'selected_date': selected, 'today': today, 'operating_hours': hours, 'court_grid': rows,
        'selected_court': selected_court,
    })


@require_safe
@ensure_csrf_cookie
def shop(request):
    return render(request, 'customer/shop.html', {
        'products': Product.objects.filter(is_active=True),
        'form': CustomerSaleForm(initial=_product_initial(request)),
    })


@csrf_protect
def register(request):
    if request.method not in {'GET', 'POST'}:
        return HttpResponse(status=405)
    if request.user.is_authenticated:
        return redirect('customer:dashboard')
    form = CustomerRegistrationForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
                CustomerAccount.objects.create(user=user)  # Never claim an existing Member by name/email.
        except IntegrityError:
            form.add_error('username', 'This username was just registered. Choose another.')
        except DatabaseError:
            logger.exception('Customer registration failed')
            return HttpResponse('Registration unavailable. Please try again later.', status=503)
        else:
            login(request, user)
            return redirect('customer:dashboard')
    return render(request, 'customer/register.html', {'form': form},
                  status=400 if request.method == 'POST' else 200)


@require_safe
@customer_login
def dashboard(request):
    account = account_for(request.user)
    return render(request, 'customer/dashboard.html', {
        'account': account, 'member': account.member,
        'bookings': Booking.objects.filter(customer=request.user).select_related('court')[:20],
        'sales': Sale.objects.filter(customer=request.user)[:20],
    })


@require_POST
@csrf_protect
@customer_login
def sale_create(request):
    form = CustomerSaleForm(request.POST)
    try:
        if form.is_valid():
            sale = create_customer_sale(request.user, **form.cleaned_data)
            return redirect('customer:sale_detail', pk=sale.pk)
    except ValidationError as error:
        form.add_error(None, error.messages)
    except DatabaseError:
        logger.exception('Customer sale creation failed')
        return HttpResponse('Purchase unavailable. Check your account before retrying.', status=503)
    return render(request, 'customer/shop.html', {
        'products': Product.objects.filter(is_active=True), 'form': form,
    }, status=400)


@require_safe
@customer_login
def sale_detail(request, pk):
    sale = get_object_or_404(Sale.objects.select_related('member'), pk=pk, customer=request.user)
    return render(request, 'customer/sale_detail.html', {'sale': sale, 'sale_items': sale.items.select_related('product')})


@require_POST
@csrf_protect
@customer_login
def sale_cancel(request, pk):
    get_object_or_404(Sale, pk=pk, customer=request.user)
    try:
        cancel_customer_sale(request.user, pk)
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    except DatabaseError:
        logger.exception('Customer purchase cancellation failed')
        return HttpResponse('Cancellation unavailable. Check your account before retrying.', status=503)
    else:
        messages.success(request, 'Unpaid purchase cancelled.')
    return redirect('customer:sale_detail', pk=pk)


@csrf_protect
@customer_login
def booking_create(request):
    if request.method not in {'GET', 'POST'}:
        return HttpResponse(status=405)
    initial = {'court': request.GET.get('court'), 'date': request.GET.get('date', timezone.localdate()),
               'start_time': request.GET.get('time')}
    form = CustomerBookingForm(request.POST if request.method == 'POST' else None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            booking = create_customer_booking(request.user,
                court=form.cleaned_data['court'], start_datetime=form.cleaned_data['start_datetime'],
                payment_method=form.cleaned_data['payment_method'])
            return redirect('customer:booking_detail', pk=booking.pk)
        except ValidationError as error:
            form.add_error(None, error.messages)
        except IntegrityError:
            form.add_error(None, 'This court session was just reserved. Choose another time.')
        except DatabaseError:
            logger.exception('Customer booking creation failed')
            return HttpResponse('Reservation unavailable. Check your account before retrying.', status=503)
    return render(request, 'customer/booking_form.html', {
        'form': form, 'member': account_for(request.user).member,
    }, status=400 if request.method == 'POST' else 200)


@require_safe
@customer_login
def booking_detail(request, pk):
    booking = get_object_or_404(Booking.objects.select_related('court'), pk=pk, customer=request.user)
    return render(request, 'customer/booking_detail.html', {'booking': booking})


@require_POST
@csrf_protect
@customer_login
def booking_cancel(request, pk):
    get_object_or_404(Booking, pk=pk, customer=request.user)
    try:
        cancel_customer_booking(request.user, pk)
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    except DatabaseError:
        logger.exception('Customer booking cancellation failed')
        return HttpResponse('Cancellation unavailable. Check your account before retrying.', status=503)
    else:
        messages.success(request, 'Reservation cancelled and court released.')
    return redirect('customer:booking_detail', pk=pk)


@require_safe
@customer_login
def checkout(request, kind, pk):
    model = {'sale': Sale, 'booking': Booking}.get(kind)
    if not model:
        raise Http404('Transaction does not exist.')
    get_object_or_404(model, pk=pk, customer=request.user)
    if settings.RAZORPAY_TEST_MODE_ENABLED:
        return redirect('commerce:razorpay_payment', kind=kind, pk=pk)
    if settings.DEMO_PAYMENT_GATEWAY_ENABLED:
        return redirect('commerce:demo_payment', kind=kind, pk=pk)
    return HttpResponse('Online payment is currently unavailable. Contact the club.', status=503)
