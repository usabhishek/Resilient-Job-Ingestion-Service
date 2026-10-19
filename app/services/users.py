"""User accounts: signup, login, password reset, profile, deletion, and admin queries."""
import re
import uuid
from datetime import datetime, timedelta, timezone
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from app.auth import hash_secret, verify_secret, normalize_answer
from app.services.repository import Doc, to_doc, now

EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 10
SECURITY_QUESTION = "What was the name of your first school?"
_DUMMY_HASH = hash_secret("dummy")        # keeps login timing similar for unknown emails


def check_signup_fields(name: str, email: str, password: str, answer: str) -> str | None:
    """Returns an error message, or None when everything is valid."""
    if not name.strip() or len(name.strip()) > 60:
        return "Please enter your name (up to 60 characters)."
    if not EMAIL_RX.match(email.strip()):
        return "Please enter a valid email address."
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if not normalize_answer(answer):
        return "Please answer the security question."
    return None


# ------------------------------------------------------------------ CREATE
def create_user(db: Database, name: str, email: str, password: str, answer: str,
                role: str = "user") -> Doc:
    t = now()
    user = {
        "_id": str(uuid.uuid4()), "name": name.strip(), "email": email.strip().lower(),
        "password_hash": hash_secret(password),
        "recovery_hash": hash_secret(normalize_answer(answer)),
        "role": role, "failed_attempts": 0, "locked_until": None, "last_login_at": None,
        "created_at": t, "updated_at": t,
    }
    try:
        db.users.insert_one(user)
    except DuplicateKeyError:                 # unique index on email
        raise ValueError("This email is already registered.")
    return to_doc(user)


def seed_admin(db: Database, email: str | None, password: str | None) -> bool:
    """Creates the admin account from ADMIN_EMAIL / ADMIN_PASSWORD (once)."""
    if not email or not password:
        return False
    if db.users.find_one({"email": email.strip().lower()}):
        return False
    create_user(db, "Admin", email, password, "admin", role="admin")
    return True


# -------------------------------------------------------------------- READ
def get_by_email(db: Database, email: str) -> Doc | None:
    return to_doc(db.users.find_one({"email": email.strip().lower()}))


def get_by_id(db: Database, user_id: str) -> Doc | None:
    return to_doc(db.users.find_one({"_id": user_id}))


def _is_locked(user: dict) -> bool:
    until = user.get("locked_until")
    if not until:
        return False
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until > now()


def _register_failure(db: Database, user: dict) -> None:
    attempts = user.get("failed_attempts", 0) + 1
    if attempts >= MAX_FAILED_ATTEMPTS:        # too many wrong tries -> lock the account briefly
        db.users.update_one({"_id": user["_id"]}, {"$set": {
            "failed_attempts": 0, "locked_until": now() + timedelta(minutes=LOCK_MINUTES)}})
    else:
        db.users.update_one({"_id": user["_id"]}, {"$set": {"failed_attempts": attempts}})


def authenticate(db: Database, email: str, password: str) -> tuple[Doc | None, str | None]:
    """Returns (user, None) on success or (None, error message)."""
    user = db.users.find_one({"email": email.strip().lower()})
    if not user:
        verify_secret(password, _DUMMY_HASH)
        return None, "Invalid email or password."
    if _is_locked(user):
        return None, f"Too many failed attempts. Try again in {LOCK_MINUTES} minutes."
    if not verify_secret(password, user["password_hash"]):
        _register_failure(db, user)
        return None, "Invalid email or password."
    db.users.update_one({"_id": user["_id"]}, {"$set": {
        "failed_attempts": 0, "locked_until": None, "last_login_at": now()}})
    return to_doc(user), None


# ------------------------------------------------------------------ UPDATE
def update_name(db: Database, user_id: str, name: str) -> Doc | None:
    db.users.update_one({"_id": user_id}, {"$set": {"name": name.strip(), "updated_at": now()}})
    return get_by_id(db, user_id)


def change_password(db: Database, user_id: str, current_password: str, new_password: str) -> str | None:
    """Returns an error message, or None on success. Logs the user out everywhere else."""
    user = db.users.find_one({"_id": user_id})
    if not user or not verify_secret(current_password, user["password_hash"]):
        return "Current password is incorrect."
    if len(new_password) < 8:
        return "New password must be at least 8 characters."
    db.users.update_one({"_id": user_id}, {"$set": {
        "password_hash": hash_secret(new_password), "updated_at": now()}})
    db.sessions.delete_many({"user_id": user_id})
    return None


def reset_password(db: Database, email: str, answer: str, new_password: str) -> str | None:
    """Forgot password: email + security answer. Returns an error message, or None on success."""
    generic = "Email or security answer is incorrect."
    user = db.users.find_one({"email": email.strip().lower()})
    if not user:
        verify_secret(answer, _DUMMY_HASH)
        return generic
    if _is_locked(user):
        return f"Too many failed attempts. Try again in {LOCK_MINUTES} minutes."
    if len(new_password) < 8:
        return "New password must be at least 8 characters."
    if not verify_secret(normalize_answer(answer), user["recovery_hash"]):
        _register_failure(db, user)
        return generic
    db.users.update_one({"_id": user["_id"]}, {"$set": {
        "password_hash": hash_secret(new_password), "failed_attempts": 0,
        "locked_until": None, "updated_at": now()}})
    db.sessions.delete_many({"user_id": user["_id"]})
    return None


# ------------------------------------------------------------------ DELETE
def clear_ingestions(db: Database, owner_id: str | None = None) -> tuple[int, int]:
    """Deletes jobs and runs of one user (or of everyone when owner_id is None).
    Returns (jobs_deleted, runs_deleted)."""
    query = {"owner_id": owner_id} if owner_id else {}
    jobs = db.jobs.delete_many(query).deleted_count
    runs = db.ingestion_runs.delete_many(query).deleted_count
    return jobs, runs


def delete_user_and_data(db: Database, user_id: str) -> bool:
    """Removes the account together with all of the user's jobs, runs and sessions."""
    clear_ingestions(db, user_id)
    db.sessions.delete_many({"user_id": user_id})
    return db.users.delete_one({"_id": user_id}).deleted_count == 1


# ------------------------------------------------------------ ADMIN QUERIES
def users_with_counts(db: Database) -> list[dict]:
    """Every user with their job count, run count and last ingestion time (two $group pipelines)."""
    jobs = {r["_id"]: r["n"] for r in db.jobs.aggregate(
        [{"$group": {"_id": "$owner_id", "n": {"$sum": 1}}}])}
    runs = {r["_id"]: r for r in db.ingestion_runs.aggregate(
        [{"$group": {"_id": "$owner_id", "n": {"$sum": 1}, "last": {"$max": "$started_at"}}}])}
    result = []
    for u in db.users.find().sort("created_at", -1):
        result.append({
            "id": u["_id"], "name": u["name"], "email": u["email"], "role": u["role"],
            "created_at": u["created_at"], "last_login_at": u.get("last_login_at"),
            "jobs": jobs.get(u["_id"], 0),
            "runs": runs.get(u["_id"], {}).get("n", 0),
            "last_ingestion_at": runs.get(u["_id"], {}).get("last"),
        })
    return result
