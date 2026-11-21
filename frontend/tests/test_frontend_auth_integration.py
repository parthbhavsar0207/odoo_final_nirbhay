"""Nayan's grouped navigation respects the shared staff-login permissions."""

from html.parser import HTMLParser
from io import StringIO
from unittest import skipUnless
from urllib.parse import urlsplit

from django.contrib.auth import SESSION_KEY, get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import connection
from django.test import Client, TestCase
from django.urls import resolve, reverse


class HeaderMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.in_header = False
        self.links = []
        self.forms = []
        self.text = []
        self.current_form = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "header":
            self.in_header = True
        if not self.in_header:
            return
        if tag == "a":
            self.links.append(attrs.get("href", ""))
        elif tag == "form":
            self.current_form = {"attrs": attrs, "controls": []}
            self.forms.append(self.current_form)
        elif tag in {"input", "button"} and self.current_form is not None:
            self.current_form["controls"].append(attrs)

    def handle_endtag(self, tag):
        if tag == "form":
            self.current_form = None
        elif tag == "header":
            self.in_header = False

    def handle_data(self, data):
        if self.in_header:
            self.text.append(data.strip())


@skipUnless(connection.vendor == "postgresql", "Requires shared PostgreSQL staff roles")
class FrontendAuthenticationIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("setup_staff_roles", stdout=StringIO())
        cls.users = {}
        for role in ["Owner", "Reception", "Counter"]:
            user = get_user_model().objects.create(
                username="navigation-" + role.lower(), is_staff=True, is_active=True,
            )
            user.groups.add(Group.objects.get(name=role))
            cls.users[role] = user

    def page(self, role, route):
        self.client.force_login(self.users[role])
        response = self.client.get(reverse(route))
        self.assertEqual(response.status_code, 200)
        return response, HeaderMarkup(response.content.decode())

    def test_anonymous_login_uses_new_design_without_private_navigation_links(self):
        response = self.client.get(reverse("staff_login"))
        self.assertEqual(response.status_code, 200)
        header = HeaderMarkup(response.content.decode())
        self.assertContains(response, "club-navbar")
        self.assertContains(response, "staff-nav")
        self.assertIn(reverse("staff_login"), header.links)
        for route in [
            "dashboard", "club:member_list", "club:member_create", "club:booking_list",
            "club:booking_export_csv", "commerce:guest_counter", "commerce:member_counter",
        ]:
            self.assertNotIn(reverse(route), header.links)
        self.assertNotIn("/" + "#commerce-performance", header.links)
        self.assertNotIn("/" + "#inventory-alerts", header.links)
        self.assertEqual(header.forms, [])

    def test_owner_grouped_navigation_connects_operational_routes_and_dashboard_sections(self):
        response, header = self.page("Owner", "dashboard")
        for label in ["Courts &amp; Bookings", "Members Ledger", "Shop &amp; Bar POS"]:
            self.assertContains(response, label)
        for route in [
            "dashboard", "club:booking_list", "club:booking_export_csv", "club:member_list",
            "club:member_create", "club:plan_list", "commerce:guest_counter", "commerce:member_counter",
        ]:
            self.assertIn(reverse(route), header.links)
        for fragment in ["commerce-performance", "inventory-alerts"]:
            self.assertIn(reverse("dashboard") + "#" + fragment, header.links)
            self.assertContains(response, 'id="' + fragment + '"')

    def test_counter_navigation_excludes_records_and_owner_reporting(self):
        response, header = self.page("Counter", "commerce:guest_counter")
        self.assertContains(response, "Shop &amp; Bar POS")
        self.assertIn(reverse("commerce:guest_counter"), header.links)
        self.assertIn(reverse("commerce:member_counter"), header.links)
        for route in ["dashboard", "club:member_list", "club:booking_list", "club:booking_export_csv"]:
            self.assertNotIn(reverse(route), header.links)
            self.assertEqual(self.client.get(reverse(route)).status_code, 403)
        self.assertNotIn(reverse("dashboard") + "#commerce-performance", header.links)
        self.assertNotIn(reverse("dashboard") + "#inventory-alerts", header.links)

    def test_reception_navigation_preserves_booking_member_workflows_without_counter_links(self):
        response, header = self.page("Reception", "club:member_list")
        self.assertContains(response, "Members Ledger")
        for route in ["club:booking_list", "club:booking_create", "club:member_list", "club:member_create", "club:plan_list"]:
            self.assertIn(reverse(route), header.links)
            self.assertEqual(self.client.get(reverse(route)).status_code, 200)
        for route in ["commerce:guest_counter", "commerce:member_counter", "dashboard"]:
            self.assertNotIn(reverse(route), header.links)
            self.assertEqual(self.client.get(reverse(route)).status_code, 403)

    def test_account_menu_shows_actual_username_instead_of_placeholder_admin(self):
        _, header = self.page("Counter", "commerce:guest_counter")
        self.assertIn(self.users["Counter"].username, " ".join(header.text))
        self.assertNotIn("Admin", header.text)

    def test_desktop_and_mobile_logout_forms_post_csrf_and_end_the_session(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.users["Counter"])
        response = client.get(reverse("commerce:guest_counter"))
        header = HeaderMarkup(response.content.decode())
        forms = [form for form in header.forms if form["attrs"].get("action") == reverse("staff_logout")]
        self.assertEqual(len(forms), 2)
        for form in forms:
            self.assertEqual(form["attrs"].get("method"), "post")
            tokens = [control for control in form["controls"] if control.get("name") == "csrfmiddlewaretoken"]
            self.assertEqual(len(tokens), 1)
            self.assertTrue(tokens[0].get("value"))
        token = client.cookies["csrftoken"].value
        response = client.post(reverse("staff_logout"), {"csrfmiddlewaretoken": token})
        self.assertRedirects(response, reverse("staff_login"), fetch_redirect_response=False)
        self.assertNotIn(SESSION_KEY, client.session)
        self.assertEqual(client.get(reverse("commerce:guest_counter")).status_code, 302)

    def test_owner_navigation_links_resolve_to_real_named_routes(self):
        _, header = self.page("Owner", "dashboard")
        for href in header.links:
            parts = urlsplit(href)
            if not parts.netloc and parts.path.startswith("/"):
                with self.subTest(href=href):
                    match = resolve(parts.path)
                    self.assertTrue(match.view_name)
                    response = self.client.get(parts.path)
                    self.assertIn(response.status_code, {200, 302})
