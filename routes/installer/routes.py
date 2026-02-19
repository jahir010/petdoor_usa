from fastapi import APIRouter, Depends, HTTPException, status, Form, Request, Response, UploadFile, File, Query
from pydantic import BaseModel
from tortoise.functions import Sum, Avg, Count
from applications.user.models import User, UserRole
from app.token import get_current_user
from applications.customer.posts import PostRequest, Bid, InstallationSurface, StatusEnum
from applications.customer.models import InstallerReview
from applications.installer.models import AvailabilitySettings, InstallerServiceArea
from applications.admin.models import ServiceArea
from app.auth import login_required, role_required
from app.utils.file_manager import save_file
from typing import Optional, List
from datetime import datetime
from decimal import Decimal





router = APIRouter(tags=['Installer'])




#===============================================================
#                   Installer this month earnings Endpoint
#===============================================================



@router.get("/installer/earnings/")
async def get_installer_earnings(
    user: User = Depends(role_required(UserRole.INSTALLER))
    ):
    
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    
    today = datetime.now()
    start_of_month = datetime(today.year, today.month, 1)
    query = PostRequest.filter(
        installer_id = user.id,
        assigned_at__gte=start_of_month,
        assigned_at__lt=today
    )

    in_progress_count = await query.filter(status=StatusEnum.IN_PROGRESS).count()
    completed_count = await query.filter(status=StatusEnum.COMPLETED).count()

    result = await query.filter(
            status=StatusEnum.COMPLETED
        ).annotate(
            total=Sum("price")
        ).values("total")
    
    earnings = result[0]["total"] if result and result[0]["total"] else 0.0


    return {"installer_id": user.id, "in_progress_count": in_progress_count, "completed_count": completed_count, "earnings": earnings}







@router.get("/installer-ratings")
async def ratings(
    limit: int = Query(20, ge=1, le=100),
    skip: int = Query(0, ge=0),
    user: User = Depends(get_current_user)
):
    rows = await (
        InstallerReview
        .all()
        .annotate(
            total_rating=Sum("rating"),
            total_reviews=Count("id")
        )
        .group_by("installer_id")
        .offset(skip)
        .limit(limit)
        .values("installer_id", "total_rating", "total_reviews")
    )

    result = []
    for row in rows:
        avg = (
            row["total_rating"] / row["total_reviews"]
            if row["total_reviews"] > 0
            else 0
        )

        installer = await User.get_or_none(id=row["installer_id"])

        result.append({
            "installer_id": installer.id,
            "installer name": installer.name,
            "installer_photo": installer.photo,
            "average_rating": round(float(avg), 2),
            "total_reviews": row["total_reviews"]
        })

    # sort top-rated installers
    result.sort(key=lambda x: x["average_rating"], reverse=True)

    return result



@router.post("/installer-availability/")
async def availability(
    is_available: Optional[bool] = Form(None),
    week_hours: Optional[float] = Form(None),
    user: User = Depends(get_current_user)):
    available = await AvailabilitySettings.filter(installer_id = user.id).first()
    if available:
        if is_available:
            available.is_available = is_available
        if week_hours:
            available.active_hourse_par_week = week_hours
        await available.save()


    else:
        available = await AvailabilitySettings.create(
            installer_id = user.id,
            is_available=is_available,
            active_hourse_par_week = week_hours
        )

    return available




@router.get("/installer-availability-get/")
async def availability_get(
    user: User = Depends(get_current_user)):
    available = await AvailabilitySettings.filter(installer_id = user.id).first()

    if not available:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="There is no availablity exist")
    

    return available



#==============================================================
#           Installer Area
#==============================================================

class ServiceAreaUpdateSchema(BaseModel):
    area_ids: List[int]


@router.get("/service-areas")
async def list_service_areas(user: User = Depends(get_current_user)):
    areas = await ServiceArea.all().values("id", "name")
    return areas
    




@router.get("/installer/service-areas")
async def get_installer_service_areas(
    user: User = Depends(get_current_user)
):
    rows = await InstallerServiceArea.filter(
        installer=user
    ).prefetch_related("area").values("area_id", "area__name")

    return rows #[row["area_id"] for row in rows]




# @router.post("/installer/service-areas")
# async def update_service_areas(
#     payload: ServiceAreaUpdateSchema,
#     user: User = Depends(get_current_user)
# ):
#     # Remove old areas
#     await InstallerServiceArea.filter(installer=user).delete()

#     # Insert new areas
#     objects = [
#         InstallerServiceArea(
#             installer=user,
#             area_id=area_id
#         )
#         for area_id in payload.area_ids
#     ]

#     await InstallerServiceArea.bulk_create(objects)

#     return {"message": "Service areas updated successfully"}



@router.post("/installer/service-areas")
async def update_service_areas(
    payload: ServiceAreaUpdateSchema,
    user: User = Depends(get_current_user)
):
    # 1️⃣ Validate area IDs
    valid_area_ids = await ServiceArea.filter(
        id__in=payload.area_ids
    ).values_list("id", flat=True)

    valid_area_ids = set(valid_area_ids)

    invalid_ids = set(payload.area_ids) - valid_area_ids
    if invalid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid service area IDs: {list(invalid_ids)}"
        )

    # 2️⃣ Remove old areas
    await InstallerServiceArea.filter(installer=user).delete()

    # 3️⃣ Insert new areas
    objects = [
        InstallerServiceArea(
            installer=user,
            area_id=area_id
        )
        for area_id in valid_area_ids
    ]

    await InstallerServiceArea.bulk_create(objects)

    return {"message": "Service areas updated successfully"}





