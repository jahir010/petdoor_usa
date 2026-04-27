from fastapi import APIRouter, Depends, HTTPException, status, Form, Request, Response, UploadFile, File, Query
from pydantic import BaseModel
from applications.user.models import User, UserRole
from app.token import get_current_user
from applications.customer.posts import PostRequest, Bid, InstallationSurface, StatusEnum
from applications.admin.models import CustomerInfo
from applications.installer.models import InstallerServiceArea
from routes.communications.notifications import send_notification, NotificationIn
from app.auth import login_required, role_required
from app.utils.file_manager import save_file
from app.utils.send_email import send_email
from typing import Optional, Dict, Any
from datetime import datetime
from tortoise.expressions import Q





router = APIRouter(tags=['Customer Posts'])



async def serialize_bid(bid: Bid) -> Dict[str, Any]:

    # print(bid)
    
    data = {
        "id": bid.id,
        "post_id": bid.post_request_id,
        "installer_id": bid.installer_id,
        "installer_name": bid.installer.name,
        "price" : bid.price,
        "status": bid.status,
        "note": bid.note,
        "created_at": bid.created_at,
        "updated_at": bid.updated_at
    }
    # print(data)

    return data


@router.post("/posts/")
async def create_post(
    pet_name: str = Form(...),
    pet_type: str = Form(...),
    price: float = Form(...),
    size: str = Form(...),
    installation_surface: InstallationSurface = Form(...),
    service_area_id: int = Form(...),
    address_line_1: str = Form(...),
    address_line_2: Optional[str] = Form(None),
    city: str = Form(...),
    state: str = Form(...),
    zip_code: str = Form(...),
    country: str = Form(...),
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
        address_line_1=address_line_1,
        address_line_2=address_line_2,
        city=city,
        state=state,
        zip_code=zip_code,
        country=country,
        photos=photo_urls
    )

    area_installers = await InstallerServiceArea.filter(area_id = service_area_id)


    for area in area_installers:
        #print(f"installer id: {area.installer_id}")
        try:
            await send_notification(NotificationIn(
                user_id=area.installer_id,
                title="New Job alert",
                body=f"New job afears id {post.id}. please accept it"
            ))

        except:
            pass

    return {"post": post}





