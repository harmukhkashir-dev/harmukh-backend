"""
Backend API Tests for Orders Endpoints
Tests: POST /api/orders, GET /api/orders/:id, GET /api/auth/orders
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://kashmir-shop-preview.preview.emergentagent.com')


class TestOrdersAPI:
    """Test suite for Orders API endpoints"""
    
    def test_create_order_success(self, api_client):
        """Test POST /api/orders creates an order"""
        # First get a valid product
        products_response = api_client.get(f"{BASE_URL}/api/products")
        products = products_response.json()
        product = products[0]
        
        order_data = {
            "items": [
                {"product_id": product["id"], "quantity": 2}
            ],
            "guest_details": {
                "name": "Test Customer",
                "email": "testcustomer@example.com",
                "phone": "9876543210",
                "address": "123 Test Street",
                "city": "Test City",
                "state": "Test State",
                "pincode": "123456"
            }
        }
        
        response = api_client.post(f"{BASE_URL}/api/orders", json=order_data)
        assert response.status_code == 200
        order = response.json()
        
        assert "id" in order
        assert "order_number" in order
        assert order["order_number"].startswith("HK")
        assert len(order["items"]) == 1
        assert order["items"][0]["product_id"] == product["id"]
        assert order["items"][0]["quantity"] == 2
        assert order["payment_status"] == "pending"
        assert order["order_status"] == "pending"
        
        # Verify pricing
        assert order["subtotal"] == product["price"] * 2
        assert order["total_amount"] == order["subtotal"] + order["shipping_fee"]
        
        return order["id"]
    
    def test_create_order_multiple_items(self, api_client):
        """Test POST /api/orders with multiple items"""
        products_response = api_client.get(f"{BASE_URL}/api/products")
        products = products_response.json()
        
        order_data = {
            "items": [
                {"product_id": products[0]["id"], "quantity": 1},
                {"product_id": products[1]["id"], "quantity": 2}
            ],
            "guest_details": {
                "name": "Multi Item Customer",
                "email": "multiitem@example.com",
                "phone": "9876543211",
                "address": "456 Multi Street",
                "city": "Multi City",
                "state": "Multi State",
                "pincode": "654321"
            }
        }
        
        response = api_client.post(f"{BASE_URL}/api/orders", json=order_data)
        assert response.status_code == 200
        order = response.json()
        
        assert len(order["items"]) == 2
        expected_subtotal = (products[0]["price"] * 1) + (products[1]["price"] * 2)
        assert order["subtotal"] == expected_subtotal
    
    def test_create_order_invalid_product(self, api_client):
        """Test POST /api/orders with invalid product ID returns 404"""
        order_data = {
            "items": [
                {"product_id": "invalid-product-id-xyz", "quantity": 1}
            ],
            "guest_details": {
                "name": "Test Customer",
                "email": "test@example.com",
                "phone": "9876543210",
                "address": "123 Test Street",
                "city": "Test City",
                "state": "Test State",
                "pincode": "123456"
            }
        }
        
        response = api_client.post(f"{BASE_URL}/api/orders", json=order_data)
        assert response.status_code == 404
    
    def test_get_order_by_id(self, api_client):
        """Test GET /api/orders/:id returns order details"""
        # First create an order
        products_response = api_client.get(f"{BASE_URL}/api/products")
        products = products_response.json()
        
        order_data = {
            "items": [
                {"product_id": products[0]["id"], "quantity": 1}
            ],
            "guest_details": {
                "name": "Get Order Test",
                "email": "getorder@example.com",
                "phone": "9876543212",
                "address": "789 Get Street",
                "city": "Get City",
                "state": "Get State",
                "pincode": "789012"
            }
        }
        
        create_response = api_client.post(f"{BASE_URL}/api/orders", json=order_data)
        created_order = create_response.json()
        order_id = created_order["id"]
        
        # Get the order
        response = api_client.get(f"{BASE_URL}/api/orders/{order_id}")
        assert response.status_code == 200
        order = response.json()
        
        assert order["id"] == order_id
        assert order["order_number"] == created_order["order_number"]
    
    def test_get_order_not_found(self, api_client):
        """Test GET /api/orders/:id with invalid ID returns 404"""
        response = api_client.get(f"{BASE_URL}/api/orders/invalid-order-id-xyz")
        assert response.status_code == 404
    
    def test_get_user_orders(self, authenticated_client):
        """Test GET /api/auth/orders returns user orders"""
        client, user_data = authenticated_client
        
        response = client.get(f"{BASE_URL}/api/auth/orders")
        assert response.status_code == 200
        orders = response.json()
        
        assert isinstance(orders, list)
        # May be empty if user hasn't placed any orders yet
    
    def test_get_user_orders_unauthenticated(self, api_client):
        """Test GET /api/auth/orders without auth returns 401"""
        response = api_client.get(f"{BASE_URL}/api/auth/orders")
        assert response.status_code == 401
    
    def test_free_shipping_threshold(self, api_client):
        """Test free shipping for orders over 500"""
        products_response = api_client.get(f"{BASE_URL}/api/products")
        products = products_response.json()
        
        # Find a product that when ordered in quantity results in subtotal >= 500
        high_value_product = None
        for p in products:
            if p["price"] >= 500:
                high_value_product = p
                break
        
        if high_value_product:
            order_data = {
                "items": [
                    {"product_id": high_value_product["id"], "quantity": 1}
                ],
                "guest_details": {
                    "name": "Free Shipping Test",
                    "email": "freeship@example.com",
                    "phone": "9876543213",
                    "address": "Free Ship Street",
                    "city": "Free City",
                    "state": "Free State",
                    "pincode": "111111"
                }
            }
            
            response = api_client.post(f"{BASE_URL}/api/orders", json=order_data)
            order = response.json()
            
            assert order["shipping_fee"] == 0
            assert order["total_amount"] == order["subtotal"]
