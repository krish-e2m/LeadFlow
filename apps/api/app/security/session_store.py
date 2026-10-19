import time
from typing import Optional, Tuple

import redis.asyncio as aioredis
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.logging import logger

_redis_client: Optional[aioredis.Redis] = None


def get_redis_client() -> aioredis.Redis:
    """Returns or lazily initializes the async Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def close_redis_client() -> None:
    """Gracefully closes the Redis client connection pool."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


class SessionStore:
    """
    Manages session lifecycle, refresh-token rotation, and token revocation via Redis.
    Guarantees strict fail-closed enforcement when revocation state cannot be verified.
    """

    @classmethod
    async def register_refresh_token(
        cls, user_id: str, jti: str, family_id: str, ttl_seconds: Optional[int] = None
    ) -> None:
        """Register a freshly issued refresh token in Redis."""
        ttl = ttl_seconds or (settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)
        try:
            r = get_redis_client()
            pipe = r.pipeline()
            # Store token under its jti
            pipe.set(f"auth:refresh:{user_id}:{jti}", family_id, ex=ttl)
            # Track active token in family
            pipe.set(f"auth:family:{family_id}", jti, ex=ttl)
            await pipe.execute()
        except Exception as e:
            logger.error(f"Failed to register refresh token in Redis: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service temporarily unavailable.",
            ) from e

    @classmethod
    async def rotate_refresh_token(
        cls, user_id: str, old_jti: str, family_id: str, new_jti: str
    ) -> Tuple[bool, str]:
        """
        Rotates an existing refresh token.
        Detects token reuse: if old_jti is no longer active, the entire family is invalidated.
        Returns: (success: bool, reason_or_status: str)
        """
        try:
            r = get_redis_client()
            token_key = f"auth:refresh:{user_id}:{old_jti}"
            family_key = f"auth:family:{family_id}"

            # Check if this token is currently active
            stored_family = await r.get(token_key)
            active_jti = await r.get(family_key)

            if not stored_family or active_jti != old_jti:
                # Token Reuse Detected! An old or invalid token was presented.
                # Invalidate entire token family to protect against replay attacks.
                logger.warning(
                    f"Refresh token reuse detected for user {user_id}, family {family_id}. Revoking family."
                )
                await r.delete(family_key)
                # Mark family as compromised
                await r.set(f"auth:compromised_family:{family_id}", "true", ex=86400)
                return False, "REUSE_DETECTED"

            # Check if family is marked compromised
            if await r.get(f"auth:compromised_family:{family_id}"):
                return False, "COMPROMISED_FAMILY"

            ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
            pipe = r.pipeline()
            # Invalidate old token immediately
            pipe.delete(token_key)
            # Register new token in family
            pipe.set(f"auth:refresh:{user_id}:{new_jti}", family_id, ex=ttl)
            pipe.set(family_key, new_jti, ex=ttl)
            await pipe.execute()

            return True, "ROTATED"
        except Exception as e:
            logger.error(f"Failed to rotate refresh token in Redis: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication session store temporarily unavailable.",
            ) from e

    @classmethod
    async def revoke_refresh_token(cls, user_id: str, jti: str) -> None:
        """Revokes a specific refresh token."""
        try:
            r = get_redis_client()
            token_key = f"auth:refresh:{user_id}:{jti}"
            family_id = await r.get(token_key)
            pipe = r.pipeline()
            pipe.delete(token_key)
            if family_id:
                pipe.delete(f"auth:family:{family_id}")
            await pipe.execute()
        except Exception as e:
            logger.error(f"Failed to revoke refresh token: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication session store unavailable.",
            ) from e

    @classmethod
    async def revoke_access_token(cls, access_jti: str, remaining_seconds: int = 900) -> None:
        """Adds an access token jti to the blocklist until its natural expiration."""
        try:
            r = get_redis_client()
            await r.set(f"auth:revoked_access:{access_jti}", "true", ex=max(remaining_seconds, 60))
        except Exception as e:
            logger.error(f"Failed to blocklist access token: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication session store unavailable.",
            ) from e

    @classmethod
    async def invalidate_all_user_sessions(cls, user_id: str) -> None:
        """
        Invalidates all existing tokens for a user (used on password change/reset).
        Records a timestamp: tokens issued before this timestamp are rejected.
        """
        try:
            r = get_redis_client()
            now_ts = int(time.time())
            ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
            await r.set(f"auth:user_revoked_before:{user_id}", str(now_ts), ex=ttl)
        except Exception as e:
            logger.error(f"Failed to invalidate user sessions in Redis: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication session store unavailable.",
            ) from e

    @classmethod
    async def is_access_token_revoked(cls, user_id: str, access_jti: str, iat: int) -> bool:
        """
        Verifies whether an access token has been revoked or invalidated.
        Fails closed if Redis is unavailable.
        """
        try:
            r = get_redis_client()
            pipe = r.pipeline()
            pipe.get(f"auth:revoked_access:{access_jti}")
            pipe.get(f"auth:user_revoked_before:{user_id}")
            results = await pipe.execute()

            is_blocklisted, revoked_before_str = results
            if is_blocklisted:
                return True

            if revoked_before_str:
                revoked_before = int(revoked_before_str)
                if iat <= revoked_before:
                    return True

            return False
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Redis unavailable during revocation check: {e}")
            # Fail closed: reject authentication if revocation check cannot complete
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Security validation service unavailable.",
            ) from e

    @classmethod
    async def set_org_suspended(cls, org_id: str, suspended: bool) -> None:
        """Sets or clears the organization suspension flag in Redis."""
        try:
            r = get_redis_client()
            key = f"auth:org_suspended:{org_id}"
            if suspended:
                await r.set(key, "true")
            else:
                await r.delete(key)
        except Exception as e:
            logger.error(f"Failed to update org suspension flag in Redis: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Organization status synchronization service unavailable.",
            ) from e

    @classmethod
    async def is_org_suspended(cls, org_id: str) -> bool:
        """Checks if an organization is flagged as suspended in Redis."""
        try:
            r = get_redis_client()
            val = await r.get(f"auth:org_suspended:{org_id}")
            return bool(val == "true")
        except Exception as e:
            logger.error(f"Failed to check org suspension in Redis: {e}")
            # Fail closed: treat as suspended/unavailable if verification fails
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Security status verification service unavailable.",
            ) from e
