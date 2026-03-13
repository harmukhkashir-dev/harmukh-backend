"""
Backend API Tests for Products Endpoints
Tests: GET /api/products, GET /api/products/:id, GET /api/categories
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://kashmir-shop-preview.preview.emergentagent.com')


class TestProductsAPI:
    """Test suite for Products API endpoints"""
    
    def test_health_check(self, api_client):
        """Test health endpoint returns healthy status"""
        response = api_client.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "razorpay_configured" in data
        assert "woocommerce_configured" in data

    def test_get_all_products(self, api_client):
        """Test GET /api/products returns list of products"""
        response = api_client.get(f"{BASE_URL}/api/products")
        assert response.status_code == 200
        products = response.json()
        assert isinstance(products, list)
        assert len(products) > 0
        
        # Verify product structure
        product = products[0]
        required_fields = ["id", "name", "description", "price", "category", "image_url", "weight", "in_stock"]
        for field in required_fields:
            assert field in product, f"Missing required field: {field}"
    
    def test_get_products_by_category(self, api_client):
        """Test GET /api/products with category filter"""
        response = api_client.get(f"{BASE_URL}/api/products", params={"category": "Saffron"})
        assert response.status_code == 200
        products = response.json()
        assert isinstance(products, list)
        for product in products:
            assert product["category"] == "Saffron"
    
    def test_get_featured_products(self, api_client):
        """Test GET /api/products with featured filter"""
        response = api_client.get(f"{BASE_URL}/api/products", params={"featured": True})
        assert response.status_code == 200
        products = response.json()
        assert isinstance(products, list)
        for product in products:
            assert product["is_featured"] == True
    
    def test_get_single_product(self, api_client):
        """Test GET /api/products/:id returns a single product"""
        # First get all products to get a valid ID
        response = api_client.get(f"{BASE_URL}/api/products")
        products = response.json()
        product_id = products[0]["id"]
        
        # Get single product
        response = api_client.get(f"{BASE_URL}/api/products/{product_id}")
        assert response.status_code == 200
        product = response.json()
        assert product["id"] == product_id
        assert "name" in product
        assert "price" in product
    
    def test_get_single_product_not_found(self, api_client):
        """Test GET /api/products/:id with invalid ID returns 404"""
        response = api_client.get(f"{BASE_URL}/api/products/invalid-product-id-12345")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
    
    def test_get_categories(self, api_client):
        """Test GET /api/categories returns list of categories"""
        response = api_client.get(f"{BASE_URL}/api/categories")
        assert response.status_code == 200
        data = response.json()
        assert "categories" in data
        assert isinstance(data["categories"], list)
        assert len(data["categories"]) > 0
        
        # Known categories from the seeded data
        expected_categories = ["Saffron", "Dry Fruits", "Honey", "Wellness", "Bundles"]
        for expected in expected_categories:
            assert expected in data["categories"], f"Missing category: {expected}"
    
    def test_get_featured_products_endpoint(self, api_client):
        """Test GET /api/featured-products returns featured products"""
        response = api_client.get(f"{BASE_URL}/api/featured-products")
        assert response.status_code == 200
        products = response.json()
        assert isinstance(products, list)
        for product in products:
            assert product["is_featured"] == True
    
    def test_get_bestsellers(self, api_client):
        """Test GET /api/bestsellers returns bestseller products"""
        response = api_client.get(f"{BASE_URL}/api/bestsellers")
        assert response.status_code == 200
        products = response.json()
        assert isinstance(products, list)
        for product in products:
            assert product["is_bestseller"] == True
    
    def test_product_price_structure(self, api_client):
        """Test product price fields are correct"""
        response = api_client.get(f"{BASE_URL}/api/products")
        products = response.json()
        
        for product in products:
            assert product["price"] > 0
            if product.get("original_price"):
                assert product["original_price"] >= product["price"]
            if product.get("discount_percent"):
                assert 0 <= product["discount_percent"] <= 100
