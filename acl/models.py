import os
import uuid
import datetime
from django.db import models
from django.conf import settings
from .managers import UserManager
from django.contrib.auth.models import Group, PermissionsMixin
from django.contrib.auth.models import BaseUserManager, AbstractBaseUser

#new
class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        """
        Creates and saves a new user with the given email and password.
        """
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """
        Creates and saves a new superuser with the given email and password.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)
#end




# new
class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.CharField(max_length=100, unique=True)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    is_active = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_suspended = models.BooleanField(default=False)
    date_created = models.DateTimeField(auto_now_add=True)
    
    # ForeignKey to Group, allowing only one group per user
    group = models.ForeignKey(Group, null=True, blank=True, related_name='user_group', on_delete=models.SET_NULL)

    USERNAME_FIELD = "email"

    objects = UserManager()

    def __str__(self):
        return '%s' % (str(self.id))

    def has_perm(self, perm, obj=None):
        return True

    def has_module_perms(self, app_label):
        return True

    class Meta:
        db_table = "systemusers"
# end


class AccountActivity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        User, related_name="user_account_activity", on_delete=models.CASCADE
    )
    actor = models.ForeignKey(
        User, related_name="activity_actor", on_delete=models.CASCADE
    )
    activity = models.TextField(null=True, blank=True)
    remarks = models.TextField(null=True, blank=True)
    action_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "account_activities"

    def __str__(self):
        return str(self.id)
