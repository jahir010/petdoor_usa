from tortoise import fields, models

from enum import Enum


class PaymentType(str, Enum):
    STRIPE = "stripe"
    OTHERS = "others"


class Payment(models.Model):
    id = fields.UUIDField(pk=True)
    post = fields.ForeignKeyField("models.PostRequest", related_name="payments")
    customer = fields.ForeignKeyField("models.User", related_name="customer_payments")
    installer = fields.ForeignKeyField("models.User", related_name="installer_payments")
    payment_type = fields.CharField(max_length=10, default="cash")
    stripe_payment_intent_id = fields.CharField(max_length=100, unique=True, null=True)
    stripe_charge_id = fields.CharField(max_length=100, null=True)
    amount = fields.IntField()              # total in cents
    platform_fee = fields.IntField(default=0)        # your commission in cents
    installer_amount = fields.IntField()    # amount installer gets
    currency = fields.CharField(max_length=10, default="usd")
    status = fields.CharField(max_length=30, default="pending") # pending | succeeded | failed | refunded
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)



class Payout(models.Model):
    id = fields.UUIDField(pk=True)
    installer = fields.ForeignKeyField("models.User", related_name="payouts")
    stripe_payout_id = fields.CharField(max_length=100)
    amount = fields.IntField()
    currency = fields.CharField(max_length=10)
    status = fields.CharField(max_length=30) # pending | paid | failed
    arrival_date = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)



# class CommisionLog(models.Model):
#     id = fields.UUIDField(pk=True)
#     installer = fields.ForeignKeyField("models.User", related_name="installer_commisions")
#     #post = fields.ForeignKeyField("models.PostRequest", related_name="commisions")
#     amount = fields.FloatField(default=0.0)
#     created_at = fields.DatetimeField(auto_now_add=True)


class InstallerPayment(models.Model):
    id = fields.UUIDField(pk=True)
    installer = fields.ForeignKeyField("models.User", related_name="admin_payments")
    payment_type = fields.CharEnumField(PaymentType)
    amount = fields.FloatField()
    status = fields.CharField(max_length=30, default="pending")
    stripe_payment_intent_id = fields.CharField(max_length=100, unique=True, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)


