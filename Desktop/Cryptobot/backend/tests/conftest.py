import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_openapi_docs(client: AsyncClient):
    response = await client.get("/api/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert data["info"]["title"] == "TBX Trade Terminal"
