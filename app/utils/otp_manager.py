from fastapi import HTTPException, Request
from pydantic import EmailStr
import secrets

from app.config import settings
# from app.config import settings
from app.redis import get_redis
# from app.utils.send_email import send_email
# from app.utils.send_sms import send_sms
import re
from fastapi.templating import Jinja2Templates

from app.utils.send_email import send_email

templates = Jinja2Templates(directory="templates")



# -------------------------
# Detect Input Type (Email / Phone)
# -------------------------
def detect_input_type(value: str) -> str:
    value = value.strip()

    if re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', value):
        return 'email'

    raise HTTPException(status_code=400, detail="Invalid Email.")

# -------------------------
# Constants
# -------------------------
OTP_EXPIRY_SECONDS = 60 * 5
MAX_ATTEMPTS_PER_HOUR = 20


def _otp_key(user_key: str, purpose: str):
    return f"{purpose}:otp:{user_key}"


def _otp_attempts_key(user_key: str, purpose: str):
    return f"{purpose}:otp_attempts:{user_key}"


def _session_key(user_key: str, purpose: str):
    return f"{purpose}:session:{user_key}"


# -------------------------
# Generate OTP
# -------------------------
async def generate_otp(user_key: str, purpose: str):
    redis = get_redis()

    otp_key = _otp_key(user_key, purpose)
    attempts_key = _otp_attempts_key(user_key, purpose)

    key_type = detect_input_type(user_key)

    attempts_raw = await redis.get(attempts_key)
    attempts = int(attempts_raw) if attempts_raw else 0


    if attempts >= MAX_ATTEMPTS_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail="Too many OTP requests. Try again later.",
        )

    otp = str(secrets.randbelow(900000) + 100000)
    await redis.set(otp_key, otp, ex=OTP_EXPIRY_SECONDS)

    

    title = "Verify Your Email Address - Petdoor USA"

    if purpose == "login" or purpose == "forgot_password" or purpose == "update_email":
        html_message = f"""html
                <!DOCTYPE html>
                <html>
                <head>
                <meta charset="UTF-8">
                </head>

                <body style="margin:0; padding:0; font-family: Arial, sans-serif; background-color:#f4f4f4;">

                <table align="center" width="100%" cellpadding="0" cellspacing="0"
                style="max-width:600px; background:#ffffff; margin-top:20px; border-radius:8px; overflow:hidden;">

                <tr>
                <td style="background-color:#4CAF50; color:#ffffff; padding:20px; text-align:center; font-size:20px; font-weight:bold;">
                    Petdoor USA
                </td>
                </tr>

                <tr>
                <td style="padding:20px; color:#333333; font-size:15px; line-height:1.6;">

                    <p>Hi,</p>

                    <p>
                        Please verify your email address using the OTP below:
                    </p>

                    <div style="margin:30px 0; text-align:center;">
                        <span style="
                            display:inline-block;
                            background:#f5f5f5;
                            padding:15px 30px;
                            font-size:28px;
                            letter-spacing:5px;
                            font-weight:bold;
                            color:#4CAF50;
                            border-radius:8px;
                        ">
                            {otp}
                        </span>
                    </div>

                    <p>
                        This OTP is valid for <strong>5 minutes</strong>.
                        Please do not share this code with anyone for security reasons.
                    </p>

                    <p style="margin-top:30px;">
                        Best regards,<br>
                        <strong>Petdoor USA Team</strong>
                    </p>

                </td>
                </tr>

                </table>

                </body>
                </html>
                """
    else:

        html_message = f"""html
                <!DOCTYPE html>
                <html>
                <head>
                <meta charset="UTF-8">
                </head>

                <body style="margin:0; padding:0; font-family: Arial, sans-serif; background-color:#f4f4f4;">

                <table align="center" width="100%" cellpadding="0" cellspacing="0"
                style="max-width:600px; background:#ffffff; margin-top:20px; border-radius:8px; overflow:hidden;">

                <tr>
                <td style="background-color:#4CAF50; color:#ffffff; padding:20px; text-align:center; font-size:20px; font-weight:bold;">
                    Petdoor USA
                </td>
                </tr>

                <tr>
                <td style="padding:20px; color:#333333; font-size:15px; line-height:1.6;">

                    <p>Hi,</p>

                    <p>
                        Thank you for signing up with Petdoor USA.
                        To complete your account registration, please verify your email address using the OTP below:
                    </p>

                    <div style="margin:30px 0; text-align:center;">
                        <span style="
                            display:inline-block;
                            background:#f5f5f5;
                            padding:15px 30px;
                            font-size:28px;
                            letter-spacing:5px;
                            font-weight:bold;
                            color:#4CAF50;
                            border-radius:8px;
                        ">
                            {otp}
                        </span>
                    </div>

                    <p>
                        This OTP is valid for <strong>5 minutes</strong>.
                        Please do not share this code with anyone for security reasons.
                    </p>

                    <p>
                        If you did not create an account with Petdoor USA, you can safely ignore this email.
                    </p>

                    <p style="margin-top:30px;">
                        Best regards,<br>
                        <strong>Petdoor USA Team</strong>
                    </p>

                </td>
                </tr>

                </table>

                </body>
                </html>
                """

    if key_type == "email":
        if not settings.DEBUG:
            try:
                await send_email(
                    subject=title,
                    to=user_key,
                    html_message=html_message
                )            
            except Exception as e:
                print(f"Error sending email to {user_key}: {e}")
    else:
        raise HTTPException(status_code=400, detail="Invalid email")

    count = await redis.incr(attempts_key)
    if count == 1:
        await redis.expire(attempts_key, 3600)

    return otp


# -------------------------
# Verify OTP
# -------------------------
async def verify_otp(user_key: str, otp_value: str, purpose: str) -> str:
    redis = get_redis()
    otp_key = _otp_key(user_key, purpose)
    stored_otp = await redis.get(otp_key)
    if not stored_otp:
        raise HTTPException(status_code=400, detail="OTP expired or not found.")

    if stored_otp != otp_value:
        raise HTTPException(status_code=400, detail="Invalid OTP.")

    await redis.delete(otp_key)

    session_key = secrets.token_urlsafe(32)
    redis_session_key = _session_key(user_key, purpose)

    await redis.set(redis_session_key, session_key, ex=OTP_EXPIRY_SECONDS)
    return session_key


# -------------------------
# Verify Session Key
# -------------------------
async def verify_session_key(user_key: str, session_key: str, purpose: str) -> bool:
    redis = get_redis()

    stored = await redis.get(_session_key(user_key, purpose))
    if not stored:
        raise HTTPException(status_code=400, detail="Invalid or expired session key.")

    if stored != session_key:
        raise HTTPException(status_code=400, detail="Invalid session key.")

    await redis.delete(_session_key(user_key, purpose))
    return True
