from fastapi import APIRouter, Depends, HTTPException, status, Form, Request, Response, UploadFile, File, Query, Path
from pydantic import BaseModel
from app.utils.send_email import send_email
from applications.user.models import User, UserRole
from applications.admin.models import FAQ, ContactInfo, CustomerInfo, ServiceArea, JobManagementSettings, PaymentSettings
from app.token import get_current_user
from applications.customer.posts import PostRequest, Bid, InstallationSurface, StatusEnum, BidStatus
from applications.payments.models import Payment
from app.auth import login_required, role_required
from app.utils.file_manager import save_file
from typing import Optional
from datetime import datetime
from routes.communications.notifications import NotificationIn, send_notification
from tortoise.functions import Count
from enum import Enum
from tortoise.expressions import Q






router = APIRouter(tags=['Admin'])


@router.post("/faqs/")
async def create_faq(
    question: str = Form(...),
    answer: str = Form(...),
    user: User = Depends(role_required(UserRole.ADMIN))
    ):
    
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    
    faq = await FAQ.create(
        question=question,
        answer=answer
    )

    return {"faq": faq}

@router.get("/faqs/")
async def list_faqs(
    search_query: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1),
    user: User = Depends(get_current_user)
    ):
    
    query = FAQ.all()

    if search_query:
        query = query.filter(question__icontains=search_query)

    faqs = await query.offset(offset).limit(limit)

    return {"faqs": faqs}



@router.delete("/faqs/{faq_id}")
async def delete_faq(
    faq_id: str,
    user: User = Depends(role_required(UserRole.ADMIN))
    ):
    
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    
    faq = await FAQ.filter(id=faq_id).first()
    if not faq:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FAQ not found")
    
    await faq.delete()

    return {"detail": "FAQ deleted successfully"}


@router.get("/faqs/{faq_id}")
async def get_faq(
    faq_id: str,
    user: User = Depends(get_current_user)
    ):
    
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    
    faq = await FAQ.filter(id=faq_id).first()
    if not faq:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FAQ not found")
    
    return {"faq": faq}




@router.post("/contact-infos/")
async def create_contact_info(
    phone_number: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    user: User = Depends(role_required(UserRole.ADMIN))
    ):
    
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    
    contact_info = await ContactInfo.filter(admin_id=user.id).first()
    if contact_info:
        if phone_number:
            contact_info.phone_number = phone_number
        if email:
            contact_info.email = email
        await contact_info.save()
    else:
        contact_info = await ContactInfo.create(
            admin_id=user.id,
            phone_number=phone_number,
            email=email
        )

    return {"contact_info": contact_info}




@router.get("/contact-infos/")
async def get_contact_info(
    user: User = Depends(get_current_user)
    ):
    
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    
    contact_info = await ContactInfo.all().first()
    if not contact_info:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact info not found")
    
    return {"contact_info": contact_info}






@router.get("/recent-jobs/")
async def recent_job_list(
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1),
    user: User = Depends(role_required(UserRole.ADMIN))
    ):
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    jobs = await PostRequest.all().order_by("-updated_at", "-created_at").offset(offset).limit(limit)

    if not jobs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="jobs not found")
    
    return {"jobs": jobs}



@router.get("/recent-bids")
async def recent_bids_list(
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1),
    user: User = Depends(role_required(UserRole.ADMIN))
    ):
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    
    bids = await Bid.filter(status__in = [BidStatus.PENDING, BidStatus.ACCEPTED]).order_by("-updated_at", "-created_at").offset(offset).limit(limit)

    if not bids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bids not found")
    

    return {"bids": bids}





