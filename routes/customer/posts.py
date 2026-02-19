from fastapi import APIRouter, Depends, HTTPException, status, Form, Request, Response, UploadFile, File, Query
from pydantic import BaseModel
from applications.user.models import User, UserRole
from app.token import get_current_user
from applications.customer.posts import PostRequest, Bid, InstallationSurface, StatusEnum
from applications.installer.models import InstallerServiceArea
from routes.communications.notifications import send_notification, NotificationIn
from app.auth import login_required, role_required
from app.utils.file_manager import save_file
from typing import Optional
from datetime import datetime
from tortoise.expressions import Q





router = APIRouter(tags=['Customer Posts'])




@router.post("/posts/")
async def create_post(
    pet_name: str = Form(...),
    pet_type: str = Form(...),
    price: float = Form(...),
    size: str = Form(...),
    installation_surface: InstallationSurface = Form(...),
    service_area_id: int = Form(...),
    address: str = Form(...),
    photos: list[UploadFile] = File(None),
    user: User = Depends(role_required(UserRole.CUSTOMER))
):
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    
    photo_urls = []
    if photos:
        for photo in photos:
            if photo.filename:
                file_url = await save_file(photo, upload_to="post_photos")
                photo_urls.append(file_url)



    post = await PostRequest.create(
        customer_id=user.id,
        pet_name=pet_name,
        pet_type=pet_type,
        price=price,
        size=size,
        installation_surface=installation_surface,
        area_id = service_area_id,
        Address=address,
        photos=photo_urls
    )

    area_installers = await InstallerServiceArea.filter(area_id = service_area_id)


    for area in area_installers:
        print(f"installer id: {area.installer_id}")
        try:
            await send_notification(NotificationIn(
                user_id=area.installer_id,
                title="New Job alert",
                body=f"New job afears id {post.id}. please accept it"
            ))

        except:
            pass

    return {"post": post}



# @router.get("/posts/")
# async def list_posts(
#     new_status: StatusEnum | None = Query(None),
#     user: User = Depends(get_current_user)
# ):
#     if not user:
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    
#     if user.role == UserRole.CUSTOMER:
#         filters = {"customer_id": user.id}
#     if user.role == UserRole.INSTALLER:
#         areas = await InstallerServiceArea.filter(installer_id = user.id).prefetch_related("area")
#         area_ids = []
#         for area in areas:
#             area_ids.append(area.area_id)
#         filters = {"area_id__in": area_ids}
#         filters["installer_id__in"] = [user.id, "null"]
#     if new_status:
#         filters["status"] = new_status

#     posts = await PostRequest.filter(**filters).prefetch_related("customer").order_by("-created_at")
#     return {"posts": posts}



# @router.get("/posts/")
# async def list_posts(
#     new_status: StatusEnum | None = Query(None),
#     user: User = Depends(get_current_user)
# ):
#     if not user:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Authentication required"
#         )

#     query = Q()

#     # 👤 CUSTOMER: only their own posts
#     if user.role == UserRole.CUSTOMER:
#         query &= Q(customer_id=user.id)
#         if new_status:
#             query &= Q(status=new_status)

#         posts = await (
#             PostRequest
#             .filter(query)
#             .prefetch_related("customer")
#             .order_by("-created_at")
#         )

#         return {"posts": posts}

#     # 🛠 INSTALLER: posts in their service areas
#     elif user.role == UserRole.INSTALLER:
#         areas = await InstallerServiceArea.filter(
#             installer_id=user.id
#         ).values_list("area_id", flat=True)

#         query1 &= (Q(area_id__in=areas) & Q(installer_id__isnull=True))
#         query2 &= Q(installer_id=user.id) 

#     if new_status:
#         query1 &= Q(status=new_status)
#         query2 &= Q(status=new_status)

#     new_posts = await (
#         PostRequest
#         .filter(query1)
#         .prefetch_related("customer")
#         .order_by("-created_at")
#     )
#     assigned_post = await (
#         PostRequest
#         .filter(query2)
#         .prefetch_related("customer")
#         .order_by("-created_at")
#     )

#     return {"new_posts": new_posts, "assigned_post": assigned_post}



@router.get("/posts/")
async def list_posts(
    new_status: StatusEnum | None = Query(None),
    user: User = Depends(get_current_user)
):
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )

    # 👤 CUSTOMER
    if user.role == UserRole.CUSTOMER:
        query = Q(customer_id=user.id)

        if new_status:
            query &= Q(status=new_status)

        posts = await (
            PostRequest
            .filter(query)
            .prefetch_related("customer")
            .order_by("-created_at")
        )

        return {"posts": posts}

    # 🛠 INSTALLER
    elif user.role == UserRole.INSTALLER:

        areas = await InstallerServiceArea.filter(
            installer_id=user.id
        ).values_list("area_id", flat=True)

        query1 = Q(area_id__in=areas) & Q(installer_id__isnull=True)
        query2 = Q(installer_id=user.id)

        if new_status:
            query1 &= Q(status=new_status)
            query2 &= Q(status=new_status)

        new_posts = await (
            PostRequest
            .filter(query1)
            .prefetch_related("customer")
            .order_by("-created_at")
        )

        assigned_post = await (
            PostRequest
            .filter(query2)
            .prefetch_related("customer")
            .order_by("-created_at")
        )

        return {
            "new_posts": new_posts,
            "assigned_post": assigned_post
        }

    # ❌ Other roles
    raise HTTPException(
        status_code=403,
        detail="Not authorized"
    )



