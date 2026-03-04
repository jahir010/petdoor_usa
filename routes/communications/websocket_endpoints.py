from fastapi import APIRouter, WebSocket, Depends
from app.auth import login_required
from starlette.websockets import WebSocketDisconnect
from app.utils.websocket_manager import manager, ConnectionPurpose, ClientType
from app.redis import get_redis
import json
import logging
import asyncio
from datetime import datetime 
from applications.communication.chat import *
from applications.user.models import User
from app.token import get_current_user
from tortoise.expressions import Q


logger = logging.getLogger(__name__)

router = APIRouter(tags=['WebSocket'])



# ============================================================================
# PURPOSE 2: MESSAGING (with persistence and offline support)
# ============================================================================

@router.websocket("/ws/chat/{client_type}/{user_id}")
async def chat_endpoint(
    websocket: WebSocket,
    client_type: str,
    user_id: str,
    redis=Depends(get_redis)
):
    """
    Direct messaging with offline support.
    
    ✓ Messages persist in database
    ✓ Offline messages delivered on reconnection
    ✓ Chat sessions persist (no auto-disappear)
    ✓ Works like Uber, WhatsApp, Facebook
    
    Message format (send):
    {
        "action": "send",
        "to_type": "customers",
        "to_id": "456",
        "text": "Hello!",
        "from_name": "John",
        "media_type": "image",  # optional
        "media_url": "https://..."  # optional
    }
    
    For edit:
    {
        "action": "edit",
        "message_id": "uuid",
        "new_text": "Updated text"
    }
    
    For delete:
    {
        "action": "delete",
        "message_id": "uuid"
    }
    
    For react:
    {
        "action": "react",
        "message_id": "uuid",
        "reaction": "👍"
    }
    
    For remove react:
    {
        "action": "remove_react",
        "message_id": "uuid",
        "reaction": "👍"
    }
    
    Message received:
    {
        "type": "messaging",
        "from_type": "riders",
        "from_id": "123",
        "from_name": "John Rider",
        "text": "Hello!",
        "timestamp": "2025-12-08T...",
        "message_id": "uuid",
        "edited_at": null,
        "is_deleted": false,
        "reactions": {},
        "media_type": null,
        "media_url": null,
        "is_offline_message": false
    }
    
    Control received:
    {
        "type": "control",
        "action": "edit/delete/react/remove_react",
        ...
    }
    """
    
    # Validate client type
    valid_types = {
        ClientType.INSTALLERS.value,
        ClientType.CUSTOMERS.value,
        ClientType.ADMINS.value
    }

    if client_type not in valid_types:
        await websocket.close(code=4000, reason="Invalid client type")
        return

    # Connect to manager
    # ⭐ This will automatically deliver offline messages
    connected = await manager.connect(
        websocket,
        client_type,
        user_id,
        ConnectionPurpose.MESSAGING.value
    )

    if not connected:
        return

    try:
        while True:
            data = await websocket.receive_json()

            action = data.get("action", "send")

            if action == "send":
                # Extract message details
                to_type = data.get("to_type")
                to_id = data.get("to_id")
                text = data.get("text")
                from_name = data.get("from_name", str(user_id))
                media_type = data.get("media_type")
                media_url = data.get("media_url")

                # Validate input
                if not (text or (media_type and media_url)) or not to_type or not to_id:
                    await websocket.send_json({
                        "error": "Missing required fields",
                        "required": ["to_type", "to_id", "text or media_url"]
                    })
                    continue

                to_id = str(to_id)

                # Send message (auto-creates session if needed)
                success = await manager.send_message(
                    client_type,
                    user_id,
                    to_type,
                    to_id,
                    text,
                    from_name,
                    media_type,
                    media_url
                )

                print(success)

                if success:
                    # Publish to Redis for real-time analytics
                    await redis.publish(f"chat:{to_type}:{to_id}", json.dumps({
                        "from_type": client_type,
                        "from_id": user_id,
                        "text": text
                    }))

                    await websocket.send_json({
                        "status": "sent",
                        "message_id": data.get("message_id")
                    })
                else:
                    await websocket.send_json({"error": "Failed to send message"})

            elif action == "edit":
                message_id = data.get("message_id")
                new_text = data.get("new_text")
                if not message_id or not new_text:
                    await websocket.send_json({"error": "Missing fields for edit"})
                    continue
                success = await manager.edit_message(message_id, new_text, client_type, user_id)
                await websocket.send_json({"status": "edited" if success else "error"})

            elif action == "delete":
                message_id = data.get("message_id")
                if not message_id:
                    await websocket.send_json({"error": "Missing message_id"})
                    continue
                success = await manager.delete_message(message_id, client_type, user_id)
                await websocket.send_json({"status": "deleted" if success else "error"})

            elif action == "react":
                message_id = data.get("message_id")
                reaction = data.get("reaction")
                if not message_id or not reaction:
                    await websocket.send_json({"error": "Missing fields for react"})
                    continue
                success = await manager.add_reaction(message_id, reaction, client_type, user_id)
                await websocket.send_json({"status": "reacted" if success else "error"})

            elif action == "remove_react":
                message_id = data.get("message_id")
                reaction = data.get("reaction")
                if not message_id or not reaction:
                    await websocket.send_json({"error": "Missing fields for remove_react"})
                    continue
                success = await manager.remove_reaction(message_id, reaction, client_type, user_id)
                await websocket.send_json({"status": "reaction_removed" if success else "error"})

            else:
                await websocket.send_json({"error": "Unknown action"})

    except WebSocketDisconnect:
        manager.disconnect(client_type, user_id, ConnectionPurpose.MESSAGING.value)
        logger.info(f"Chat connection closed: {client_type}:{user_id}")

    except Exception as e:
        logger.error(f"Chat error: {str(e)}")
        manager.disconnect(client_type, user_id, ConnectionPurpose.MESSAGING.value)


