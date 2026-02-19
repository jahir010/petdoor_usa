from fastapi import APIRouter, Depends, HTTPException, status, Form, Request, Response, UploadFile, File, Query, Path
from pydantic import BaseModel
from applications.user.models import User, UserRole
from applications.admin.models import FAQ, ContactInfo, CustomerInfo, ServiceArea, JobManagementSettings
from app.token import get_current_user
from applications.customer.posts import PostRequest, Bid, InstallationSurface, StatusEnum, BidStatus
from app.auth import login_required, role_required
from app.utils.file_manager import save_file
from typing import Optional
from datetime import datetime
from routes.communications.notifications import NotificationIn, send_notification






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
    address: str = Form(...),
    photos: list[UploadFile] = File(None),
    cust_ids: list[str] = Form(...),
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
        Address=address,
        photos=photo_urls
    )

    cust_info = await CustomerInfo.create(
        post_request_id = post.id,
        cust_name = cust_name,
        cust_email = cust_email,
        cust_phone = cust_phone
    )


    if cust_ids:
        for cust_id in cust_ids:
            try:
                await send_notification(NotificationIn(
                    user_id=cust_id,
                    title="New boj assined",
                    body=f"You have assigned a new job {post.id} . please accept the job",
                ))
            except Exception as e:
                pass


    return {"post": post, "cust_info": cust_info}




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

