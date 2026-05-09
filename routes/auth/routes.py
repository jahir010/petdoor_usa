from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Form, Request, Response
from pydantic import BaseModel
from pydantic import EmailStr
from fastapi.security import OAuth2PasswordRequestForm
from passlib.context import CryptContext

from app.config import settings
from applications.user.models import User, UserRole
from app.token import get_current_user, create_access_token, create_refresh_token
from tortoise.contrib.pydantic import pydantic_model_creator
from app.utils.otp_manager import generate_otp, verify_otp, verify_session_key
import re

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def detect_input_type(value: str) -> str:
    value = value.strip()
    email_regex = r'^[\w\.-]+@[\w\.-]+\.\w+$'

    if re.match(email_regex, value):
        return 'email'
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Email address.")


class OAuth2EmailPasswordForm:
    def __init__(
            self,
            email: EmailStr = Form(...),
            password: str = Form(...),
            scope: str = Form(""),
            client_id: str = Form(None),
            client_secret: str = Form(None),
    ):
        self.email = email
        self.password = password
        self.scopes = scope.split()
        self.client_id = client_id
        self.client_secret = client_secret


User_Pydantic = pydantic_model_creator(User, name="User")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


@router.post("/login_auth2/", response_model=TokenResponse)
async def login_auth2(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await User.get_or_none(email=form_data.username)  # <- use username as email
    if not user or not pwd_context.verify(form_data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_data = {
        "sub": str(user.id),
        "is_active": user.is_active,
        "role": user.role,
        "is_staff": user.is_staff,
    }

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post(
    "/login",
    description="""
### 🔐 Test User Accounts

Use the following **test credentials** to explore the API based on different roles.

---

#### 👑 **Admin User**
- **Email:** `admin@gmail.com`  
- **Password:** `admin`  
- **Role:** ADMIN  
- **Flags:** Staff  

---

#### 🧑‍💼 **Installer Users**
- **Email examples:** `user1@example.com`, `user2@example.com`, ... (all installers)  
- **Password:** `installer`  
- **Role:** INSTALLER  
- **Flags:** Staff  

---

#### 🧑‍💻 **Customer Users**
- **Email examples:** `customer1@gmail.com`, `customer2@gmail.com`, `user3@example.com`, ... (all customers)  
- **Password:** `customer`  
- **Role:** CUSTOMER  

---

⚠️ **Note:** These credentials are for **testing purposes only**. All installer users share the same password (`installer`), all customer users share the same password (`customer`), and the admin uses `admin`.
"""
)
async def login(
    email: str = Form(...),
    password: str = Form(...),
    otp_value: Optional[str] = None
):
    lookup_field = await detect_input_type(email)

    if lookup_field == "email":
        user = await User.get_or_none(email=email)
        if not user or not pwd_context.verify(password, user.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )

        if user.is_otp:
            if otp_value is None:
                try:
                    otp = await generate_otp(email, "login")
                except HTTPException:
                    raise
                except Exception:
                    raise HTTPException(status_code=500, detail="Failed to generate OTP")

                return {
                    "status": "success",
                    "details": "OTP required.",
                    "message": (
                        f"OTP sent to {email}. Expires in 1 minute."
                        f"{f' OTP: {otp}' if settings.DEBUG else ''}"
                    ),
                    "purpose": "login",
                }
            try:
                await verify_otp(email, otp_value, "login")
            except Exception:
                raise HTTPException(
                    status_code=400,
                    detail="OTP verification failed. Enter correct OTP.",
                )

        token_data = {
            "sub": str(user.id),
            "is_active": user.is_active,
            "role": user.role,
            "is_staff": user.is_staff,
        }

        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "role": user.role,
        }
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid credentials")


@router.post("/send_otp")
async def send_otp(
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    purpose: str = Form("signup", description="""signup, installer_signup, forgot_password, update_email"""),
):
    key_type = await detect_input_type(email)
    if key_type != "email":
        raise HTTPException(status_code=400, detail="Invalid email")

    user = await User.get_or_none(email=email)
    SIGNUP_PURPOSES = {"signup", "installer_signup"}
    FORGOT_PURPOSES = {"forgot_password", "update_email"}


    # Purpose validation
    if purpose in SIGNUP_PURPOSES:
        if user:
            raise HTTPException(
                status_code=400,
                detail="Email already registered. Please login.",
            )

    elif purpose in FORGOT_PURPOSES:
        if not user:
            raise HTTPException(
                status_code=400,
                detail="User not found for password reset.",
            )
    else:
        raise HTTPException(status_code=400, detail="Invalid purpose")


    # Generate OTP
    try:
        # otp = await generate_otp(email, purpose)
        otp = background_tasks.add_task(generate_otp, email, purpose)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to generate OTP")

    return {
        "status": "success",
        "message": (
            f"OTP sent to {email}. Expires in 5 minute."
            f"{f' OTP: {otp}' if settings.DEBUG else ''}"
        ),
        "purpose": purpose,
    }



@router.post("/signup", response_model=dict)
async def signup(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    otp_value: str = Form(...),
    purpose: str = Form(
        ...,
        description="""signup, installer_signup""",
    ),
):
    try:
        await verify_otp(email, otp_value, purpose)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="OTP verification failed. Enter correct OTP.",
        )

    lookup_field = await detect_input_type(email)
    if lookup_field != "email":
        raise HTTPException(status_code=400, detail="Invalid email")

    if await User.get_or_none(email=email):
        raise HTTPException(status_code=400, detail="Email already registered")

    ROLE_MAP = {
        "signup": {
            "role": UserRole.CUSTOMER,
        },
        "installer_signup": {
            "role": UserRole.INSTALLER,
        },
    }

    if purpose not in ROLE_MAP:
        raise HTTPException(status_code=400, detail="Invalid signup purpose")

    role_data = ROLE_MAP[purpose]

    hashed_password = pwd_context.hash(password)

    user = await User.create(
        name=name,
        email=email,
        password=hashed_password,
        role=role_data["role"],
        is_active=True,
    )

    token_data = {
        "sub": str(user.id),
        "role": user.role,
        "is_active": user.is_active,
        "is_staff": user.is_staff,
    }

    return {
        "message": "User created successfully",
        "access_token": create_access_token(token_data),
        "refresh_token": create_refresh_token(token_data),
        "token_type": "bearer",
        "role": user.role,
    }


