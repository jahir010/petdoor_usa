from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Form, UploadFile, File, Query
from tortoise.contrib.pydantic import pydantic_model_creator
from tortoise.expressions import Q
from tortoise.transactions import in_transaction

from app.auth import login_required, permission_required
from applications.user.models import User, UserRole
from app.utils.file_manager import update_file, delete_file

router = APIRouter(prefix="/users", tags=["Users"])

# Serializers
UserOut = pydantic_model_creator(User, name="UserOut", exclude=("password",))


async def serialize_user(user: User) -> Dict[str, Any]:
    await user.fetch_related(
        "groups",
        "user_permissions"
    )

    groups = await user.groups.all()
    permissions = await user.user_permissions.all()
    data = {
        "id": user.id,
        "email": user.email,
        "phone": user.phone,
        "name": user.name,
        "photo": user.photo,
        "role": user.role,
        "is_active": user.is_active,
        "is_suspended": user.is_suspended,
        "is_staff": user.is_staff,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "groups": [{"id": g.id, "name": g.name} for g in groups],
        "permissions": [{"id": p.id, "codename": p.codename, "name": p.name} for p in permissions],
    }

    return data


# CRUD endpoints
@router.get("/", response_model=Dict[str, Any])
async def list_users(
    offset: int = 0,
    limit: int = 20,
    role: Optional[UserRole] = Query(None),
    search: Optional[str] = None,
    user: User = Depends(login_required),
):
    query = User.exclude(id=user.id)
    if user.role != UserRole.ADMIN:
        query = query.exclude(role=UserRole.ADMIN)

    if role is not None:
        query = query.filter(role=role)

    if search:
        q = search.strip()
        query = query.filter(
            Q(name__icontains=q)
            | Q(email__icontains=q)
            | Q(phone__icontains=q)
        )

    # Total BEFORE pagination
    total = await query.count()
    users = await query.offset(offset).limit(limit)

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "count": len(users),
        "results": [await serialize_user(user) for user in users],
    }



@router.patch("/me/update-profile", response_model=Dict[str, Any])
async def update_profile(
    user: User = Depends(login_required),

    name: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
):
    update_data = {}

    if name is not None:
        update_data["name"] = name

    if phone is not None:
        update_data["phone"] = phone

    # Handle photo upload
    if photo:
        file_path = await update_file(photo, user.photo, "user_photo")
        update_data["photo"] = file_path

    if not update_data:
        raise HTTPException(status_code=400, detail="No valid fields provided")

    async with in_transaction():
        for field, value in update_data.items():
            setattr(user, field, value)
        await user.save()

    return await serialize_user(user)

@router.patch("/toggle-two-factor")
async def update_two_factor(
   user: User = Depends(login_required), 
):
    user.is_otp = not user.is_otp
    await user.save(update_fields=["is_otp"])
    return {
        "status": "success",
        "two_factor_enabled": user.is_otp,
        "two-factor": user.is_otp,
    }





@router.get("/me", response_model=Dict[str, Any])
async def get_user(user: User = Depends(login_required)):
    return await serialize_user(user)


@router.get("/details", response_model=Dict[str, Any], dependencies=[Depends(permission_required('view_user'))])
async def get_user_details_by_admin(
    user_id: Optional[str] = Query(None),
):
    user = await User.get_or_none(id=user_id)
    return await serialize_user(user)



@router.patch("/update-profile", response_model=Dict[str, Any], dependencies=[Depends(permission_required('update_user'))])
async def update_user_profile_by_admin(
    user_id: Optional[str] = Query(None),

    name: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
):
    user = await User.get_or_none(id=user_id)
    update_data = {}

    if name is not None:
        update_data["name"] = name

    if phone is not None:
        update_data["phone"] = phone

    # Handle photo upload
    if photo:
        file_path = await update_file(photo, user.photo, "user_photo")
        update_data["photo"] = file_path

    if not update_data:
        raise HTTPException(status_code=400, detail="No valid fields provided")

    async with in_transaction():
        for field, value in update_data.items():
            setattr(user, field, value)
        await user.save()

    return await serialize_user(user)





@router.patch("/role-management", response_model=Dict[str, Any], dependencies=[Depends(permission_required('update_user'))])
async def update_role_by_admin(
    user_id: Optional[str] = Query(None),
    role: Optional[UserRole] = Form(None),
):
    user = await User.filter(id=user_id).exclude(role=UserRole.ADMIN).first()
    if not user:
        raise HTTPException(status_code=400, detail="User not found")
    update_data = {}

    if role is not None:
        update_data["role"] = role

    if not update_data:
        raise HTTPException(status_code=400, detail="No valid fields provided")

    async with in_transaction():
        for field, value in update_data.items():
            setattr(user, field, value)
        await user.save()

    return await serialize_user(user)





@router.delete("/me/delete", response_model=Dict[str, Any])
async def delete_user(user: User = Depends(login_required)):
    async with in_transaction():
        await delete_file(user.photo)
        await user.delete()
        return {
            "details": "User deleted",
            "status": "success",
        }




@router.patch("/suspend", response_model=Dict[str, Any], dependencies=[Depends(permission_required("update_user"))])
async def toggle_user_suspend_status(
    user_id: Optional[str] = Query(..., description="User ID to suspend/unsuspend"),
):
    user = await User.get_or_none(id=user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    async with in_transaction():
        user.is_suspended = not user.is_suspended
        await user.save(update_fields=["is_suspended"])

    return {
        "details": "User suspended successfully"
        if user.is_suspended
        else "User unsuspended successfully",
        "status": "success",
        "is_suspended": user.is_suspended,
    }
