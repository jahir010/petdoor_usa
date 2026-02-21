import asyncio
import json
import logging
from typing import Dict, Set, Optional, Tuple, List
from fastapi import WebSocket
from applications.user.models import User
from collections import defaultdict
from datetime import datetime, timedelta
from enum import Enum
import uuid
from tortoise.expressions import Q

logger = logging.getLogger(__name__)


class ConnectionPurpose(str, Enum):
    """Message purposes - prevents cross-contamination"""
    MESSAGING = "messaging"
    NOTIFICATIONS = "notifications"


class ClientType(str, Enum):
    """Valid client types"""
    INSTALLERS = "installers"
    CUSTOMERS = "customers"
    ADMINS = "admins"


class WSConnection:
    """Represents a single WebSocket connection with metadata"""

    def __init__(self, websocket: WebSocket, client_type: str, user_id: str, purpose: str):
        self.websocket = websocket
        self.client_type = client_type
        self.user_id = user_id
        self.purpose = purpose
        self.connected_at = datetime.utcnow()
        self.last_message_at = datetime.utcnow()
        self.message_count = 0
        self.is_active = True
        self.connection_id = str(uuid.uuid4())

    async def send_json(self, data: dict) -> bool:
        """Send JSON data through WebSocket"""
        try:
            await self.websocket.send_json(data)
            self.last_message_at = datetime.utcnow()
            self.message_count += 1
            return True
        except Exception as e:
            logger.error(f"Failed to send JSON: {str(e)}")
            self.is_active = False
            return False

    def to_dict(self) -> dict:
        """Serialize connection metadata"""
        return {
            "connection_id": self.connection_id,
            "client_type": self.client_type,
            "user_id": self.user_id,
            "purpose": self.purpose,
            "connected_at": self.connected_at.isoformat(),
            "last_message_at": self.last_message_at.isoformat(),
            "message_count": self.message_count
        }


