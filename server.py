from fastapi import FastAPI, APIRouter, HTTPException, Request
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from datetime import datetime, timedelta
import razorpay
import hmac
import hashlib
import httpx
import jwt
import base64

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Razorpay client
razorpay_key_id = os.environ.get('RAZORPAY_KEY_ID', '')
razorpay_key_secret = os.environ.get('RAZORPAY_KEY_SECRET', '')
razorpay_client = None

if razorpay_key_id and razorpay_key_secret:
    razorpay_client = razorpay.Client(auth=(razorpay_key_id, razorpay_key_secret))
    logging.info("Razorpay client initialized with live keys")

# WooCommerce configuration
woo_url = os.environ.get('WOOCOMMERCE_URL', '')
woo_key = os.environ.get('WOOCOMMERCE_CONSUMER_KEY', '')
woo_secret = os.environ.get('WOOCOMMERCE_CONSUMER_SECRET', '')

# JWT Secret for session tokens
JWT_SECRET = os.environ.get('JWT_SECRET', 'harmukh-kashir-secret-key-2024')
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24 * 7  # 7 days

# Create the main app
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# ==================== MODELS ====================

class Product(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str
    short_description: str
    price: float
    original_price: Optional[float] = None
    discount_percent: Optional[int] = None
    category: str
    image_url: str
    images: Optional[List[str]] = []  # Multiple product images for gallery
    weight: str
    in_stock: bool = True
    is_featured: bool = False
    is_bestseller: bool = False
    benefits: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)

class CartItem(BaseModel):
    product_id: str
    quantity: int

class GuestDetails(BaseModel):
    name: str
    email: str
    phone: str
    address: str
    city: str
    state: str
    pincode: str

class OrderItem(BaseModel):
    product_id: str
    product_name: str
    quantity: int
    price: float
    image_url: str

