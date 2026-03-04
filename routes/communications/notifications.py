from fastapi import APIRouter, Depends, HTTPException, status, Form, Request, Response, UploadFile, File, Query
from pydantic import BaseModel
from applications.user.models import User, UserRole, DeviceToken
from app.token import get_current_user

from app.auth import login_required, role_required
from firebase_admin import messaging
from applications.communication.notifications import PushNotification, NotificationSetting
from typing import Optional






router = APIRouter(tags=['notification'])






class DeviceTokenIn(BaseModel):
    user_id: str
    token: str
    platform: str

class NotificationIn(BaseModel):
    user_id: str
    title: str
    body: str




@router.post("/save_token/")
async def save_device_token(data: DeviceTokenIn, user: User = Depends(get_current_user)):
    exists = await DeviceToken.filter(user_id=user.id, platform=data.platform).first()
    if exists:
        exists.token = data.token
        await exists.save()
    else:
        await DeviceToken.create(**data.dict())
    return {"status": "success"}



@router.post("/send_notification/")
async def send_notification(data: NotificationIn):
    device = await DeviceToken.filter(user_id=data.user_id).first()
    if not device:
        raise HTTPException(404, "Device token not found")
    settings = await NotificationSetting.filter(user_id=data.user_id).first()
    if settings and not settings.is_enabled:
        raise HTTPException(403, "Notifications are disabled for this user")

    message = messaging.Message(
        notification=messaging.Notification(
            title=data.title,
            body=data.body,
        ),
        token=device.token,
    )
    push_notification = await PushNotification.create(
        user_id=data.user_id,
        title=data.title,
        body=data.body
    )
    await push_notification.save()
    try:
        resp = messaging.send(message)
        return {"status": "sent", "response": resp}
    except Exception as e:
        raise HTTPException(500, f"Send error: {e}")


@router.get("/test_notification/")
async def test(user: User = Depends(get_current_user)):
#    print(f"Firebase JSON>>>>>>>>>>>>>>>>>>>>>>: {firebase_json}")
   deliveries = 42  # Example metrics or calculations

   await send_notification(NotificationIn(
        user_id=user.id,
        title="Test Notification",
        body=f"This is a test notification."
    ))
   

@router.put("/toggle_notifications/")
async def toggle_notifications(
    push_notification: Optional[bool] = Form(None),
    email_notification: Optional[bool] = Form(None), 
    user: User = Depends(get_current_user)):
    setting = await NotificationSetting.filter(user=user).first()
    if setting:
        if push_notification:
            setting.push_notification = push_notification
        if email_notification:
            setting.email_notification = email_notification
        await setting.save()
    else:
        await NotificationSetting.create(user=user, push_notification=push_notification, email_notification=email_notification)
    return {"status": "success", "push_notification": push_notification, "email_notification": email_notification}

@router.get("/notification_settings/")
async def get_notification_settings(user: User = Depends(get_current_user)):
    setting = await NotificationSetting.filter(user=user).first()
    if not setting:
        raise HTTPException(status_code=404, detail="Notification settings not found")
    return setting  # Default to enabled if no setting found
   

@router.get("/get_notifications/")
async def get_notifications(user: User = Depends(get_current_user)):
    notifications = await PushNotification.filter(user_id=user.id)
    return [n for n in notifications]


@router.get("/get-notification/{ntf_id}/")
async def get_notification(ntf_id:str, user: User = Depends(get_current_user)):
    notification = await PushNotification.filter(id=ntf_id).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")