class ProductionConnectionManager:
    """
    Enterprise-grade connection manager with database persistence.
    
    This manager:
    1. Stores all messages in database for offline users
    2. Delivers messages on reconnection
    3. Maintains chat session state in database
    4. Queues notifications for offline users
    5. Keeps location history for analytics
    6. Supports message edit, delete, reactions, image sending
    7. Persistent chat lists with sorting by recent activity
    """

    def __init__(self):
        # In-memory active connections
        # Structure: connections[purpose][client_type][user_id] = WSConnection
        self.connections: Dict[str, Dict[str, Dict[str, WSConnection]]] = {
            ConnectionPurpose.MESSAGING.value: {
                ClientType.INSTALLERS.value: {},
                ClientType.CUSTOMERS.value: {},
                ClientType.ADMINS.value: {}
            },
            ConnectionPurpose.NOTIFICATIONS.value: {
                ClientType.INSTALLERS.value: {},
                ClientType.CUSTOMERS.value: {},
                ClientType.ADMINS.value: {}
            }
        }

        # Active chats (cache, but methods query DB for accuracy)
        self.active_chats: Dict[str, Set[str]] = defaultdict(set)

        # Heartbeat tasks
        self.heartbeat_tasks: Dict[str, asyncio.Task] = {}

    async def connect(
        self,
        websocket: WebSocket,
        client_type: str,
        user_id: str,
        purpose: str,
        username: Optional[str] = None
    ) -> bool:
        """
        Accept and register a new WebSocket connection.
        Also delivers any offline messages/notifications.
        """
        try:
            # Validate inputs
            if client_type not in [ct.value for ct in ClientType]:
                logger.error(f"Invalid client_type: {client_type}")
                await websocket.close(code=4000, reason="Invalid client type")
                return False

            if purpose not in [cp.value for cp in ConnectionPurpose]:
                logger.error(f"Invalid purpose: {purpose}")
                await websocket.close(code=4001, reason="Invalid purpose")
                return False

            # Accept connection
            await websocket.accept()

            # Create connection object
            conn = WSConnection(websocket, client_type, str(user_id), purpose)

            # Store connection
            self.connections[purpose][client_type][str(user_id)] = conn

            logger.info(
                f"✓ Connected: {client_type}:{user_id} (Purpose: {purpose}) "
                f"[ID: {conn.connection_id}]"
            )

            # KEY: Deliver offline messages/notifications on reconnection
            if purpose == ConnectionPurpose.MESSAGING.value:
                await self._deliver_offline_messages(client_type, str(user_id), conn)
            elif purpose == ConnectionPurpose.NOTIFICATIONS.value:
                await self._deliver_offline_notifications(client_type, str(user_id), conn)

            # Start heartbeat
            await self._start_heartbeat(purpose, client_type, str(user_id))

            return True

        except Exception as e:
            logger.error(f"Connection failed: {str(e)}")
            return False

    async def _deliver_offline_messages(self, client_type: str, user_id: str, conn: WSConnection) -> None:
        """
        Get undelivered messages from database and send to reconnecting user.
        This replicates real apps like Uber, WhatsApp, Facebook Messenger.
        """
        try:
            from applications.communication.chat import ChatMessage

            # Get messages where user is recipient and not delivered
            offline_messages = await ChatMessage.filter(
                to_type=client_type,
                to_id=user_id,
                is_delivered=False
            ).order_by("created_at")

            if offline_messages:
                logger.info(f"Found {len(offline_messages)} offline messages for {client_type}:{user_id}")

                # Send all offline messages
                for msg in offline_messages:
                    payload = {
                        "type": ConnectionPurpose.MESSAGING.value,
                        "from_type": msg.from_type,
                        "from_id": msg.from_id,
                        "from_name": msg.from_name,
                        "text": msg.text if not msg.is_deleted else "This message was deleted",
                        "message_id": msg.message_id,
                        "timestamp": msg.created_at.isoformat(),
                        "edited_at": msg.edited_at.isoformat() if msg.edited_at else None,
                        "is_deleted": msg.is_deleted,
                        "reactions": msg.reactions,
                        "media_type": msg.media_type,
                        "media_url": msg.media_url,
                        "is_offline_message": True  # Mark as previously offline
                    }

                    success = await conn.send_json(payload)

                    if success:
                        # Mark as delivered
                        msg.is_delivered = True
                        await msg.save()
                        logger.info(f"Delivered offline message {msg.message_id}")

        except Exception as e:
            logger.error(f"Error delivering offline messages: {str(e)}")

    async def _deliver_offline_notifications(self, client_type: str, user_id: str, conn: WSConnection) -> None:
        """
        Get queued notifications and send to reconnecting user.
        """
        try:
            from applications.communication.chat import OfflineNotification

            # Get undelivered notifications
            notifications = await OfflineNotification.filter(
                to_type=client_type,
                to_id=user_id,
                is_delivered=False
            ).order_by("created_at")

            if notifications:
                logger.info(f"Found {len(notifications)} offline notifications for {client_type}:{user_id}")

                for notif in notifications:
                    payload = {
                        "type": ConnectionPurpose.NOTIFICATIONS.value,
                        "notification_id": notif.notification_id,
                        "title": notif.title,
                        "body": notif.body,
                        "data": notif.data,
                        "urgency": notif.urgency,
                        "timestamp": notif.created_at.isoformat(),
                        "is_offline_notification": True  # Mark as previously queued
                    }

                    success = await conn.send_json(payload)

                    if success:
                        notif.is_delivered = True
                        notif.delivered_at = datetime.utcnow()
                        await notif.save()
                        logger.info(f"Delivered offline notification {notif.notification_id}")

        except Exception as e:
            logger.error(f"Error delivering offline notifications: {str(e)}")

    async def _start_heartbeat(self, purpose: str, client_type: str, user_id: str) -> None:
        """Periodic heartbeat to detect dead connections"""
        task_key = f"{purpose}:{client_type}:{user_id}"

        async def heartbeat():
            try:
                while True:
                    await asyncio.sleep(60)  # Every 60 seconds
                    conn = self.get_connection(client_type, user_id, purpose)
                    if conn and conn.is_active:
                        try:
                            await conn.send_json({"type": "ping"})
                        except:
                            conn.is_active = False
                            break
                    else:
                        break
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Heartbeat error: {str(e)}")

        task = asyncio.create_task(heartbeat())
        self.heartbeat_tasks[task_key] = task

    def disconnect(self, client_type: str, user_id: str, purpose: Optional[str] = None) -> None:
        """
        Disconnect a user from one or all purposes.
        Does NOT delete chat history (it's in database).
        """
        try:
            user_id = str(user_id)
            if purpose:
                # Disconnect from specific purpose
                if (purpose in self.connections and
                    client_type in self.connections[purpose] and
                    user_id in self.connections[purpose][client_type]):
                    del self.connections[purpose][client_type][user_id]

                # Cancel heartbeat
                task_key = f"{purpose}:{client_type}:{user_id}"
                if task_key in self.heartbeat_tasks:
                    self.heartbeat_tasks[task_key].cancel()
                    del self.heartbeat_tasks[task_key]

                logger.info(f"✗ Disconnected: {client_type}:{user_id} (Purpose: {purpose})")
            else:
                # Disconnect from ALL purposes
                for p in [ConnectionPurpose.MESSAGING.value,
                          ConnectionPurpose.NOTIFICATIONS.value]:
                    if p in self.connections and client_type in self.connections[p]:
                        if user_id in self.connections[p][client_type]:
                            del self.connections[p][client_type][user_id]

                    task_key = f"{p}:{client_type}:{user_id}"
                    if task_key in self.heartbeat_tasks:
                        self.heartbeat_tasks[task_key].cancel()
                        del self.heartbeat_tasks[task_key]


                # Cleanup chats cache
                key = f"{client_type}:{user_id}"
                if key in self.active_chats:
                    for partner_key in list(self.active_chats[key]):
                        if partner_key in self.active_chats:
                            self.active_chats[partner_key].discard(key)

        except Exception as e:
            logger.error(f"Disconnect error: {str(e)}")

    def get_connection(
        self,
        client_type: str,
        user_id: str,
        purpose: str
    ) -> Optional[WSConnection]:
        """Get a specific connection"""
        try:
            return self.connections.get(purpose, {}).get(client_type, {}).get(str(user_id))
        except:
            return None

    async def send_to(
        self,
        message: dict,
        client_type: str,
        user_id: str,
        purpose: str
    ) -> bool:
        """
        Send message to a user.
        If user is offline, store in database for later delivery (for notifications only, messages handled separately).
        """
        try:
            user_id = str(user_id)
            conn = self.get_connection(client_type, user_id, purpose)

            if conn and conn.is_active:
                # User is online - send directly
                success = await conn.send_json(message)
                if not success:
                    self.disconnect(client_type, user_id, purpose)
                return success
            else:
                # User is offline - store only if notifications
                if purpose == ConnectionPurpose.NOTIFICATIONS.value:
                    await self._store_offline_notification(message, client_type, user_id)

                logger.info(f"User {client_type}:{user_id} offline - queued {purpose}")
                return True  # We stored it, so return success

        except Exception as e:
            logger.error(f"Send failed: {str(e)}")
            return False

    async def _store_offline_notification(self, message: dict, client_type: str, user_id: str) -> None:
        """Store notification in database for offline user"""
        try:
            from applications.communication.chat import OfflineNotification

            notif = OfflineNotification(
                to_type=client_type,
                to_id=user_id,
                notification_id=message.get("notification_id", str(uuid.uuid4())),
                title=message.get("title"),
                body=message.get("body"),
                data=message.get("data", {}),
                urgency=message.get("urgency", "normal"),
                is_delivered=False,
                expires_at=datetime.utcnow() + timedelta(days=30)
            )
            await notif.save()
            logger.info(f"Stored offline notification: {notif.notification_id}")

        except Exception as e:
            logger.error(f"Failed to store offline notification: {str(e)}")

    async def broadcast_to_type(
        self,
        message: dict,
        client_type: str,
        purpose: str
    ) -> Dict[str, bool]:
        """Broadcast to all users of a specific client type"""
        results = {}
        try:
            users = self.connections.get(purpose, {}).get(client_type, {})
            for user_id, conn in list(users.items()):
                if conn.is_active:
                    results[user_id] = await conn.send_json(message)
                    if not results[user_id]:
                        self.disconnect(client_type, user_id, purpose)
        except Exception as e:
            logger.error(f"Broadcast failed: {str(e)}")
        return results

    

    # ============================================================
    # CHAT SESSION MANAGEMENT
    # ============================================================

    async def start_chat(self, from_type: str, from_id: str, to_type: str, to_id: str) -> bool:
        """
        Start a new chat session between two users.
        Creates persistent session in database.
        """
        try:
            from applications.communication.chat import ChatSession

            from_key = f"{from_type}:{from_id}"
            to_key = f"{to_type}:{to_id}"

            # In-memory
            self.active_chats[from_key].add(to_key)
            self.active_chats[to_key].add(from_key)

            # Database (for persistence and reconnection detection)

            session = await ChatSession.filter(
                user1_type=from_type,
                user1_id=from_id,
                user2_type=to_type,
                user2_id=to_id
            ).first()
            if not session:
                session = await ChatSession.filter(
                    user1_type=to_type,
                    user1_id=to_id,
                    user2_type=from_type,
                    user2_id=from_id
                ).first()
            
            if session:
                session.is_active = True
                await session.save()

            else:
                session = await ChatSession.create(
                    user1_type=from_type,
                    user1_id=from_id,
                    user2_type=to_type,
                    user2_id=to_id,
                    defaults={
                        "is_active": True,
                        "last_message_at": datetime.utcnow()
                    }
                )


            logger.info(f"Chat session started: {from_key} <-> {to_key}")
            return True

        except Exception as e:
            logger.error(f"Failed to start chat: {str(e)}")
            return False

    async def end_chat(self, from_type: str, from_id: str, to_type: str, to_id: str) -> bool:
        """End a chat session (remove from chat list)"""
        try:
            from applications.communication.chat import ChatSession

            from_key = f"{from_type}:{from_id}"
            to_key = f"{to_type}:{to_id}"

            # In-memory cleanup
            if from_key in self.active_chats:
                self.active_chats[from_key].discard(to_key)
            if to_key in self.active_chats:
                self.active_chats[to_key].discard(from_key)

            # Database
            session = await ChatSession.get_or_none(
                user1_type=from_type,
                user1_id=from_id,
                user2_type=to_type,
                user2_id=to_id
            )

            if not session:
                session = await ChatSession.get_or_none(
                        user1_type=to_type,
                        user1_id=to_id,
                        user2_type=from_type,
                        user2_id=from_id
                    )

            if session:
                session.is_active = False
                session.ended_at = datetime.utcnow()
                await session.save()

            logger.info(f"Chat session ended: {from_key} <-> {to_key}")
            return {"status": True, "session_status": session.is_active}

        except Exception as e:
            logger.error(f"Failed to end chat: {str(e)}")
            return {"status": True}

    async def is_chatting_with(self, from_type: str, from_id: str, to_type: str, to_id: str) -> bool:
        """
        Check if two users have an actinstallersive chat session.
        Checks both in-memory and database.
        """
        try:
            from applications.communication.chat import ChatSession

            from_key = f"{from_type}:{from_id}"
            to_key = f"{to_type}:{to_id}"

            # Check in-memory first (faster)
            if to_key in self.active_chats.get(from_key, set()):
                return True

            # Check database (for reconnection scenarios)
            session = await ChatSession.get_or_none(
                user1_type=from_type,
                user1_id=from_id,
                user2_type=to_type,
                user2_id=to_id,
                is_active=True
            )

            if session:
                # Restore to in-memory cache
                self.active_chats[from_key].add(to_key)
                self.active_chats[to_key].add(from_key)
                return True

            return False

        except Exception as e:
            logger.error(f"Error checking chat status: {str(e)}")
            return False

    async def send_message(
        self,
        from_type: str,
        from_id: str,
        to_type: str,
        to_id: str,
        text: Optional[str] = None,
        from_name: str = None,
        media_type: Optional[str] = None,
        media_url: Optional[str] = None
    ) -> bool:
        """
        Send a message and store in database for persistence.
        Works whether recipient is online or offline.
        Automatically creates chat session if not exists.
        Supports text and images.
        """
        try:
            from applications.communication.chat import ChatMessage, ChatSession

            message_id = str(uuid.uuid4())

            print(f"from send message {message_id}")

            # Store in database
            msg = ChatMessage(
                from_type=from_type,
                from_id=from_id,
                from_name=from_name,
                to_type=to_type,
                to_id=to_id,
                text=text,
                message_id=message_id,
                is_delivered=False,
                is_read=False,
                media_type=media_type,
                media_url=media_url
            )
            await msg.save()

            # Find or create session
            session = await ChatSession.get_or_none(
                Q(user1_type=from_type, user1_id=from_id, user2_type=to_type, user2_id=to_id) |
                Q(user1_type=to_type, user1_id=to_id, user2_type=from_type, user2_id=from_id)
            )
            if not session:
                session = ChatSession(
                    user1_type=from_type,
                    user1_id=from_id,
                    user2_type=to_type,
                    user2_id=to_id,
                    is_active=True,
                    last_message_at=datetime.utcnow()
                )
            else:
                session.last_message_at = datetime.utcnow()
                session.is_active = True
            await session.save()

            # Update in-memory cache
            from_key = f"{from_type}:{from_id}"
            to_key = f"{to_type}:{to_id}"
            self.active_chats[from_key].add(to_key)
            self.active_chats[to_key].add(from_key)

            # Prepare payload
            payload = {
                "type": ConnectionPurpose.MESSAGING.value,
                "from_type": from_type,
                "from_id": from_id,
                "from_name": from_name,
                "text": text,
                "message_id": message_id,
                "timestamp": datetime.utcnow().isoformat(),
                "edited_at": None,
                "is_deleted": False,
                "reactions": {},
                "media_type": media_type,
                "media_url": media_url
            }
            print(f"after payload {payload}")

            # Send if online and mark delivered
            conn = self.get_connection(to_type, to_id, ConnectionPurpose.MESSAGING.value)
            if conn and conn.is_active:
                print(f"connetion active {conn}")
                success = await conn.send_json(payload)
                if success:
                    msg.is_delivered = True
                    await msg.save()
                else:
                    self.disconnect(to_type, to_id, ConnectionPurpose.MESSAGING.value)
                    return False
            # Offline: remains is_delivered=False, will deliver on connect

            return True

        except Exception as e:
            logger.error(f"Failed to send message: {str(e)}")
            return False

    async def edit_message(
        self,
        message_id: str,
        new_text: str,
        editor_type: str,
        editor_id: str
    ) -> bool:
        """Edit a message if sender"""
        try:
            from applications.communication.chat import ChatMessage

            msg = await ChatMessage.get_or_none(message_id=message_id)
            if not msg or msg.from_type != editor_type or msg.from_id != editor_id or msg.is_deleted:
                return False

            msg.text = new_text
            msg.edited_at = datetime.utcnow()
            await msg.save()

            # Send control to recipient
            conn = self.get_connection(msg.to_type, msg.to_id, ConnectionPurpose.MESSAGING.value)
            if conn and conn.is_active:
                await conn.send_json({
                    "type": "control",
                    "action": "edit",
                    "message_id": message_id,
                    "new_text": new_text,
                    "edited_at": msg.edited_at.isoformat()
                })

            return True

        except Exception as e:
            logger.error(f"Failed to edit message: {str(e)}")
            return False

    async def delete_message(
        self,
        message_id: str,
        deleter_type: str,
        deleter_id: str
    ) -> bool:
        """Delete a message if sender"""
        try:
            from applications.communication.chat import ChatMessage

            msg = await ChatMessage.get_or_none(message_id=message_id)
            if not msg or msg.from_type != deleter_type or msg.from_id != deleter_id:
                return False

            msg.is_deleted = True
            await msg.save()

            # Send control to recipient
            conn = self.get_connection(msg.to_type, msg.to_id, ConnectionPurpose.MESSAGING.value)
            if conn and conn.is_active:
                await conn.send_json({
                    "type": "control",
                    "action": "delete",
                    "message_id": message_id
                })

            return True

        except Exception as e:
            logger.error(f"Failed to delete message: {str(e)}")
            return False

    async def add_reaction(
        self,
        message_id: str,
        reaction: str,
        user_type: str,
        user_id: str
    ) -> bool:
        """Add reaction to message"""
        try:
            from applications.communication.chat import ChatMessage

            msg = await ChatMessage.get_or_none(message_id=message_id)
            if not msg:
                return False

            user_key = f"{user_type}:{user_id}"
            if reaction not in msg.reactions:
                msg.reactions[reaction] = []
            if user_key not in msg.reactions[reaction]:
                msg.reactions[reaction].append(user_key)
            await msg.save()

            # Send control to both (if online)
            for t, i in [(msg.from_type, msg.from_id), (msg.to_type, msg.to_id)]:
                if t == user_type and i == user_id:
                    continue  # Skip sender
                conn = self.get_connection(t, i, ConnectionPurpose.MESSAGING.value)
                if conn and conn.is_active:
                    await conn.send_json({
                        "type": "control",
                        "action": "react",
                        "message_id": message_id,
                        "reaction": reaction,
                        "user": user_key
                    })

            return True

        except Exception as e:
            logger.error(f"Failed to add reaction: {str(e)}")
            return False

    async def remove_reaction(
        self,
        message_id: str,
        reaction: str,
        user_type: str,
        user_id: str
    ) -> bool:
        """Remove reaction from message"""
        try:
            from applications.communication.chat import ChatMessage

            msg = await ChatMessage.get_or_none(message_id=message_id)
            if not msg:
                return False

            user_key = f"{user_type}:{user_id}"
            if reaction in msg.reactions and user_key in msg.reactions[reaction]:
                msg.reactions[reaction].remove(user_key)
                if not msg.reactions[reaction]:
                    del msg.reactions[reaction]
                await msg.save()

                # Send control to both
                for t, i in [(msg.from_type, msg.from_id), (msg.to_type, msg.to_id)]:
                    if t == user_type and i == user_id:
                        continue
                    conn = self.get_connection(t, i, ConnectionPurpose.MESSAGING.value)
                    if conn and conn.is_active:
                        await conn.send_json({
                            "type": "control",
                            "action": "remove_react",
                            "message_id": message_id,
                            "reaction": reaction,
                            "user": user_key
                        })

            return True

        except Exception as e:
            logger.error(f"Failed to remove reaction: {str(e)}")
            return False

    async def send_notification(
        self,
        to_type: str,
        to_id: str,
        title: str,
        body: str,
        data: dict = None,
        urgency: str = "normal"
    ) -> bool:
        """Send notification to user (offline or online)"""
        try:
            notification_id = str(uuid.uuid4())

            message = {
                "type": ConnectionPurpose.NOTIFICATIONS.value,
                "notification_id": notification_id,
                "title": title,
                "body": body,
                "data": data or {},
                "urgency": urgency,
                "timestamp": datetime.utcnow().isoformat()
            }

            conn = self.get_connection(to_type, to_id, ConnectionPurpose.NOTIFICATIONS.value)
            if conn and conn.is_active:
                success = await conn.send_json(message)
                return success
            else:
                await self._store_offline_notification(message, to_type, to_id)
                return True

        except Exception as e:
            logger.error(f"Failed to send notification: {str(e)}")
            return False

    async def get_chat_partners(self, client_type: str, user_id: str) -> List[Dict]:
        """Get all active chat partners for a user, sorted by recent activity"""
        try:
            from applications.communication.chat import ChatSession

            sessions = await ChatSession.filter(
                (Q(user1_type=client_type, user1_id=user_id) | Q(user2_type=client_type, user2_id=user_id)) &
                Q(is_active=True)
            ).order_by("-last_message_at")

            result = []
            for s in sessions:
                if s.user1_type == client_type and s.user1_id == user_id:
                    user = await User.get(id=s.user2_id)
                    result.append({
                        "type": s.user2_type,
                        "id": s.user2_id,
                        "user_name": user.name,
                        "last_message_at": s.last_message_at.isoformat() if s.last_message_at else None
                    })
                else:
                    user = await User.get(id=s.user1_id)
                    result.append({
                        "type": s.user1_type,
                        "id": s.user1_id,
                        "user_name": user.name,
                        "last_message_at": s.last_message_at.isoformat() if s.last_message_at else None
                    })

            return result

        except Exception as e:
            logger.error(f"Error getting chat partners: {str(e)}")
            return []

    def get_active_users(self, client_type: str = None, purpose: str = None) -> Dict:
        """Get statistics about active connections"""
        result = {}

        if purpose:
            purposes = [purpose]
        else:
            purposes = [cp.value for cp in ConnectionPurpose]

        for p in purposes:
            if client_type:
                users = self.connections.get(p, {}).get(client_type, {})
                result[f"{p}:{client_type}"] = list(users.keys())
            else:
                for ct in [ClientType.INSTALLERS.value, ClientType.CUSTOMERS.value, ClientType.ADMINS.value]:
                    users = self.connections.get(p, {}).get(ct, {})
                    result[f"{p}:{ct}"] = list(users.keys())

        return result

    def get_stats(self) -> dict:
        """Get connection statistics"""
        stats = {
            "total_active_connections": 0,
            "by_purpose": {},
            "by_client_type": {},
            "active_chats": len(self.active_chats),
            "heartbeat_tasks": len(self.heartbeat_tasks)
        }

        for purpose in [cp.value for cp in ConnectionPurpose]:
            purpose_count = 0
            for client_type in [ClientType.INSTALLERS.value, ClientType.CUSTOMERS.value, ClientType.ADMINS.value]:
                count = len(self.connections.get(purpose, {}).get(client_type, {}))
                purpose_count += count

                key = f"{client_type}"
                if key not in stats["by_client_type"]:
                    stats["by_client_type"][key] = 0
                stats["by_client_type"][key] += count

            stats["by_purpose"][purpose] = purpose_count
            stats["total_active_connections"] += purpose_count

        return stats


# Global instance
manager = ProductionConnectionManager()