@router.post("/posts-admin/")
async def create_post_from_admin(
    cust_name: str = Form(...),
    cust_email: str = Form(...),
    cust_phone: str = Form(...),
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
    inst_ids: Optional[list[str]] = Form(None),
    user: User = Depends(role_required(UserRole.ADMIN))
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

    cust_info = await CustomerInfo.create(
        post_request_id = post.id,
        cust_name = cust_name,
        cust_email = cust_email,
        cust_phone = cust_phone
    )

    post.metadata = { "installers": inst_ids }
    await post.save()

    try:
        await send_email(subject="Your Pet Door Installation Job Has Been Created", to=cust_email, html_message=f"""<!DOCTYPE html>

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
                                    <p>Hi {cust_name},</p>

                                    <p>Your pet door installation request has been successfully created on your behalf.</p>

                                    <h3 style="margin-top:20px;">Job Details:</h3>
                                    <ul style="padding-left:20px;">
                                    <li><strong>Service:</strong> Pet Door Installation</li>
                                    <li><strong>Estimated Cost:</strong> ${price}</li>
                                    <li><strong>Job ID:</strong> {post.id}</li>
                                    </ul>

                                    <p style="margin-top:20px;">
                                    Our team will now review your request and notify installers. You will receive updates as soon as an installer responds.
                                    </p>

                                    <p>
                                    If you have any questions or want to make changes, feel free to contact us.
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
    except Exception as e:
        pass


    if inst_ids:
        for inst_id in inst_ids:
            try:
                await send_notification(NotificationIn(
                    user_id=inst_id,
                    title="New job assigned",
                    body=f"You have assigned a new job {post.id} . please accept the job",
                ))
            except Exception as e:
                pass


    return {"post": post, "cust_info": cust_info}



@router.get("/posts-admin/")
async def list_posts_from_admin(
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1),
    user: User = Depends(role_required(UserRole.INSTALLER, isGranted=True))
):
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    
    posts = await PostRequest.filter(
            metadata__contains={"installers": [user.id]},
            installer=None
        ).order_by("-updated_at", "-created_at").offset(offset).limit(limit)
    if not posts:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="posts not found")
    
    return {"posts": posts}




@router.post("/service-areas")
async def create_service_area(
    name: str = Form(...),
    user: User = Depends(role_required(UserRole.ADMIN))):
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    
    area = await ServiceArea.filter(name=name)

    if area:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Area already exist!")
    
    area = await ServiceArea.create(
        name = name
    )

    return area





@router.post("/job-management-settings")
async def job_management(
    auto_assign_job: Optional[bool] = Form(None),
    job_timeout_hours: Optional[int] = Form(None),
    user: User = Depends(role_required(UserRole.ADMIN))
    ):
    job_settings = await JobManagementSettings.filter().first()

    if job_settings:
        if auto_assign_job:
            job_settings.auto_assign_job = auto_assign_job
        if job_timeout_hours:
            job_settings.job_timeout_hours = job_timeout_hours
        
        await job_settings.save()

    else: 
        job_settings = await JobManagementSettings.create(
            auto_assign_job = auto_assign_job,
            job_timeout_hours = job_timeout_hours
        )

    return job_settings


@router.get("/job-management-settings")
async def get_job_management(
    user: User = Depends(role_required(UserRole.ADMIN))
    ):
    job_settings = await JobManagementSettings.filter().first()

    if not job_settings:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job settings not found")
    
    return job_settings




@router.post("/user-list")
async def get_user_list(
    user_role: UserRole = Form(...),
    user: User = Depends(role_required(UserRole.ADMIN))
    ):
    
    users = await User.filter(role=user_role)

    if not users:
        raise HTTPException(status_code=status.HTTP_204_NO_CONTENT, detail="There is no result")
    
    return users



@router.delete("/delete-user/{user_id}/")
async def delete_user(
    user_id: str = Path(...),
    user: User = Depends(role_required(UserRole.ADMIN))
):
    deleted_user = await User.get_or_none(id=user_id)

    if not deleted_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    await deleted_user.delete()

    return {"detail": "The user has been deleted successfully"}







@router.get("/post-stats")
async def post_statistics(
    user: User = Depends(role_required(UserRole.ADMIN))
):
    stats = await (
        PostRequest
        .annotate(count=Count("id"))
        .group_by("status")
        .values("status", "count")
    )

    result = {
        "new_job_count": 0,
        "pending_bid_count": 0,
        "installer_assigned_count": 0,
        "deu_count": 0,
    }

    for item in stats:
        if item["status"] == StatusEnum.PENDING:
            result["new_job_count"] = item["count"]
        elif item["status"] == StatusEnum.RECEIVING_BIDS:
            result["pending_bid_count"] = item["count"]
        elif item["status"] == StatusEnum.INSTALLER_ASSIGNED:
            result["installer_assigned_count"] = item["count"]
        elif item["status"] == StatusEnum.IN_PROGRESS:
            result["deu_count"] = item["count"]

    return result

class PaymentStype(str, Enum):
    cash = "cash"
    stripe = "stripe"

class PaymentStatus(str, Enum):
    pending = "pending"
    succeeded = "succeeded"
    faild = "faild"
    refunded = "refunded"

@router.get("/payment-history/")
async def payment_history(
    payment_type: Optional[PaymentStype] = Query(None),
    payment_status: Optional[PaymentStatus] = Query(None),
    user_id: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1),
    user: User = Depends(get_current_user)
):

    filters = Q()

    if payment_type:
        filters &= Q(payment_type=payment_type)

    if payment_status:
        filters &= Q(status=payment_status)

    if user_id:
        filters &= (Q(customer_id=user_id) | Q(installer_id=user_id))

    if start_date:
        filters &= Q(updated_at__gte=start_date)

    if end_date:
        filters &= Q(updated_at__lte=end_date)

    history = await Payment.filter(filters).offset(offset).limit(limit)

    return history



@router.get("/payment-settings/")
async def payment_settings(
    user: User = Depends(role_required(UserRole.ADMIN, UserRole.CUSTOMER))
    ):
    payment_setting = await PaymentSettings.filter().first()

    if not payment_setting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="payment settings not found")

    return payment_setting


@router.post("/payment-settings/")
async def payment_settings(
    new_status: bool = Form(...),
    user: User = Depends(role_required(UserRole.ADMIN))
    ):
    payment_setting = await PaymentSettings.filter().first()

    if payment_setting:
        payment_setting.status = new_status
        await PaymentSettings.save()
    else:
        payment_setting = await PaymentSettings.create(status=new_status)

    return payment_setting