# ============================================================================
# PURPOSE 3: NOTIFICATIONS (with offline queueing)
# ============================================================================

@router.websocket("/ws/notifications/{client_type}/{user_id}")
async def notifications_endpoint(
    websocket: WebSocket,
    client_type: str,
    user_id: str,
    redis=Depends(get_redis)
):
    """
    Real-time notifications with offline queueing.
    
    ✓ Notifications queued if user offline
    ✓ Delivered on reconnection
    ✓ Works like Firebase Cloud Messaging
    
    Notification received:
    {
        "type": "notifications",
        "notification_id": "uuid",
        "title": "Order Update",
        "body": "Your order has been accepted",
        "data": {"order_id": "12345"},
        "urgency": "normal",
        "timestamp": "2025-12-08T...",
        "is_offline_notification": false
    }
    """
    
    # Validate client type
    valid_types = {
        ClientType.INSTALLERS.value,
        ClientType.CUSTOMERS.value,
        ClientType.ADMINS.value
    }

    if client_type not in valid_types:
        await websocket.close(code=4000, reason="Invalid client type")
        return

    # Connect to manager
    # This will automatically deliver offline notifications
    connected = await manager.connect(
        websocket,
        client_type,
        user_id,
        ConnectionPurpose.NOTIFICATIONS.value
    )

    if not connected:
        return

    try:
        # Notification connections are mostly receive-only
        # Keep alive while receiving
        while True:
            try:
                # Timeout to detect disconnects
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=300.0  # 5 minute timeout
                )

                # Handle ping/pong
                if data:
                    try:
                        msg = json.loads(data)
                        if msg.get("type") == "pong":
                            logger.debug(f"Pong from {client_type}:{user_id}")
                    except json.JSONDecodeError:
                        pass

            except asyncio.TimeoutError:
                # Periodically send ping
                try:
                    await websocket.send_json({
                        "type": "ping",
                        "timestamp": datetime.utcnow().isoformat()
                    })
                except:
                    break

    except WebSocketDisconnect:
        manager.disconnect(client_type, user_id, ConnectionPurpose.NOTIFICATIONS.value)
        logger.info(f"Notification connection closed: {client_type}:{user_id}")

    except Exception as e:
        logger.error(f"Notification error: {str(e)}")
        manager.disconnect(client_type, user_id, ConnectionPurpose.NOTIFICATIONS.value)


# ============================================================================
# MANAGEMENT ENDPOINTS (HTTP) - Chat Session Management
# ============================================================================

@router.post("/chat/start/{from_type}/{from_id}/{to_type}/{to_id}", dependencies=[Depends(login_required)])
async def start_chat(from_type: str, from_id: str, to_type: str, to_id: str):
    """
    Start a new chat session between two users.
    This persists in database so chat doesn't disappear on disconnect.
    
    ✓ Creates persistent database record
    ✓ Can reconnect and continue conversation
    ✓ Message history preserved
    """
    success = await manager.start_chat(from_type, from_id, to_type, to_id)
    if success:
        return {"status": "chat_started", "from": f"{from_type}:{from_id}", "to": f"{to_type}:{to_id}"}
    return {"error": "Failed to start chat"}


@router.post("/chat/end/{from_type}/{from_id}/{to_type}/{to_id}", dependencies=[Depends(login_required)])
async def end_chat(from_type: str, from_id: str, to_type: str, to_id: str):
    """End a chat session (remove from list)"""
    success = await manager.end_chat(from_type, from_id, to_type, to_id)
    if success:
        return success
    return {"error": "Failed to end chat"}


