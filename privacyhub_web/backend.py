from __future__ import annotations

import hashlib
import base64
import os
import re
import hmac
import json
import secrets
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from typing import Dict, List, Optional

from fastapi import Cookie, FastAPI, File, Form, Header, HTTPException, UploadFile, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


try:
    import requests
except ImportError:
    requests = None

try:
    from cvat_sdk import make_client
    from cvat_sdk.core.proxies.tasks import ResourceType
    from cvat_sdk.exceptions import ApiException
except ImportError:
    make_client = None
    ResourceType = None
    ApiException = Exception


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / "privacy_module" / "input"
OUTPUT_DIR = PROJECT_ROOT / "privacy_module" / "output"
APPROVED_DIR = PROJECT_ROOT / "privacy_module" / "review" / "approved"
DATABASE_DIR = PROJECT_ROOT / "database"
DATABASE_PATH = DATABASE_DIR / "privacy.db"
XTREME1_URL = os.getenv("XTREME1_URL", "http://localhost:8190")
DEFAULT_DATASET_ID = 4
ALLOWED_UPLOAD_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB per image

# A PrivacyHub API token stays valid for this many days after it is
# generated. Generating a new token deactivates any previous token for
# that user, so a user only ever has one *live* token at a time - it does
# not rotate just because the UI is refreshed.
API_TOKEN_VALIDITY_DAYS = 30

# Simple per-token sliding-window rate limit for the public API.
RATE_LIMIT_MAX_REQUESTS = 60
RATE_LIMIT_WINDOW_SECONDS = 60


for folder in (INPUT_DIR, OUTPUT_DIR, APPROVED_DIR, DATABASE_DIR):
    folder.mkdir(parents=True, exist_ok=True)


app = FastAPI(title="PrivacyHub", version="1.0.0")
privacyhub_bearer = HTTPBearer(auto_error=False)

app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="static",
)

app.mount(
    "/media/input",
    StaticFiles(directory=INPUT_DIR),
    name="input",
)

app.mount(
    "/media/output",
    StaticFiles(directory=OUTPUT_DIR),
    name="output",
)

app.mount(
    "/media/approved",
    StaticFiles(directory=APPROVED_DIR),
    name="approved",
)


SESSION_COOKIE = "privacyhub_session"

SESSIONS: Dict[str, int] = {}
RESULTS: Dict[int, List[dict]] = {}
JOBS: Dict[str, dict] = {}
# API delivery information is kept in memory only until a reviewed image is approved.
PENDING_API_DELIVERIES: Dict[tuple, dict] = {}
# Images received through the external PrivacyHub API and waiting for the
# user to start protection from the Upload & Protect page.
API_INCOMING: Dict[int, List[dict]] = {}
LOCK = threading.Lock()

# Sliding-window request timestamps per API token, used for rate limiting.
# Kept in memory: it resets on restart, which is fine for a per-minute window.
RATE_LIMIT_HITS: Dict[str, List[float]] = {}
RATE_LIMIT_LOCK = threading.Lock()

_ENGINE = None
_ENGINE_LOCK = threading.Lock()


def get_engine():
    """
    Load the PrivacyEngine (BERT NER, YOLO, PaddleOCR) once and reuse it.

    Loading these models from disk takes ~20-30s. Re-instantiating PrivacyEngine
    on every job would pay that cost every single run, so we cache a single
    instance for the life of the process instead.
    """
    global _ENGINE

    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                from privacy_engine.pipeline import PrivacyEngine

                _ENGINE = PrivacyEngine()

    return _ENGINE


def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processing_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                token_prefix TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                last_used_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )

        # Migration for databases created before `expires_at` / `token_last4` existed.
        existing_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(api_tokens)").fetchall()
        }
        if "expires_at" not in existing_columns:
            conn.execute("ALTER TABLE api_tokens ADD COLUMN expires_at TEXT")
        if "token_last4" not in existing_columns:
            conn.execute("ALTER TABLE api_tokens ADD COLUMN token_last4 TEXT")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT,
                endpoint TEXT NOT NULL,
                request_time TEXT NOT NULL,
                status TEXT NOT NULL,
                job_id TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )

def hash_password(password: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        120_000,
    ).hex()

    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)

        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            salt.encode(),
            120_000,
        ).hex()

        return hmac.compare_digest(actual, expected)

    except ValueError:
        return False

def hash_api_token(token: str) -> str:
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def generate_api_token() -> str:
    return "ph_live_" + secrets.token_urlsafe(32)

def authenticate_api_token(authorization: Optional[str]) -> dict:
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="PrivacyHub API token is required.",
        )

    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Use Authorization: Bearer <PrivacyHub-token>.",
        )

    token = authorization[7:].strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="PrivacyHub API token is empty.",
        )

    token_hash = hash_api_token(token)

    with get_db() as conn:
        row = conn.execute(
            """
            SELECT
                api_tokens.user_id,
                api_tokens.expires_at,
                users.id,
                users.username,
                users.email,
                users.created_at
            FROM api_tokens
            JOIN users ON users.id = api_tokens.user_id
            WHERE api_tokens.token_hash = ?
              AND api_tokens.is_active = 1
            """,
            (token_hash,),
        ).fetchone()

        if not row:
            raise HTTPException(
                status_code=401,
                detail="Invalid or inactive PrivacyHub API token.",
            )

        if row["expires_at"]:
            try:
                expires_at = datetime.fromisoformat(row["expires_at"])
            except ValueError:
                expires_at = None
            if expires_at and datetime.now() > expires_at:
                raise HTTPException(
                    status_code=401,
                    detail=(
                        "PrivacyHub API token has expired. "
                        "Generate a new one from API Access."
                    ),
                )

        conn.execute(
            """
            UPDATE api_tokens
            SET last_used_at = ?
            WHERE token_hash = ?
            """,
            (
                datetime.now().isoformat(
                    timespec="seconds"
                ),
                token_hash,
            ),
        )


    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "created_at": row["created_at"],
        "token_hash": token_hash,
    }

def record_api_usage(
    user_id: int,
    token_hash: str,
    endpoint: str,
    status: str,
    job_id: Optional[str] = None,
):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO api_usage
            (
                user_id,
                token_hash,
                endpoint,
                request_time,
                status,
                job_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                token_hash,
                endpoint,
                datetime.now().isoformat(
                    timespec="seconds"
                ),
                status,
                job_id,
            ),
        )


def within_rate_limit(token_hash: str) -> bool:
    """
    Sliding-window rate limit: at most RATE_LIMIT_MAX_REQUESTS requests
    per RATE_LIMIT_WINDOW_SECONDS for a given API token. Returns True
    (and records the hit) when the caller is within the limit, or False
    when the request should be rejected with 429.
    """
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS

    with RATE_LIMIT_LOCK:
        hits = [t for t in RATE_LIMIT_HITS.get(token_hash, []) if t > window_start]

        if len(hits) >= RATE_LIMIT_MAX_REQUESTS:
            RATE_LIMIT_HITS[token_hash] = hits
            return False

        hits.append(now)
        RATE_LIMIT_HITS[token_hash] = hits
        return True


def current_user(session: Optional[str]) -> dict:
    if not session or session not in SESSIONS:
        raise HTTPException(status_code=401, detail="Not signed in")

    user_id = SESSIONS[session]

    with get_db() as conn:
        row = conn.execute(
            "SELECT id, username, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="Session expired")

    return dict(row)


def safe_filename(name: str) -> str:
    name = Path(name).name

    if not name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid filename")

    return name


def result_counts(results: List[dict]):
    approved = sum(
        r.get("review_status") == "APPROVED"
        for r in results
    )

    rejected = sum(
        r.get("review_status") == "REJECTED"
        for r in results
    )

    review = len(results) - approved - rejected

    return len(results), approved, review, rejected


def serialize_result(result: dict) -> dict:
    input_path = Path(result["input_path"])
    output_path = Path(result["output_path"])

    return {
        "filename": input_path.name,
        "display_name": result.get(
            "original_filename",
            input_path.name,
        ),
        "output_url": f"/media/output/{output_path.name}",
        "review_status": result.get(
            "review_status",
            "REVIEW",
        ),
        "faces": len(result.get("faces", [])),
        "plates": len(result.get("plates", [])),
        "text_pii": len(result.get("text_regions", [])),
    }


# ---------------------------- auth ----------------------------


@app.post("/api/auth/signup")
def signup(
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    username = username.strip()
    email = email.strip().lower()

    if not username or not email or not password:
        raise HTTPException(
            status_code=400,
            detail="Please complete all fields.",
        )

    if password != confirm_password:
        raise HTTPException(
            status_code=400,
            detail="Passwords do not match.",
        )

    if len(password) < 6:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 6 characters.",
        )

    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO users
                (username, email, password_hash, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    username,
                    email,
                    hash_password(password),
                    datetime.now().isoformat(
                        timespec="seconds"
                    ),
                ),
            )

    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=400,
            detail="An account with that username or email already exists.",
        )

    return {
        "success": True,
        "message": "Account created successfully.",
    }


@app.post("/api/auth/login")
def login(
    email: str = Form(...),
    password: str = Form(...),
):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()

    if not row or not verify_password(
        password,
        row["password_hash"],
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password.",
        )

    token = secrets.token_urlsafe(32)

    SESSIONS[token] = row["id"]

    response = {
        "success": True,
        "user": {
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
        },
    }

    out = JSONResponse(response)

    out.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
    )

    return out


@app.post("/api/auth/logout")
def logout(
    session: Optional[str] = Cookie(
        None,
        alias=SESSION_COOKIE,
    ),
):
    if session:
        SESSIONS.pop(session, None)

    out = JSONResponse({"success": True})

    out.delete_cookie(SESSION_COOKIE)

    return out


@app.get("/api/auth/me")
def me(
    session: Optional[str] = Cookie(
        None,
        alias=SESSION_COOKIE,
    ),
):
    user = current_user(session)

    return {
        "authenticated": True,
        "user": user,
    }

# ---------------------------- PrivacyHub API tokens ----------------------------

@app.post("/api/auth/api-token")
def create_api_token(
    session: Optional[str] = Cookie(
        None,
        alias=SESSION_COOKIE,
    ),
):
    user = current_user(session)

    with get_db() as conn:
        existing = conn.execute(
            """
            SELECT expires_at
            FROM api_tokens
            WHERE user_id = ?
              AND is_active = 1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (user["id"],),
        ).fetchone()

        # If the user already has a live, unexpired token, "Generate" is a
        # no-op: we do NOT rotate it. The plaintext can't be shown again
        # (only its hash is stored), so we just confirm it's still active.
        if existing:
            still_valid = True
            if existing["expires_at"]:
                try:
                    still_valid = datetime.now() <= datetime.fromisoformat(existing["expires_at"])
                except ValueError:
                    still_valid = True

            if still_valid:
                return {
                    "success": True,
                    "created_new": False,
                    "message": (
                        "You already have an active PrivacyHub API token. "
                        "It stays valid until it expires or you revoke it — "
                        "use Revoke Token first if you need a new one now."
                    ),
                    "expires_at": existing["expires_at"],
                }

        token = generate_api_token()
        token_hash = hash_api_token(token)
        token_prefix = token[:16]
        token_last4 = token[-4:]

        created_at = datetime.now()
        expires_at = created_at + timedelta(days=API_TOKEN_VALIDITY_DAYS)

        # Retire any previous (now-expired, or otherwise inactive) tokens
        # before inserting the new one, so a user only ever has one live row.
        conn.execute(
            """
            UPDATE api_tokens
            SET is_active = 0
            WHERE user_id = ?
              AND is_active = 1
            """,
            (user["id"],),
        )

        conn.execute(
            """
            INSERT INTO api_tokens
            (user_id, token_hash, token_prefix, token_last4, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                token_hash,
                token_prefix,
                token_last4,
                created_at.isoformat(timespec="seconds"),
                expires_at.isoformat(timespec="seconds"),
            ),
        )

    return {
        "success": True,
        "created_new": True,
        "message": "PrivacyHub API token created.",
        "token": token,
        "expires_at": expires_at.isoformat(timespec="seconds"),
    }


