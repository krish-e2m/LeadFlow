import asyncio

from app.providers.manager import provider_manager


async def main():
    statuses = await provider_manager.get_all_provider_statuses()
    print("--- Provider Configuration & Health Report ---")
    for s in statuses:
        print(f"[{s.name}]")
        print(f"  is_configured:  {s.is_configured}")
        print(f"  is_healthy:     {s.is_healthy}")
        print(f"  status_message: {s.status_message}")


if __name__ == "__main__":
    asyncio.run(main())
