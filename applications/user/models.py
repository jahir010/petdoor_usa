from tortoise import fields, models
from passlib.hash import bcrypt
from app.utils.generate_unique import generate_unique
from enum import Enum


class Permission(models.Model):
    id = fields.IntField(pk=True, readonly=True, hidden=True)
    name = fields.CharField(max_length=100, unique=True, editable=False)
    codename = fields.CharField(max_length=100, unique=True, editable=False)

    def __str__(self):
        return f"{self.codename}"


class Group(models.Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=100, unique=True)

    permissions: fields.ManyToManyRelation["Permission"] = fields.ManyToManyField(
        "models.Permission", related_name="groups", through="group_permissions"
    )

    def __str__(self):
        return self.name


class UserRole(str, Enum):
    CUSTOMER = "CUSTOMER"
    INSTALLER = "INSTALLER"
    ADMIN = "ADMIN"

class User(models.Model):
    id = fields.CharField(pk=True, max_length=60)
    name = fields.CharField(max_length=50, null=True, blank=True, default="Unknown User")
    email = fields.CharField(max_length=100, null=True, unique=True)
    password = fields.CharField(max_length=128)
    photo = fields.CharField(max_length=255, null=True, blank=True)
    phone = fields.CharField(max_length=255, null=True, blank=True)
    address = fields.TextField(null=True, blank=True)

    role = fields.CharEnumField(UserRole)

    is_active = fields.BooleanField(default=True)
    is_suspended = fields.BooleanField(default=False)
    is_staff = fields.BooleanField(default=False)

    last_login_at = fields.DatetimeField(null=True)
    is_otp = fields.BooleanField(default=False)

    stripe_account_id = fields.CharField(max_length=100, null=True)
    stripe_account_completed = fields.BooleanField(default=False)

    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    groups: fields.ManyToManyRelation["Group"] = fields.ManyToManyField(
        "models.Group", related_name="users", through="user_groups"
    )

    user_permissions: fields.ManyToManyRelation["Permission"] = fields.ManyToManyField(
        "models.Permission", related_name="users", through="user_permissions"
    )

    async def has_permission(self, codename: str) -> bool:
        if self.role == UserRole.ADMIN:
            return True

        await self.fetch_related("user_permissions", "groups__permissions")

        if self.is_staff:
            for perm in self.user_permissions:
                if perm.codename == codename:
                    return True

            for group in self.groups:
                for perm in group.permissions:
                    if perm.codename == codename:
                        return True
        return False

    @classmethod
    def set_password(cls, password: str) -> str:
        return bcrypt.hash(password)

    def verify_password(self, password: str) -> bool:
        return bcrypt.verify(password, self.password)

    class Meta:
        table = "users"

    def __str__(self):
        return f"{self.name} ({self.email})"

    async def save(self, *args, **kwargs):
        if not self.id:
            text = "USR"
            if self.role == UserRole.ADMIN:
                text = "ADM"
            if self.role == UserRole.INSTALLER:
                text = "INT"
            if self.role == UserRole.CUSTOMER:
                text = "CUS"
            self.id = (await generate_unique(User, text=text, max_length=5)).upper()
        if self.password and not self.password.startswith("$2b$"):
            self.password = self.set_password(self.password)

        await super().save(*args, **kwargs)



class DeviceToken(models.Model):
    id = fields.IntField(pk=True)
    user_id = fields.CharField(max_length=64)
    token = fields.CharField(max_length=256)
    platform = fields.CharField(max_length=32)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