class Order(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    order_number: str = Field(default_factory=lambda: f"HK{datetime.now().strftime('%Y%m%d')}{str(uuid.uuid4())[:6].upper()}")
    items: List[OrderItem]
    total_amount: float
    subtotal: float
    shipping_fee: float = 0
    guest_details: GuestDetails
    user_id: Optional[str] = None
    payment_status: str = "pending"
    payment_id: Optional[str] = None
    razorpay_order_id: Optional[str] = None
    order_status: str = "pending"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class CreateOrderRequest(BaseModel):
    items: List[CartItem]
    guest_details: GuestDetails
    user_id: Optional[str] = None

class PaymentVerifyRequest(BaseModel):
    order_id: str
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str

# Auth Models
class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    email: str
    password: str
    first_name: str
    last_name: str
    phone: Optional[str] = None

class User(BaseModel):
    id: str
    email: str
    first_name: str
    last_name: str
    phone: Optional[str] = None
    woo_customer_id: Optional[int] = None
    billing_address: Optional[dict] = None
    shipping_address: Optional[dict] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class AuthResponse(BaseModel):
    user: User
    token: str

# ==================== HELPER FUNCTIONS ====================

def create_jwt_token(user_id: str, email: str) -> str:
    """Create a JWT token for the user"""
    payload = {
        "user_id": user_id,
        "email": email,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_jwt_token(token: str) -> dict:
    """Verify a JWT token and return the payload"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_woo_customer_by_email(email: str) -> Optional[dict]:
    """Get WooCommerce customer by email"""
    if not woo_url or not woo_key:
        return None
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{woo_url}/wp-json/wc/v3/customers",
                params={"email": email},
                auth=(woo_key, woo_secret),
                timeout=30
            )
            if response.status_code == 200:
                customers = response.json()
                if customers and len(customers) > 0:
                    return customers[0]
    except Exception as e:
        logging.error(f"Error fetching WooCommerce customer: {e}")
    return None

async def create_woo_customer(data: RegisterRequest) -> Optional[dict]:
    """Create a WooCommerce customer"""
    if not woo_url or not woo_key:
        return None
    
    try:
        async with httpx.AsyncClient() as client:
            customer_data = {
                "email": data.email,
                "first_name": data.first_name,
                "last_name": data.last_name,
                "username": data.email,
                "password": data.password,
            }
            if data.phone:
                customer_data["billing"] = {"phone": data.phone}
            
            response = await client.post(
                f"{woo_url}/wp-json/wc/v3/customers",
                json=customer_data,
                auth=(woo_key, woo_secret),
                timeout=30
            )
            if response.status_code in [200, 201]:
                return response.json()
            else:
                logging.error(f"WooCommerce customer creation failed: {response.text}")
    except Exception as e:
        logging.error(f"Error creating WooCommerce customer: {e}")
    return None

async def validate_woo_credentials(email: str, password: str) -> Optional[dict]:
    """Validate credentials against WordPress/WooCommerce"""
    if not woo_url:
        return None
    
    try:
        # Try WordPress REST API authentication
        async with httpx.AsyncClient() as client:
            # First, try to get customer by email
            customer = await get_woo_customer_by_email(email)
            if customer:
                # For WooCommerce, we'll create a custom validation
                # Since WC REST API doesn't expose password validation,
                # we'll use WordPress application passwords or JWT auth
                # For now, we'll store users in our DB with hashed passwords
                return customer
    except Exception as e:
        logging.error(f"Error validating WooCommerce credentials: {e}")
    return None

# ==================== SEED DATA ====================

INITIAL_PRODUCTS = [
    {
        "id": "prod-saffron-1",
        "name": "Authentic Kashmiri Saffron",
        "description": "Long, deep-crimson saffron strands with rich aroma and natural color. A few strands are enough to transform milk, desserts, and festive dishes. Our saffron is carefully handpicked from the pristine fields of Pampore, Kashmir - known as the Saffron Town of India.",
        "short_description": "Pure & unmixed saffron threads with strong aroma & deep color",
        "price": 599,
        "original_price": 699,
        "discount_percent": 14,
        "category": "Saffron",
        "image_url": "https://images.unsplash.com/photo-1649185916372-856dc9ccd611?w=600",
        "weight": "1gm",
        "in_stock": True,
        "is_featured": True,
        "is_bestseller": True,
        "benefits": ["Pure & unmixed saffron threads", "Strong aroma & deep color", "Carefully sourced from Kashmir", "No fillers or artificial coloring"]
    },
    {
        "id": "prod-walnut-1",
        "name": "Kashmiri Walnut Kernels – Fresh Crop",
        "description": "Premium quality Kashmiri walnut kernels from the latest harvest. These light-colored, crunchy walnuts are known for their superior taste and high nutritional value.",
        "short_description": "Fresh crop premium quality walnut kernels from Kashmir",
        "price": 999,
        "original_price": 1199,
        "discount_percent": 17,
        "category": "Dry Fruits",
        "image_url": "https://images.unsplash.com/photo-1602948750761-97ea79ee42ec?w=600",
        "weight": "500gm",
        "in_stock": True,
        "is_featured": True,
        "is_bestseller": True,
        "benefits": ["Fresh crop from Kashmir", "Light colored kernels", "High in Omega-3", "Perfect for cooking & snacking"]
    },
    {
        "id": "prod-almond-1",
        "name": "Kashmiri Almonds Nuts",
        "description": "Authentic Kashmiri almonds known for their unique taste and paper-thin shell.",
        "short_description": "Authentic Kashmiri almonds with unique taste",
        "price": 799,
        "original_price": 849,
        "discount_percent": 6,
        "category": "Dry Fruits",
        "image_url": "https://images.unsplash.com/photo-1567779833503-606dc39a14fd?w=600",
        "weight": "500gm",
        "in_stock": True,
        "is_featured": True,
        "is_bestseller": False,
        "benefits": ["Authentic Kashmiri variety", "Paper-thin shell", "Rich in Vitamin E", "Natural sweetness"]
    },
    {
        "id": "prod-honey-1",
        "name": "Kashmiri Saffron Honey",
        "description": "Pure Kashmiri honey infused with authentic saffron strands.",
        "short_description": "Pure honey infused with authentic Kashmiri saffron",
        "price": 649,
        "original_price": 719,
        "discount_percent": 10,
        "category": "Honey",
        "image_url": "https://images.unsplash.com/photo-1613548058193-1cd24c1bebcf?w=600",
        "weight": "500gm",
        "in_stock": True,
        "is_featured": True,
        "is_bestseller": False,
        "benefits": ["Infused with real saffron", "100% pure honey", "No added sugar", "Perfect for Kahwa"]
    },
    {
        "id": "prod-shilajit-1",
        "name": "Kashmiri Shilajit",
        "description": "Pure Himalayan Shilajit sourced from the high-altitude mountains of Kashmir.",
        "short_description": "Pure Himalayan Shilajit for energy & wellness",
        "price": 629,
        "original_price": 649,
        "discount_percent": 3,
        "category": "Wellness",
        "image_url": "https://images.unsplash.com/photo-1659109415631-6a6dd78b68f8?w=600",
        "weight": "10gm",
        "in_stock": True,
        "is_featured": False,
        "is_bestseller": False,
        "benefits": ["Pure Himalayan source", "Rich in minerals", "Boosts energy & stamina", "Natural wellness supplement"]
    },
    {
        "id": "prod-bundle-wellness",
        "name": "Harmukh Wellness Bundle",
        "description": "A thoughtfully curated wellness bundle featuring our best products.",
        "short_description": "Curated bundle with Saffron, Honey & Shilajit",
        "price": 1999,
        "original_price": 2257,
        "discount_percent": 11,
        "category": "Bundles",
        "image_url": "https://images.unsplash.com/photo-1720780493330-10b1b0ba2e6f?w=600",
        "weight": "Bundle",
        "in_stock": True,
        "is_featured": True,
        "is_bestseller": False,
        "benefits": ["Save ₹258 on bundle", "Complete wellness kit", "Premium quality products", "Perfect gift option"]
    },
    {
        "id": "prod-bundle-winter",
        "name": "Harmukh Winter Care Bundle",
        "description": "Stay warm and healthy this winter with our specially curated Winter Care Bundle.",
        "short_description": "Winter essentials bundle for immunity & warmth",
        "price": 1499,
        "original_price": 1607,
        "discount_percent": 7,
        "category": "Bundles",
        "image_url": "https://images.unsplash.com/photo-1720780493330-10b1b0ba2e6f?w=600",
        "weight": "Bundle",
        "in_stock": True,
        "is_featured": False,
        "is_bestseller": False,
        "benefits": ["Save ₹108 on bundle", "Winter immunity boost", "Energy-rich dry fruits", "Stay warm & healthy"]
    }
]

# ==================== WOOCOMMERCE SYNC ====================

async def fetch_woo_products() -> List[dict]:
    """Fetch all products from WooCommerce"""
    if not woo_url or not woo_key:
        return []
    
    all_products = []
    page = 1
    per_page = 50
    
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            while True:
                response = await client.get(
                    f"{woo_url}/wp-json/wc/v3/products",
                    params={"per_page": per_page, "page": page, "status": "publish"},
                    auth=(woo_key, woo_secret)
                )
                if response.status_code != 200:
                    logging.error(f"WooCommerce fetch failed: {response.status_code}")
                    break
                
                products = response.json()
                if not products:
                    break
                
                all_products.extend(products)
                
                if len(products) < per_page:
                    break
                page += 1
        
        logging.info(f"Fetched {len(all_products)} products from WooCommerce")
        return all_products
    except Exception as e:
        logging.error(f"Error fetching WooCommerce products: {e}")
        return []

def transform_woo_product(woo_product: dict) -> dict:
    """Transform WooCommerce product to our format"""
    import html
    import re
    
    # Get ALL images (not just primary)
    images = []
    if woo_product.get("images") and len(woo_product["images"]) > 0:
        for img in woo_product["images"]:
            img_url = img.get("src", "")
            if img_url:
                images.append(img_url)
    
    image_url = images[0] if images else ""
    
    # Get category and decode HTML entities
    category = "Uncategorized"
    if woo_product.get("categories") and len(woo_product["categories"]) > 0:
        category = html.unescape(woo_product["categories"][0].get("name", "Uncategorized"))
    
    # Calculate discount
    regular_price = float(woo_product.get("regular_price") or woo_product.get("price") or 0)
    sale_price = float(woo_product.get("sale_price") or woo_product.get("price") or 0)
    
    discount_percent = 0
    if regular_price > 0 and sale_price > 0 and sale_price < regular_price:
        discount_percent = int(((regular_price - sale_price) / regular_price) * 100)
    
    # Extract weight from product data
    weight = woo_product.get("weight", "")
    if not weight:
        name = woo_product.get("name", "")
        if "1gm" in name.lower() or "1 gm" in name.lower():
            weight = "1gm"
        elif "500gm" in name.lower() or "500 gm" in name.lower():
            weight = "500gm"
        elif "1kg" in name.lower() or "1 kg" in name.lower():
            weight = "1kg"
        else:
            weight = ""
    
    # Clean HTML from description
    description = woo_product.get("description", "")
    description = re.sub('<[^<]+?>', '', description)
    description = html.unescape(description).replace('•', '\n•').strip()
    
    short_desc = woo_product.get("short_description", "")
    short_desc = html.unescape(re.sub('<[^<]+?>', '', short_desc)).strip()
    
    # Decode product name too
    product_name = html.unescape(woo_product.get("name", ""))
    
    return {
        "id": f"woo-{woo_product['id']}",
        "woo_id": woo_product["id"],
        "name": product_name,
        "description": description,
        "short_description": short_desc or (description[:150] + "..." if len(description) > 150 else description),
        "price": sale_price if sale_price > 0 else regular_price,
        "original_price": regular_price if discount_percent > 0 else None,
        "discount_percent": discount_percent if discount_percent > 0 else None,
        "category": category,
        "image_url": image_url,
        "images": images,  # All product images for gallery
        "weight": weight,
        "in_stock": woo_product.get("stock_status") == "instock",
        "is_featured": woo_product.get("featured", False),
        "is_bestseller": woo_product.get("total_sales", 0) > 5 or woo_product.get("featured", False),
        "benefits": [],
        "created_at": datetime.utcnow()
    }

@api_router.post("/sync-products")
async def sync_woo_products():
    """Sync products from WooCommerce"""
    woo_products = await fetch_woo_products()
    if not woo_products:
        return {"message": "No products fetched from WooCommerce", "count": 0}
    
    # Clear old products that don't have woo_id (seed data)
    await db.products.delete_many({"woo_id": {"$exists": False}})
    
    synced_count = 0
    for woo_product in woo_products:
        transformed = transform_woo_product(woo_product)
        
        # Upsert product
        await db.products.update_one(
            {"woo_id": woo_product["id"]},
            {"$set": transformed},
            upsert=True
        )
        synced_count += 1
    
    return {"message": f"Synced {synced_count} products from WooCommerce", "count": synced_count}

# ==================== AUTH ROUTES ====================

@api_router.post("/auth/register", response_model=AuthResponse)
async def register(request: RegisterRequest):
    """Register a new user - syncs with WooCommerce"""
    # Check if user already exists
    existing_user = await db.users.find_one({"email": request.email.lower()})
    if existing_user:
        raise HTTPException(status_code=400, detail="User with this email already exists")
    
    # Try to create customer in WooCommerce
    woo_customer = await create_woo_customer(request)
    
    # Hash password for local storage
    import hashlib
    password_hash = hashlib.sha256(request.password.encode()).hexdigest()
    
    # Create user in our database
    user_data = {
        "id": str(uuid.uuid4()),
        "email": request.email.lower(),
        "first_name": request.first_name,
        "last_name": request.last_name,
        "phone": request.phone,
        "password_hash": password_hash,
        "woo_customer_id": woo_customer.get("id") if woo_customer else None,
        "billing_address": woo_customer.get("billing") if woo_customer else None,
        "shipping_address": woo_customer.get("shipping") if woo_customer else None,
        "created_at": datetime.utcnow()
    }
    
    await db.users.insert_one(user_data)
    
    # Create JWT token
    token = create_jwt_token(user_data["id"], user_data["email"])
    
    user = User(
        id=user_data["id"],
        email=user_data["email"],
        first_name=user_data["first_name"],
        last_name=user_data["last_name"],
        phone=user_data["phone"],
        woo_customer_id=user_data["woo_customer_id"],
        billing_address=user_data["billing_address"],
        shipping_address=user_data["shipping_address"]
    )
    
    return AuthResponse(user=user, token=token)

@api_router.post("/auth/login", response_model=AuthResponse)
async def login(request: LoginRequest):
    """Login user - validates against local DB (synced with WooCommerce)"""
    import hashlib
    password_hash = hashlib.sha256(request.password.encode()).hexdigest()
    
    # Find user in our database
    user_data = await db.users.find_one({
        "email": request.email.lower(),
        "password_hash": password_hash
    })
    
    if not user_data:
        # Try to find by email only and check if user exists in WooCommerce
        woo_customer = await get_woo_customer_by_email(request.email.lower())
        if woo_customer:
            # User exists in WooCommerce but not in our DB
            # Create a local record (they'll need to reset password or we sync)
            raise HTTPException(
                status_code=401, 
                detail="Account found in WooCommerce. Please register in app to sync your account."
            )
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Create JWT token
    token = create_jwt_token(user_data["id"], user_data["email"])
    
    user = User(
        id=user_data["id"],
        email=user_data["email"],
        first_name=user_data["first_name"],
        last_name=user_data["last_name"],
        phone=user_data.get("phone"),
        woo_customer_id=user_data.get("woo_customer_id"),
        billing_address=user_data.get("billing_address"),
        shipping_address=user_data.get("shipping_address")
    )
    
    return AuthResponse(user=user, token=token)

@api_router.get("/auth/me", response_model=User)
async def get_current_user(request: Request):
    """Get current user from token"""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    token = auth_header.split(" ")[1]
    payload = verify_jwt_token(token)
    
    user_data = await db.users.find_one({"id": payload["user_id"]})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    
    return User(
        id=user_data["id"],
        email=user_data["email"],
        first_name=user_data["first_name"],
        last_name=user_data["last_name"],
        phone=user_data.get("phone"),
        woo_customer_id=user_data.get("woo_customer_id"),
        billing_address=user_data.get("billing_address"),
        shipping_address=user_data.get("shipping_address")
    )

@api_router.put("/auth/profile")
async def update_profile(request: Request):
    """Update user profile"""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    token = auth_header.split(" ")[1]
    payload = verify_jwt_token(token)
    
    body = await request.json()
    update_data = {}
    
    if "first_name" in body:
        update_data["first_name"] = body["first_name"]
    if "last_name" in body:
        update_data["last_name"] = body["last_name"]
    if "phone" in body:
        update_data["phone"] = body["phone"]
    if "billing_address" in body:
        update_data["billing_address"] = body["billing_address"]
    if "shipping_address" in body:
        update_data["shipping_address"] = body["shipping_address"]
    
    if update_data:
        await db.users.update_one(
            {"id": payload["user_id"]},
            {"$set": update_data}
        )
    
    return {"message": "Profile updated successfully"}

@api_router.get("/auth/orders")
async def get_user_orders(request: Request):
    """Get orders for authenticated user"""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    token = auth_header.split(" ")[1]
    payload = verify_jwt_token(token)
    
    orders = await db.orders.find({"user_id": payload["user_id"]}).sort("created_at", -1).to_list(100)
    return orders

# ==================== PRODUCT ROUTES ====================

@api_router.get("/")
async def root():
    return {"message": "Harmukh Kashir API", "version": "1.0.0"}

@api_router.get("/products", response_model=List[Product])
async def get_products(category: Optional[str] = None, featured: Optional[bool] = None):
    query = {}
    if category:
        query["category"] = category
    if featured is not None:
        query["is_featured"] = featured
    
    products = await db.products.find(query).to_list(100)
    return [Product(**p) for p in products]

@api_router.get("/products/{product_id}", response_model=Product)
async def get_product(product_id: str):
    product = await db.products.find_one({"id": product_id})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return Product(**product)

@api_router.get("/categories")
async def get_categories():
    import html
    categories = await db.products.distinct("category")
    # Dedupe and clean categories (remove similar names like Bundle/Bundles)
    seen = set()
    clean_categories = []
    for cat in categories:
        decoded = html.unescape(cat)
        # Normalize for comparison (lowercase, singular)
        normalized = decoded.lower().rstrip('s')
        if normalized not in seen and decoded not in seen:
            seen.add(normalized)
            seen.add(decoded)
            clean_categories.append(decoded)
    return {"categories": sorted(clean_categories)}

@api_router.get("/featured-products", response_model=List[Product])
async def get_featured_products():
    products = await db.products.find({"is_featured": True}).to_list(10)
    return [Product(**p) for p in products]

@api_router.get("/bestsellers", response_model=List[Product])
async def get_bestsellers():
    products = await db.products.find({"is_bestseller": True}).to_list(10)
    return [Product(**p) for p in products]

# ==================== ORDER ROUTES ====================

@api_router.post("/orders", response_model=Order)
async def create_order(request: CreateOrderRequest):
    items_with_details = []
    subtotal = 0
    
    for item in request.items:
        product = await db.products.find_one({"id": item.product_id})
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
        
        item_total = product["price"] * item.quantity
        subtotal += item_total
        
        items_with_details.append(OrderItem(
            product_id=item.product_id,
            product_name=product["name"],
            quantity=item.quantity,
            price=product["price"],
            image_url=product["image_url"]
        ))
    
    shipping_fee = 0 if subtotal >= 500 else 50
    total_amount = subtotal + shipping_fee
    
    order = Order(
        items=items_with_details,
        total_amount=total_amount,
        subtotal=subtotal,
        shipping_fee=shipping_fee,
        guest_details=request.guest_details,
        user_id=request.user_id
    )
    
    await db.orders.insert_one(order.dict())
    return order

@api_router.get("/orders/{order_id}", response_model=Order)
async def get_order(order_id: str):
    order = await db.orders.find_one({"id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return Order(**order)

@api_router.get("/orders/track/{order_number}")
async def track_order(order_number: str):
    order = await db.orders.find_one({"order_number": order_number.upper()})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    # Remove _id and return
    order.pop("_id", None)
    return order

# ==================== PAYMENT ROUTES ====================

@api_router.post("/payment/create-order")
async def create_payment_order(order_id: str, amount: int):
    order = await db.orders.find_one({"id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if razorpay_client:
        try:
            razorpay_order = razorpay_client.order.create({
                "amount": amount,
                "currency": "INR",
                "receipt": order_id[:40],
                "payment_capture": 1,
                "notes": {
                    "order_id": order_id,
                    "customer_name": order["guest_details"]["name"],
                    "customer_email": order["guest_details"]["email"]
                }
            })
            
            await db.orders.update_one(
                {"id": order_id},
                {"$set": {"razorpay_order_id": razorpay_order["id"]}}
            )
            
            return {
                "id": razorpay_order["id"],
                "amount": razorpay_order["amount"],
                "currency": razorpay_order["currency"],
                "status": razorpay_order["status"],
                "key_id": razorpay_key_id,
                "prefill": {
                    "name": order["guest_details"]["name"],
                    "email": order["guest_details"]["email"],
                    "contact": order["guest_details"]["phone"]
                }
            }
        except Exception as e:
            logging.error(f"Razorpay order creation failed: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Payment order creation failed: {str(e)}")
    else:
        mock_id = f"order_mock_{uuid.uuid4().hex[:16]}"
        await db.orders.update_one({"id": order_id}, {"$set": {"razorpay_order_id": mock_id}})
        return {"id": mock_id, "amount": amount, "currency": "INR", "status": "created", "mock": True}

@api_router.post("/payment/verify")
async def verify_payment(request: PaymentVerifyRequest):
    if razorpay_client:
        try:
            params_dict = {
                'razorpay_order_id': request.razorpay_order_id,
                'razorpay_payment_id': request.razorpay_payment_id,
                'razorpay_signature': request.razorpay_signature
            }
            razorpay_client.utility.verify_payment_signature(params_dict)
            
            await db.orders.update_one(
                {"id": request.order_id},
                {"$set": {
                    "payment_status": "paid",
                    "payment_id": request.razorpay_payment_id,
                    "order_status": "confirmed",
                    "updated_at": datetime.utcnow()
                }}
            )
            return {"status": "success", "message": "Payment verified successfully"}
        except razorpay.errors.SignatureVerificationError:
            await db.orders.update_one({"id": request.order_id}, {"$set": {"payment_status": "failed"}})
            raise HTTPException(status_code=400, detail="Payment verification failed")
    else:
        await db.orders.update_one(
            {"id": request.order_id},
            {"$set": {"payment_status": "paid", "payment_id": request.razorpay_payment_id, "order_status": "confirmed"}}
        )
        return {"status": "success", "message": "Payment verified", "mock": True}

@api_router.get("/payment/key")
async def get_razorpay_key():
    if razorpay_key_id:
        return {"key_id": razorpay_key_id}
    raise HTTPException(status_code=500, detail="Razorpay not configured")

# ==================== NOTIFICATIONS ====================

@api_router.post("/notifications/register")
async def register_notification_token(token: str, device_type: str):
    existing = await db.notification_tokens.find_one({"token": token})
    if existing:
        return {"message": "Token already registered"}
    await db.notification_tokens.insert_one({"id": str(uuid.uuid4()), "token": token, "device_type": device_type, "created_at": datetime.utcnow()})
    return {"message": "Token registered successfully"}

@api_router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "razorpay_configured": razorpay_client is not None,
        "woocommerce_configured": bool(woo_url and woo_key)
    }

# Include router
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_event():
    count = await db.products.count_documents({})
    if count == 0:
        logger.info("Seeding initial products...")
        for product_data in INITIAL_PRODUCTS:
            product = Product(**product_data)
            await db.products.insert_one(product.dict())
        logger.info(f"Seeded {len(INITIAL_PRODUCTS)} products")
    else:
        logger.info(f"Products already exist ({count} products)")
    
    if razorpay_client:
        logger.info("Razorpay integration: LIVE")
    if woo_url:
        logger.info(f"WooCommerce integration: {woo_url}")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
