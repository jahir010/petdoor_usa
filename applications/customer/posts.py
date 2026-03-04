from tortoise import models, fields
import uuid
from enum import Enum

class InstallationSurface(str, Enum):
    DOOR = "DOOR"
    WALL = "WALL"
    GLASS = "GLASS"
    OTHER = "OTHER"


class StatusEnum(str, Enum):
    PENDING = "PENDING"
    RECEIVING_BIDS = "RECEIVING_BIDS"
    INSTALLER_ASSIGNED = "INSTALLER_ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BidStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    CANCELED = "CANCELED"



class PostRequest(models.Model):
    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    customer = fields.ForeignKeyField("models.User", related_name="posts")
    installer = fields.ForeignKeyField("models.User", related_name="assigned_posts", null=True)
    area = fields.ForeignKeyField("models.ServiceArea", related_name="post_area", on_delete=fields.CASCADE)
    pet_name = fields.CharField(max_length=100)
    pet_type = fields.CharField(max_length=100)
    price = fields.FloatField()
    size = fields.CharField(max_length=100)
    installation_surface = fields.CharEnumField(InstallationSurface)
    Address = fields.TextField()
    photos = fields.JSONField(null=True)  # List of photo URLs
    status = fields.CharEnumField(StatusEnum, default=StatusEnum.PENDING)
    scheduled_date = fields.DatetimeField(null=True)
    note = fields.TextField(null=True)
    assigned_at = fields.DatetimeField(null=True)
    is_additional_service = fields.BooleanField(default=False)
    additional_service_note = fields.TextField(null=True)
    is_customer_satisfied = fields.BooleanField(null=True)
    customer_satisfaction_note = fields.TextField(null=True)
    metadata = fields.JSONField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)


    class Meta:
        table = "post_requests"

    
class Bid(models.Model):
    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    post_request = fields.ForeignKeyField("models.PostRequest", related_name="bids")
    installer = fields.ForeignKeyField("models.User", related_name="bids")
    price = fields.FloatField()
    status = fields.CharEnumField(BidStatus, default=BidStatus.PENDING)
    note = fields.TextField(null=True)
    updated_at = fields.DatetimeField(auto_now=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "bids"
