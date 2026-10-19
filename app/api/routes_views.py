from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.auth import current_user_or_none
from app.services.repository import Doc

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse, tags=["Dashboard"])
async def home(request: Request, user: Doc | None = Depends(current_user_or_none)):
    """Not logged in -> login. Admin -> admin dashboard. Everyone else -> the job page.
    The page itself is tiny: jobs are loaded page by page by JavaScript."""
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user.role == "admin":
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(request=request, name="user_dashboard.html",
                                      context={"user": user})