@app.post("/api/auth/api-token/revoke")
def revoke_api_token(
    session: Optional[str] = Cookie(
        None,
        alias=SESSION_COOKIE,
    ),
):
    user = current_user(session)

    with get_db() as conn:
        cursor = conn.execute(
            """
            UPDATE api_tokens
            SET is_active = 0
            WHERE user_id = ?
              AND is_active = 1
            """,
            (user["id"],),
        )
        revoked = cursor.rowcount > 0

    return {
        "success": True,
        "revoked": revoked,
        "message": (
            "PrivacyHub API token revoked. Generate a new one when you're ready."
            if revoked
            else "No active PrivacyHub API token to revoke."
        ),
    }


@app.get("/api/auth/api-token")
def get_api_token(
    session: Optional[str] = Cookie(
        None,
        alias=SESSION_COOKIE,
    ),
):
    user = current_user(session)

    with get_db() as conn:
        row = conn.execute(
            """
            SELECT
                token_prefix,
                token_last4,
                created_at,
                expires_at,
                last_used_at,
                is_active
            FROM api_tokens
            WHERE user_id = ?
              AND is_active = 1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (user["id"],),
        ).fetchone()

    if not row:
        return {
            "success": True,
            "has_token": False,
        }

    is_expired = False
    days_remaining = None

    if row["expires_at"]:
        try:
            expires_at = datetime.fromisoformat(row["expires_at"])
            is_expired = datetime.now() > expires_at
            days_remaining = max(0, (expires_at - datetime.now()).days)
        except ValueError:
            pass

    return {
        "success": True,
        "has_token": True,
        "token_prefix": row["token_prefix"],
        "token_last4": row["token_last4"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "last_used_at": row["last_used_at"],
        "is_active": bool(row["is_active"]) and not is_expired,
        "is_expired": is_expired,
        "days_remaining": days_remaining,
    }


@app.get("/api/auth/api-usage")
def get_api_usage(
    session: Optional[str] = Cookie(
        None,
        alias=SESSION_COOKIE,
    ),
):
    user = current_user(session)

    with get_db() as conn:
        summary = conn.execute(
            """
            SELECT
                COUNT(*) AS total_requests,
                SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) AS successful_requests,
                SUM(CASE WHEN status IN ('REVIEW', 'HOLD') THEN 1 ELSE 0 END) AS review_requests,
                SUM(CASE WHEN status = 'RATE_LIMITED' THEN 1 ELSE 0 END) AS rate_limited_requests,
                SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed_requests,
                MAX(request_time) AS last_request
            FROM api_usage
            WHERE user_id = ?
            """,
            (user["id"],),
        ).fetchone()

        recent_rows = conn.execute(
            """
            SELECT endpoint, request_time, status, job_id
            FROM api_usage
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 10
            """,
            (user["id"],),
        ).fetchall()

    return {
        "success": True,
        "total_requests": int(summary["total_requests"] or 0),
        "successful_requests": int(summary["successful_requests"] or 0),
        "review_requests": int(summary["review_requests"] or 0),
        "rate_limited_requests": int(summary["rate_limited_requests"] or 0),
        "failed_requests": int(summary["failed_requests"] or 0),
        "last_request": summary["last_request"],
        "recent": [dict(row) for row in recent_rows],
    }

# ---------------------------- dashboard ----------------------------


def list_approved_images() -> List[dict]:
    approved_files = [
        p.name
        for p in APPROVED_DIR.iterdir()
        if p.is_file()
        and p.suffix.lower()
        in {".jpg", ".jpeg", ".png", ".webp"}
    ]

    # Look up detection stats for each approved file by matching it against
    # the output images we've generated, so the Approved Dataset view can
    # show per-image info (faces/plates/text PII) instead of just a filename.

    stats_by_output_name: Dict[str, dict] = {}

    for user_results in RESULTS.values():
        for result in user_results:
            output_name = Path(
                result["output_path"]
            ).name

            stats_by_output_name[output_name] = {
                "faces": len(
                    result.get("faces", [])
                ),
                "plates": len(
                    result.get("plates", [])
                ),
                "text_pii": len(
                    result.get("text_regions", [])
                ),
            }

    images = []

    for name in sorted(approved_files):
        entry = {
            "filename": name,
            "url": f"/media/approved/{name}",
        }

        stats = stats_by_output_name.get(name)

        if stats:
            entry.update(stats)

        images.append(entry)

    return images


@app.get("/api/dashboard")
def dashboard(
    session: Optional[str] = Cookie(
        None,
        alias=SESSION_COOKIE,
    ),
):
    user = current_user(session)

    results = RESULTS.get(
        user["id"],
        [],
    )

    total, approved, review, rejected = result_counts(
        results
    )

    return {
        "user": user,
        "counts": {
            "processed": total,
            "approved": approved,
            "review": review,
            "rejected": rejected,
        },
        "approved_images": list_approved_images(),
    }


@app.get("/api/approved")
def approved_images(
    session: Optional[str] = Cookie(
        None,
        alias=SESSION_COOKIE,
    ),
):
    current_user(session)

    return {
        "images": list_approved_images()
    }


@app.get("/api/approved/{filename}/download")
def download_approved_image(
    filename: str,
    session: Optional[str] = Cookie(
        None,
        alias=SESSION_COOKIE,
    ),
):
    current_user(session)

    # Strip any path components so this can't be used to read arbitrary
    # files outside the approved dataset folder.
    safe_name = Path(filename).name
    approved_path = APPROVED_DIR / safe_name

    if not approved_path.exists() or not approved_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Approved image not found.",
        )

    return FileResponse(
        approved_path,
        filename=safe_name,
        media_type="application/octet-stream",
    )


@app.delete("/api/approved/{filename}")
def delete_approved_image(
    filename: str,
    session: Optional[str] = Cookie(
        None,
        alias=SESSION_COOKIE,
    ),
):
    user = current_user(session)

    safe_name = Path(filename).name
    approved_path = APPROVED_DIR / safe_name

    if not approved_path.exists() or not approved_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Approved image not found.",
        )

    approved_path.unlink()

    # If this masked/blurred image is tracked in the user's results, roll
    # it back to REJECTED so it disappears from the Approved count and
    # from the delivery queue, instead of lingering as a phantom APPROVED
    # entry whose file no longer exists.
    with LOCK:
        for result in RESULTS.get(user["id"], []):
            if Path(result.get("output_path", "")).name != safe_name:
                continue

            result["review_status"] = "REJECTED"

            PENDING_API_DELIVERIES.pop(
                (user["id"], Path(result["input_path"]).name),
                None,
            )

    return {
        "success": True,
        "message": f"{safe_name} was removed from the Approved Dataset.",
    }


# ---------------------------- protection ----------------------------


def run_processing(
    job_id: str,
    user_id: int,
    files_data: list,
    selected_types: list,
    api_metadata: Optional[list] = None,
):
    try:
        with LOCK:
            JOBS[job_id]["status"] = "running"
            JOBS[job_id]["total"] = len(files_data)
            JOBS[job_id]["current"] = 0
            JOBS[job_id]["message"] = (
                "Loading privacy engine..."
            )

        engine = get_engine()

        image_results = []

        # Preserve the current application's behavior.
        for old_file in APPROVED_DIR.iterdir():
            if old_file.is_file():
                old_file.unlink()

        api_metadata = api_metadata or []

        for index, (filename, content) in enumerate(
            files_data,
            start=1,
        ):
            filename = safe_filename(filename)

            stem = Path(filename).stem
            suffix = Path(filename).suffix

            namespaced = (
                f"{job_id}_{index}_{stem}{suffix}"
            )

            input_path = INPUT_DIR / namespaced

            output_path = (
                OUTPUT_DIR
                / f"masked_{namespaced}"
            )

            input_path.write_bytes(content)

            with LOCK:
                JOBS[job_id]["current"] = index - 1
                JOBS[job_id]["message"] = (
                    f"Protecting {filename}..."
                )

            result = engine.process(
                input_path,
                output_path,
                selected_types=selected_types,
            )

            # The original upload has served its purpose: the pipeline
            # reads it from input_path and writes the masked image to
            # output_path. Nothing downstream (review, approve, delivery)
            # reads the input file again, so remove it to keep the input
            # folder from filling up with renamed duplicates.
            try:
                input_path.unlink()
            except OSError:
                pass

            result["input_path"] = str(input_path)
            result["output_path"] = str(output_path)
            result["original_filename"] = filename

            api_meta = api_metadata[index - 1] if index - 1 < len(api_metadata) else None
            if api_meta:
                result["api_delivery"] = {
                    "destination": api_meta.get("destination", "RETURN"),
                    "dataset_id": api_meta.get("dataset_id"),
                    "annotation_platform": api_meta.get("annotation_platform", ""),
                    "platform_url": api_meta.get("platform_url", ""),
                    "platform_token": api_meta.get("platform_token", ""),
                    "project_id": api_meta.get("project_id"),
                    "task_name": api_meta.get("task_name", ""),
                    "image_field": api_meta.get("image_field", "image"),
                    "filename": api_meta.get("original_filename", filename),
                    "api_job_id": api_meta.get("job_id"),
                }
                PENDING_API_DELIVERIES[(user_id, input_path.name)] = {
                    "destination": api_meta.get("destination", "RETURN"),
                    "dataset_id": api_meta.get("dataset_id"),
                    "annotation_platform": api_meta.get("annotation_platform", ""),
                    "platform_url": api_meta.get("platform_url", ""),
                    "platform_token": api_meta.get("platform_token", ""),
                    "project_id": api_meta.get("project_id"),
                    "task_name": api_meta.get("task_name", ""),
                    "image_field": api_meta.get("image_field", "image"),
                    "xtreme1_token": api_meta.get("xtreme1_token", ""),
                    "job_id": api_meta.get("job_id"),
                }
                with LOCK:
                    incoming = API_INCOMING.get(user_id, [])
                    API_INCOMING[user_id] = [
                        item for item in incoming
                        if item.get("job_id") != api_meta.get("job_id")
                    ]
                staged_path = INPUT_DIR / str(api_meta.get("stored_filename", ""))
                if staged_path.is_file() and staged_path != input_path:
                    try:
                        staged_path.unlink()
                    except OSError:
                        pass

            image_results.append(result)

            if result.get("review_status") == "APPROVED":
                shutil.copy2(
                    output_path,
                    APPROVED_DIR / output_path.name,
                )

            with get_db() as conn:
                conn.execute(
                    """
                    INSERT INTO processing_jobs
                    (user_id, filename, status, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        filename,
                        result.get(
                            "review_status",
                            "REVIEW",
                        ),
                        datetime.now().isoformat(
                            timespec="seconds"
                        ),
                    ),
                )

            with LOCK:
                JOBS[job_id]["current"] = index

        RESULTS[user_id] = image_results

        with LOCK:
            JOBS[job_id]["status"] = "completed"
            JOBS[job_id]["current"] = len(files_data)
            JOBS[job_id]["message"] = (
                "Protection completed."
            )
            JOBS[job_id]["results"] = [
                serialize_result(r)
                for r in image_results
            ]

    except Exception as exc:
        with LOCK:
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["message"] = str(exc)


# ---------------------------- NEW PRIVACY API ----------------------------

