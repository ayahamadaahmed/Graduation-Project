import asyncio
import os
import time

from dotenv import load_dotenv

from langchain_mcp_adapters.client import (
    MultiServerMCPClient,
)

from langchain_mcp_adapters.tools import (
    load_mcp_tools,
)


def find_tool(
    tools,
    name: str,
):
    for tool in tools:
        if tool.name == name:
            return tool

    raise RuntimeError(
        f"Tool not found: {name}"
    )


async def timed_call(
    label: str,
    tool,
):
    started = time.perf_counter()

    await tool.ainvoke(
        {}
    )

    elapsed_ms = (
        time.perf_counter()
        - started
    ) * 1000

    print(
        f"{label:<32} "
        f"{elapsed_ms:8.2f} ms"
    )

    return elapsed_ms


async def main():

    load_dotenv(
        override=True
    )

    tenant_id = os.getenv(
        "TENANT_ID",
        "clinic-001",
    )

    mcp_url = os.getenv(
        "MCP_URL",
        "http://127.0.0.1:9000/mcp",
    )

    client = MultiServerMCPClient(
        {
            "healthcare": {
                "transport": "http",
                "url": mcp_url,
                "headers": {
                    # Agent -> MCP credential (MCP_AUTH_MODE).
                    **(
                        {"X-MedMind-Service-Token": os.environ["MCP_SERVER_TOKEN"]}
                        if os.getenv("MCP_SERVER_TOKEN")
                        else {}
                    ),
                    "X-Tenant-ID":
                        tenant_id,
                },
            }
        }
    )

    print()
    print("=" * 70)
    print("EPHEMERAL SESSION")
    print("=" * 70)

    ephemeral_tools = await (
        client.get_tools()
    )

    ephemeral_specialties = (
        find_tool(
            ephemeral_tools,
            "list_specialties",
        )
    )

    # Warm-up
    await timed_call(
        "ephemeral warmup",
        ephemeral_specialties,
    )

    ephemeral_results = []

    for index in range(
        1,
        6,
    ):
        elapsed = await timed_call(
            f"ephemeral #{index}",
            ephemeral_specialties,
        )

        ephemeral_results.append(
            elapsed
        )

    print()
    print("=" * 70)
    print("PERSISTENT SESSION")
    print("=" * 70)

    async with client.session(
        "healthcare"
    ) as session:

        persistent_tools = await (
            load_mcp_tools(
                session,
                server_name="healthcare",
            )
        )

        persistent_specialties = (
            find_tool(
                persistent_tools,
                "list_specialties",
            )
        )

        # Warm-up
        await timed_call(
            "persistent warmup",
            persistent_specialties,
        )

        persistent_results = []

        for index in range(
            1,
            6,
        ):
            elapsed = await timed_call(
                f"persistent #{index}",
                persistent_specialties,
            )

            persistent_results.append(
                elapsed
            )

    ephemeral_avg = (
        sum(
            ephemeral_results
        )
        / len(
            ephemeral_results
        )
    )

    persistent_avg = (
        sum(
            persistent_results
        )
        / len(
            persistent_results
        )
    )

    improvement_ms = (
        ephemeral_avg
        - persistent_avg
    )

    improvement_percent = (
        (
            improvement_ms
            / ephemeral_avg
        )
        * 100
        if ephemeral_avg
        else 0
    )

    print()
    print("=" * 70)
    print("RESULT")
    print("=" * 70)

    print(
        f"Ephemeral average : "
        f"{ephemeral_avg:.2f} ms"
    )

    print(
        f"Persistent average: "
        f"{persistent_avg:.2f} ms"
    )

    print(
        f"Saved             : "
        f"{improvement_ms:.2f} ms"
    )

    print(
        f"Improvement       : "
        f"{improvement_percent:.1f}%"
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )