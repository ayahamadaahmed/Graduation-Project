import asyncio

from mcp_server.backend_client import (
    BackendClient,
)


class FakeResponse:

    is_success = True
    content = b"{}"
    status_code = 200

    def json(
        self,
    ):
        return {}


class FakeAsyncClient:

    instances = []

    def __init__(
        self,
        *args,
        **kwargs,
    ):
        self.request_calls = 0
        self.close_calls = 0

        self.__class__.instances.append(
            self
        )

    async def request(
        self,
        *args,
        **kwargs,
    ):
        self.request_calls += 1

        return FakeResponse()

    async def aclose(
        self,
    ):
        self.close_calls += 1


def test_backend_client_reuses_single_http_client(
    monkeypatch,
):

    FakeAsyncClient.instances.clear()

    monkeypatch.setattr(
        "mcp_server.backend_client.httpx.AsyncClient",
        FakeAsyncClient,
    )

    client = BackendClient()

    async def scenario():

        # Startup twice should still create
        # only one AsyncClient.
        await client.start()
        await client.start()

        assert (
            len(
                FakeAsyncClient.instances
            )
            == 1
        )

        underlying_client = (
            FakeAsyncClient.instances[0]
        )

        # Two Backend requests should reuse
        # the same HTTP client.
        await client.request(
            tenant_id="clinic-001",
            method="GET",
            path="/api/v1/specialties",
        )

        await client.request(
            tenant_id="clinic-001",
            method="GET",
            path="/api/v1/doctors",
        )

        assert (
            underlying_client.request_calls
            == 2
        )

        # Shutdown twice should close
        # the underlying client once.
        await client.close()
        await client.close()

        assert (
            underlying_client.close_calls
            == 1
        )

    asyncio.run(
        scenario()
    )


def test_backend_client_requires_start():

    client = BackendClient()

    async def scenario():

        try:

            await client.request(
                tenant_id="clinic-001",
                method="GET",
                path="/api/v1/specialties",
            )

        except RuntimeError as exc:

            assert (
                "has not been started"
                in str(exc)
            )

        else:

            raise AssertionError(
                "Expected request before start "
                "to fail."
            )

    asyncio.run(
        scenario()
    )