@app.post("/api/v1/anonymize")
async def anonymize_api(
        credentials: Optional[HTTPAuthorizationCredentials] = Security(
        privacyhub_bearer
    ),
    file: UploadFile = File(...),
    selected_types: str = Form("FACE,PLATE,EMAIL,PHONE,NAME,ID"),
    destination: str = Form("RETURN"),
    dataset_id: Optional[int] = Form(None),
    annotation_platform: Optional[str] = Form(None),
    platform_url: Optional[str] = Form(None),
    platform_token: Optional[str] = Form(None),
    project_id: Optional[int] = Form(None),
    task_name: Optional[str] = Form(None),
    image_field: Optional[str] = Form(None),
    x_xtreme1_token: Optional[str] = Header(
        None,
        alias="X-Xtreme1-Token",
    ),
    session: Optional[str] = Cookie(
        None,
        alias=SESSION_COOKIE,
    ),
):
    user = None
    token_hash = None
    job_id = None
    usage_recorded = False

    try:
        authorization = (
    f"{credentials.scheme} {credentials.credentials}"
    if credentials
    else None
)
        if authorization:
            # External callers: a PrivacyHub API Bearer token.
            user = authenticate_api_token(authorization)
            token_hash = user["token_hash"]
        else:
            # Same-origin calls from PrivacyHub's own logged-in UI (e.g. the
            # "Run API Delivery" panel) authenticate via the normal session
            # cookie instead. This avoids ever putting the user's secret
            # API token into frontend JS just so the UI can call its own API.
            session_user = current_user(session)
            token_hash = f"session:{session_user['id']}"
            user = {**session_user, "token_hash": token_hash}

        # ---------------------------------------------------------
        # 0. Rate limit
        # ---------------------------------------------------------
        if not within_rate_limit(token_hash):
            record_api_usage(
                user_id=user["id"],
                token_hash=token_hash,
                endpoint="/api/v1/anonymize",
                status="RATE_LIMITED",
                job_id=None,
            )
            usage_recorded = True

            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded: max {RATE_LIMIT_MAX_REQUESTS} "
                    f"requests per {RATE_LIMIT_WINDOW_SECONDS} seconds. "
                    "Please slow down and try again shortly."
                ),
                headers={"Retry-After": str(RATE_LIMIT_WINDOW_SECONDS)},
            )

        # ---------------------------------------------------------
        # 1. Validate destination
        # ---------------------------------------------------------
        destination = destination.strip().upper()

        allowed_destinations = {
            "RETURN",
            "ANNOTATION",
            # Backward compatibility for older API clients.
            "XTREME1",
        }

        if destination not in allowed_destinations:
                raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported destination '{destination}'. "
                    f"Allowed destinations: "
                    f"{sorted(allowed_destinations)}"
                ),
            )

        if destination == "XTREME1":
            destination = "ANNOTATION"
            annotation_platform = "XTREME1"

        if destination == "ANNOTATION":
            annotation_platform = (annotation_platform or "").strip().upper()
            if annotation_platform not in {"CVAT", "XTREME1", "LABEL_STUDIO"}:
                raise HTTPException(status_code=400, detail="Choose CVAT, Xtreme1, or Label Studio.")
            platform_url = (platform_url or "").strip()
            platform_token = (platform_token or "").strip()
            if not platform_url:
                raise HTTPException(status_code=400, detail="Platform URL is required.")
            if not platform_token:
                raise HTTPException(status_code=400, detail="Platform access token is required.")
            if annotation_platform == "XTREME1" and dataset_id is None:
                raise HTTPException(status_code=400, detail="Xtreme1 Dataset ID is required.")
            if annotation_platform == "LABEL_STUDIO" and project_id is None:
                raise HTTPException(status_code=400, detail="Label Studio Project ID is required.")
            if annotation_platform == "CVAT" and project_id is not None and project_id < 1:
                raise HTTPException(status_code=400, detail="CVAT Project ID must be a positive integer.")
            task_name = (task_name or "").strip()
            image_field = (image_field or "image").strip() or "image"

        # ---------------------------------------------------------
        # 2. Validate file type
        # ---------------------------------------------------------
        suffix = Path(file.filename or "").suffix.lower()

        if suffix not in ALLOWED_UPLOAD_SUFFIXES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported file type. "
                    f"Allowed: {sorted(ALLOWED_UPLOAD_SUFFIXES)}"
                ),
            )

        # ---------------------------------------------------------
        # 3. Read uploaded image
        # ---------------------------------------------------------
        contents = await file.read()

        if len(contents) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"File is too large. "
                    f"Maximum size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
                ),
            )

        # ---------------------------------------------------------
        # 4. Create API job ID and file paths
        # ---------------------------------------------------------
        timestamp = int(time.time() * 1000)

        job_id = f"api_{timestamp}"

        filename = Path(
            file.filename or f"image{suffix}"
        ).name

        input_path = (
            INPUT_DIR
            / f"{job_id}_{filename}"
        )

        output_path = (
            OUTPUT_DIR
            / f"{job_id}_protected{suffix}"
        )

        # ---------------------------------------------------------
        # 5. Save original image temporarily
        # ---------------------------------------------------------
        with open(input_path, "wb") as f:
            f.write(contents)

        # ---------------------------------------------------------
        # 6. Parse selected privacy types
        # ---------------------------------------------------------
        selected = [
            item.strip().upper()
            for item in selected_types.split(",")
            if item.strip()
        ]

        # ---------------------------------------------------------
        # 7. Stage the image for the existing Upload & Protect workflow.
        #    The external API receives a job acknowledgement here; the
        #    Privacy Engine is intentionally NOT run yet.
        # ---------------------------------------------------------
        if not selected:
            raise HTTPException(
                status_code=400,
                detail="Select at least one privacy type.",
            )

        with LOCK:
            API_INCOMING.setdefault(user["id"], []).append({
                "job_id": job_id,
                "stored_filename": input_path.name,
                "original_filename": filename,
                "selected_types": selected,
                "destination": destination,
                "dataset_id": int(dataset_id) if dataset_id is not None else None,
                "annotation_platform": (annotation_platform or "").strip().upper(),
                "platform_url": (platform_url or "").strip(),
                "platform_token": (platform_token or "").strip(),
                "project_id": int(project_id) if project_id is not None else None,
                "task_name": (task_name or "").strip(),
                "image_field": (image_field or "image").strip() or "image",
                # Kept in memory only; never written to the database.
                "xtreme1_token": (x_xtreme1_token or "").strip(),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            })

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO processing_jobs
                (user_id, filename, status, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    user["id"],
                    filename,
                    "PENDING",
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )

        record_api_usage(
            user_id=user["id"],
            token_hash=token_hash,
            endpoint="/api/v1/anonymize",
            status="PENDING",
            job_id=job_id,
        )
        usage_recorded = True

        return JSONResponse(
            status_code=202,
            content={
            "success": True,
            "message": "Image received and waiting for protection from Upload & Protect.",
            "job_id": job_id,
            "status": "PENDING",
            "destination": destination,
            "requested_destination": destination,
            "privacy": {
                "review_status": "PENDING",
                "needs_human_review": False,
            },
            "original_filename": filename,
            },
        )

    except HTTPException:
        if user and token_hash and not usage_recorded:
            record_api_usage(
                user_id=user["id"],
                token_hash=token_hash,
                endpoint="/api/v1/anonymize",
                status="FAILED",
                job_id=job_id,
            )
        raise

    except Exception as e:
        if user and token_hash and not usage_recorded:
            record_api_usage(
                user_id=user["id"],
                token_hash=token_hash,
                endpoint="/api/v1/anonymize",
                status="FAILED",
                job_id=job_id,
            )
        print(f"[API ERROR] {e}")
        raise HTTPException(
            status_code=500,
            detail="PrivacyHub API processing failed.",
        )

        raise HTTPException(
            status_code=500,
            detail=f"Image processing failed: {str(e)}",
        )
# ---------------------------- API incoming staging ----------------------------

@app.get("/api/incoming")
def api_incoming(
    session: Optional[str] = Cookie(None, alias=SESSION_COOKIE),
):
    user = current_user(session)
    with LOCK:
        items = list(API_INCOMING.get(user["id"], []))

    return {
        "images": [
            {
                "job_id": item["job_id"],
                "filename": item["original_filename"],
                "stored_filename": item["stored_filename"],
                "selected_types": item["selected_types"],
                "destination": item["destination"],
                "dataset_id": item.get("dataset_id"),
                "created_at": item["created_at"],
                "url": f"/media/input/{item['stored_filename']}",
            }
            for item in items
            if (INPUT_DIR / item["stored_filename"]).is_file()
        ]
    }


# ---------------------------- existing web protection ----------------------------


@app.post("/api/protect")
async def protect(
    files: List[UploadFile] = File(...),
    selected_types: str = Form(...),
    api_job_ids: str = Form("[]"),
    session: Optional[str] = Cookie(
        None,
        alias=SESSION_COOKIE,
    ),
):
    user = current_user(session)

    try:
        types = json.loads(selected_types)

        if not isinstance(types, list) or not types:
            raise ValueError

    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Select at least one privacy type.",
        )

    files_data = []

    for f in files:
        name = f.filename or "image"

        if (
            Path(name).suffix.lower()
            not in ALLOWED_UPLOAD_SUFFIXES
        ):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {name}",
            )

        content = await f.read()

        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{name} exceeds the 25MB upload limit."
                ),
            )

        files_data.append(
            (name, content)
        )

    if not files_data:
        raise HTTPException(
            status_code=400,
            detail="Please select at least one image.",
        )

    try:
        incoming_job_ids = json.loads(api_job_ids or "[]")
        if not isinstance(incoming_job_ids, list):
            incoming_job_ids = []
    except Exception:
        incoming_job_ids = []

    incoming_by_job = {}
    with LOCK:
        for item in API_INCOMING.get(user["id"], []):
            incoming_by_job[item["job_id"]] = item

    api_metadata = [incoming_by_job.get(job_id_value) for job_id_value in incoming_job_ids]
    while len(api_metadata) < len(files_data):
        api_metadata.append(None)

    job_id = secrets.token_urlsafe(16)

    JOBS[job_id] = {
        "status": "queued",
        "current": 0,
        "total": len(files_data),
        "message": "Queued...",
    }

    thread = threading.Thread(
        target=run_processing,
        args=(
            job_id,
            user["id"],
            files_data,
            types,
            api_metadata,
        ),
        daemon=True,
    )

    thread.start()

    return {
        "job_id": job_id
    }


@app.get("/api/jobs/{job_id}")
def job_status(
    job_id: str,
    session: Optional[str] = Cookie(
        None,
        alias=SESSION_COOKIE,
    ),
):
    current_user(session)

    job = JOBS.get(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    return job


@app.get("/api/results")
def results(
    session: Optional[str] = Cookie(
        None,
        alias=SESSION_COOKIE,
    ),
):
    user = current_user(session)

    return {
        "results": [
            serialize_result(r)
            for r in RESULTS.get(
                user["id"],
                [],
            )
        ]
    }


@app.post("/api/review/{filename}/approve")
def approve(
    filename: str,
    session: Optional[str] = Cookie(None, alias=SESSION_COOKIE),
):
    user = current_user(session)
    results = RESULTS.get(user["id"], [])

    for result in results:
        if Path(result["input_path"]).name != filename:
            continue
        output_path = Path(result["output_path"])
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="Protected image not found")

        result["review_status"] = "APPROVED"
        pending_key = (user["id"], Path(result["input_path"]).name)
        pending = PENDING_API_DELIVERIES.get(pending_key)

        # API-originated images do not enter Approved images at approval time.
        # They remain queued until the user explicitly runs API Delivery.
        if pending or result.get("api_delivery"):
            pending = pending or {}
            pending["review_status"] = "APPROVED"
            pending["delivery_status"] = "WAITING_FOR_DELIVERY"
            PENDING_API_DELIVERIES[pending_key] = pending
            result["delivery_status"] = "WAITING_FOR_DELIVERY"
            return {
                "success": True,
                "message": "Image approved. It is waiting for API Delivery.",
                "destination": pending.get("destination", result.get("api_delivery", {}).get("destination")),
                "delivery_status": "WAITING_FOR_DELIVERY",
            }

        # Existing browser-upload workflow remains unchanged.
        shutil.copy2(output_path, APPROVED_DIR / output_path.name)
        return {
            "success": True,
            "message": "Image approved and added to the Approved Dataset.",
            "destination": None,
        }