@router.get("/posts/{post_id}/")
async def get_post(
    post_id: str,
    user: User = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    
    post = await PostRequest.filter(id=post_id).prefetch_related("customer").first()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    return {"post": post}


@router.post("/posts/{post_id}/bids/")
async def place_bid(
    post_id: str,
    price: float = Form(...),
    note: str = Form(None),
    user: User = Depends(role_required(UserRole.INSTALLER))
):
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    
    post = await PostRequest.filter(id=post_id).first()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    
    if post.status not in [StatusEnum.RECEIVING_BIDS, StatusEnum.PENDING]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bids are not being accepted for this post")

    bid = await Bid.create(
        post_request_id=post.id,
        installer_id=user.id,
        price=price,
        note=note
    )
    post.status = StatusEnum.RECEIVING_BIDS
    await post.save()

    try:
        await send_notification(NotificationIn(
            user_id=post.customer_id,
            title="New bid",
            body=f"you got bid of {bid.price} on {post.id}"
        ))

    except:
        pass

    return {"bid": bid}



@router.get("/posts-bids/")
async def list_bids(
    post_id: Optional[str] = Query(None),
    user: User = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    
    
    if post_id and user.role == UserRole.CUSTOMER:
        post = await PostRequest.filter(id=post_id, customer_id=user.id).prefetch_related("customer").first()
        if not post:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
        bids = await Bid.filter(post_request_id=post.id).prefetch_related("installer").order_by("-created_at")
        customer_name = post.customer.name
        customer_id = post.customer.id
        customer_photo= post.customer.photo
    elif post_id and user.role == UserRole.INSTALLER:
        print("INSTALLER BID LISTING FOR POST:", post_id, "USER ID:", user.id)
        post = await PostRequest.filter(id=post_id).prefetch_related("customer").first()
        print("FOUND POST:", post)
        if not post:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
        bids = await Bid.filter(post_request_id=post.id, installer_id=user.id).prefetch_related("installer").order_by("-created_at")
        customer_name = post.customer.name
        customer_id = post.customer.id
        customer_photo= post.customer.photo
    elif not post_id and user.role == UserRole.INSTALLER:
        print("INSTALLER ALL BIDS LISTING FOR USER ID:", user.id)
        bids = await Bid.filter(installer_id=user.id).prefetch_related("post_request__customer").order_by("-created_at")
        print("INSTALLER ALL BIDS:", bids)
        customer_name = ""
        customer_id = ""
        customer_photo= ''
        return {"bids": bids}
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    return {"customer_id": customer_id, "customer_name": customer_name, "customer_photo": customer_photo, "post": post, "bids": bids}




@router.post("/bid/{bid_id}/accept/")
async def accept_bid(
    bid_id: str,
    user: User = Depends(role_required(UserRole.CUSTOMER))
):
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    
    bid = await Bid.filter(id=bid_id).first()
    if not bid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bid not found")

    post = await PostRequest.filter(id=bid.post_request_id).first()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    if post.customer_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    
    post.installer_id = bid.installer_id
    post.status = StatusEnum.INSTALLER_ASSIGNED
    post.price = bid.price
    post.assigned_at = datetime.now()

    await post.save()

    try:
        await send_notification(NotificationIn(
            user_id=bid.installer_id,
            title="bid accepted",
            body=f"Your bid of {bid.price} has been accepted"
        ))

    except:
        pass

    return {"message": "Bid accepted successfully", "post": post}




@router.post("/post/{post_id}/accept/")
async def accept_post_without_bid(
    post_id: str,
    user: User = Depends(role_required(UserRole.INSTALLER))
):
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    
    post = await PostRequest.filter(id=post_id).prefetch_related("customer").first()

    
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    if post.status not in [StatusEnum.PENDING, StatusEnum.RECEIVING_BIDS]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Post cannot be accepted at this stage")

    post.installer_id = user.id
    post.status = StatusEnum.INSTALLER_ASSIGNED
    post.assigned_at = datetime.now()

    await post.save()

    try:
        await send_notification(NotificationIn(
            user_id=post.customer_id,
            title="Installer Assigned",
            body=f"Installer {user.name}"
        ))

    except:
        pass

    return {"message": "Post accepted without bid successfully", "post": post}




@router.patch("/posts/{post_id}/update/")
async def update_post(
    post_id: str,
    new_status: Optional[StatusEnum] = Form(None),
    scheduled_date: Optional[datetime] = Form(None),
    note: Optional[str] = Form(None),
    is_additional_service: Optional[bool] = Form(None),
    additional_service_note: Optional[str] = Form(None),
    is_customer_satisfied: Optional[bool] = Form(None),
    customer_satisfaction_note: Optional[str] = Form(None),
    user: User = Depends(get_current_user)
    ):
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
        
        post = await PostRequest.filter(id=post_id).first()
        if not post:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

        update_fields = {}
        if new_status is not None:
            if user.role == UserRole.INSTALLER and post.status == StatusEnum.INSTALLER_ASSIGNED and new_status == StatusEnum.IN_PROGRESS:
                update_fields["status"] = new_status
            elif user.role == UserRole.CUSTOMER and post.status in [StatusEnum.IN_PROGRESS, StatusEnum.INSTALLER_ASSIGNED] and new_status == StatusEnum.COMPLETED:
                update_fields["status"] = new_status
            else: 
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not allowed to change this status!")
        if scheduled_date is not None:
            update_fields["scheduled_date"] = scheduled_date
        if note is not None:
            update_fields["note"] = note
        if is_additional_service is not None:
            update_fields["is_additional_service"] = is_additional_service
        if additional_service_note is not None:
            update_fields["additional_service_note"] = additional_service_note
        if is_customer_satisfied is not None:
            update_fields["is_customer_satisfied"] = is_customer_satisfied
        if customer_satisfaction_note is not None:
            update_fields["customer_satisfaction_note"] = customer_satisfaction_note

        for field, value in update_fields.items():
            setattr(post, field, value)

        await post.save()

        return {"message": "Post updated successfully", "post": post}