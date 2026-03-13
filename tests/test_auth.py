"""
Backend API Tests for Auth Endpoints
Tests: POST /api/auth/register, POST /api/auth/login, GET /api/auth/me
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://kashmir-shop-preview.preview.emergentagent.com')


class TestAuthAPI:
    """Test suite for Auth API endpoints"""
    
    def test_register_new_user(self, api_client):
        """Test POST /api/auth/register creates new user"""
        unique_id = str(uuid.uuid4())[:8]
        user_data = {
            "email": f"test_register_{unique_id}@example.com",
            "password": "TestPass123!",
            "first_name": "Test",
            "last_name": "Register",
            "phone": "9876543210"
        }
        
        response = api_client.post(f"{BASE_URL}/api/auth/register", json=user_data)
        assert response.status_code == 200
        data = response.json()
        
        assert "user" in data
        assert "token" in data
        assert data["user"]["email"] == user_data["email"].lower()
        assert data["user"]["first_name"] == user_data["first_name"]
        assert data["user"]["last_name"] == user_data["last_name"]
        assert len(data["token"]) > 0
    
    def test_register_duplicate_email(self, api_client):
        """Test POST /api/auth/register with duplicate email returns error"""
        unique_id = str(uuid.uuid4())[:8]
        user_data = {
            "email": f"test_dup_{unique_id}@example.com",
            "password": "TestPass123!",
            "first_name": "Test",
            "last_name": "Duplicate"
        }
        
        # First registration should succeed
        response = api_client.post(f"{BASE_URL}/api/auth/register", json=user_data)
        assert response.status_code == 200
        
        # Second registration with same email should fail
        response = api_client.post(f"{BASE_URL}/api/auth/register", json=user_data)
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "already exists" in data["detail"].lower()
    
    def test_login_success(self, api_client, registered_user):
        """Test POST /api/auth/login with valid credentials"""
        login_data = {
            "email": registered_user["credentials"]["email"],
            "password": registered_user["credentials"]["password"]
        }
        
        response = api_client.post(f"{BASE_URL}/api/auth/login", json=login_data)
        assert response.status_code == 200
        data = response.json()
        
        assert "user" in data
        assert "token" in data
        assert data["user"]["email"] == login_data["email"].lower()
    
    def test_login_invalid_password(self, api_client, registered_user):
        """Test POST /api/auth/login with invalid password returns 401"""
        login_data = {
            "email": registered_user["credentials"]["email"],
            "password": "WrongPassword123!"
        }
        
        response = api_client.post(f"{BASE_URL}/api/auth/login", json=login_data)
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data
    
    def test_login_nonexistent_user(self, api_client):
        """Test POST /api/auth/login with nonexistent user returns 401"""
        login_data = {
            "email": "nonexistent_user_xyz@example.com",
            "password": "SomePassword123!"
        }
        
        response = api_client.post(f"{BASE_URL}/api/auth/login", json=login_data)
        assert response.status_code == 401
    
    def test_get_current_user(self, authenticated_client):
        """Test GET /api/auth/me returns current user"""
        client, user_data = authenticated_client
        
        response = client.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 200
        data = response.json()
        
        assert data["email"] == user_data["user"]["email"]
        assert data["first_name"] == user_data["user"]["first_name"]
    
    def test_get_current_user_no_token(self, api_client):
        """Test GET /api/auth/me without token returns 401"""
        response = api_client.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 401
    
    def test_get_current_user_invalid_token(self, api_client):
        """Test GET /api/auth/me with invalid token returns 401"""
        api_client.headers.update({"Authorization": "Bearer invalid_token_xyz"})
        response = api_client.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 401
    
    def test_register_missing_fields(self, api_client):
        """Test POST /api/auth/register with missing required fields"""
        incomplete_data = {
            "email": "incomplete@example.com"
            # Missing: password, first_name, last_name
        }
        
        response = api_client.post(f"{BASE_URL}/api/auth/register", json=incomplete_data)
        assert response.status_code == 422  # Validation error