@app.post("/api/review/{filename}/reject")
def reject(
    filename: str,
    session: Optional[str] = Cookie(
        None,
        alias=SESSION_COOKIE,
    ),
):
    user = current_user(session)

    results = RESULTS.get(
        user["id"],
        [],
    )

    for result in results:
        if Path(result["input_path"]).name == filename:

            approved_path = (
                APPROVED_DIR
                / Path(result["output_path"]).name
            )

            if approved_path.exists():
                approved_path.unlink()

            result["review_status"] = "REJECTED"

            PENDING_API_DELIVERIES.pop(
                (user["id"], Path(result["input_path"]).name),
                None,
            )

            return {
                "success": True,
                "message": "Image rejected. It will not be delivered.",
            }

    raise HTTPException(
        status_code=404,
        detail="Image not found",
    )


# ---------------------------- Unified delivery queue ------------------------


# ---------------------- Custom Annotator API (single request) ---------------------
#
# A generic "send this image to any annotator in ONE HTTP request" adapter.
# Every annotator accepts images differently, so nothing here is hardcoded to a
# product: the user describes the request (URL, method, auth, request type and
# any extra parameters) and we build exactly that request. Dataset ID, dataset
# name, project ID and similar values are simply ordinary parameters, added only
# when the target annotator needs them.

CUSTOM_METHODS = {"POST", "PUT", "PATCH"}
CUSTOM_AUTH_TYPES = {"NONE", "BEARER", "API_KEY", "HEADER", "QUERY"}
CUSTOM_REQUEST_TYPES = {"MULTIPART", "JSON", "RAW"}
CUSTOM_JSON_ENCODINGS = {"BASE64", "DATA_URI"}
CUSTOM_RAW_ENCODINGS = {"BYTES", "BASE64"}


def _clean_key_value_pairs(raw, label: str) -> List[tuple]:
    """Turn [{"key": ..., "value": ...}, ...] into [(key, value), ...].

    Rows with a blank key are ignored, so an empty row in the UI is harmless.
    """
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{label} must be a list of key/value rows.")
    pairs: List[tuple] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"{label} contains an invalid row.")
        key = str(item.get("key", "")).strip()
        if not key:
            continue
        pairs.append((key, str(item.get("value", ""))))
    return pairs


def _parse_success_condition(text: Optional[str]):
    """Parse 'path == value', 'path != value' or a bare 'path' (must be truthy)."""
    text = (text or "").strip()
    if not text:
        return None
    match = re.match(r"^(\S+?)\s*(==|!=)\s*(.+)$", text)
    if not match:
        return (text, "TRUTHY", None)
    path, operator, rhs = match.groups()
    rhs = rhs.strip()
    try:
        expected = json.loads(rhs)  # true / false / 12 / null / "quoted"
    except ValueError:
        expected = rhs.strip("'\"")  # plain word such as: ok
    return (path, operator, expected)


def _lookup_dotted_path(data, path: str):
    """Walk 'data.items.0.status' / 'data.items[0].status'. Returns (found, value)."""
    current = data
    for part in path.replace("[", ".").replace("]", "").split("."):
        if part == "":
            continue
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False, None
    return True, current


def _condition_values_equal(actual, expected) -> bool:
    # bool is an int subclass in Python, so True == 1; keep them distinct.
    if isinstance(actual, bool) or isinstance(expected, bool):
        return isinstance(actual, bool) and isinstance(expected, bool) and actual == expected
    if actual == expected:
        return True
    return str(actual) == str(expected)  # 5 vs "5" from a string-typed API


def _coerce_json_value(value: str):
    """JSON body values: 5 -> number, true -> bool, "5" (quoted) -> string."""
    try:
        return json.loads(value)
    except ValueError:
        return value


_TEMPLATE_VAR_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_TEMPLATE_BUILTINS = {"filename"}
_MAX_CHAIN_STEPS = 8
# Chain setup steps (e.g. fetching a presigned URL or creating a task) often
# use GET, which the single-request mode never needed.
_CHAIN_METHODS = CUSTOM_METHODS | {"GET"}


def _validate_request_spec(
    raw: dict,
    label: str,
    require_image_field: bool,
    allow_templates: bool = False,
    allow_get: bool = False,
) -> dict:
    """Validate one request description.

    Shared by the single-request mode and by every step of a chained flow.
    When allow_templates is True, {variable} placeholders are permitted in the
    URL and in parameter values; they are checked against the variables known
    at that point by _validate_chain_config and rendered at delivery time.
    """
    url = str(raw.get("url", "")).strip()
    has_template = allow_templates and bool(_TEMPLATE_VAR_RE.search(url))
    probe = _TEMPLATE_VAR_RE.sub("placeholder", url) if has_template else url
    parsed = urlparse(probe)
    url_ok = parsed.scheme in {"http", "https"} and parsed.netloc
    if not url_ok and not (has_template and _TEMPLATE_VAR_RE.fullmatch(url)):
        # A bare "{variable}" is allowed: it renders to the full URL at
        # delivery time and is re-validated there.
        raise ValueError(f"{label}: endpoint URL must be a valid HTTP or HTTPS URL.")

    method = str(raw.get("method") or "POST").strip().upper()
    valid_methods = _CHAIN_METHODS if allow_get else CUSTOM_METHODS
    if method not in valid_methods:
        raise ValueError(f"{label}: HTTP method must be one of {sorted(valid_methods)}.")

    request_type = str(raw.get("request_type") or "MULTIPART").strip().upper()
    if request_type not in CUSTOM_REQUEST_TYPES:
        raise ValueError(f"{label}: request type must be Multipart, JSON or Raw Binary.")

    auth = raw.get("auth") or {}
    if not isinstance(auth, dict):
        raise ValueError(f"{label}: authentication settings are invalid.")
    auth_type = str(auth.get("type") or "NONE").strip().upper()
    if auth_type not in CUSTOM_AUTH_TYPES:
        raise ValueError(f"{label}: unsupported authentication type.")
    auth_name = str(auth.get("name") or "").strip()
    auth_value = str(auth.get("value") or "").strip()
    if auth_type != "NONE" and not auth_value:
        raise ValueError(f"{label}: authentication token / key value is required.")
    if auth_type in {"HEADER", "QUERY"} and not auth_name:
        which = "header" if auth_type == "HEADER" else "query parameter"
        raise ValueError(f"{label}: authentication {which} name is required.")

    image_field = str(raw.get("image_field") or "").strip()
    if require_image_field and request_type in {"MULTIPART", "JSON"} and not image_field:
        raise ValueError(f"{label}: image field name is required for Multipart and JSON requests.")

    json_encoding = str(raw.get("json_encoding") or "BASE64").strip().upper()
    if json_encoding not in CUSTOM_JSON_ENCODINGS:
        raise ValueError(f"{label}: JSON image encoding must be plain base64 or data URI.")
    raw_encoding = str(raw.get("raw_encoding") or "BYTES").strip().upper()
    if raw_encoding not in CUSTOM_RAW_ENCODINGS:
        raise ValueError(f"{label}: raw body content must be raw bytes or base64 text.")

    success_condition = str(raw.get("success_condition") or "").strip()
    _parse_success_condition(success_condition)  # cheap syntax check

    return {
        "url": url,
        "method": method,
        "request_type": request_type,
        "auth_type": auth_type,
        "auth_name": auth_name,
        "auth_value": auth_value,
        "image_field": image_field,
        "json_encoding": json_encoding,
        "raw_encoding": raw_encoding,
        "query_params": _clean_key_value_pairs(raw.get("query_params"), "Query parameters"),
        "headers": _clean_key_value_pairs(raw.get("headers"), "Headers"),
        "body_params": _clean_key_value_pairs(raw.get("body_params"), "Body parameters"),
        "success_condition": success_condition,
    }


def _find_template_refs(spec: dict) -> set:
    """Collect {variable} names referenced in a step's URL and parameter values."""
    refs = set()

    def scan(text):
        refs.update(_TEMPLATE_VAR_RE.findall(str(text)))

    scan(spec["url"])
    for _key, value in spec["query_params"]:
        scan(value)
    for _key, value in spec["headers"]:
        scan(value)
    for _key, value in spec["body_params"]:
        scan(value)
    return refs


def _validate_chain_config(cfg: dict) -> dict:
    """Validate {"steps": [...]} — a chained multi-request annotator flow.

    Each step is a full request description (same options as the single-request
    mode). A step may capture values from its JSON response into {variables}
    that later steps can reference in their URL, headers, query or body
    parameters. Exactly one step must carry the image (send_image).
    """
    raw_steps = cfg.get("steps")
    if len(raw_steps) > _MAX_CHAIN_STEPS:
        raise ValueError(
            f"Custom Annotator API: at most {_MAX_CHAIN_STEPS} chained steps are supported."
        )
    known_vars = set(_TEMPLATE_BUILTINS)
    steps: list = []
    image_step_count = 0
    for index, raw_step in enumerate(raw_steps):
        label = f"Step {index + 1}"
        if not isinstance(raw_step, dict):
            raise ValueError(f"Custom Annotator API {label}: each step must be an object.")
        name = str(raw_step.get("name") or f"step_{index + 1}").strip()
        step_label = f"{label} '{name}'"
        send_image = bool(raw_step.get("send_image", False))
        spec = _validate_request_spec(
            raw_step,
            step_label,
            require_image_field=send_image,
            allow_templates=True,
            allow_get=True,
        )

        capture = []
        for item in raw_step.get("capture") or []:
            if not isinstance(item, dict):
                raise ValueError(f"{step_label}: capture entries must be objects.")
            var_name = str(item.get("name") or "").strip()
            path = str(item.get("path") or "").strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", var_name):
                raise ValueError(
                    f"{step_label}: capture name '{var_name}' is not a valid variable name "
                    "(use letters, digits and underscores)."
                )
            if var_name in known_vars or any(c["name"] == var_name for c in capture):
                raise ValueError(f"{step_label}: variable '{var_name}' is already defined.")
            if not path:
                raise ValueError(f"{step_label}: capture '{var_name}' needs a response field path.")
            capture.append({"name": var_name, "path": path})

        unknown = sorted(_find_template_refs(spec) - known_vars)
        if unknown:
            rendered = ", ".join("{" + u + "}" for u in unknown)
            raise ValueError(
                f"{step_label}: unknown variable(s) {rendered}. "
                f"Available here: {', '.join(sorted(known_vars))}."
            )

        if send_image:
            image_step_count += 1
        known_vars.update(item["name"] for item in capture)
        steps.append({**spec, "name": name, "capture": capture, "send_image": send_image})

    if image_step_count != 1:
        raise ValueError(
            "Custom Annotator API: exactly one chained step must carry the image "
            "(set send_image on one step)."
        )
    return {"mode": "CHAIN", "steps": steps}


def _render_template(text: str, variables: dict, label: str) -> str:
    """Replace {variable} placeholders. Names are pre-validated at config time,
    so an unknown name here is a bug, not a user error."""

    def repl(match):
        var = match.group(1)
        if var not in variables:
            raise RuntimeError(f"{label}: variable '{{{var}}}' was not captured.")
        return str(variables[var])

    return _TEMPLATE_VAR_RE.sub(repl, str(text))


