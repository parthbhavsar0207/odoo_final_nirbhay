"""Portal identity links Django accounts to the single shared Member."""
from django.conf import settings
from django.db import models


class CustomerAccount(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='customer_account')
    member = models.OneToOneField('club.Member', null=True, blank=True, on_delete=models.PROTECT, related_name='customer_account')

    def __str__(self):
        return self.user.get_username()