@router.get("/posts/")
async def list_posts(
    new_status: StatusEnum | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1),
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
            .offset(offset)
            .limit(limit)
        )

        return {"posts": posts}

    # 🛠 INSTALLER
    elif user.role == UserRole.INSTALLER:

        areas = await InstallerServiceArea.filter(
            installer_id=user.id
        ).values_list("area_id", flat=True)

        query1 = Q(installer_id__isnull=True) & (Q(area_id__in=areas) | Q(metadata__contains={"installers": [user.id]}))
        query2 = Q(installer_id=user.id)

        if new_status:
            query1 &= Q(status=new_status)
            query2 &= Q(status=new_status)

        new_posts = await (
            PostRequest
            .filter(query1)
            .prefetch_related("customer")
            .order_by("-created_at")
            .offset(offset)
            .limit(limit)
        )

        assigned_post = await (
            PostRequest
            .filter(query2)
            .prefetch_related("customer")
            .order_by("-created_at")
            .offset(offset)
            .limit(limit)
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
    
    post = await PostRequest.filter(id=post_id).prefetch_related("customer", "installer").first()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    
    if post.installer:
        installer_name = post.installer.name
        return {"post": post, "installer_name": installer_name, "customer_name": post.customer.name}

    return {"post": post, "customer_name": post.customer.name}


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
    
    
    if post_id and user.role in [UserRole.CUSTOMER, UserRole.ADMIN]:
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
        bids = await Bid.filter(installer_id=user.id).prefetch_related("installer").order_by("-created_at")
        print("INSTALLER ALL BIDS:", bids)
        customer_name = ""
        customer_id = ""
        customer_photo= ''
        return {"bids": [await serialize_bid(bid) for bid in bids]}
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    return {"customer_id": customer_id, "customer_name": customer_name, "customer_photo": customer_photo, "post": post, "bids": [await serialize_bid(bid) for bid in bids]}




@router.post("/bid/{bid_id}/accept/")
async def accept_bid(
    bid_id: str,
    user: User = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    
    bid = await Bid.filter(id=bid_id).prefetch_related("installer").first()
    if not bid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bid not found")

    post = await PostRequest.filter(id=bid.post_request_id).first()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    
    price = post.price
    extra_cost = bid.price - price

    if post.customer_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    
    post.installer_id = bid.installer_id
    post.status = StatusEnum.INSTALLER_ASSIGNED
    post.price = bid.price
    post.assigned_at = datetime.now()

    await post.save()
    cust_info = await CustomerInfo.filter(post_request_id=post.id).first()

    try:
        await send_email(subject="Your Job Has Been Assigned", to=cust_info.cust_email, html_message=
                         f"""<!DOCTYPE html>

                            <html>
                            <head>
                            <meta charset="UTF-8">
                            </head>
                            <body style="margin:0; padding:0; font-family: Arial, sans-serif; background-color:#f4f4f4;">
                            <table align="center" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px; background:#ffffff; margin-top:20px; border-radius:8px; overflow:hidden;">

                            <tr>
                            <td style="background-color:#4CAF50; color:#ffffff; padding:20px; text-align:center; font-size:20px; font-weight:bold;">
                                Petdoorusa
                            </td>
                            </tr>

                            <tr>
                            <td style="padding:20px; color:#333333; font-size:15px; line-height:1.6;">
                                <p>Hi {cust_info.cust_name},</p>

                                <p>Your pet door installation job has now been officially assigned to an installer.</p>

                                <h3 style="margin-top:20px;">Job Details:</h3>
                                <ul style="padding-left:20px;">
                                <li><strong>Job ID:</strong> {post.id}</li>
                                <li><strong>Original Price:</strong> ${price:.2f}</li>
                                <li><strong>Additional Cost:</strong> ${extra_cost}</li>
                                <li><strong>Total Cost:</strong> ${post.price:.2f}</li>
                                <li><strong>Assigned Installer:</strong> {bid.installer.name}</li>
                                </ul>

                                <h3 style="margin-top:20px;">Reason:</h3>
                                <p>{bid.note}</p>

                                <p style="margin-top:20px;">
                                The installer will proceed with the job shortly and may contact you for final scheduling.
                                </p>

                                <p>
                                If you have any concerns or need assistance, please let us know.
                                </p>

                                <h3 style="margin-top:20px;">Installer Contact Information:</h3>
                                <ul style="padding-left:20px;">
                                <li><strong>Name:</strong> {bid.installer.name}</li>
                                <li><strong>Email:</strong> {bid.installer.email}</li>
                                <li><strong>Phone:</strong> {bid.installer.phone}</li>
                                </ul>

                                <p style="margin-top:30px;">
                                Best regards,<br>
                                <strong>Petdoorusa Team</strong>
                                </p>
                            </td>
                            </tr>

                            </table>
                            </body>
                            </html>
                            """)

    except:
        pass

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
    cust_info = await CustomerInfo.filter(post_request_id=post.id).first()

    print(f"post customer email: {cust_info.cust_email}")

    try:
        await send_email(subject="Your Job Has Been Accepted by an Installer", to=cust_info.cust_email, html_message=f"""<!DOCTYPE html>

                            <html>
                            <head>
                            <meta charset="UTF-8">
                            </head>
                            <body style="margin:0; padding:0; font-family: Arial, sans-serif; background-color:#f4f4f4;">
                            <table align="center" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px; background:#ffffff; margin-top:20px; border-radius:8px; overflow:hidden;">

                            <tr>
                            <td style="background-color:#4CAF50; color:#ffffff; padding:20px; text-align:center; font-size:20px; font-weight:bold;">
                                Petdorausa
                            </td>
                            </tr>

                            <tr>
                            <td style="padding:20px; color:#333333; font-size:15px; line-height:1.6;">
                                <p>Hi {cust_info.cust_name},</p>

                                <p><strong>Good news!</strong> Your pet door installation job has been accepted by an installer.</p>

                                <h3 style="margin-top:20px;">Job Details:</h3>
                                <ul style="padding-left:20px;">
                                <li><strong>Job ID:</strong> {post.id}</li>
                                <li><strong>Accepted Price:</strong> ${post.price}</li>
                                <li><strong>Installer:</strong> {user.name}</li>
                                </ul>

                                <p style="margin-top:20px;">
                                The installer will contact you soon to schedule the work.
                                </p>

                                <h3 style="margin-top:20px;">Installer Contact Information:</h3>
                                <ul style="padding-left:20px;">
                                <li><strong>Name:</strong> {user.name}</li>
                                <li><strong>Email:</strong> {user.email}</li>
                                <li><strong>Phone:</strong> {user.phone}</li>
                                </ul>

                                <p style="margin-top:20px;">
                                If you have any questions, feel free to reach out.
                                </p>

                                <p style="margin-top:30px;">
                                Best regards,<br>
                                <strong>Petdorausa Team</strong>
                                </p>
                            </td>
                            </tr>

                            </table>
                            </body>
                            </html>
                            """)
        
    except: 
        pass

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
            elif user.role in [UserRole.INSTALLER] and post.status in [StatusEnum.IN_PROGRESS, StatusEnum.INSTALLER_ASSIGNED, StatusEnum.INSTALLER_ASSIGNED] and new_status == StatusEnum.COMPLETED:
                update_fields["status"] = new_status
                user.total_earnings += post.price
                user.payable_commision_ammount += (post.price * 0.2)
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
        await user.save()

        return {"message": "Post updated successfully", "post": post}



@router.patch("/adjust-bid/{bid_id}/")
async def adjust_bid(
    bid_id: str ,
    price: float = Query(...),
    reason: Optional[str] = Query(None),
    user: User = Depends(role_required(UserRole.INSTALLER))
    ):
    
    bid = await Bid.get_or_none(id=bid_id)
    if not bid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bid not found")
    
    bid.price = price
    bid.note = reason
    await bid.save()

    post = await PostRequest.get(id=bid.post_request_id)

    try:
        await send_notification(NotificationIn(
            user_id=post.customer_id,
            title="bid adjustment",
            body=f"you got and bid adjustment for {post.id} of bid {bid.id}"
        ))
    except:
        pass

    return bid



