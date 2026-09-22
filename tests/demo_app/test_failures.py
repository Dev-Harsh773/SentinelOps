"""Tests for the controlled failure system and administrative failure toggles."""


def test_failure_admin_endpoints(client):
    """Verify getting failure status, enabling, and disabling failure mode."""
    # Initially disabled
    res = client.get("/admin/failures")
    assert res.status_code == 200
    assert res.json()["order_processing_error"] is False

    # Enable
    res_enable = client.post("/admin/failures/order-processing/enable")
    assert res_enable.status_code == 200
    assert res_enable.json()["order_processing_error"] is True

    # Verify status changed
    res_status = client.get("/admin/failures")
    assert res_status.json()["order_processing_error"] is True

    # Disable
    res_disable = client.post("/admin/failures/order-processing/disable")
    assert res_disable.status_code == 200
    assert res_disable.json()["order_processing_error"] is False


def test_controlled_order_processing_failure_lifecycle(client):
    """Key integration test verifying the full reversible controlled-failure lifecycle:

    1. Failure disabled -> POST /orders returns 201 Created.
    2. Failure enabled -> Same valid POST /orders returns 500 with X-Request-ID.
    3. GET /health while failure enabled -> Remains 200 OK.
    4. Failure disabled again -> Same valid POST /orders returns 201 Created again.
    """
    valid_payload = {"product_id": "p1", "quantity": 1}

    # Step 1: Normal operation
    res_normal = client.post("/orders", json=valid_payload)
    assert res_normal.status_code == 201
    assert "x-request-id" in res_normal.headers

    # Step 2: Enable failure mode
    client.post("/admin/failures/order-processing/enable")

    # Step 3: Trigger controlled failure
    res_failure = client.post("/orders", json=valid_payload)
    assert res_failure.status_code == 500
    assert res_failure.json() == {"detail": "Order processing failed."}
    # Request ID must be present in the 500 failure response for correlation
    assert "x-request-id" in res_failure.headers
    assert len(res_failure.headers["x-request-id"]) > 0

    # Step 4: Health remains independent and operational
    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "ok"

    # Step 5: Disable failure mode
    client.post("/admin/failures/order-processing/disable")

    # Step 6: Verify full recovery
    res_recovered = client.post("/orders", json=valid_payload)
    assert res_recovered.status_code == 201
    assert res_recovered.json()["status"] == "created"


def test_missing_product_returns_404_even_when_failure_is_enabled(client):
    """Verify product validation precedes failure mode evaluation.

    An invalid product must return 404 rather than 500, even if the controlled
    failure mode happens to be active.
    """
    client.post("/admin/failures/order-processing/enable")
    invalid_payload = {"product_id": "non_existent_sku", "quantity": 1}

    response = client.post("/orders", json=invalid_payload)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