def parse_custom_annotator_config(raw: Optional[str]) -> dict:
    """Validate the Custom Annotator API settings sent by the UI (JSON string).

    Accepts the flat single-request form, or {"steps": [...]} for a chained
    multi-request flow (for annotators whose upload takes several dependent
    HTTP calls, e.g. Xtreme1's presigned-URL flow or CVAT's
    create-task-then-upload flow).
    """
    if not raw or not str(raw).strip():
        raise ValueError("Custom Annotator API settings are missing.")
    try:
        cfg = json.loads(raw)
    except ValueError:
        raise ValueError("Custom Annotator API settings are not valid JSON.")
    if not isinstance(cfg, dict):
        raise ValueError("Custom Annotator API settings must be a JSON object.")
    steps = cfg.get("steps")
    if isinstance(steps, list) and steps:
        return _validate_chain_config(cfg)
    config = _validate_request_spec(cfg, "Custom Annotator API", require_image_field=True)
    config["mode"] = "SINGLE"
    return config



def deliver_to_custom_annotator(output_path: Path, config: dict) -> dict:
    """Send one protected image to any annotator.

    Single-request mode sends one HTTP request; chain mode (config["mode"] ==
    "CHAIN") runs a sequence of dependent requests where later steps can use
    values captured from earlier responses. `config` must come from
    parse_custom_annotator_config().
    """
    if config.get("mode") == "CHAIN":
        return _deliver_chain(output_path, config)
    if requests is None:
        raise RuntimeError("requests is not installed")

    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(output_path.suffix.lower(), "application/octet-stream")

    headers = {key: value for key, value in config["headers"]}
    params: List[tuple] = list(config["query_params"])

    auth_type = config["auth_type"]
    secret = config["auth_value"]
    if auth_type == "BEARER":
        headers["Authorization"] = f"Bearer {secret}"
    elif auth_type == "API_KEY":
        # "Token <key>" style, used by Label Studio and legacy CVAT keys.
        headers["Authorization"] = f"Token {secret}"
    elif auth_type == "HEADER":
        headers[config["auth_name"]] = secret
    elif auth_type == "QUERY":
        params.append((config["auth_name"], secret))

    def redact(text) -> str:
        text = str(text)
        return text.replace(secret, "***") if secret else text

    image_bytes = output_path.read_bytes()
    request_type = config["request_type"]
    kwargs: dict = {}

    if request_type == "MULTIPART":
        # requests must generate the multipart boundary itself.
        headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
        kwargs["files"] = {config["image_field"]: (output_path.name, image_bytes, mime)}
        kwargs["data"] = config["body_params"]
    elif request_type == "JSON":
        payload = {key: _coerce_json_value(value) for key, value in config["body_params"]}
        encoded = base64.b64encode(image_bytes).decode("ascii")
        payload[config["image_field"]] = (
            f"data:{mime};base64,{encoded}" if config["json_encoding"] == "DATA_URI" else encoded
        )
        kwargs["json"] = payload
    else:  # RAW: the whole body is the image
        if config["raw_encoding"] == "BASE64":
            kwargs["data"] = base64.b64encode(image_bytes)
            default_type = "text/plain"
        else:
            kwargs["data"] = image_bytes
            default_type = mime
        if not any(k.lower() == "content-type" for k in headers):
            headers["Content-Type"] = default_type

    try:
        response = requests.request(
            config["method"],
            config["url"],
            headers=headers,
            params=params,
            timeout=60,
            **kwargs,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Request failed: {redact(exc)}")

    if not 200 <= response.status_code < 300:
        detail = redact(response.text.strip()[:500]) or "No response body."
        raise RuntimeError(f"Annotator returned HTTP {response.status_code}: {detail}")

    _check_success_condition(response, config["success_condition"], redact)
    condition = _parse_success_condition(config["success_condition"])

    parsed_url = urlparse(config["url"])
    return {
        # Query string is left out on purpose: it may carry the API key.
        "url": f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}",
        "method": config["method"],
        "request_type": request_type,
        "status_code": response.status_code,
        "success_condition_checked": bool(condition),
    }


def _check_success_condition(response, condition_text: str, redact, label: str = None) -> None:
    """Evaluate the optional JSON success condition; raise RuntimeError if unmet.

    Shared by the single-request path and every chained step, so both have the
    exact same semantics (including the response-shape hint). `label` is a
    "Step N 'name'" prefix used only in chain mode; single-request messages are
    unchanged.
    """
    prefix = f"{label}: " if label else ""
    condition = _parse_success_condition(condition_text)
    if not condition:
        return
    path, operator, expected = condition
    try:
        body = response.json()
    except ValueError:
        raise RuntimeError(
            f"{prefix}success condition '{condition_text}' is set, but the response was not JSON."
        )
    found, actual = _lookup_dotted_path(body, path)
    if operator == "TRUTHY":
        met = found and bool(actual)
    elif operator == "==":
        met = found and _condition_values_equal(actual, expected)
    else:  # "!=":
        met = (not found) or not _condition_values_equal(actual, expected)
    if not met:
        seen = redact(repr(actual))[:120] if found else "field not found"
        if isinstance(body, dict):
            top_keys = ", ".join(str(k) for k in list(body.keys())[:12])
            shape_hint = f" Response top-level keys: {top_keys}." if top_keys else " Response was an empty JSON object."
        elif isinstance(body, list):
            shape_hint = f" Response was a JSON list with {len(body)} item(s)."
        else:
            shape_hint = f" Response was JSON: {redact(repr(body))[:120]}."
        raise RuntimeError(
            f"{prefix}HTTP {response.status_code} received, but success condition "
            f"'{condition_text}' was not met ({seen}).{redact(shape_hint)}"
        )


def _deliver_chain(output_path: Path, config: dict) -> dict:
    """Run a chained multi-request annotator flow.

    Each step is a full request description (same options as the single-request
    mode). Steps run in order; a step can capture values from its JSON response
    into {variables} that later steps reference in their URL, headers, query or
    body parameters. Exactly one step carries the image (validated at config
    time). All per-step secrets are redacted from error messages.
    """
    if requests is None:
        raise RuntimeError("requests is not installed")

    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(output_path.suffix.lower(), "application/octet-stream")

    image_bytes = output_path.read_bytes()
    variables: dict = {"filename": output_path.name}
    secrets = [step["auth_value"] for step in config["steps"] if step["auth_value"]]

    def redact(text) -> str:
        out = str(text)
        for secret in secrets:
            if secret:
                out = out.replace(secret, "***")
        return out

    results = []
    for index, step in enumerate(config["steps"]):
        label = f"Step {index + 1} '{step['name']}'"

        def render(text):
            return _render_template(text, variables, label)

        url = render(step["url"])
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(f"{label}: rendered URL is not a valid HTTP(S) URL.")

        headers = {key: render(value) for key, value in step["headers"]}
        params = [(key, render(value)) for key, value in step["query_params"]]

        auth_type = step["auth_type"]
        secret = step["auth_value"]
        if auth_type == "BEARER":
            headers["Authorization"] = f"Bearer {secret}"
        elif auth_type == "API_KEY":
            headers["Authorization"] = f"Token {secret}"
        elif auth_type == "HEADER":
            headers[step["auth_name"]] = secret
        elif auth_type == "QUERY":
            params.append((step["auth_name"], secret))

        kwargs: dict = {}
        request_type = step["request_type"]
        if step["send_image"]:
            if request_type == "MULTIPART":
                # requests must generate the multipart boundary itself.
                headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
                kwargs["files"] = {step["image_field"]: (output_path.name, image_bytes, mime)}
                kwargs["data"] = [(key, render(value)) for key, value in step["body_params"]]
            elif request_type == "JSON":
                payload = {
                    key: _coerce_json_value(render(value))
                    for key, value in step["body_params"]
                }
                encoded = base64.b64encode(image_bytes).decode("ascii")
                payload[step["image_field"]] = (
                    f"data:{mime};base64,{encoded}"
                    if step["json_encoding"] == "DATA_URI"
                    else encoded
                )
                kwargs["json"] = payload
            else:  # RAW: the whole body is the image
                if step["raw_encoding"] == "BASE64":
                    kwargs["data"] = base64.b64encode(image_bytes)
                    default_type = "text/plain"
                else:
                    kwargs["data"] = image_bytes
                    default_type = mime
                if not any(k.lower() == "content-type" for k in headers):
                    headers["Content-Type"] = default_type
        else:
            # Setup step: same body options, but without the image.
            if request_type == "MULTIPART":
                kwargs["data"] = [(key, render(value)) for key, value in step["body_params"]]
            elif request_type == "JSON":
                kwargs["json"] = {
                    key: _coerce_json_value(render(value))
                    for key, value in step["body_params"]
                }
            # RAW setup steps send an empty body.

        try:
            response = requests.request(
                step["method"],
                url,
                headers=headers,
                params=params,
                timeout=60,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"{label}: request failed: {redact(exc)}")

        if not 200 <= response.status_code < 300:
            detail = redact(response.text.strip()[:500]) or "No response body."
            raise RuntimeError(f"{label}: annotator returned HTTP {response.status_code}: {detail}")

        _check_success_condition(response, step["success_condition"], redact, label)

        if step["capture"]:
            try:
                body = response.json()
            except ValueError:
                raise RuntimeError(
                    f"{label}: capture is configured, but the response was not JSON."
                )
            for cap in step["capture"]:
                found, value = _lookup_dotted_path(body, cap["path"])
                if not found:
                    raise RuntimeError(
                        f"{label}: could not capture '{cap['name']}': "
                        f"path '{cap['path']}' not found in the response."
                    )
                variables[cap["name"]] = value

        results.append(
            {
                "name": step["name"],
                "method": step["method"],
                # Query string left out on purpose: it may carry a secret.
                "url": f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
                "status_code": response.status_code,
            }
        )

    image_step = next(step["name"] for step in config["steps"] if step["send_image"])
    return {
        "mode": "CHAIN",
        "steps": results,
        "image_step": image_step,
        "status_code": results[-1]["status_code"],
    }

def _http_error(response, label: str):
    detail = response.text.strip()[:800] or f"HTTP {response.status_code}"
    raise RuntimeError(f"{label} failed: HTTP {response.status_code}: {detail}")


def deliver_to_cvat(
    image_path: Path,
    base_url: str,
    token: str,
    project_id: Optional[int] = None,
    task_name: Optional[str] = None,
):
    """Create a CVAT task, upload one image, and verify media using the
    official CVAT Python SDK (cvat-sdk).

    We deliberately use the SDK here instead of hand-built HTTP requests.
    CVAT's REST API has upload-protocol details (chunking, Upload-Start /
    Upload-Finish headers, trailing-slash conventions, etc.) that the
    official web client and SDK both implement correctly, but that are easy
    to get subtly wrong by hand -- which is exactly what was happening
    before. The SDK is maintained by the CVAT team and is exercised
    directly against app.cvat.ai in their own example scripts, so it's the
    most reliable way to talk to both cloud and self-hosted CVAT.
    """
    if make_client is None:
        raise RuntimeError(
            "cvat-sdk is not installed. Run: pip install cvat-sdk --break-system-packages"
        )

    base_url = base_url.rstrip("/")
    parsed = urlparse(base_url)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("CVAT URL must be a valid HTTP or HTTPS URL.")

    if not token:
        raise ValueError("CVAT Personal Access Token is required.")

    if not image_path.exists() or not image_path.is_file():
        raise ValueError(f"CVAT source image does not exist: {image_path}")

    task_spec = {
        "name": task_name or image_path.stem,
        # CVAT requires either labels or a project_id. When the task isn't
        # tied to a project, give it one generic label so creation succeeds
        # even if the user hasn't set up labels yet.
        "labels": [{"name": "object"}] if project_id is None else [],
    }

    if project_id is not None:
        task_spec["project_id"] = int(project_id)
        # If a project is set, CVAT takes labels from the project instead,
        # so an explicit labels list isn't needed (and can conflict).
        task_spec.pop("labels", None)

    try:
        with make_client(host=base_url, access_token=token) as client:
            task = client.tasks.create_from_data(
                spec=task_spec,
                resource_type=ResourceType.LOCAL,
                resources=[str(image_path)],
                # Wait for CVAT's background processing to actually finish
                # (or fail) before returning, instead of firing-and-forgetting.
                data_params={"image_quality": 70},
            )

            # Re-fetch the task to confirm CVAT actually attached media.
            task.fetch()
            task_size = getattr(task, "size", None)

            if not isinstance(task_size, int) or task_size <= 0:
                raise RuntimeError(
                    "CVAT task was created and the upload finished, "
                    "but CVAT reports no attached media."
                )

            return {
                "platform": "CVAT",
                "task_id": task.id,
                "project_id": project_id,
                "verified": True,
                "media_count": task_size,
            }
    except ApiException as exc:
        raise RuntimeError(
            f"CVAT task creation/upload failed: HTTP {exc.status}: {exc.reason or exc.body}"
        )




