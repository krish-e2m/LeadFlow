import asyncio

from arq.connections import RedisSettings, create_pool
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine


async def test_postgres():
    print(f"Testing PostgreSQL connection to: {settings.DATABASE_URL}")
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            print("PostgreSQL connection SUCCESSFUL! Result:", result.scalar())
            return True
    except Exception as e:
        print(f"PostgreSQL connection FAILED: {type(e).__name__}: {e}")
        return False


async def test_redis():
    print(f"Testing Redis connection to: {settings.REDIS_URL}")
    try:
        redis_pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
        await redis_pool.ping()
        print("Redis connection SUCCESSFUL!")
        await redis_pool.close()
        return True
    except Exception as e:
        print(f"Redis connection FAILED: {type(e).__name__}: {e}")
        return False


async def main():
    pg_ok = await test_postgres()
    redis_ok = await test_redis()
    print("\n--- Summary ---")
    print(f"PostgreSQL: {'OK' if pg_ok else 'UNAVAILABLE'}")
    print(f"Redis:      {'OK' if redis_ok else 'UNAVAILABLE'}")


if __name__ == "__main__":
    asyncio.run(main())
