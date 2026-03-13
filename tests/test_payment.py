"""
Backend API Tests for Payment Endpoints
Tests: POST /api/payment/create-order, POST /api/payment/verify, GET /api/payment/key
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://kashmir-shop-preview.preview.emergentagent.com')


class TestPaymentAPI:
    """Test suite for Payment API endpoints"""
    
    def test_get_razorpay_key(self, api_client):
        """Test GET /api/payment/key returns Razorpay key ID"""
        response = api_client.get(f"{BASE_URL}/api/payment/key")
        assert response.status_code == 200
        data = response.json()
        
        assert "key_id" in data
        # Razorpay key should start with 'rzp_'
        assert data["key_id"].startswith("rzp_")
    
    def test_create_payment_order(self, api_client):
        """Test POST /api/payment/create-order creates Razorpay order"""
        # First create an order in our system
        products_response = api_client.get(f"{BASE_URL}/api/products")
        products = products_response.json()
        
        order_data = {
            "items": [
                {"product_id": products[0]["id"], "quantity": 1}
            ],
            "guest_details": {
                "name": "Payment Test",
                "email": "payment@example.com",
                "phone": "9876543214",
                "address": "Payment Street",
                "city": "Payment City",
                "state": "Payment State",
                "pincode": "222222"
            }
        }
        
        create_response = api_client.post(f"{BASE_URL}/api/orders", json=order_data)
        order = create_response.json()
        
        # Create payment order
        # Amount should be in paise (multiply by 100)
        amount_in_paise = int(order["total_amount"] * 100)
        
        response = api_client.post(
            f"{BASE_URL}/api/payment/create-order",
            params={"order_id": order["id"], "amount": amount_in_paise}
        )
        assert response.status_code == 200
        payment_data = response.json()
        
        assert "id" in payment_data
        assert "amount" in payment_data
        assert payment_data["amount"] == amount_in_paise
        assert payment_data["currency"] == "INR"
        assert payment_data["status"] == "created"
        
        # If not mocked, should have Razorpay order ID format
        if not payment_data.get("mock"):
            assert payment_data["id"].startswith("order_")
    
    def test_create_payment_order_invalid_order(self, api_client):
        """Test POST /api/payment/create-order with invalid order ID"""
        response = api_client.post(
            f"{BASE_URL}/api/payment/create-order",
            params={"order_id": "invalid-order-xyz", "amount": 50000}
        )
        assert response.status_code == 404
    
    def test_verify_payment_invalid_signature(self, api_client):
        """Test POST /api/payment/verify with invalid signature"""
        # First create an order
        products_response = api_client.get(f"{BASE_URL}/api/products")
        products = products_response.json()
        
        order_data = {
            "items": [
                {"product_id": products[0]["id"], "quantity": 1}
            ],
            "guest_details": {
                "name": "Verify Test",
                "email": "verify@example.com",
                "phone": "9876543215",
                "address": "Verify Street",
                "city": "Verify City",
                "state": "Verify State",
                "pincode": "333333"
            }
        }
        
        create_response = api_client.post(f"{BASE_URL}/api/orders", json=order_data)
        order = create_response.json()
        
        # Try to verify with invalid signature
        verify_data = {
            "order_id": order["id"],
            "razorpay_payment_id": "pay_invalid_xyz",
            "razorpay_order_id": "order_invalid_xyz",
            "razorpay_signature": "invalid_signature_xyz"
        }
        
        response = api_client.post(f"{BASE_URL}/api/payment/verify", json=verify_data)
        # Should fail with 400 (signature verification failure)
        assert response.status_code == 400
    
    def test_razorpay_configured(self, api_client):
        """Test that Razorpay is properly configured"""
        response = api_client.get(f"{BASE_URL}/api/health")
        data = response.json()
        
        assert data["razorpay_configured"] == True