def get_label_studio_auth_headers(base_url: str, token: str) -> dict:
    """Build the right Authorization header for whichever kind of Label
    Studio token was pasted in.

    Label Studio has two incompatible token types (see
    https://docs.humansignal.com/guide/access_tokens):
      - Legacy Token: sent directly as 'Authorization: Token <token>'.
      - Personal Access Token (PAT) -- the default you get from
        app.humansignal.com, the public hosted site: this is actually a
        JWT *refresh* token, not something you can send directly. You must
        first exchange it via POST /api/token/refresh for a short-lived
        access token, then send THAT as 'Authorization: Bearer <access>'.
        It expires after ~5 minutes.

    We can't tell which kind of token the user pasted in just by looking
    at it, so we try the PAT exchange first; if that fails (e.g. it's
    actually a Legacy Token, which /api/token/refresh will reject), we
    fall back to sending it directly with the classic Token scheme.
    """
    base_url = base_url.rstrip("/")

    try:
        refresh_response = requests.post(
            f"{base_url}/api/token/refresh",
            json={"refresh": token},
            timeout=15,
        )
        if refresh_response.status_code == 200:
            access = (refresh_response.json() or {}).get("access")
            if access:
                return {"Authorization": f"Bearer {access}"}
    except requests.RequestException:
        pass

    return {"Authorization": f"Token {token}"}


def wait_label_studio_import(
    base_url: str,
    auth_headers: dict,
    project_id: int,
    import_id,
    timeout: int = 90,
):
    """Poll Label Studio's async import-status endpoint until it settles.

    Label Studio Cloud / Enterprise ("non-Community" editions -- this is
    what you get on the public app.humansignal.com site, as opposed to a
    self-hosted/Docker Community-edition instance) processes /import
    requests in the background. The POST only ever returns
    `{"import": <id>}`; the *actual* outcome -- including data errors that
    a 200 response would otherwise hide -- only ever shows up on
    GET /api/projects/{project_id}/imports/{import_id}/, which is why we
    poll it here instead of trusting the POST response.
    """
    base_url = base_url.rstrip("/")
    start = time.time()

    while time.time() - start <= timeout:
        response = requests.get(
            f"{base_url}/api/projects/{int(project_id)}/imports/{import_id}/",
            headers=auth_headers,
            timeout=30,
        )
        if response.status_code not in {200, 201}:
            _http_error(response, "Label Studio import status check")

        info = response.json() if response.content else {}
        status = (info.get("status") or "").lower()

        if status == "completed":
            return info
        if status == "failed":
            raise RuntimeError(
                "Label Studio import failed: "
                f"{info.get('error') or 'no error detail returned'}"
            )
        # "created" / "in_progress" -> still processing, keep polling.
        time.sleep(1.5)

    raise TimeoutError(
        f"Label Studio import {import_id} did not finish within {timeout}s."
    )


def deliver_to_label_studio(
    image_path: Path,
    base_url: str,
    token: str,
    project_id: int,
    image_field: str = "image",
):
    """Upload a local image straight into a Label Studio project.

    Label Studio's own docs are explicit that images (unlike plain text)
    must be referenced by URL, not embedded as base64 in a JSON task -- see
    https://labelstud.io/guide/tasks.html ("If you're importing audio,
    image, or video data, you must use URLs to refer to those data types.").
    A base64 data: URI is not a documented/supported path and isn't
    guaranteed to survive Label Studio's own re-export/storage flows.

    The reliable, documented way to hand Label Studio a *local* image file
    is the same one its own "Import" button in the Data Manager uses under
    the hood: POST the raw file as multipart/form-data to
    /api/projects/{id}/import. Label Studio stores the file itself (giving
    it a real, servable URL) and auto-creates one task, matching the file
    to whichever <Image> object tag is configured in the project's
    labeling config. This mirrors how CVAT's SDK uploads the actual local
    file rather than sending bytes inline.

    This has to handle two different response shapes depending on which
    Label Studio you're talking to:
      - Self-hosted Community Edition (localhost / Docker): the import is
        synchronous and the POST itself returns task_count / task_ids.
      - Label Studio's hosted/public site and Enterprise ("non-Community"
        editions): the import is asynchronous. The POST only returns
        {"import": <id>}, and we have to poll the import-status endpoint
        (wait_label_studio_import) to find out whether it actually
        succeeded.

    Note: because Label Studio picks the data key itself from the project
    config, `image_field` has no effect here and is accepted only so
    existing callers of this function don't have to change.
    """
    if requests is None:
        raise RuntimeError("requests is not installed")

    base_url = base_url.rstrip("/")
    parsed = urlparse(base_url)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Label Studio URL must be a valid HTTP or HTTPS URL.")
    if not token:
        raise ValueError("Label Studio access token is required.")
    if project_id is None:
        raise ValueError("Label Studio Project ID is required.")
    if not image_path.exists() or not image_path.is_file():
        raise ValueError(f"Label Studio source image does not exist: {image_path}")

    mime = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
    }.get(image_path.suffix.lower(), "application/octet-stream")

    auth_headers = get_label_studio_auth_headers(base_url, token)

    with open(image_path, "rb") as f:
        response = requests.post(
            f"{base_url}/api/projects/{int(project_id)}/import",
            params={
                "commit_to_project": "true",
                "return_task_ids": "true",
            },
            headers=auth_headers,
            files={"file": (image_path.name, f, mime)},
            timeout=120,
        )

    if response.status_code not in {200, 201}:
        _http_error(response, "Label Studio image import")

    body = response.json() if response.content else {}

    if "import" in body:
        # Public site / Enterprise: async. Poll for the real outcome.
        info = wait_label_studio_import(base_url, auth_headers, project_id, body["import"])
        task_ids = info.get("task_ids") or []
        task_count = info.get("task_count") or 0

        if not task_ids and not task_count:
            raise RuntimeError(
                "Label Studio finished the import but reported no created "
                f"task. Response: {json.dumps(info)[:500]}"
            )

        return {
            "platform": "LABEL_STUDIO",
            "project_id": int(project_id),
            "task_id": task_ids[0] if task_ids else None,
            "verified": True,
            "response": info,
        }

    # Self-hosted Community Edition: sync. The POST already has the answer.
    # Re-fetch-style verification: confirm Label Studio actually reports a
    # created task, the same way deliver_to_cvat() re-fetches the CVAT task
    # to confirm media really attached, instead of trusting a bare 200.
    task_ids = body.get("task_ids") or []
    task_count = body.get("task_count")

    if not task_ids and not task_count:
        raise RuntimeError(
            "Label Studio accepted the upload but did not report a "
            f"created task. Response: {json.dumps(body)[:500]}"
        )

    return {
        "platform": "LABEL_STUDIO",
        "project_id": int(project_id),
        "task_id": task_ids[0] if task_ids else None,
        "verified": True,
        "response": body,
    }


def deliver_to_annotation_platform(
    image_path: Path,
    platform: str,
    platform_url: str,
    platform_token: str,
    dataset_id: Optional[int] = None,
    project_id: Optional[int] = None,
    task_name: Optional[str] = None,
    image_field: str = "image",
):
    platform = (platform or "").strip().upper()
    if platform == "CVAT":
        return deliver_to_cvat(image_path, platform_url, platform_token, project_id, task_name)
    if platform == "XTREME1":
        if dataset_id is None:
            raise ValueError("Xtreme1 Dataset ID is required.")
        return upload_to_xtreme1(image_path, platform_token, int(dataset_id), base_url=platform_url)
    if platform == "LABEL_STUDIO":
        return deliver_to_label_studio(image_path, platform_url, platform_token, int(project_id), image_field)
    raise ValueError("Unsupported annotation platform.")


def _unified_delivery_items(user_id: int) -> List[dict]:
    """Return one delivery queue for both direct uploads and API uploads."""
    items: List[dict] = []

    api_output_names = set()
    for result in RESULTS.get(user_id, []):
        if not result.get("api_delivery"):
            continue
        output_name = Path(result.get("output_path", "")).name
        if output_name:
            api_output_names.add(output_name)

        if result.get("review_status") != "APPROVED":
            continue
        if result.get("delivery_status") in {"DELIVERED", "RETURN_READY"}:
            continue
        output_path = Path(result["output_path"])
        if not output_path.exists():
            continue
        items.append({
            "source": "API",
            "filename": Path(result["input_path"]).name,
            "original_filename": result.get("api_delivery", {}).get("filename", result.get("original_filename")),
            "job_id": result.get("api_delivery", {}).get("api_job_id"),
            "destination": result.get("api_delivery", {}).get("destination", "RETURN"),
            "delivery_status": result.get("delivery_status", "WAITING_FOR_DELIVERY"),
            "output_url": f"/media/output/{output_path.name}",
            "can_return": True,
            "can_xtreme1": True,
        })

    # Direct PrivacyHub uploads use the existing Approved Dataset files.
    # They are eligible for Xtreme1 from this same delivery action, but not
    # for Return Image because there is no calling API application to return to.
    for output_path in sorted(APPROVED_DIR.iterdir()):
        if not output_path.is_file() or output_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        if output_path.name in api_output_names:
            continue
        items.append({
            "source": "PRIVACYHUB",
            "filename": output_path.name,
            "original_filename": output_path.name,
            "job_id": None,
            "destination": "XTREME1",
            "delivery_status": "READY",
            "output_url": f"/media/approved/{output_path.name}",
            "can_return": False,
            "can_xtreme1": True,
        })

    return items


@app.post("/api/annotation/cvat/projects")
def list_cvat_projects(
    platform_url: str = Form(...),
    platform_token: str = Form(...),
    session: Optional[str] = Cookie(None, alias=SESSION_COOKIE),
):
    """List CVAT projects visible to the supplied Personal Access Token.

    The token is used only for this request and is not stored by PrivacyHub.
    """
    current_user(session)
    if requests is None:
        raise HTTPException(status_code=500, detail="requests is not installed")

    base_url = (platform_url or "").strip().rstrip("/")
    token = (platform_token or "").strip()
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="CVAT URL must be a valid HTTP or HTTPS URL.")
    if not token:
        raise HTTPException(status_code=400, detail="CVAT Personal Access Token is required.")

    try:
        response = requests.get(
            f"{base_url}/api/projects",
            headers={"Authorization": f"Bearer {token}"},
            params={"page_size": 100},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Unable to reach CVAT: {exc}")

    if response.status_code != 200:
        detail = response.text.strip()[:500] or f"HTTP {response.status_code}"
        raise HTTPException(status_code=response.status_code, detail=f"CVAT project lookup failed: {detail}")

    try:
        body = response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="CVAT returned an invalid JSON response.")

    projects = body.get("results", body if isinstance(body, list) else [])
    return {
        "projects": [
            {
                "id": project.get("id"),
                "name": project.get("name") or f"Project {project.get('id')}",
                "organization": project.get("organization"),
            }
            for project in projects
            if project.get("id") is not None
        ]
    }


