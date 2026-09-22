"""Tests for the demo application product catalog endpoints."""


def test_list_products(client):
    """Verify listing products returns all pre-populated items."""
    response = client.get("/products")
    assert response.status_code == 200
    products = response.json()
    assert len(products) >= 2
    ids = [p["id"] for p in products]
    assert "p1" in ids
    assert "p2" in ids


def test_get_product_by_id(client):
    """Verify retrieving a known product returns 200 with accurate price in minor units."""
    response = client.get("/products/p1")
    assert response.status_code == 200
    product = response.json()
    assert product["id"] == "p1"
    assert product["name"] == "Keyboard"
    assert product["price"] == 2499


def test_get_unknown_product_returns_404(client):
    """Verify requesting an unknown product returns 404."""
    response = client.get("/products/non_existent_product")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
