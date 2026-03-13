import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://kashmir-shop-preview.preview.emergentagent.com')

@pytest.fixture
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session

@pytest.fixture
def test_user_data():
    """Generate unique test user data"""
    unique_id = str(uuid.uuid4())[:8]
    return {
        "email": f"test_{unique_id}@example.com",
        "password": "TestPass123!",
        "first_name": "Test",
        "last_name": f"User{unique_id}",
        "phone": "9876543210"
    }

@pytest.fixture
def registered_user(api_client, test_user_data):
    """Register a new test user and return user data with token"""
    response = api_client.post(f"{BASE_URL}/api/auth/register", json=test_user_data)
    if response.status_code == 200:
        data = response.json()
        return {
            "user": data["user"],
            "token": data["token"],
            "credentials": test_user_data
        }
    pytest.skip(f"Failed to register test user: {response.text}")

@pytest.fixture
def authenticated_client(api_client, registered_user):
    """Session with auth header"""
    api_client.headers.update({"Authorization": f"Bearer {registered_user['token']}"})
    return api_client, registered_user
