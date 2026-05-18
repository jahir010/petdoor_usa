import os
import importlib
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from app.task_config import start_scheduler

from app.config import settings, init_db
from app.redis import init_redis, redis_client
from app.routes import register_routes
from app.utils.sync_permissions import sync_permissions
from app.utils.auto_routing import get_module
from app.utils.firebase_push import init_firebase
from fastapi.templating import Jinja2Templates
from app.dummy.user import seed_users

# import logging
# logging.basicConfig(level=logging.DEBUG)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    init_redis()
    start_scheduler()
    init_firebase()
    try:
        await sync_permissions()
    except Exception as e:
        print(f"--Permission sync skipped: {e}")
    if settings.DEBUG:
        await seed_users()

    for app_name in get_module(base_dir="applications"):
        try:
            importlib.import_module(f"applications.{app_name}.signals")
        except ModuleNotFoundError:
            print(f"⚠️ Warning: No signals.py in '{app_name}' sub-app.")
    yield
    if redis_client:
        await redis_client.aclose()
    print("Application shutdown complete.")


app = FastAPI(lifespan=lifespan, debug=settings.DEBUG)
register_routes(app)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="templates/static"), name="static")
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    routes = get_module()
    routes.sort()
    html_file = "development.html" if settings.ENV == 'development' else "index.html"
    return templates.TemplateResponse(
        html_file,
        {
            "request": request,
            "routes": routes,
            "image_url": "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1920&q=80"
        }
    )


allow_origins = [
    "https://kyjuanbrown.com",
    "https://www.kyjuanbrown.com",
    "https://petdoorusa.netlify.app",
]
if settings.DEBUG:
    allow_origins = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "https://petdoorusa.netlify.app",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


os.makedirs(settings.MEDIA_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.MEDIA_DIR), name="media")
