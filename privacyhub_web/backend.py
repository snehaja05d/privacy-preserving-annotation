from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import Cookie, FastAPI, File, Form, Header, HTTPException, UploadFile, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


try:
    import requests
except ImportError:
    requests = None


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / "privacy_module" / "input"
OUTPUT_DIR = PROJECT_ROOT / "privacy_module" / "output"
APPROVED_DIR = PROJECT_ROOT / "privacy_module" / "review" / "approved"
DATABASE_DIR = PROJECT_ROOT / "database"
DATABASE_PATH = DATABASE_DIR / "privacy.db"
XTREME1_URL = "http://localhost:8190"
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

            result["input_path"] = str(input_path)
            result["output_path"] = str(output_path)
            result["original_filename"] = filename

            api_meta = api_metadata[index - 1] if index - 1 < len(api_metadata) else None
            if api_meta:
                result["api_delivery"] = {
                    "destination": api_meta.get("destination", "RETURN"),
                    "dataset_id": api_meta.get("dataset_id"),
                    "filename": api_meta.get("original_filename", filename),
                    "api_job_id": api_meta.get("job_id"),
                }
                PENDING_API_DELIVERIES[(user_id, input_path.name)] = {
                    "destination": api_meta.get("destination", "RETURN"),
                    "dataset_id": api_meta.get("dataset_id"),
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
            "XTREME1",
            "WEBHOOK",
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
    x_xtreme1_token: Optional[str] = Header(None, alias="X-Xtreme1-Token"),
    session: Optional[str] = Cookie(None, alias=SESSION_COOKIE),
):
    user = current_user(session)
    source = source.strip().upper()
    destination = destination.strip().upper()

    if source not in {"API", "PRIVACYHUB"}:
        raise HTTPException(status_code=400, detail="Unsupported delivery source.")
    if destination not in {"RETURN", "XTREME1", "WEBHOOK"}:
        raise HTTPException(status_code=400, detail="Unsupported delivery destination.")
    if destination == "WEBHOOK":
        raise HTTPException(status_code=400, detail="Webhook delivery is coming soon.")
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
    if destination not in {"RETURN", "XTREME1", "WEBHOOK"}:
        raise HTTPException(status_code=400, detail="Unsupported delivery destination.")
    if destination == "WEBHOOK":
        raise HTTPException(status_code=400, detail="Webhook delivery is coming soon.")

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
):
    if requests is None:
        raise RuntimeError(
            "requests is not installed"
        )

    response = requests.get(
        f"{XTREME1_URL}/api/dataset/info/{dataset_id}",
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
):
    if requests is None:
        raise RuntimeError(
            "requests is not installed"
        )

    response = requests.get(
        f"{XTREME1_URL}/api/data/findByPage",
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
):
    start = time.time()

    while time.time() - start <= timeout:

        response = requests.get(
            f"{XTREME1_URL}/api/data/findUploadRecordBySerialNumbers",
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
):
    start = time.time()

    while time.time() - start <= timeout:

        data = get_dataset_items(
            token,
            dataset_id,
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
):
    info = get_dataset_info(
        token,
        dataset_id,
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
        f"{XTREME1_URL}/api/data/generatePresignedUrl",
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
        f"{XTREME1_URL}/api/data/upload",
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
    )

    item = wait_dataset_item(
        token,
        dataset_id,
        filename,
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