@router.post("/verify_otp")
async def verify_otp_route(
    email: str = Form(...),
    otp_value: str = Form(...),
    purpose: str = Form(...),
):
    try:
        session_key = await verify_otp(email, otp_value, purpose)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "status": "success",
        "message": "OTP verified successfully.",
        "sessionKey": session_key,
        "purpose": purpose,
    }



@router.post("/reset_password", response_model=dict)
async def reset_password(
        user: User = Depends(get_current_user),
        old_password: str = Form(...),
        password: str = Form(...)
):
    is_verified = user.verify_password(old_password)
    if not is_verified:
        raise HTTPException(status_code=400, detail="Invalid Old Password")
    user.password = user.set_password(password)
    await user.save()

    token_data = {
        "sub": str(user.id),
        "is_active": user.is_active,
        "role": user.role,
        "is_staff": user.is_staff,
    }

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return {
        "message": "Password reset successfully",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/forgot_password", response_model=dict)
async def forgot_password(
    email: str = Form(...),
    password: str = Form(...),
    session_key: str = Form(...),
):
    lookup_field = await detect_input_type(email)


    if lookup_field == "email":
        user = await User.get_or_none(email=email)
    elif lookup_field == "phone":
        user = await User.get_or_none(phone=email)
    else:
        user = await User.get_or_none(username=email)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        await verify_session_key(email, session_key, purpose="forgot_password")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Session key invalid: {e}")

    user.password = pwd_context.hash(password)
    await user.save()

    token_data = {
        "sub": str(user.id),
        "is_active": user.is_active,
        "role": user.role,
        "is_staff": user.is_staff,
    }

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return {
        "status": "success",
        "message": "Password reset successfully",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.get("/verify-token")
async def verify_token(request: Request, user: User = Depends(get_current_user)):
    response_data = {
        "status": "success",
        "id": user.id,
        "name": f"{user.name}",
        "role": user.role,
        "email": user.email,
        "is_active": user.is_active,
        "is_staff": user.is_staff,
        "photo": getattr(user, "photo", None),
    }

    if hasattr(request.state, "new_tokens"):
        response_data["new_tokens"] = request.state.new_tokens

    return response_data

