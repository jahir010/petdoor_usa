from app.utils.task_decorators import every
from app.utils.send_email import send_email
import pytz
from app.config import settings
dhaka_tz = pytz.timezone('Asia/Dhaka')


@every(day=1, hour=8, minute=0, tz=dhaka_tz)
async def check_email_schedule():
    await send_email(
        subject="Good Morning Message",
        to=["softvence.moynul@gmail.com"],
        html_message="<h3>Hello Moynul! </h3><p>Good Morning. How are you. Don't worry, I am running.</p>",
        from_name=settings.APP_NAME,
        from_email=settings.DEFAULT_FROM_EMAIL
    )
    print("send Good Morning email everyday at 8:00 AM")
    
    