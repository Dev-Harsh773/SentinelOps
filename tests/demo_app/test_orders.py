"""Tests for the demo application order creation endpoints under normal operation."""


def test_create_order_success(client):
    """Verify placing a valid order computes total correctly in minor units and returns 201."""
    payload = {"product_id": "p1", "quantity": 2}
    response = client.post("/orders", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "order_id" in data and len(data["order_id"]) > 0
    assert data["product_id"] == "p1"
    assert data["quantity"] == 2
    # 2 * 2499 = 4998 minor units
    assert data["total"] == 4998
    assert data["status"] == "created"
    assert "x-request-id" in response.headers


def test_create_order_unknown_product_returns_404(client):
    """Verify attempting to order a non-existent product returns 404."""
    payload = {"product_id": "invalid_product_99", "quantity": 1}
    response = client.post("/orders", json=payload)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_create_order_invalid_quantity_rejected(client):
    """Verify non-positive quantities are rejected with HTTP 422."""
    for invalid_qty in [0, -1, -5]:
        response = client.post("/orders", json={"product_id": "p1", "quantity": invalid_qty})
        assert response.status_code == 422
