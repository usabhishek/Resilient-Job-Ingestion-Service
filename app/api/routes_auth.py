"""Login, signup, forgot-password, logout (HTML pages) and the logged-in user's own account API."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pymongo.database import Database
from app.auth import (COOKIE_NAME, create_session, current_user_or_none, delete_session,
                      require_user, set_session_cookie)
from app.database import get_db, run_db
from app.schemas.user import AccountDelete, PasswordChange, ProfileUpdate, UserPublic
from app.services import users as user_service
from app.services.repository import Doc

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def page(request: Request, template: str, status_code: int = 200, **context):
    return templates.TemplateResponse(request=request, name=template, status_code=status_code,
                                      context={"user": None, "error": None, "message": None, **context})


def to_public(user: Doc) -> UserPublic:
    return UserPublic(id=user.id, name=user.name, email=user.email, role=user.role,
                      created_at=user.created_at)


async def login_response(db: Database, user: Doc) -> RedirectResponse:
    token = await run_db(create_session, db, user.id)
    response = RedirectResponse("/", status_code=303)
    set_session_cookie(response, token)
    return response


# ------------------------------------------------------------------- pages
@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request, user: Doc | None = Depends(current_user_or_none)):
    if user:
        return RedirectResponse("/", status_code=303)
    return page(request, "login.html", message=request.query_params.get("msg"))


@router.post("/login", include_in_schema=False)
async def login(request: Request, email: str = Form(""), password: str = Form(""),
                db: Database = Depends(get_db)):
    user, error = await run_db(user_service.authenticate, db, email, password)
    if not user:
        return page(request, "login.html", status_code=401, error=error, email=email)
    return await login_response(db, user)


@router.get("/signup", response_class=HTMLResponse, include_in_schema=False)
async def signup_page(request: Request, user: Doc | None = Depends(current_user_or_none)):
    if user:
        return RedirectResponse("/", status_code=303)
    return page(request, "signup.html", question=user_service.SECURITY_QUESTION)


@router.post("/signup", include_in_schema=False)
async def signup(request: Request, name: str = Form(""), email: str = Form(""),
                 password: str = Form(""), answer: str = Form(""),
                 db: Database = Depends(get_db)):
    error = user_service.check_signup_fields(name, email, password, answer)
    user = None
    if not error:
        try:
            user = await run_db(user_service.create_user, db, name, email, password, answer)
        except ValueError as e:
            error = str(e)
    if not user:
        return page(request, "signup.html", status_code=400, error=error, name=name, email=email,
                    question=user_service.SECURITY_QUESTION)
    return await login_response(db, user)


@router.get("/forgot-password", response_class=HTMLResponse, include_in_schema=False)
async def forgot_page(request: Request):
    return page(request, "forgot.html", question=user_service.SECURITY_QUESTION)


@router.post("/forgot-password", include_in_schema=False)
async def forgot(request: Request, email: str = Form(""), answer: str = Form(""),
                 new_password: str = Form(""), db: Database = Depends(get_db)):
    error = await run_db(user_service.reset_password, db, email, answer, new_password)
    if error:
        return page(request, "forgot.html", status_code=400, error=error, email=email,
                    question=user_service.SECURITY_QUESTION)
    return RedirectResponse("/login?msg=Password+changed.+Please+log+in.", status_code=303)


@router.post("/logout", include_in_schema=False)
async def logout(request: Request, db: Database = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        await run_db(delete_session, db, token)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/account", response_class=HTMLResponse, include_in_schema=False)
async def account_page(request: Request, user: Doc | None = Depends(current_user_or_none)):
    if not user:
        return RedirectResponse("/login", status_code=303)
    return page(request, "account.html", user=user)


# ------------------------------------------------------ my account (JSON API)
@router.get("/api/me", response_model=UserPublic, tags=["Account"])
async def get_me(user: Doc = Depends(require_user)):
    return to_public(user)


@router.patch("/api/me", response_model=UserPublic, tags=["Account"])
async def update_me(body: ProfileUpdate, user: Doc = Depends(require_user),
                    db: Database = Depends(get_db)):
    """UPDATE my profile (name)."""
    updated = await run_db(user_service.update_name, db, user.id, body.name)
    return to_public(updated)


@router.post("/api/me/password", tags=["Account"])
async def change_my_password(body: PasswordChange, request: Request,
                             user: Doc = Depends(require_user), db: Database = Depends(get_db)):
    """Change password. All other sessions are logged out; this browser stays logged in."""
    error = await run_db(user_service.change_password, db, user.id,
                         body.current_password, body.new_password)
    if error:
        raise HTTPException(status_code=400, detail=error)
    token = await run_db(create_session, db, user.id)
    response = JSONResponse({"detail": "Password changed."})
    set_session_cookie(response, token)
    return response


@router.post("/api/me/delete", tags=["Account"])
async def delete_my_account(body: AccountDelete, user: Doc = Depends(require_user),
                            db: Database = Depends(get_db)):
    """DELETE my account together with all my jobs and ingestion history."""
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="The admin account cannot be deleted.")
    checked, _ = await run_db(user_service.authenticate, db, user.email, body.password)
    if not checked:
        raise HTTPException(status_code=400, detail="Password is incorrect.")
    await run_db(user_service.delete_user_and_data, db, user.id)
    response = JSONResponse({"detail": "Account deleted."})
    response.delete_cookie(COOKIE_NAME)
    return response