@router.get("/chat/history/{from_type}/{from_id}/{to_type}/{to_id}", dependencies=[Depends(login_required)])
async def get_chat_history(
    from_type: str,
    from_id: str,
    to_type: str,
    to_id: str,
    limit: int = 50
):
    """
    Get message history with another user.
    ✓ Works whether users are online or offline
    ✓ Shows all previous messages
    ✓ Like WhatsApp chat history
    """
    try:
        messages = await ChatMessage.filter(
            Q(
                from_type=from_type,
                from_id=from_id,
                to_type=to_type,
                to_id=to_id
            ) | Q(
                from_type=to_type,
                from_id=to_id,
                to_type=from_type,
                to_id=from_id
            )
        ).order_by("-created_at").limit(limit)

        return {
            "messages": [
                { 
                    "message_id": m.message_id,
                    "from_type": m.from_type,
                    "from_id": m.from_id,
                    "from_name": m.from_name,
                    "text": m.text if not m.is_deleted else "This message was deleted",
                    "timestamp": m.created_at.isoformat(),
                    "edited_at": m.edited_at.isoformat() if m.edited_at else None,
                    "is_deleted": m.is_deleted,
                    "reactions": m.reactions,
                    "media_type": m.media_type,
                    "media_url": m.media_url,
                    "is_read": m.is_read
                }
                for m in reversed(messages)
            ]
        }

    except Exception as e:
        logger.error(f"Error getting chat history: {str(e)}")
        return {"error": str(e)}


@router.get("/chat/partners/{client_type}/{user_id}", dependencies=[Depends(login_required)])
async def get_chat_partners(client_type: str, user_id: str):
    """Get all active chat partners for a user, sorted by recent"""
    partners = await manager.get_chat_partners(client_type, user_id)
    return {"partners": partners}



@router.get("/stats", dependencies=[Depends(login_required)])
async def get_stats():
    """Get connection statistics"""
    return manager.get_stats()


@router.get("/active-users", dependencies=[Depends(login_required)])
async def get_active_users(client_type: str = None, purpose: str = None):
    """Get list of active users"""
    return manager.get_active_users(client_type, purpose)


@router.post("/notifications/send/{to_type}/{to_id}", dependencies=[Depends(login_required)])
async def send_notification(
    to_type: str,
    to_id: str,
    title: str,
    body: str,
    data: dict = None,
    urgency: str = "normal"
):
    """
    Send a notification to a user.
    ✓ Queued if offline
    ✓ Delivered immediately if online
    ✓ Delivered on reconnection if offline
    """
    success = await manager.send_notification(
        to_type,
        to_id,
        title,
        body,
        data,
        urgency
    )

    if success:
        return {"status": "notification_sent"}
    return {"error": "Failed to send notification"}


@router.post("/notifications/broadcast/{to_type}", dependencies=[Depends(login_required)])
async def broadcast_notification(
    to_type: str,
    title: str,
    body: str,
    data: dict = None,
    urgency: str = "normal"
):
    """Broadcast a notification to all users of a type"""
    results = await manager.broadcast_to_type(
        {
            "type": "notifications",
            "title": title,
            "body": body,
            "data": data or {},
            "urgency": urgency
        },
        to_type,
        "notifications"
    )

    return {
        "status": "broadcast_sent",
        "total": len(results),
        "successful": sum(1 for v in results.values() if v)
    }




# ============================================================================
# UTILITY ENDPOINTS
# ============================================================================

@router.get("/chat/unread/{client_type}/{user_id}", dependencies=[Depends(login_required)])
async def get_unread_messages(client_type: str, user_id: str):
    """Get count of unread messages"""
    try:
        unread_count = await ChatMessage.filter(
            to_type=client_type,
            to_id=user_id,
            is_read=False
        ).count()

        return {"unread_count": unread_count}

    except Exception as e:
        logger.error(f"Error getting unread count: {str(e)}")
        return {"error": str(e)}


@router.post("/chat/mark-read/{to_type}/{to_id}/{from_type}/{from_id}", dependencies=[Depends(login_required)])
async def mark_messages_read(to_type: str, to_id: str, from_type: str, from_id: str):
    """Mark all messages from a sender as read"""
    try:
        await ChatMessage.filter(
            to_type=to_type,
            to_id=to_id,
            from_type=from_type,
            from_id=from_id,
            is_read=False
        ).update(is_read=True)

        return {"status": "marked_read"}

    except Exception as e:
        logger.error(f"Error marking read: {str(e)}")
        return {"error": str(e)}




