import asyncio
from time import perf_counter

from mcp_server.backend_client import backend_client


async def timed_request(
    name: str,
    path: str,
) -> None:
    started = perf_counter()

    result = await backend_client.request(
        method="GET",
        path=path,
    )

    elapsed = perf_counter() - started

    print(
        f"{name}: {elapsed:.2f}s"
    )
    print(result)


async def main() -> None:
    await timed_request(
        "Health request 1",
        "/health/live",
    )

    await timed_request(
        "Provider request 1",
        "/api/v1/providers/current",
    )

    await timed_request(
        "Provider request 2",
        "/api/v1/providers/current",
    )


if __name__ == "__main__":
    asyncio.run(main())