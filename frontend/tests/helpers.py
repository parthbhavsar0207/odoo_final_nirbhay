"""Explicit authenticated staff fixtures for existing business-request tests."""

from uuid import uuid4

from django.contrib.auth import get_user_model


def login_test_staff(client):
    user = get_user_model().objects.create(
        username="test-staff-" + uuid4().hex,
        is_active=True, is_staff=True, is_superuser=True,
    )
    user.set_unusable_password()
    user.save(update_fields=["password"])
    client.force_login(user)
    return user
