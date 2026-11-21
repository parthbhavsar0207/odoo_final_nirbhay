"""Private club records require an active staff session and server permissions."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from io import StringIO
from unittest import skipUnless

from django.contrib.auth import SESSION_KEY, get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.db import connection
from django.http import HttpResponse
from django.test import Client, TestCase, override_settings
from django.urls import include, path, reverse
from django.utils import timezone

from club.models import Booking, Member, MembershipPlan, Court
from commerce.models import Product, Sale
from commerce.services import create_sale
from config.access import STAFF_PERMISSIONS


def unreviewed_operation(request):
    return HttpResponse("PRIVATE_UNREVIEWED_SCREEN")


# Keep real named auth/error-template routes available when testing a future
# route not yet present in the access policy.
urlpatterns = [
    path("unreviewed/", unreviewed_operation, name="unreviewed_operation"),
    path("static/unreviewed/", unreviewed_operation, name="unreviewed_static_operation"),
    path("", include("config.urls")),
]


@skipUnless(connection.vendor == "postgresql", "Requires the shared PostgreSQL staff application")
class StaffAuthenticationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("setup_staff_roles", stdout=StringIO())
        password_hash = make_password("Authentication-test-only-7!")
        user_model = get_user_model()
        cls.owner = user_model.objects.create(username="auth-owner", password=password_hash, is_staff=True)
        cls.reception = user_model.objects.create(username="auth-reception", password=password_hash, is_staff=True)
        cls.counter = user_model.objects.create(username="auth-counter", password=password_hash, is_staff=True)
        cls.unassigned = user_model.objects.create(username="auth-unassigned", password=password_hash, is_staff=True)
        cls.visitor = user_model.objects.create(username="auth-visitor", password=password_hash)
        cls.inactive = user_model.objects.create(username="auth-inactive", password=password_hash, is_staff=True, is_active=False)
        for user, role in [(cls.owner, "Owner"), (cls.reception, "Reception"), (cls.counter, "Counter")]:
            user.groups.add(Group.objects.get(name=role))
        cls.plan = MembershipPlan.objects.create(
            tier="silver", name="Public Silver", court_hourly_rate=Decimal("200.00"),
            shop_discount_percent=Decimal("10.00"), bar_discount_percent=Decimal("5.00"),
        )
        cls.member = Member.objects.create(
            name="PRIVATE_AUTH_MEMBER_TOKEN", email="private-auth@example.com",
            phone="PRIVATE_AUTH_CONTACT_TOKEN", plan=cls.plan,
        )
        cls.court = Court.objects.create(name="Public Tennis", sport="tennis", hourly_rate=Decimal("500.00"))
        day = timezone.localdate() + timedelta(days=1)
        cls.booking = Booking.objects.create(
            court=cls.court, booked_by_member=cls.member, status="confirmed",
            start_datetime=timezone.make_aware(datetime.combine(day, time(9))),
        )
        cls.product = Product.objects.create(
            name="Public racket", category="shop", price=Decimal("12.50"), stock_quantity=777777,
        )
        cls.sale = create_sale(quantities={cls.product.pk: 2}, payment_method="cash", member_id=cls.member.pk)

    def url(self, name):
        if name in {"club:member_edit", "club:member_change_plan"}:
            return reverse(name, args=[self.member.pk])
        if name in {"club:plan_edit", "club:plan_toggle_active"}:
            return reverse(name, args=[self.plan.pk])
        if name in {"club:booking_detail", "club:booking_cancel", "club:booking_receipt"}:
            return reverse(name, args=[self.booking.pk])
        if name in {"commerce:sale_detail", "commerce:sale_receipt", "commerce:sale_complete", "commerce:sale_cancel"}:
            return reverse(name, args=[self.sale.pk])
        return reverse(name)

    def assert_no_private_payload(self, response):
        self.assertNotIn(self.member.name, response.content.decode())
        self.assertNotIn(self.member.phone, response.content.decode())
        self.assertNotIn(self.member.email, response.content.decode())

    def test_anonymous_private_pages_redirect_before_returning_data(self):
        for name in STAFF_PERMISSIONS:
            with self.subTest(route=name):
                response = self.client.get(self.url(name))
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(reverse("staff_login") + "?next="))
                self.assert_no_private_payload(response)

    def test_authenticated_nonstaff_cannot_open_private_pages(self):
        self.client.force_login(self.visitor)
        for name in STAFF_PERMISSIONS:
            with self.subTest(route=name):
                response = self.client.get(self.url(name))
                self.assertEqual(response.status_code, 403)
                self.assert_no_private_payload(response)

    def test_unassigned_staff_cannot_open_business_records(self):
        self.client.force_login(self.unassigned)
        for name in ["dashboard", "club:member_list", "club:booking_list", "commerce:guest_counter", "commerce:sale_receipt"]:
            with self.subTest(route=name):
                response = self.client.get(self.url(name))
                self.assertEqual(response.status_code, 403)
                self.assert_no_private_payload(response)

    def test_inactive_account_has_no_authenticated_access(self):
        self.client.force_login(self.inactive)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assert_no_private_payload(response)

    def test_owner_can_open_dashboard_and_operational_screens(self):
        self.client.force_login(self.owner)
        for name in ["dashboard", "club:member_list", "club:booking_list", "club:plan_create", "commerce:guest_counter", "commerce:sale_receipt"]:
            with self.subTest(route=name):
                self.assertEqual(self.client.get(self.url(name)).status_code, 200)

    def test_reception_can_manage_members_bookings_but_not_owner_or_counter(self):
        self.client.force_login(self.reception)
        for name in ["club:member_list", "club:member_create", "club:booking_create", "club:booking_receipt", "club:plan_list"]:
            with self.subTest(allowed=name):
                self.assertEqual(self.client.get(self.url(name)).status_code, 200)
        for name in ["dashboard", "commerce:guest_counter", "commerce:sale_receipt", "club:plan_create"]:
            with self.subTest(denied=name):
                self.assertEqual(self.client.get(self.url(name)).status_code, 403)

    def test_counter_can_use_sales_but_cannot_list_members_or_export_bookings(self):
        self.client.force_login(self.counter)
        for name in ["commerce:guest_counter", "commerce:member_counter", "commerce:sale_detail", "commerce:sale_receipt"]:
            with self.subTest(allowed=name):
                self.assertEqual(self.client.get(self.url(name)).status_code, 200)
        for name in ["dashboard", "club:member_list", "club:booking_export_csv", "club:booking_export_csv_alias", "club:plan_create"]:
            with self.subTest(denied=name):
                self.assertEqual(self.client.get(self.url(name)).status_code, 403)

    def test_private_json_export_receipt_and_member_pricing_cannot_bypass_login(self):
        for url in [
            self.url("club:booking_detail") + "?ajax=1", self.url("club:booking_receipt"),
            self.url("club:booking_export_csv"), self.url("club:booking_export_csv_alias"),
            reverse("club:api_calculate_price") + f"?court={self.court.pk}&member={self.member.pk}",
            self.url("commerce:sale_receipt"),
        ]:
            with self.subTest(url=url):
                response = self.client.get(url, HTTP_ACCEPT="application/json", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
                self.assertEqual(response.status_code, 302)
                self.assert_no_private_payload(response)

    def test_denied_sale_writes_leave_inventory_and_records_unchanged(self):
        count = Sale.objects.count()
        for user in [None, self.visitor, self.reception, self.unassigned]:
            client = Client()
            if user:
                client.force_login(user)
            for name in ["commerce:sale_create", "commerce:member_sale_create", "commerce:sale_complete", "commerce:sale_cancel"]:
                with self.subTest(user=user, route=name):
                    response = client.post(self.url(name), {
                        "product": self.product.pk, "member": self.member.pk,
                        "quantity": "2", "payment_method": "cash",
                    })
                    self.assertEqual(response.status_code, 302 if user is None else 403)
        self.product.refresh_from_db()
        self.sale.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 777777)
        self.assertEqual(self.sale.status, Sale.Status.DRAFT)
        self.assertEqual(Sale.objects.count(), count)

    def test_view_permission_does_not_allow_sale_completion(self):
        user = get_user_model().objects.create(username="read-only-staff", is_staff=True)
        user.user_permissions.add(Permission.objects.get(content_type__app_label="commerce", codename="view_sale"))
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url("commerce:sale_detail")).status_code, 200)
        self.assertEqual(self.client.post(self.url("commerce:sale_complete")).status_code, 403)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, Sale.Status.DRAFT)

    def test_staff_home_redirects_to_the_assigned_role_screen(self):
        for user, target in [(self.owner, "dashboard"), (self.reception, "club:member_list"), (self.counter, "commerce:guest_counter")]:
            with self.subTest(user=user):
                client = Client()
                client.force_login(user)
                self.assertRedirects(client.get(reverse("staff_home")), reverse(target), fetch_redirect_response=False)

    def test_valid_staff_login_uses_django_session_and_password_hash(self):
        response = self.client.post(reverse("staff_login"), {
            "username": self.counter.username, "password": "Authentication-test-only-7!",
        })
        self.assertRedirects(response, reverse("staff_home"), fetch_redirect_response=False)
        self.assertEqual(self.client.session[SESSION_KEY], str(self.counter.pk))
        self.assertNotEqual(self.counter.password, "Authentication-test-only-7!")
        self.assertTrue(self.counter.check_password("Authentication-test-only-7!"))

    def test_wrong_password_unknown_nonstaff_and_inactive_accounts_cannot_login(self):
        for username, password in [
            (self.owner.username, "wrong-password"), ("does-not-exist", "Authentication-test-only-7!"),
            (self.visitor.username, "Authentication-test-only-7!"), (self.inactive.username, "Authentication-test-only-7!"),
        ]:
            with self.subTest(username=username):
                client = Client()
                response = client.post(reverse("staff_login"), {"username": username, "password": password})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].non_field_errors())
                self.assertNotIn(SESSION_KEY, client.session)

    def test_login_redirect_cannot_send_session_to_an_external_host(self):
        for target in ["https://untrusted.example/", "//untrusted.example/", "http://untrusted.example/"]:
            with self.subTest(next=target):
                response = Client().post(reverse("staff_login"), {
                    "username": self.counter.username, "password": "Authentication-test-only-7!", "next": target,
                })
                self.assertRedirects(response, reverse("staff_home"), fetch_redirect_response=False)

    def test_safe_next_opens_authorized_counter_after_login(self):
        target = reverse("commerce:guest_counter")
        response = self.client.post(reverse("staff_login"), {
            "username": self.counter.username, "password": "Authentication-test-only-7!", "next": target,
        })
        self.assertRedirects(response, target, fetch_redirect_response=False)

    def test_ungranted_next_uses_role_landing_without_opening_private_page(self):
        response = self.client.post(reverse("staff_login"), {
            "username": self.counter.username, "password": "Authentication-test-only-7!", "next": "/",
        })
        self.assertRedirects(response, reverse("staff_home"), fetch_redirect_response=False)
        response = self.client.get(reverse("staff_home"))
        self.assertRedirects(response, reverse("commerce:guest_counter"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 403)

    def test_login_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(reverse("staff_login"), {"username": self.owner.username, "password": "Authentication-test-only-7!"})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(SESSION_KEY, client.session)

    def test_logout_is_post_only_csrf_protected_and_removes_private_session(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.counter)
        self.assertEqual(client.get(reverse("staff_logout")).status_code, 405)
        self.assertIn(SESSION_KEY, client.session)
        self.assertEqual(client.post(reverse("staff_logout")).status_code, 403)
        client.get(reverse("commerce:guest_counter"))
        token = client.cookies["csrftoken"].value
        response = client.post(reverse("staff_logout"), {"csrfmiddlewaretoken": token})
        self.assertRedirects(response, reverse("staff_login"), fetch_redirect_response=False)
        self.assertNotIn(SESSION_KEY, client.session)
        self.assertEqual(client.get(self.url("commerce:sale_detail")).status_code, 302)

    def test_counter_checkout_requires_both_staff_session_and_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.counter)
        data = {"product": self.product.pk, "quantity": "2", "payment_method": "cash"}
        self.assertEqual(client.post(reverse("commerce:sale_create"), data).status_code, 403)
        client.get(reverse("commerce:guest_counter"))
        token = client.cookies["csrftoken"].value
        response = client.post(reverse("commerce:sale_create"), {**data, "csrfmiddlewaretoken": token})
        self.assertEqual(response.status_code, 302)
        sale = Sale.objects.latest("pk")
        for name in ["commerce:sale_complete", "commerce:sale_cancel"]:
            self.assertEqual(client.post(reverse(name, args=[sale.pk])).status_code, 403)
            self.assertEqual(client.post(reverse(name, args=[sale.pk]), {"csrfmiddlewaretoken": token}).status_code, 302)
        self.product.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 777777)
        self.assertEqual(sale.status, Sale.Status.CANCELLED)

    def test_anonymous_public_screens_exclude_member_and_transaction_identity(self):
        urls = [
            reverse("club:sports_directory"), reverse("club:sport_detail", args=["tennis"]),
            reverse("club:public_plans"), reverse("club:public_availability") + "?date=" + timezone.localtime(self.booking.start_datetime).date().isoformat(),
            reverse("club:search_suggestions") + "?q=Public", reverse("club:help_bot_faq"),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assert_no_private_payload(response)

    def test_anonymous_search_does_not_reveal_exact_inventory_counts(self):
        response = self.client.get(reverse("club:search_suggestions"), {"q": self.product.name})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("777777", response.content.decode())
        self.assertIn(self.product.name, response.content.decode())

    def test_public_facility_endpoints_reject_state_changing_methods(self):
        for name, args in [
            ("club:sports_directory", None), ("club:sport_detail", ["tennis"]),
            ("club:public_plans", None), ("club:public_availability", None),
            ("club:search_suggestions", None), ("club:help_bot_faq", None),
        ]:
            with self.subTest(route=name):
                self.assertEqual(self.client.post(reverse(name, args=args)).status_code, 405)

    def test_private_responses_are_not_cached_after_logout(self):
        self.client.force_login(self.owner)
        for name in ["dashboard", "club:member_list", "commerce:sale_detail"]:
            with self.subTest(route=name):
                response = self.client.get(self.url(name))
                self.assertEqual(response.status_code, 200)
                self.assertIn("no-store", response["Cache-Control"])
                self.assertIn("private", response["Cache-Control"])

    @override_settings(ROOT_URLCONF=__name__)
    def test_unreviewed_new_route_fails_closed_even_for_staff(self):
        for name in ["unreviewed_operation", "unreviewed_static_operation"]:
            client = Client()
            self.assertEqual(client.get(reverse(name)).status_code, 302)
            client.force_login(self.owner)
            response = client.get(reverse(name))
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("PRIVATE_UNREVIEWED_SCREEN", response.content.decode())

    def test_role_setup_is_repeatable_and_does_not_assign_or_replace_users(self):
        users = list(get_user_model().objects.order_by("pk").values())
        groups_before = {group.name: set(group.permissions.values_list("pk", flat=True)) for group in Group.objects.all()}
        call_command("setup_staff_roles", stdout=StringIO())
        call_command("setup_staff_roles", stdout=StringIO())
        self.assertEqual(list(get_user_model().objects.order_by("pk").values()), users)
        self.assertEqual({group.name: set(group.permissions.values_list("pk", flat=True)) for group in Group.objects.all()}, groups_before)
        self.assertEqual(set(Group.objects.values_list("name", flat=True)), {"Owner", "Reception", "Counter"})
