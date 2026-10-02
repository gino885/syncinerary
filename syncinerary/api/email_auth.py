"""Password hashing, bounded authentication attempts, and SMTP delivery."""
import asyncio
import hashlib
import secrets
import smtplib
import ssl
from email.message import EmailMessage

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, Request
from redis.exceptions import RedisError

from syncinerary.config import settings
from syncinerary.store.redis import get_redis

_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
_dummy_hash = _hasher.hash(secrets.token_urlsafe(32))
_hash_slots = asyncio.Semaphore(4)



async def hash_password(password: str) -> str:
    async with _hash_slots:
        return await asyncio.to_thread(_hasher.hash, password)


async def check_password(password: str, encoded: str | None) -> bool:
    def check():
        try:
            return _hasher.verify(encoded or _dummy_hash, password) and encoded is not None
        except (VerificationError, InvalidHashError):
            return False
    async with _hash_slots:
        return await asyncio.to_thread(check)


# INCR and expiry share one atomic script, including the first request.
RATE_NAMESPACE = "auth:attempts"

_RATE = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return {n, redis.call('TTL', KEYS[1])}
"""


async def rate_limit(request: Request, email: str, action: str) -> None:
    host = request.client.host if request.client else "unknown"
    # Do not trust a user-supplied X-Forwarded-For. Configure uvicorn's trusted
    # proxy IPs when deploying behind a reverse proxy.
    keys = [(f"ip:{host}", 120), (f"{action}:{email}", 5 if action != "login" else 10)]
    try:
        for value, limit in keys:
            digest = hashlib.sha256(value.encode()).hexdigest()
            count, ttl = await get_redis().eval(_RATE, 1, f"{RATE_NAMESPACE}:{digest}", 900)
            if count > limit:
                raise HTTPException(429, "Too many attempts. Try again later.",
                                    headers={"Retry-After": str(max(ttl, 1))})
    except RedisError as exc:
        raise HTTPException(503, "Sign-in is temporarily unavailable. Try again shortly.") from exc


async def send_code(email: str, code: str, purpose: str) -> None:
    """Never log codes or return them in API responses. Plain SMTP is local only."""
    if not settings.smtp_host or not settings.smtp_from:
        raise HTTPException(503, "Email delivery is not configured. Contact the app owner.")
    if settings.smtp_security == "plain" and settings.smtp_host not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(503, "Email delivery needs a secure SMTP connection.")
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = email
    message["Subject"] = "Reset your Syncinerary password" if purpose == "reset" else "Verify your Syncinerary email"
    message.set_content(
        f"Your Syncinerary code is: {code}\n\n"
        "Enter this code in the app. It expires in 15 minutes and works once.\n"
        "Never share this code. If you did not request it, ignore this email.\n"
    )

    def deliver():
        transport = smtplib.SMTP_SSL if settings.smtp_security == "tls" else smtplib.SMTP
        kwargs = {"timeout": 10}
        if settings.smtp_security == "tls":
            kwargs["context"] = ssl.create_default_context()
        with transport(settings.smtp_host, settings.smtp_port, **kwargs) as smtp:
            if settings.smtp_security == "starttls":
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            smtp.send_message(message)
    try:
        await asyncio.to_thread(deliver)
    except (OSError, smtplib.SMTPException) as exc:
        raise HTTPException(503, "Could not send the email. Try again shortly.") from exc