@app.get("/api/delivery/pending")
def unified_delivery_pending(session: Optional[str] = Cookie(None, alias=SESSION_COOKIE)):
    user = current_user(session)
    items = _unified_delivery_items(user["id"])
    return {
        "images": items,
        "counts": {
            "total": len(items),
            "api": sum(item["source"] == "API" for item in items),
            "privacyhub": sum(item["source"] == "PRIVACYHUB" for item in items),
        },
    }


@app.post("/api/delivery/run")
def run_unified_delivery(
    filename: str = Form(...),
    source: str = Form(...),
    destination: str = Form("RETURN"),
    dataset_id: Optional[int] = Form(None),
    annotation_platform: Optional[str] = Form(None),
    platform_url: Optional[str] = Form(None),
    platform_token: Optional[str] = Form(None),
    project_id: Optional[int] = Form(None),
    task_name: Optional[str] = Form(None),
    image_field: Optional[str] = Form(None),
    custom_config: Optional[str] = Form(None),
    x_xtreme1_token: Optional[str] = Header(None, alias="X-Xtreme1-Token"),
    session: Optional[str] = Cookie(None, alias=SESSION_COOKIE),
):
    user = current_user(session)
    source = source.strip().upper()
    destination = destination.strip().upper()

    if source not in {"API", "PRIVACYHUB"}:
        raise HTTPException(status_code=400, detail="Unsupported delivery source.")
    if destination not in {"RETURN", "ANNOTATION", "CUSTOM", "XTREME1"}:
        raise HTTPException(status_code=400, detail="Unsupported delivery destination.")
    custom_settings = None
    if destination == "CUSTOM":
        try:
            custom_settings = parse_custom_annotator_config(custom_config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    if destination == "XTREME1":
        destination = "ANNOTATION"
        annotation_platform = "XTREME1"
        platform_token = (x_xtreme1_token or "").strip()
        platform_url = XTREME1_URL
    if destination == "ANNOTATION":
        annotation_platform = (annotation_platform or "").strip().upper()
        platform_url = (platform_url or "").strip()
        platform_token = (platform_token or "").strip()
        if annotation_platform not in {"CVAT", "XTREME1", "LABEL_STUDIO"}:
            raise HTTPException(status_code=400, detail="Choose CVAT, Xtreme1, or Label Studio.")
        if not platform_url or not platform_token:
            raise HTTPException(status_code=400, detail="Platform URL and access token are required.")
        if annotation_platform == "XTREME1" and dataset_id is None:
            raise HTTPException(status_code=400, detail="Xtreme1 Dataset ID is required.")
        if annotation_platform == "LABEL_STUDIO" and project_id is None:
            raise HTTPException(status_code=400, detail="Label Studio Project ID is required.")
        image_field = (image_field or "image").strip() or "image"
    if destination == "RETURN" and source != "API":
        raise HTTPException(status_code=400, detail="Return Image is available only for images received through the PrivacyHub API.")

    output_path: Optional[Path] = None
    api_result = None

    if source == "API":
        api_result = next(
            (
                r for r in RESULTS.get(user["id"], [])
                if r.get("api_delivery") and Path(r["input_path"]).name == filename
            ),
            None,
        )
        if not api_result:
            raise HTTPException(status_code=404, detail="Approved API image not found.")
        if api_result.get("review_status") != "APPROVED":
            raise HTTPException(status_code=400, detail="Image must be approved before delivery.")
        output_path = Path(api_result["output_path"])
    else:
        output_path = APPROVED_DIR / filename

    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Protected image not found.")

    if destination == "ANNOTATION":
        try:
            annotation_result = deliver_to_annotation_platform(
                image_path=output_path,
                platform=annotation_platform,
                platform_url=platform_url,
                platform_token=platform_token,
                dataset_id=dataset_id,
                project_id=project_id,
                task_name=task_name,
                image_field=image_field or "image",
            )
        except Exception as exc:
            if source == "API" and api_result is not None:
                pending_key = (user["id"], Path(api_result["input_path"]).name)
                pending = PENDING_API_DELIVERIES.setdefault(pending_key, {})
                pending["delivery_status"] = "WAITING_FOR_DELIVERY"
                api_result["delivery_status"] = "WAITING_FOR_DELIVERY"
            raise HTTPException(status_code=502, detail=f"Annotation platform delivery failed: {exc}")

        if source == "API" and api_result is not None:
            pending_key = (user["id"], Path(api_result["input_path"]).name)
            pending = PENDING_API_DELIVERIES.setdefault(pending_key, {})
            pending.update({
                "destination": "ANNOTATION",
                "annotation_platform": annotation_platform,
                "platform_url": platform_url,
                "project_id": project_id,
                "dataset_id": dataset_id,
                "delivery_status": "DELIVERED",
            })
            api_result["delivery_status"] = "DELIVERED"

        if source == "API":
            approved_path = APPROVED_DIR / output_path.name
            if output_path.resolve() != approved_path.resolve():
                shutil.copy2(output_path, approved_path)

        return {
            "success": True,
            "source": source,
            "destination": "ANNOTATION",
            "platform": annotation_platform,
            "delivery_status": "DELIVERED",
            "annotation": annotation_result,
        }

    if destination == "CUSTOM":
        pending = None
        if source == "API" and api_result is not None:
            pending_key = (user["id"], Path(api_result["input_path"]).name)
            pending = PENDING_API_DELIVERIES.setdefault(pending_key, {})
        try:
            custom_result = deliver_to_custom_annotator(output_path, custom_settings)
        except Exception as exc:
            if pending is not None:
                pending["destination"] = "CUSTOM"
                pending["delivery_status"] = "WAITING_FOR_DELIVERY"
                api_result["delivery_status"] = "WAITING_FOR_DELIVERY"
            raise HTTPException(status_code=502, detail=f"Custom Annotator API delivery failed: {exc}")

        if pending is not None:
            pending["destination"] = "CUSTOM"
            pending["custom_url"] = custom_result["url"]
            pending["delivery_status"] = "DELIVERED"
            api_result["delivery_status"] = "DELIVERED"

        # Keep a local approved copy for API-sourced images (PrivacyHub files
        # are already in APPROVED_DIR).
        if source == "API":
            approved_path = APPROVED_DIR / output_path.name
            if output_path.resolve() != approved_path.resolve():
                shutil.copy2(output_path, approved_path)

        return {
            "success": True,
            "source": source,
            "destination": "CUSTOM",
            "delivery_status": "DELIVERED",
            "filename": api_result.get("api_delivery", {}).get("filename") if api_result else output_path.name,
            "custom": custom_result,
        }

    if destination == "XTREME1":
        token = (x_xtreme1_token or "").strip()
        if not token or dataset_id is None:
            raise HTTPException(status_code=400, detail="Xtreme1 Dataset ID and Bearer Token are required.")
        try:
            xtreme_result = upload_to_xtreme1(output_path, token, int(dataset_id))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        if source == "API" and api_result is not None:
            pending_key = (user["id"], Path(api_result["input_path"]).name)
            pending = PENDING_API_DELIVERIES.setdefault(pending_key, {})
            pending["destination"] = "XTREME1"
            pending["dataset_id"] = int(dataset_id)
            pending["delivery_status"] = "DELIVERED"
            api_result["delivery_status"] = "DELIVERED"

        return {
            "success": True,
            "source": source,
            "destination": "XTREME1",
            "delivery_status": "DELIVERED",
            "filename": api_result.get("api_delivery", {}).get("filename") if api_result else output_path.name,
            "xtreme1": xtreme_result,
        }

    # RETURN is intentionally API-only.
    pending_key = (user["id"], Path(api_result["input_path"]).name)
    pending = PENDING_API_DELIVERIES.setdefault(pending_key, {})
    pending["destination"] = "RETURN"
    pending["delivery_status"] = "RETURN_READY"
    api_result["delivery_status"] = "RETURN_READY"
    return {
        "success": True,
        "source": "API",
        "destination": "RETURN",
        "delivery_status": "RETURN_READY",
        "job_id": api_result.get("api_delivery", {}).get("api_job_id"),
    }


# ---------------------------- API delivery queue ----------------------------

@app.get("/api/api-delivery/pending")
def api_delivery_pending(session: Optional[str] = Cookie(None, alias=SESSION_COOKIE)):
    user = current_user(session)
    items = []
    for result in RESULTS.get(user["id"], []):
        if not result.get("api_delivery") or result.get("review_status") != "APPROVED":
            continue
        if result.get("delivery_status") in {"DELIVERED", "RETURN_READY"}:
            continue
        items.append({
            "filename": Path(result["input_path"]).name,
            "original_filename": result.get("api_delivery", {}).get("filename", result.get("original_filename")),
            "job_id": result.get("api_delivery", {}).get("api_job_id"),
            "destination": result.get("api_delivery", {}).get("destination", "RETURN"),
            "delivery_status": result.get("delivery_status", "WAITING_FOR_DELIVERY"),
            "output_url": f"/media/output/{Path(result['output_path']).name}",
        })
    return {"images": items}


@app.post("/api/api-delivery/run")
def run_api_delivery(
    filename: str = Form(...),
    destination: str = Form("RETURN"),
    dataset_id: Optional[int] = Form(None),
    x_xtreme1_token: Optional[str] = Header(None, alias="X-Xtreme1-Token"),
    session: Optional[str] = Cookie(None, alias=SESSION_COOKIE),
):
    user = current_user(session)
    destination = destination.strip().upper()
    if destination not in {"RETURN", "XTREME1"}:
        raise HTTPException(status_code=400, detail="Unsupported delivery destination.")

    result = next((r for r in RESULTS.get(user["id"], []) if r.get("api_delivery") and Path(r["input_path"]).name == filename), None)
    if not result:
        raise HTTPException(status_code=404, detail="Approved API image not found.")
    if result.get("review_status") != "APPROVED":
        raise HTTPException(status_code=400, detail="Image must be approved before delivery.")

    output_path = Path(result["output_path"])
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Protected image not found.")

    pending_key = (user["id"], Path(result["input_path"]).name)
    pending = PENDING_API_DELIVERIES.setdefault(pending_key, {})
    pending["destination"] = destination
    pending["delivery_status"] = "DELIVERING"
    result["delivery_status"] = "DELIVERING"

    try:
        if destination == "XTREME1":
            token = (x_xtreme1_token or "").strip()
            if not token or dataset_id is None:
                raise HTTPException(status_code=400, detail="Xtreme1 Dataset ID and Bearer Token are required.")
            xtreme_result = upload_to_xtreme1(output_path, token, int(dataset_id))
            pending["dataset_id"] = int(dataset_id)
            pending["delivery_status"] = "DELIVERED"
            result["delivery_status"] = "DELIVERED"
            shutil.copy2(output_path, APPROVED_DIR / output_path.name)
            return {"success": True, "destination": "XTREME1", "delivery_status": "DELIVERED", "xtreme1": xtreme_result}

        # RETURN: Run API Delivery makes the protected file available to the
        # calling application through the authenticated result endpoint.
        pending["delivery_status"] = "RETURN_READY"
        result["delivery_status"] = "RETURN_READY"
        shutil.copy2(output_path, APPROVED_DIR / output_path.name)
        return {"success": True, "destination": "RETURN", "delivery_status": "RETURN_READY", "job_id": result.get("api_delivery", {}).get("api_job_id")}
    except HTTPException:
        pending["delivery_status"] = "WAITING_FOR_DELIVERY"
        result["delivery_status"] = "WAITING_FOR_DELIVERY"
        raise
    except Exception as exc:
        pending["delivery_status"] = "WAITING_FOR_DELIVERY"
        result["delivery_status"] = "WAITING_FOR_DELIVERY"
        raise HTTPException(status_code=500, detail=str(exc))


def _find_api_result_for_user(user_id: int, api_job_id: str):
    for result in RESULTS.get(user_id, []):
        if result.get("api_delivery", {}).get("api_job_id") == api_job_id:
            return result
    return None


@app.get("/api/v1/jobs/{api_job_id}")
def api_job_status(api_job_id: str, credentials: Optional[HTTPAuthorizationCredentials] = Security(privacyhub_bearer)):
    authorization = f"{credentials.scheme} {credentials.credentials}" if credentials else None
    if not authorization:
        raise HTTPException(status_code=401, detail="PrivacyHub Bearer token required.")
    user = authenticate_api_token(authorization)
    result = _find_api_result_for_user(user["id"], api_job_id)
    if not result:
        for item in API_INCOMING.get(user["id"], []):
            if item.get("job_id") == api_job_id:
                return {"job_id": api_job_id, "status": "PENDING", "delivery_status": "NOT_READY"}
        raise HTTPException(status_code=404, detail="API job not found.")

    delivery_status = result.get("delivery_status") or "NOT_DELIVERED"
    if result.get("review_status") == "REVIEW":
        status = "REVIEW"
    elif result.get("review_status") == "APPROVED" and delivery_status in {"WAITING_FOR_DELIVERY", "NOT_DELIVERED"}:
        status = "APPROVED_WAITING_FOR_DELIVERY"
    elif delivery_status in {"RETURN_READY", "DELIVERED"}:
        status = "DELIVERED"
    else:
        status = result.get("review_status", "PENDING")
    return {"job_id": api_job_id, "status": status, "delivery_status": delivery_status, "original_filename": result.get("api_delivery", {}).get("filename", result.get("original_filename")), "destination": result.get("api_delivery", {}).get("destination", "RETURN"), "needs_human_review": result.get("review_status") == "REVIEW"}


@app.get("/api/v1/jobs/{api_job_id}/result")
def api_job_result(api_job_id: str, credentials: Optional[HTTPAuthorizationCredentials] = Security(privacyhub_bearer)):
    authorization = f"{credentials.scheme} {credentials.credentials}" if credentials else None
    if not authorization:
        raise HTTPException(status_code=401, detail="PrivacyHub Bearer token required.")
    user = authenticate_api_token(authorization)
    result = _find_api_result_for_user(user["id"], api_job_id)
    if not result:
        raise HTTPException(status_code=404, detail="API job not found.")
    if result.get("delivery_status") != "RETURN_READY":
        raise HTTPException(status_code=409, detail="Protected image is not ready for return delivery.")
    output_path = Path(result["output_path"])
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Protected image not found.")
    return FileResponse(output_path, media_type="application/octet-stream", filename=f"protected_{result.get('api_delivery', {}).get('filename', output_path.name)}", headers={"X-PrivacyHub-Job-ID": api_job_id, "X-PrivacyHub-Delivery": "RETURN"})


# ---------------------------- Xtreme1 ----------------------------


def xtreme_headers(token: str):
    token = token.strip()

    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    return {
        "Authorization": f"Bearer {token}"
    }


def get_dataset_info(
    token: str,
    dataset_id: int,
    base_url: Optional[str] = None,
):
    base_url = (base_url or XTREME1_URL).rstrip("/")
    if requests is None:
        raise RuntimeError(
            "requests is not installed"
        )

    response = requests.get(
        f"{base_url}/api/dataset/info/{dataset_id}",
        headers=xtreme_headers(token),
        timeout=30,
    )

    response.raise_for_status()

    body = response.json()

    if body.get("code") != "OK":
        raise RuntimeError(
            f"Xtreme1 dataset error: {body}"
        )

    return body["data"]


def get_dataset_items(
    token: str,
    dataset_id: int,
    base_url: Optional[str] = None,
):
    base_url = (base_url or XTREME1_URL).rstrip("/")
    if requests is None:
        raise RuntimeError(
            "requests is not installed"
        )

    response = requests.get(
        f"{base_url}/api/data/findByPage",
        params={
            "datasetId": dataset_id,
            "pageNo": 1,
            "pageSize": 1000,
            "sortField": "CREATED_AT",
            "ascOrDesc": "DESC",
        },
        headers=xtreme_headers(token),
        timeout=30,
    )

    response.raise_for_status()

    body = response.json()

    if body.get("code") != "OK":
        raise RuntimeError(
            f"Xtreme1 data query error: {body}"
        )

    return body.get("data") or {}


def object_contains_filename(
    obj,
    filename,
):
    if isinstance(obj, dict):
        for key, value in obj.items():

            if key in {
                "name",
                "originalName",
                "fileName",
            } and str(value) == filename:
                return True

            if object_contains_filename(
                value,
                filename,
            ):
                return True

        return False

    if isinstance(obj, list):
        return any(
            object_contains_filename(
                v,
                filename,
            )
            for v in obj
        )

    return str(obj) == filename


def wait_upload(
    token,
    serial,
    filename,
    timeout=120,
    base_url: Optional[str] = None,
):
    base_url = (base_url or XTREME1_URL).rstrip("/")
    start = time.time()

    while time.time() - start <= timeout:

        response = requests.get(
            f"{base_url}/api/data/findUploadRecordBySerialNumbers",
            params={
                "serialNumbers": serial
            },
            headers=xtreme_headers(token),
            timeout=30,
        )

        response.raise_for_status()

        body = response.json()

        records = body.get("data") or []

        if records:
            record = records[0]

            status = str(
                record.get(
                    "status",
                    "",
                )
            ).upper()

            if status in {
                "FAILED",
                "FAIL",
                "ERROR",
                "INVALID",
            }:
                raise RuntimeError(
                    f"Xtreme1 processing failed for "
                    f"{filename}: "
                    f"{record.get('errorMessage')}"
                )

            if status in {
                "SUCCESS",
                "SUCCEEDED",
                "COMPLETED",
                "COMPLETE",
                "FINISHED",
            }:
                return record

            total = int(
                record.get(
                    "totalDataNum"
                )
                or 0
            )

            parsed = int(
                record.get(
                    "parsedDataNum"
                )
                or 0
            )

            if total > 0 and parsed >= total:
                return record

        time.sleep(2)

    raise TimeoutError(
        f"Xtreme1 processing timed out for {filename}"
    )


def wait_dataset_item(
    token,
    dataset_id,
    filename,
    timeout=120,
    base_url: Optional[str] = None,
):
    base_url = (base_url or XTREME1_URL).rstrip("/")
    start = time.time()

    while time.time() - start <= timeout:

        data = get_dataset_items(
            token,
            dataset_id,
            base_url=base_url,
        )

        for item in data.get(
            "list",
            [],
        ):
            if object_contains_filename(
                item,
                filename,
            ):
                return item

        time.sleep(2)

    raise TimeoutError(
        f"Xtreme1 upload finished, but "
        f"`{filename}` did not appear in "
        f"dataset {dataset_id}"
    )


def upload_to_xtreme1(
    image_path: Path,
    token: str,
    dataset_id: int,
    base_url: Optional[str] = None,
):
    base_url = (base_url or XTREME1_URL).rstrip("/")
    info = get_dataset_info(
        token,
        dataset_id,
        base_url=base_url,
    )

    if str(
        info.get("type", "")
    ).upper() != "IMAGE":
        raise RuntimeError(
            f"Dataset {dataset_id} is "
            f"`{info.get('type')}`, "
            f"not an IMAGE dataset."
        )

    filename = image_path.name

    presign = requests.get(
        f"{base_url}/api/data/generatePresignedUrl",
        params={
            "fileName": filename,
            "datasetId": dataset_id,
        },
        headers=xtreme_headers(token),
        timeout=30,
    )

    presign.raise_for_status()

    body = presign.json()

    if body.get("code") != "OK":
        raise RuntimeError(
            f"Could not generate presigned URL: {body}"
        )

    data = body.get("data") or {}

    presigned_url = data.get(
        "presignedUrl"
    )

    access_url = data.get(
        "accessUrl"
    )

    if not presigned_url or not access_url:
        raise RuntimeError(
            "Xtreme1 did not return both "
            "presignedUrl and accessUrl."
        )

    with open(
        image_path,
        "rb",
    ) as f:

        upload = requests.put(
            presigned_url,
            data=f,
            headers={
                "Content-Type":
                    "application/octet-stream"
            },
            timeout=120,
        )

    if upload.status_code not in {
        200,
        201,
        204,
    }:
        raise RuntimeError(
            "Storage upload failed. "
            f"HTTP {upload.status_code}: "
            f"{upload.text[:500]}"
        )

    register = requests.post(
        f"{base_url}/api/data/upload",
        json={
            "fileUrl": access_url,
            "datasetId": dataset_id,
            "source": "LOCAL",
        },
        headers=xtreme_headers(token),
        timeout=30,
    )

    register.raise_for_status()

    rb = register.json()

    if rb.get("code") != "OK":
        raise RuntimeError(
            f"Xtreme1 registration failed: {rb}"
        )

    serial = rb.get("data")

    if isinstance(serial, dict):
        serial = (
            serial.get("serialNumber")
            or serial.get("serial_number")
            or serial.get("id")
        )

    if not serial:
        raise RuntimeError(
            "Xtreme1 accepted the upload but "
            "did not return an upload serial number."
        )

    record = wait_upload(
        token,
        str(serial),
        filename,
        base_url=base_url,
    )

    item = wait_dataset_item(
        token,
        dataset_id,
        filename,
        base_url=base_url,
    )

    return {
        "filename": filename,
        "dataset_id": dataset_id,
        "dataset_name": info.get(
            "name",
            "Unknown",
        ),
        "serial_number": str(serial),
        "data_item": item,
        "upload_record": record,
    }


@app.get("/api/xtreme1/dataset")
def xtreme_dataset(
    dataset_id: int = DEFAULT_DATASET_ID,
    token: str = "",
    x_xtreme1_token: Optional[str] = Header(
        None,
        alias="X-Xtreme1-Token",
    ),
    session: Optional[str] = Cookie(
        None,
        alias=SESSION_COOKIE,
    ),
):
    current_user(session)

    token = (
        x_xtreme1_token
        or token
    ).strip()

    if not token:
        raise HTTPException(
            status_code=400,
            detail="Xtreme1 Bearer token is empty",
        )

    return get_dataset_info(
        token,
        dataset_id,
    )


@app.post("/api/xtreme1/export")
def xtreme_export(
    dataset_id: int = Form(
        DEFAULT_DATASET_ID
    ),
    token: str = Form(""),
    x_xtreme1_token: Optional[str] = Header(
        None,
        alias="X-Xtreme1-Token",
    ),
    session: Optional[str] = Cookie(
        None,
        alias=SESSION_COOKIE,
    ),
):
    user = current_user(session)

    token = (
        x_xtreme1_token
        or token
    ).strip()

    if not token:
        raise HTTPException(
            status_code=400,
            detail="Please enter your Xtreme1 Bearer token.",
        )

    approved = sorted(
        [
            p
            for p in APPROVED_DIR.iterdir()
            if p.is_file()
            and p.suffix.lower()
            in {
                ".jpg",
                ".jpeg",
                ".png",
                ".webp",
            }
        ]
    )

    if not approved:
        raise HTTPException(
            status_code=400,
            detail="No approved images available.",
        )

    results = []

    for image_path in approved:
        try:
            results.append(
                upload_to_xtreme1(
                    image_path,
                    token,
                    int(dataset_id),
                )
            )

        except Exception as exc:
            results.append(
                {
                    "filename": image_path.name,
                    "success": False,
                    "error": str(exc),
                }
            )

    return {
        "results": results,
        "successful": sum(
            bool(r.get("data_item"))
            for r in results
        ),
        "failed": sum(
            not bool(r.get("data_item"))
            for r in results
        ),
    }


# ---------------------------- home ----------------------------


@app.get("/")
def index():
    return FileResponse(
        Path(__file__).parent
        / "static"
        / "index.html"
    )


init_database()


# Warm up the ML models in the background so they're already loaded by the
# time the first "Protect Images" click happens, instead of blocking on it.
threading.Thread(
    target=get_engine,
    daemon=True,
).start()