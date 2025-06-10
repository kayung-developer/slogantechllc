# main.py
#
# Slogan Technologies LLC - IntelliWeb Engine v2.3
# A massively upgraded, feature-rich single-file web application.
#
# v2.3 Changes:
# - IMPLEMENTED: New /services page with a detailed, icon-driven layout.
# - IMPLEMENTED: New /settings page on the user dashboard.
# - FEATURE: Live Theme Switching (Cyan, Orange, Purple) with settings saved to localStorage.
# - FEATURE: User profile update functionality (Full Name, Email).
# - ENHANCED: Completely revamped /about page with new Mission, Vision, and Core Values.
# - ENHANCED: Dashboard updated with a link to the new Settings page.
#

import asyncio
import datetime
import json
import sqlite3
import re
import os
import time
from typing import List, Optional

import uvicorn
import stripe
from fastapi import FastAPI, HTTPException, Request, Form, Depends, status, Response, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from jose import JWTError, jwt
from passlib.context import CryptContext
import firebase_admin
from firebase_admin import credentials, auth, firestore, storage

# --- ============================== ---
# --- 1. CONFIGURATION AND CONSTANTS ---
# --- ============================== ---

APP_TITLE = "Slogan Technologies LLC"
DATABASE_URL = "slogan_tech.db"
SECRET_KEY = os.getenv("SECRET_KEY", "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "sk_test_YOUR_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "pk_test_YOUR_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_YOUR_SECRET")
stripe.api_key = STRIPE_SECRET_KEY
STRIPE_PRICE_ID_BASIC = os.getenv("STRIPE_PRICE_ID_BASIC", "price_1PG...")
STRIPE_PRICE_ID_PREMIUM = os.getenv("STRIPE_PRICE_ID_PREMIUM", "price_1PG...")
STRIPE_PRICE_ID_ULTIMATE = os.getenv("STRIPE_PRICE_ID_ULTIMATE", "price_1PG...")
PLAN_HIERARCHY = {"none": 0, "basic": 1, "premium": 2, "ultimate": 3}
FIREBASE_CREDS_PATH = "firebase-credentials.json"


# --- =================== ---
# --- 2. HELPER FUNCTIONS ---
# --- =================== ---

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r'[\s\W-]+', '-', text)
    return text.strip('-')


def user_has_access(user_plan: str, required_plan: str) -> bool:
    user_level = PLAN_HIERARCHY.get(user_plan, 0)
    required_level = PLAN_HIERARCHY.get(required_plan, 99)
    return user_level >= required_level


# --- ================================== ---
# --- 3. FIREBASE INTEGRATION (ADVANCED) ---
# --- ================================== ---
class FirebaseService:
    def __init__(self, creds_path: str):
        self.initialized = False
        try:
            if os.path.exists(creds_path):
                if not firebase_admin._apps:
                    cred = credentials.Certificate(creds_path)
                    project_id = cred.project_id
                    firebase_admin.initialize_app(cred, {'storageBucket': f'{project_id}.appspot.com'})
                self.initialized = True
                print("✅ Firebase Service Initialized Successfully.")
            else:
                print("⚠️ Firebase credentials not found. FirebaseService is disabled.")
        except Exception as e:
            print(f"🔥 Firebase Initialization Failed: {e}")

    def upload_file_from_bytes(self, file_bytes: bytes, destination_blob_name: str, content_type: str) -> Optional[str]:
        if not self.initialized:
            print("Firebase not initialized, cannot upload file.")
            return None
        try:
            bucket = storage.bucket()
            blob = bucket.blob(destination_blob_name)
            blob.upload_from_string(file_bytes, content_type=content_type)
            blob.make_public()
            return blob.public_url
        except Exception as e:
            print(f"🔥 Firebase Storage upload error: {e}")
            return None

firebase_service: Optional[FirebaseService] = None


# --- ============================= ---
# --- 4. DATABASE SETUP & UTILITIES ---
# --- ============================= ---

def get_db_connection():
    conn = sqlite3.connect(DATABASE_URL)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    print("🚀 Initializing database schema v2.4...")

    cursor.execute(
        "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL, hashed_password TEXT NOT NULL, full_name TEXT, role TEXT DEFAULT 'user', created_at DATETIME DEFAULT CURRENT_TIMESTAMP, subscription_plan TEXT DEFAULT 'none', subscription_status TEXT, stripe_customer_id TEXT UNIQUE, subscription_id TEXT UNIQUE, profile_picture_url TEXT)")
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, description TEXT, price REAL, stripe_price_id TEXT, image_url TEXT, stock INTEGER DEFAULT 0, details TEXT, is_featured BOOLEAN DEFAULT FALSE, required_plan TEXT DEFAULT 'basic')")
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, total_amount REAL NOT NULL, status TEXT DEFAULT 'pending', stripe_session_id TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users(id))")
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS blog_posts (id INTEGER PRIMARY KEY, title TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, content TEXT NOT NULL, author_id INTEGER, published_at DATETIME DEFAULT CURRENT_TIMESTAMP, image_url TEXT, tags TEXT, FOREIGN KEY (author_id) REFERENCES users(id))")
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS contact_messages (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, subject TEXT, message TEXT NOT NULL, received_at DATETIME DEFAULT CURRENT_TIMESTAMP, is_read BOOLEAN DEFAULT FALSE)")

    conn.commit()
    print("✅ Database schema initialized.")
    cursor.execute("SELECT COUNT(*) FROM products")
    if cursor.fetchone()[0] == 0:
        print("🌱 Seeding initial data...")
        seed_data(conn)
        print("✅ Data seeded.")
    conn.close()


def seed_data(conn):
    cursor = conn.cursor()
    try:
        hashed_password = pwd_context.hash("admin1234")
        cursor.execute("INSERT INTO users (username, email, hashed_password, role, full_name, profile_picture_url) VALUES (?, ?, ?, ?, ?, ?)", ('admin', 'admin@slogantech.dev', hashed_password, 'admin', 'Admin User', '/static_placeholder/img/avatar_admin.svg'))
    except sqlite3.IntegrityError: pass
    admin_id = 1
    products_data = [
        ('African Deity Kombat', 'game', 'Epic fighting game featuring African deities.', 59.99, 'price_1PGbWbL0v1a...',
         '/static_placeholder/img/game_adk.jpg', 100, json.dumps({'genre': 'Fighting'}), True, 'none'),
        ('AI Innovator Robotics Kit', 'kit', 'Comprehensive kit for learning AI and Robotics.', 199.99,
         'price_1PGbXBL0v1a...', '/static_placeholder/img/kit_ai_robotics.jpg', 50, json.dumps({}), True, 'none'),
        ('Intro to AI', 'course', 'A foundational course covering the basics of AI.', 0.00, None,
         '/static_placeholder/img/course_ai.jpg', -1,
         json.dumps({'video_url': 'https://www.youtube.com/embed/R9OHn5ZF4Uo'}), True, 'basic'),
        ('Game Dev AI Masterclass', 'course', 'Advanced techniques for implementing AI in games.', 0.00, None,
         '/static_placeholder/img/course_gamedev.jpg', -1,
         json.dumps({'video_url': 'https://www.youtube.com/embed/uI_2i2oK2vM'}), True, 'premium'),
        ('Robotics Vision Systems', 'course', 'Learn to build computer vision systems for robots.', 0.00, None,
         '/static_placeholder/img/course_robotics.jpg', -1,
         json.dumps({'video_url': 'https://www.youtube.com/embed/8e1b-3h8Jj4'}), False, 'ultimate'),
        ('Basic Subscription', 'subscription', 'Access to basic courses and community.', 9.99, STRIPE_PRICE_ID_BASIC,
         '/static_placeholder/img/sub_basic.jpg', -1, json.dumps({'features': ['Basic Courses', 'Forum Access']}),
         False, 'none'),
        ('Premium Subscription', 'subscription', 'Premium courses and direct support.', 29.99, STRIPE_PRICE_ID_PREMIUM,
         '/static_placeholder/img/sub_premium.jpg', -1, json.dumps({'features': ['All Courses', 'Source Code Access']}),
         True, 'none'),
        ('Ultimate Subscription', 'subscription', 'All access plus 1-on-1 mentorship.', 99.99, STRIPE_PRICE_ID_ULTIMATE,
         '/static_placeholder/img/sub_ultimate.jpg', -1, json.dumps({'features': ['All Access', 'Mentorship Calls']}),
         False, 'none'),
    ]
    cursor.executemany(
        "INSERT INTO products (name, category, description, price, stripe_price_id, image_url, stock, details, is_featured, required_plan) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        products_data)
    blog_posts_data = [
        (
            'The Rise of AI in African Innovation', slugify('The Rise of AI in African Innovation'), 'Content...',
            admin_id,
            '/static_placeholder/img/blog_ai_africa.jpg', 'AI,Africa,Tech'),
        ('Behind the Mythology of African Deity Kombat', slugify('Behind the Mythology of African Deity Kombat'),
         'Content...', admin_id, '/static_placeholder/img/blog_adk_myth.jpg', 'Gaming,Culture,ADK'),
    ]
    cursor.executemany(
        "INSERT INTO blog_posts (title, slug, content, author_id, image_url, tags) VALUES (?, ?, ?, ?, ?, ?)",
        blog_posts_data)
    conn.commit()


# --- =========================== ---
# --- 5. AUTHENTICATION & SECURITY ---
# --- =========================== ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


class Token(BaseModel): access_token: str; token_type: str


class TokenData(BaseModel): username: Optional[str] = None


def verify_password(p, h): return pwd_context.verify(p, h)


def get_password_hash(p): return pwd_context.hash(p)


def create_access_token(data: dict, expires_delta: Optional[datetime.timedelta] = None):
    expire = datetime.datetime.utcnow() + (expires_delta or datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode = data.copy();
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_user(db, username: str):
    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return dict(user) if user else None


async def get_token_from_cookie(request: Request) -> Optional[str]:
    token = request.cookies.get("access_token")
    if not token or " " not in token: return None
    return token.split(" ")[1]


async def get_current_user(request: Request, token: str = Depends(get_token_from_cookie)):
    credentials_exception = HTTPException(status_code=401, detail="Not authenticated")
    if token is None: raise credentials_exception
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None: raise credentials_exception
    except JWTError:
        raise credentials_exception
    with get_db_connection() as conn:
        user = get_user(conn, username)
    if user is None: raise credentials_exception
    request.state.user = user
    return user


async def get_current_active_user(current_user: dict = Depends(get_current_user)): return current_user


async def is_admin(current_user: dict = Depends(get_current_active_user)):
    if current_user.get('role') != 'admin': raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


# --- =================== ---
# --- 6. PYDANTIC MODELS ---
# --- =================== ---
class UserCreate(BaseModel): username: str; email: EmailStr; password: str; full_name: str


class UserUpdate(BaseModel): full_name: str; email: EmailStr


class ContactFormModel(BaseModel): name: str; email: EmailStr; subject: Optional[str] = None; message: str


# --- ========================== ---
# --- 7. FRONTEND ASSETS (EMBEDDED) ---
# --- ========================== ---
GLOBAL_CSS = """
/* SloganTech IntelliWeb Engine v2.3 - Stylesheet */
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Rajdhani:wght@300;400;600&display=swap');
:root {
    --primary-color: #0d0d2b;
    --secondary-color-base: #4a148c;
    --text-color: #e0e0e0;
    --bg-color: #0a0a1f;
    --bg-color-lighter: #1a1a3a;
    --font-main: 'Rajdhani', sans-serif;
    --font-headings: 'Orbitron', sans-serif;
    --animation-speed: 0.4s;

    /* Dynamic Theme Colors */
    --accent-color: var(--theme-accent, #00e5ff); /* Cyan Glitch */
    --accent-color-secondary: var(--theme-accent-secondary, #ff3d00); /* Fusion Orange */
    --border-color: var(--theme-border, rgba(0, 229, 255, 0.2));
    --glow-color: var(--theme-glow, rgba(0, 229, 255, 0.7));
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
    font-family: var(--font-main); background-color: var(--bg-color); color: var(--text-color);
    line-height: 1.7; overflow-x: hidden;
    background-image: 
        radial-gradient(circle at 20% 20%, rgba(74, 20, 140, 0.3), transparent 40%),
        radial-gradient(circle at 80% 80%, rgba(0, 229, 255, 0.1), transparent 35%),
        url("data:image/svg+xml,%3Csvg width='80' height='80' viewBox='0 0 80 80' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%231a1a3a' fill-opacity='0.2'%3E%3Cpath d='M80 80V0h-2v78h-78v2h80zM0 0v2h2V0H0zm2 2v2h2V2H2zm0 4v2h2V6H2zm0 4v2h2v-2H2z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");
    background-attachment: fixed; perspective: 1000px;
    transition: background-color 0.5s ease;
}
.container { width: 95%; max-width: 1400px; margin: auto; padding: 20px 0; }
h1, h2, h3, h4 { font-family: var(--font-headings); color: var(--accent-color); text-shadow: 0 0 8px var(--glow-color), 0 0 12px var(--glow-color); letter-spacing: 1px; font-weight: 700; margin-bottom: 1rem;}
h1 { font-size: 3.5rem; } h2 { font-size: 2.5rem; } h3 { font-size: 1.8rem; }
a { color: var(--accent-color); text-decoration: none; transition: color var(--animation-speed) ease, text-shadow var(--animation-speed) ease; }
a:hover { color: #fff; text-shadow: 0 0 5px #fff; }
header {
    background: rgba(10, 10, 31, 0.8); backdrop-filter: blur(12px); padding: 1rem 0;
    position: sticky; top: 0; z-index: 1000; border-bottom: 1px solid var(--border-color);
    box-shadow: 0 5px 25px rgba(0, 0, 0, 0.5); transition: border-color 0.5s ease;
}
header .container { display: flex; justify-content: space-between; align-items: center; }
.logo { font-family: var(--font-headings); font-size: 2.2rem; font-weight: 900; letter-spacing: 2px; }
.logo span { color: var(--accent-color-secondary); transition: color 0.5s ease; }
nav ul { list-style: none; display: flex; align-items: center; }
nav ul li { margin-left: 30px; }
nav ul li a { font-family: var(--font-headings); padding: 0.6rem 1rem; border: 1px solid transparent; border-radius: 5px; transition: all var(--animation-speed); }
nav ul li a:hover, nav ul li a.active { background: var(--accent-color); color: var(--bg-color); border-color: var(--accent-color); text-shadow: none; }
.hero { height: 90vh; display: flex; align-items: center; justify-content: center; text-align: center; position: relative; overflow: hidden; }
.hero-content { z-index: 2; animation: fadeInFromBottom 1.5s ease-out; }
.hero h1 {
    font-size: 4.5rem; font-weight: 900; text-transform: uppercase;
    background: linear-gradient(90deg, var(--accent-color), #fff, var(--accent-color-secondary));
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    animation: text-flicker 3s linear infinite;
}
.hero p { font-size: 1.4rem; max-width: 800px; margin: 1rem auto 2.5rem; color: #ccc; }
@keyframes text-flicker { 0% { opacity: 0.8; } 5% { opacity: 1; } 10% { opacity: 0.7; } 20% { opacity: 1; } 30% { opacity: 0.6; } 40% { opacity: 1; } 100% { opacity: 1; } }
@keyframes fadeInFromBottom { from { opacity: 0; transform: translateY(50px); } to { opacity: 1; transform: translateY(0); } }
.btn {
    display: inline-block; padding: 14px 35px; font-family: var(--font-headings); font-size: 1rem;
    font-weight: 700; text-transform: uppercase; border: 2px solid var(--accent-color);
    color: var(--accent-color); background: transparent; border-radius: 5px; position: relative;
    overflow: hidden; transition: color var(--animation-speed), border-color var(--animation-speed); z-index: 1; cursor: pointer;
}
.btn::before {
    content: ''; position: absolute; top: 0; left: 0; width: 100%; height: 100%;
    background: var(--accent-color); transform: translateX(-100%);
    transition: transform var(--animation-speed) ease-in-out, background-color var(--animation-speed); z-index: -1;
}
.btn:hover { color: var(--bg-color); }
.btn:hover::before { transform: translateX(0); }
.btn-secondary { border-color: var(--accent-color-secondary); color: var(--accent-color-secondary); }
.btn-secondary::before { background: var(--accent-color-secondary); }
.section { padding: 80px 0; }
.section-title { text-align: center; margin-bottom: 60px; position: relative; }
.section-title::after {
    content: ''; display: block; width: 100px; height: 4px;
    background: linear-gradient(90deg, var(--accent-color), var(--accent-color-secondary));
    margin: 15px auto 0; border-radius: 2px;
}
.card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 30px; }
.card {
    background: linear-gradient(145deg, var(--bg-color-lighter), var(--bg-color));
    border: 1px solid var(--border-color); border-radius: 10px; padding: 25px;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
    transition: transform var(--animation-speed) ease, box-shadow var(--animation-speed) ease, border-color var(--animation-speed) ease;
    position: relative; overflow: hidden; transform-style: preserve-3d; display: flex; flex-direction: column;
}
.card > * { z-index: 2; }
.card:hover {
    transform: translateY(-15px) scale(1.05) rotateX(5deg) rotateY(3deg);
    border-color: var(--accent-color);
    box-shadow: 0 20px 50px rgba(0,0,0,0.5), 0 0 25px var(--glow-color);
}
.card-image-placeholder { width: 100%; height: 200px; background-color: var(--bg-color); border-radius: 8px; margin-bottom: 20px; overflow: hidden; }
.card-image-placeholder img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.4s ease; }
.card:hover .card-image-placeholder img { transform: scale(1.1); }
.card h3 { font-size: 1.6rem; }
.card p { flex-grow: 1; }
.card .price { font-size: 1.5rem; font-weight: bold; color: var(--accent-color-secondary); }
form {
    display: flex; flex-direction: column; gap: 20px; background: var(--bg-color-lighter);
    padding: 40px; border-radius: 10px; border: 1px solid var(--border-color);
    box-shadow: 0 0 20px rgba(0,229,255,0.1);
}
form label { font-family: var(--font-headings); font-size: 1rem; color: var(--accent-color); }
form input, form select, form textarea {
    width: 100%; padding: 15px; background: var(--bg-color); border: 1px solid var(--border-color);
    border-radius: 5px; color: var(--text-color); font-family: var(--font-main); font-size: 1rem;
    transition: border-color var(--animation-speed), box-shadow var(--animation-speed);
}
form textarea { resize: vertical; min-height: 150px; }
form input:focus, form select:focus, form textarea:focus { outline: none; border-color: var(--accent-color); box-shadow: 0 0 15px var(--glow-color); }
footer { background-color: var(--bg-color-lighter); color: #aaa; padding: 50px 0; text-align: center; border-top: 2px solid var(--border-color); margin-top: 60px; }
footer .footer-links { list-style: none; display: flex; gap: 25px; justify-content: center; margin-bottom: 20px; }
.pricing-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 40px; align-items: center; }
.pricing-card { background: var(--bg-color-lighter); border: 2px solid var(--border-color); padding: 40px 30px; border-radius: 15px; text-align: center; transition: all 0.4s ease; }
.pricing-card.featured { transform: scale(1.1); border-color: var(--accent-color); box-shadow: 0 0 30px var(--glow-color); }
.pricing-card h3 { font-size: 2rem; }
.pricing-card .price { font-family: var(--font-headings); font-size: 3.5rem; margin: 20px 0; color: var(--accent-color); }
.pricing-card .price span { font-size: 1rem; color: #ccc; }
.pricing-card ul { list-style: none; margin-bottom: 30px; }
.pricing-card ul li { padding: 10px 0; border-bottom: 1px solid var(--border-color); }
.pricing-card ul li:last-child { border-bottom: none; }
.menu-toggle { display: none; font-size: 2.5rem; color: var(--accent-color); background: none; border: none; cursor: pointer; }
@media (max-width: 992px) {
    h1 { font-size: 2.8rem; } .hero h1 { font-size: 3.5rem; } .menu-toggle { display: block; }
    nav ul {
        display: none; flex-direction: column; position: absolute; top: 100%; right: 0;
        background: var(--bg-color-lighter); width: 100%; padding: 20px; border-top: 1px solid var(--border-color);
    }
    nav ul.active { display: flex; }
    nav ul li { margin: 15px 0; width: 100%; text-align: center; }
}
.text-center { text-align: center; } .mt-3 { margin-top: 1.5rem; } .mb-3 { margin-bottom: 1.5rem; }
.fade-in-section { opacity: 0; transform: translateY(40px); transition: opacity 0.8s ease-out, transform 0.8s ease-out; }
.fade-in-section.is-visible { opacity: 1; transform: translateY(0); }
.shop-layout { display: flex; flex-wrap: wrap; gap: 30px; }
.shop-products { flex: 3; min-width: 300px; }
.shop-cart { flex: 1; min-width: 280px; background: var(--bg-color-lighter); padding: 25px; border-radius: 10px; border: 1px solid var(--border-color); height: fit-content; position: sticky; top: 120px; }
.shop-cart-items ul { list-style: none; }
.shop-cart-items li { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid var(--border-color); }
.remove-from-cart-btn { background: var(--accent-color-secondary); border: none; color: white; cursor: pointer; padding: 3px 8px; border-radius: 3px; }
#cart-total { margin-top: 20px; font-size: 1.2rem; font-weight: bold; }
.auth-container { max-width: 500px; margin: 80px auto; }
#notification-container { position: fixed; top: 90px; right: 20px; z-index: 2000; display: flex; flex-direction: column; gap: 10px; }
.toast {
    padding: 15px 20px; border-radius: 8px; color: #fff; font-weight: bold;
    min-width: 250px; background-color: var(--bg-color-lighter);
    border-left: 5px solid var(--accent-color);
    box-shadow: 0 5px 15px rgba(0,0,0,0.4);
    animation: slideIn 0.5s ease-out forwards;
    display: flex; justify-content: space-between; align-items: center;
}
.toast.success { border-left-color: var(--accent-color); }
.toast.error { border-left-color: var(--accent-color-secondary); }
.toast.fade-out { animation: fadeOut 0.5s ease-in forwards; }
.toast-close { background: none; border: none; color: #fff; font-size: 1.5rem; cursor: pointer; opacity: 0.7; transition: opacity 0.3s; }
.toast-close:hover { opacity: 1; }
@keyframes slideIn { from { transform: translateX(120%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
@keyframes fadeOut { from { opacity: 1; } to { opacity: 0; transform: translateY(-20px); } }
.service-icon { font-size: 3rem; margin-bottom: 1rem; color: var(--accent-color); }
/* --- Carousel Styles --- */
.carousel-section { padding: 0; height: 85vh; max-height: 800px; display: flex; align-items: center; justify-content: center; overflow: hidden; background: #050511; }
.carousel-container { width: 100%; height: 100%; position: relative; perspective: 1200px; }
.carousel-slide {
    position: absolute; width: 100%; height: 100%;
    transform-style: preserve-3d;
    transition: transform 0.8s cubic-bezier(0.77, 0, 0.175, 1), opacity 0.8s ease;
    opacity: 0;
}
.carousel-slide.active { opacity: 1; z-index: 10; transform: translateZ(0) translateX(0) rotateY(0); }
.carousel-slide.prev { opacity: 0.4; z-index: 5; transform: translateZ(-300px) translateX(-50%) rotateY(35deg); }
.carousel-slide.next { opacity: 0.4; z-index: 5; transform: translateZ(-300px) translateX(50%) rotateY(-35deg); }
.carousel-image { width: 100%; height: 100%; object-fit: cover; border-radius: 10px; filter: brightness(0.6); }
.carousel-content {
    position: absolute; bottom: 10%; left: 50%; transform: translateX(-50%);
    color: white; text-align: center; width: 80%; max-width: 700px;
    background: rgba(0,0,0,0.5); backdrop-filter: blur(5px); padding: 2rem; border-radius: 10px;
}
.carousel-content h2 { font-size: 2.5rem; text-shadow: 2px 2px 8px #000; margin: 0; }
.carousel-content p { font-size: 1.1rem; margin: 0.5rem 0 1.5rem; }
.carousel-nav-btn {
    position: absolute; top: 50%; transform: translateY(-50%); z-index: 20;
    background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2);
    color: white; font-size: 2rem; width: 50px; height: 50px; border-radius: 50%;
    cursor: pointer; transition: background-color 0.3s;
}
.carousel-nav-btn:hover { background: rgba(255,255,255,0.2); }
#carousel-prev { left: 2%; }
#carousel-next { right: 2%; }
.carousel-dots {
    position: absolute; bottom: 20px; left: 50%; transform: translateX(-50%);
    z-index: 20; display: flex; gap: 10px;
}
.carousel-dot { width: 12px; height: 12px; border-radius: 50%; background: rgba(255,255,255,0.4); cursor: pointer; transition: background-color 0.3s; }
.carousel-dot.active { background: var(--accent-color); }
.carousel-progress-bar { position: absolute; bottom: 0; left: 0; height: 4px; background: var(--accent-color); width: 0; z-index: 21; }
@keyframes progress { from { width: 0%; } to { width: 100%; } }
"""
GLOBAL_JS = """
document.addEventListener('DOMContentLoaded', function() {
    // Apply saved theme on page load
    applyTheme(localStorage.getItem('sloganTechTheme') || 'theme-cyan');

    const menuToggle = document.querySelector('.menu-toggle');
    const navUl = document.querySelector('nav ul');
    if (menuToggle && navUl) {
        menuToggle.addEventListener('click', () => navUl.classList.toggle('active'));
    }
    const navLinks = document.querySelectorAll('nav ul li a');
    const currentLocation = window.location.pathname;
    navLinks.forEach(link => {
        if (link.getAttribute('href') === currentLocation) {
            link.classList.add('active');
        }
    });
    const sections = document.querySelectorAll('.fade-in-section');
    const observer = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('is-visible');
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.1 });
    sections.forEach(section => observer.observe(section));
});
function showToast(message, type = 'info', duration = 5000) {
    let container = document.getElementById('notification-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'notification-container';
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span>${message}</span><button class="toast-close">×</button>`;
    container.appendChild(toast);
    const removeToast = () => {
        toast.classList.add('fade-out');
        toast.addEventListener('animationend', () => toast.remove());
    };
    const timer = setTimeout(removeToast, duration);
    toast.querySelector('.toast-close').addEventListener('click', () => {
        clearTimeout(timer);
        removeToast();
    });
}
function applyTheme(themeName) {
    const themes = {
        'theme-cyan': {
            '--theme-accent': '#00e5ff',
            '--theme-accent-secondary': '#ff3d00',
            '--theme-border': 'rgba(0, 229, 255, 0.2)',
            '--theme-glow': 'rgba(0, 229, 255, 0.7)'
        },
        'theme-orange': {
            '--theme-accent': '#ff9100',
            '--theme-accent-secondary': '#00e5ff',
            '--theme-border': 'rgba(255, 145, 0, 0.3)',
            '--theme-glow': 'rgba(255, 145, 0, 0.7)'
        },
        'theme-purple': {
            '--theme-accent': '#d500f9',
            '--theme-accent-secondary': '#64ffda',
            '--theme-border': 'rgba(213, 0, 249, 0.3)',
            '--theme-glow': 'rgba(213, 0, 249, 0.7)'
        }
    };
    const selectedTheme = themes[themeName] || themes['theme-cyan'];
    for (const [key, value] of Object.entries(selectedTheme)) {
        document.documentElement.style.setProperty(key, value);
    }
    localStorage.setItem('sloganTechTheme', themeName);
}
class Carousel {
    constructor(selector) {
        this.container = document.querySelector(selector);
        if (!this.container) return;
        this.slides = this.container.querySelectorAll('.carousel-slide');
        this.dots = this.container.querySelectorAll('.carousel-dot');
        this.nextBtn = document.getElementById('carousel-next');
        this.prevBtn = document.getElementById('carousel-prev');
        this.currentIndex = 0;
        this.slideInterval;
        this.progressBar = this.container.querySelector('.carousel-progress-bar');
        this.init();
    }
    init() {
        this.nextBtn.addEventListener('click', () => this.nextSlide());
        this.prevBtn.addEventListener('click', () => this.prevSlide());
        this.dots.forEach(dot => {
            dot.addEventListener('click', (e) => this.goToSlide(parseInt(e.target.dataset.index)));
        });
        this.container.addEventListener('mouseenter', () => this.pause());
        this.container.addEventListener('mouseleave', () => this.play());
        this.updateCarousel();
        this.play();
    }
    goToSlide(index) {
        this.currentIndex = index;
        this.updateCarousel();
        this.resetInterval();
    }
    nextSlide() {
        this.currentIndex = (this.currentIndex + 1) % this.slides.length;
        this.updateCarousel();
        this.resetInterval();
    }
    prevSlide() {
        this.currentIndex = (this.currentIndex - 1 + this.slides.length) % this.slides.length;
        this.updateCarousel();
        this.resetInterval();
    }
    updateCarousel() {
        const prevIndex = (this.currentIndex - 1 + this.slides.length) % this.slides.length;
        const nextIndex = (this.currentIndex + 1) % this.slides.length;
        this.slides.forEach((slide, index) => {
            slide.classList.remove('active', 'prev', 'next');
            if (index === this.currentIndex) slide.classList.add('active');
            else if (index === prevIndex) slide.classList.add('prev');
            else if (index === nextIndex) slide.classList.add('next');
        });
        this.dots.forEach((dot, index) => {
            dot.classList.toggle('active', index === this.currentIndex);
        });
        this.startProgressBar();
    }
    play() {
        this.slideInterval = setInterval(() => this.nextSlide(), 5000);
        this.startProgressBar();
    }
    pause() {
        clearInterval(this.slideInterval);
        this.progressBar.style.animationPlayState = 'paused';
    }
    resetInterval() {
        this.pause();
        this.play();
    }
    startProgressBar() {
        if(this.progressBar) {
            this.progressBar.style.animation = 'none';
            // Trigger reflow
            this.progressBar.offsetHeight; 
            this.progressBar.style.animation = 'progress 5s linear forwards';
            this.progressBar.style.animationPlayState = 'running';
        }
    }
"""
SHOP_COMPONENT_JS = """
class ShopComponent {
    constructor(containerId, apiBaseUrl) {
        this.container = document.getElementById(containerId);
        if (!this.container) return;
        this.apiBaseUrl = apiBaseUrl;
        this.products = [];
        this.cart = JSON.parse(localStorage.getItem('sloganTechCart')) || {};
        this.stripe = null;
        this.init();
    }
    async initStripe() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/payments/stripe-key`);
            const { publishableKey } = await response.json();
            this.stripe = Stripe(publishableKey);
        } catch (e) {
            console.error("Could not initialize Stripe", e);
            showToast("Payment system failed to load.", "error");
        }
    }
    async fetchProducts() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/products/all`);
            this.products = await response.json();
        } catch (error) {
            console.error("Error fetching products:", error);
        }
    }
    async createCheckoutSession() {
        if (!this.stripe) {
            showToast("Payment system is not ready. Please try again.", "error");
            return;
        }
        const line_items = Object.keys(this.cart).map(productId => {
            const product = this.products.find(p => p.id.toString() === productId);
            return (product && product.stripe_price_id) ? { price: product.stripe_price_id, quantity: this.cart[productId] } : null;
        }).filter(item => item !== null);

        if (line_items.length === 0) {
            showToast("Your cart is empty or has no purchasable items.", "error");
            return;
        }
        try {
            showToast("Redirecting to secure checkout...", "info");
            const response = await fetch(`${this.apiBaseUrl}/payments/create-checkout-session`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                body: JSON.stringify({ line_items })
            });
            const session = await response.json();
            if (response.ok) {
                const result = await this.stripe.redirectToCheckout({ sessionId: session.id });
                if (result.error) showToast(result.error.message, "error");
            } else {
                 showToast(session.detail || "Could not proceed to checkout.", "error");
            }
        } catch (error) {
             showToast("An error occurred. Please try again.", "error");
        }
    }
    renderProductCard(product) {
        const isSub = product.category === 'subscription';
        const buttonText = isSub ? 'View Plans' : 'Add to Cart';
        const buttonAction = isSub ? `window.location.href='/subscriptions'` : `ShopComponentInstance.addToCart('${product.id}')`;
        return `
            <div class="card product-card" data-id="${product.id}">
                <div class="card-image-placeholder"><img src="${product.image_url || '/static_placeholder/img/default.jpg'}" alt="${product.name}"></div>
                <h3>${product.name}</h3>
                <p class="price">$${product.price.toFixed(2)}</p>
                <p>${product.description.substring(0, 100)}...</p>
                <button class="btn mt-3" onclick="${buttonAction}" ${!product.stripe_price_id && !isSub ? 'disabled' : ''}>${buttonText}</button>
            </div>
        `;
    }
    renderCart() {
        const cartItemsContainer = document.getElementById('cart-items');
        const cartTotalEl = document.getElementById('cart-total');
        if (!cartItemsContainer || !cartTotalEl) return;
        let cartHTML = '<ul>';
        let total = 0;
        if (Object.keys(this.cart).length === 0) {
            cartHTML = '<p>Your cart is empty.</p>';
        } else {
            for (const productId in this.cart) {
                const product = this.products.find(p => p.id.toString() === productId);
                if (product) {
                    const quantity = this.cart[productId];
                    cartHTML += `<li><span>${product.name} (x${quantity})</span><span>$${(product.price * quantity).toFixed(2)}</span><button class="remove-from-cart-btn" onclick="ShopComponentInstance.removeFromCart('${productId}')">×</button></li>`;
                    total += product.price * quantity;
                }
            }
            cartHTML += '</ul>';
        }
        cartItemsContainer.innerHTML = cartHTML;
        cartTotalEl.innerHTML = `Total: <strong>$${total.toFixed(2)}</strong>`;
    }
    addToCart(productId) {
        this.cart[productId] = (this.cart[productId] || 0) + 1;
        const product = this.products.find(p => p.id.toString() === productId);
        if(product) showToast(`${product.name} added to cart!`, "success");
        this.updateCart();
    }
    removeFromCart(productId) {
        if (this.cart[productId]) {
            delete this.cart[productId];
            this.updateCart();
        }
    }
    updateCart() {
        localStorage.setItem('sloganTechCart', JSON.stringify(this.cart));
        this.renderCart();
    }
    async init() {
        this.container.innerHTML = '<p>Loading Hyper-Dimensional Commerce Matrix...</p>';
        window.ShopComponentInstance = this;
        await this.initStripe();
        await this.fetchProducts();
        const productsHTML = `<div class="card-grid">${this.products.filter(p => p.category !== 'subscription' && p.category !== 'course').map(p => this.renderProductCard(p)).join('')}</div>`;
        this.container.innerHTML = `
            <div class="shop-layout">
                <div class="shop-products">
                    <h2 class="section-title">Our Store</h2>
                    ${productsHTML}
                </div>
                <aside class="shop-cart">
                    <h3>Your Cart</h3>
                    <div id="cart-items" class="shop-cart-items"></div>
                    <div id="cart-total"></div>
                    <button class="btn" id="checkout-btn" style="width: 100%; margin-top: 20px;">Checkout</button>
                </aside>
            </div>
        `;
        this.renderCart();
        document.getElementById('checkout-btn').addEventListener('click', () => this.createCheckoutSession());
    }
}
if (document.getElementById('shop-component-container')) {
    new ShopComponent('shop-component-container', '/api');
}
"""
# --- ========================== ---
# --- 8. FastAPI APP & HTML HELPERS ---
# --- ========================== ---
app = FastAPI(title=APP_TITLE)


@app.get("/static_placeholder/img/{image_name}")
@app.get("/static_placeholder/img/{image_name}")
async def get_placeholder_image(image_name: str):
    svg_content = f"""<svg width="400" height="300" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300"><rect width="100%" height="100%" fill="#1a1a3a"/><text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" font-family="Orbitron" font-size="20" fill="var(--accent-color)">SLOGAN TECH</text><text x="50%" y="60%" dominant-baseline="middle" text-anchor="middle" font-family="Rajdhani" font-size="16" fill="#e0e0e0">{image_name}</text></svg>"""
    return Response(content=svg_content, media_type="image/svg+xml")


def get_base_html(title: str, content: str, request: Request, current_page: str, extra_js: str = ""):
    # UPDATED NAVIGATION ITEMS
    nav_items = [
        {"name": "Home", "path": "/"},
        {"name": "Services", "path": "/services"},
        {"name": "Courses", "path": "/courses"},
        {"name": "Subscriptions", "path": "/subscriptions"},
        {"name": "Shop", "path": "/shop"},
        {"name": "Contact", "path": "/contact"}
    ]

    user = request.state.user if hasattr(request.state, "user") else None
    nav_html = "".join(
        f'<li><a href="{item["path"]}" class="{"active" if item["path"] == current_page else ""}">{item["name"]}</a></li>'
        for item in nav_items)

    auth_buttons = ""
    if user:
        display_name = user.get('full_name') or user['username']
        dashboard_link = "/admin" if user.get('role') == 'admin' else "/dashboard"
        dashboard_text = "Admin Panel" if user.get('role') == 'admin' else "Dashboard"
        auth_buttons = f"""
            <li><a href="{dashboard_link}" class="btn">{dashboard_text}</a></li>
            <li><a href="/auth/logout" class="btn btn-secondary" title="Logged in as {display_name}">Logout</a></li>
        """
    else:
        auth_buttons = f"""
            <li><a href="/login">Login</a></li>
            <li><a href="/register" class="btn">Sign Up</a></li>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title} | {APP_TITLE}</title>
        <style>{GLOBAL_CSS}</style><script src="https://js.stripe.com/v3/"></script>
        <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🚀</text></svg>">
    </head>
    <body>
        <header>
            <div class="container">
                <a href="/" class="logo">Slogan<span>Tech</span></a>
                <nav><ul>{nav_html}{auth_buttons}</ul></nav>
                <button class="menu-toggle" aria-label="Toggle navigation">☰</button>
            </div>
        </header>
        <main>{content}</main>
        <footer>
            <div class="container footer-content">
                <ul class="footer-links">
                    <li><a href="/about">About Us</a></li>
                    <li><a href="/blog">Blog</a></li>
                    <li><a href="/privacy">Privacy Policy</a></li>
                    <li><a href="/terms">Terms of Service</a></li>
                    <li><a href="/careers">Careers</a></li>
                </ul>
                <p>© {datetime.datetime.now().year} {APP_TITLE}. All rights reserved. Powered by the IntelliWeb Engine v2.3.2.</p>
            </div>
        </footer>
        <script>{GLOBAL_JS}</script><script>{extra_js}</script>
    </body>
    </html>
    """


@app.middleware("http")
async def add_user_to_state(request: Request, call_next):
    # ... (Middleware is unchanged and correct) ...
    request.state.user = None
    try:
        token = await get_token_from_cookie(request)
        if token:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            username: str = payload.get("sub")
            if username:
                with get_db_connection() as conn:
                    user_data = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
                    if user_data: request.state.user = dict(user_data)
    except (JWTError, sqlite3.Error):
        pass
    response = await call_next(request)
    return response


# --- ================== ---
# --- 9. PAGE ENDPOINTS ---
# --- ================== ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    with get_db_connection() as conn:
        featured_products = conn.execute(
            "SELECT * FROM products WHERE is_featured = 1 AND category != 'subscription' LIMIT 3").fetchall()
    featured_html = "".join([f"""
    <div class="card">
        <div class="card-image-placeholder"><img src="{p['image_url']}" alt="{p['name']}"></div>
        <h3>{p['name']}</h3><p>{p['description']}</p>
        <a href="{'/' + p['category'] + ('s' if p['category'] != 'game' else '')}" class="btn mt-3">Explore</a>
    </div>
    """ for p in featured_products])
    content = f"""
    <section class="hero">
        <div class="hero-content">
            <h1>Forge The Future</h1>
            <p>Pioneering advancements in AI, Game Development, and Robotics to empower the next generation of African creators.</p>
            <a href="/courses" class="btn">Start Learning</a>
            <a href="/shop" class="btn btn-secondary" style="margin-left: 20px;">Explore Tech</a>
        </div>
    </section>
    <section id="features" class="section fade-in-section">
        <div class="container">
            <h2 class="section-title">Our Innovations</h2>
            <div class="card-grid">{featured_html}</div>
        </div>
    </section>
    """
    return HTMLResponse(get_base_html("Home", content, request, "/"))


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    content = """
    <section class="section"><div class="auth-container">
        <h2 class="section-title">Create Account</h2>
        <form id="registerForm">
            <label for="username">Username</label><input type="text" id="username" name="username" required>
            <label for="email">Email</label><input type="email" id="email" name="email" required>
            <label for="full_name">Full Name</label><input type="text" id="full_name" name="full_name" required>
            <label for="password">Password</label><input type="password" id="password" name="password" required>
            <button type="submit" class="btn" style="width:100%;">Register</button>
        </form>
        <p class="text-center mt-3">Already have an account? <a href="/login">Log in here</a>.</p>
    </div></section>
    <script>
        document.getElementById('registerForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target).entries());
            showToast('Creating account...', 'info', 2000);
            try {
                const response = await fetch('/auth/register', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
                });
                const result = await response.json();
                if (response.ok) {
                    showToast('Account created! Redirecting...', 'success');
                    setTimeout(() => window.location.href = '/login', 2000);
                } else { showToast(result.detail || 'Registration failed.', 'error'); }
            } catch (error) { showToast('Network error.', 'error'); }
        });
    </script>
    """
    return HTMLResponse(get_base_html("Register", content, request, "/register"))


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    content = """
    <section class="section"><div class="auth-container">
        <h2 class="section-title">Login</h2>
        <form id="loginForm">
            <label for="username">Username or Email</label><input type="text" id="username" name="username" required>
            <label for="password">Password</label><input type="password" id="password" name="password" required>
            <button type="submit" class="btn" style="width:100%;">Login</button>
        </form>
        <p class="text-center mt-3">Don't have an account? <a href="/register">Register here</a>.</p>
    </div></section>
    <script>
        document.getElementById('loginForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const formData = new URLSearchParams(new FormData(e.target));
            showToast('Logging in...', 'info', 2000);
            try {
                const response = await fetch('/auth/token', { method: 'POST', body: formData });
                if (response.ok) {
                    showToast('Login successful! Redirecting...', 'success');
                    setTimeout(() => window.location.href = '/dashboard', 1000);
                } else {
                    const result = await response.json();
                    showToast(result.detail || 'Invalid credentials.', 'error');
                }
            } catch (error) { showToast('Network error.', 'error'); }
        });
    </script>
    """
    return HTMLResponse(get_base_html("Login", content, request, "/login"))


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, current_user: dict = Depends(get_current_active_user)):
    if current_user.get("role") == "admin": return RedirectResponse(url="/admin")

    profile_pic_url = current_user.get('profile_picture_url') or '/static_placeholder/img/avatar_default.svg'

    content = f"""
    <section class="section"><div class="container">
        <div class="text-center">
            <img src="{profile_pic_url}" alt="Profile Picture" class="profile-picture">
            <h2 class="section-title" style="margin-bottom: 2rem;">Welcome, {current_user['full_name']}</h2>
        </div>
        <div class="card-grid" style="grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));">
             <div class="card text-center">
                <h3>Account Details</h3>
                <p><strong>Subscription:</strong> <span style="text-transform: capitalize;">{current_user['subscription_plan']}</span></p>
                <p><strong>Status:</strong> <span style="text-transform: capitalize;">{current_user['subscription_status'] or 'N/A'}</span></p>
                <a href="/subscriptions" class="btn mt-3">Manage Plan</a>
            </div>
            <div class="card text-center">
                <h3>Profile Settings</h3>
                <p>Update your name, email, and app preferences.</p>
                <a href="/settings" class="btn btn-secondary mt-3">Go to Settings</a>
            </div>
        </div>
    </div></section>
    """
    return HTMLResponse(get_base_html("Dashboard", content, request, "/dashboard"))


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, current_user: dict = Depends(get_current_active_user)):
    profile_pic_url = current_user.get('profile_picture_url') or ''
    content = f"""
    <section class="section"><div class="container" style="max-width: 900px;">
        <h2 class="section-title">User Settings</h2>
        <div class="card mb-3">
            <h3>Profile Information</h3>
            <form id="profileUpdateForm">
                <div class="text-center">
                    <img src="{profile_pic_url or '/static_placeholder/img/avatar_default.svg'}" alt="Profile Picture" class="profile-picture">
                </div>
                <label for="full_name">Full Name</label><input type="text" id="full_name" name="full_name" value="{current_user['full_name']}" required>
                <label for="email">Email Address</label><input type="email" id="email" name="email" value="{current_user['email']}" required>
                <label for="profile_picture_url">Profile Picture URL</label><input type="url" id="profile_picture_url" name="profile_picture_url" value="{profile_pic_url}" placeholder="https://example.com/image.png">
                <button type="submit" class="btn mt-3">Update Profile</button>
            </form>
        </div>
        <div class="card">
            <h3>Appearance & Preferences</h3>
            <form>
                <label for="theme-select">Color Theme</label>
                <select id="theme-select">
                    <option value="theme-cyan">Cyber Cyan (Default)</option><option value="theme-orange">Fusion Orange</option><option value="theme-purple">Galactic Purple</option>
                </select>
                <label for="language-select" class="mt-3">Language</label>
                <select id="language-select"><option value="en-US">English (US)</option><option disabled>More Soon</option></select>
            </form>
        </div>
    </div></section>
    <script>
        const themeSelect = document.getElementById('theme-select');
        themeSelect.value = localStorage.getItem('sloganTechTheme') || 'theme-cyan';
        themeSelect.addEventListener('change', (e) => applyTheme(e.target.value));
        document.getElementById('profileUpdateForm').addEventListener('submit', async function(e) {{
            e.preventDefault(); const data = Object.fromEntries(new FormData(e.target).entries());
            showToast('Updating profile...', 'info');
            try {{
                const r = await fetch('/api/user/update', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(data) }});
                const res = await r.json();
                if (r.ok) {{ showToast(res.message, 'success'); setTimeout(() => window.location.reload(), 1500); }}
                else {{ showToast(res.detail || 'Update failed.', 'error'); }}
            }} catch (err) {{ showToast('Network error.', 'error'); }}
        }});
    </script>
    """
    return HTMLResponse(get_base_html("Settings", content, request, "/settings"))


@app.get("/services", response_class=HTMLResponse)
async def services_page(request: Request):
    services = [
        {"icon": "🤖", "title": "Artificial Intelligence (AI)",
         "desc": "Developing AI-driven solutions for various industries, including healthcare, finance, and retail."},
        {"icon": "📈", "title": "Machine Learning (ML)",
         "desc": "Implementing ML algorithms to improve data analysis and decision-making processes."},
        {"icon": "👁️", "title": "Computer Vision (CV)",
         "desc": "Creating CV systems for applications such as facial recognition, object detection, and autonomous vehicles."},
        {"icon": "💻", "title": "Software Development",
         "desc": "Providing custom software solutions for businesses of all sizes."},
        {"icon": "🌐", "title": "Web Development",
         "desc": "Designing and building robust, user-friendly websites and web applications."},
        {"icon": "🛡️", "title": "Cybersecurity",
         "desc": "Protecting digital assets from cyber threats through advanced security measures."},
        {"icon": "🎮", "title": "Game Development",
         "desc": "Building immersive 2D and 3D games using advanced game engines, AI mechanics, and interactive storytelling."},
        {"icon": "🦾", "title": "Robotics Development",
         "desc": "Designing and programming intelligent robotic systems for automation and industrial applications."},
        {"icon": "🎓", "title": "Technology Education",
         "desc": "Offering training programs and workshops to equip individuals with the skills needed to thrive in the tech industry."}
    ]
    services_html = "".join([f"""
    <div class="card text-center">
        <div class="service-icon">{s['icon']}</div>
        <h4>{s['title']}</h4><p>{s['desc']}</p>
    </div>
    """ for s in services])
    content = f"""
    <section class="section"><div class="container">
        <h2 class="section-title">Our Services</h2>
        <p class="text-center mb-3" style="font-size: 1.2rem;">We offer a comprehensive suite of technology services to power your vision.</p>
        <div class="card-grid">{services_html}</div>
    </div></section>
    """
    return HTMLResponse(get_base_html("Our Services", content, request, "/services"))


@app.get("/subscriptions", response_class=HTMLResponse)
async def subscriptions_page(request: Request):
    with get_db_connection() as conn:
        plans = conn.execute("SELECT * FROM products WHERE category = 'subscription' ORDER BY price").fetchall()
    plans_html = ""
    for plan in plans:
        details = json.loads(plan['details'] or '{}')
        features_html = "".join([f"<li>{feature}</li>" for feature in details.get('features', [])])
        plans_html += f"""
        <div class="pricing-card {'featured' if plan['is_featured'] else ''}">
            <h3>{plan['name']}</h3><p>{plan['description']}</p>
            <div class="price">${plan['price']:.0f}<span>/month</span></div>
            <ul>{features_html}</ul>
            <form action="/api/payments/create-checkout-session" method="POST">
                <input type="hidden" name="price_id" value="{plan['stripe_price_id']}" />
                <button type="submit" class="btn {'btn-secondary' if plan['is_featured'] else ''}">Choose Plan</button>
            </form>
        </div>
        """
    content = f"""
    <section class="section"><div class="container">
        <h2 class="section-title">Subscription Plans</h2>
        <p class="text-center mb-3">Unlock your potential. Choose a plan that fits your journey.</p>
        <div class="pricing-grid">{plans_html}</div>
    </div></section>
    """
    return HTMLResponse(get_base_html("Subscriptions", content, request, "/subscriptions"))


@app.get("/shop", response_class=HTMLResponse)
async def shop_page(request: Request):
    content = """<section class="section"><div class="container"><div id="shop-component-container"></div></div></section>"""
    return HTMLResponse(get_base_html("Shop", content, request, "/shop", extra_js=SHOP_COMPONENT_JS))


@app.get("/payment/success", response_class=HTMLResponse)
async def payment_success(request: Request):
    content = """
    <section class="section text-center"><div class="container">
        <h2 class="section-title">Payment Successful!</h2>
        <p>Thank you for your purchase. Your account has been updated.</p>
        <a href="/dashboard" class="btn mt-3">Go to Dashboard</a>
    </div></section>
    """
    return HTMLResponse(get_base_html("Payment Success", content, request, "/"))


@app.get("/payment/cancel", response_class=HTMLResponse)
async def payment_cancel(request: Request):
    content = """
    <section class="section text-center"><div class="container">
        <h2 class="section-title" style="color:var(--accent-color-secondary);">Payment Cancelled</h2>
        <p>Your payment process was cancelled. You have not been charged.</p>
        <a href="/shop" class="btn mt-3">Back to Shop</a>
    </div></section>
    """
    return HTMLResponse(get_base_html("Payment Cancelled", content, request, "/"))


@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    team_members = [
        {"name": "Olayiwola Akabashorun", "role": "Co-Founder", "img": "/static_placeholder/img/avatar_male.svg"},
        {"name": "Aondover Pascal Oryiman", "role": "Co-Founder",
         "img": "/static_placeholder/img/avatar_male.svg"},
        {"name": "Kareeem Akabashorun", "role": "CTO", "img": "/static_placeholder/img/avatar_female.svg"},
        {"name": "Solomon", "role": "Data Analytics", "img": "/static_placeholder/img/avatar_female.svg"},
    ]
    team_html = "".join([
                            f"""<div class="card text-center"><img src="{m['img']}" alt="{m['name']}" class="profile-picture" style="width:100px; height:100px; margin:auto; margin-bottom:1rem;" ><h4>{m['name']}</h4><p><em>{m['role']}</em></p></div>"""
                            for m in team_members])

    content = f"""
    <section class="section"><div class="container" style="max-width: 900px;">
        <h2 class="section-title">About Slogan</h2>
        <div class="card mb-3"><h3 class="mb-3">Our Mission</h3>
            <p>Our mission is to push the boundaries of Game, AI and Robotics, bringing Africa to the forefront of technological advancements. We aim to create a sustainable and inclusive technological ecosystem that fosters economic growth, improves quality of life, and enhances the competitiveness of African businesses on the global stage.</p>
        </div>
        <div class="card mb-3"><h3 class="mb-3">Our Vision</h3>
            <p>To be the premier Game, AI and Robotics development firm in Africa, recognized for our cutting-edge technology, innovative solutions, and commitment to empowering communities through technology.</p>
        </div>
        <h3 class="section-title">Our Team</h3>
        <div class="card-grid" style="grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));">{team_html}</div>
    </div></section>
    <section class="section" style="background: var(--bg-color-lighter);"><div class="container">
        <h3 class="section-title">Our Location</h3>
        <div class="card text-center">
            <p><strong>Lagos, Nigeria Headquarters</strong></p>
            <p>123 Tech Road, Ikoyi, Lagos, Nigeria</p>
            <div class="map-container" style="border-radius:8px; overflow:hidden; margin-top:1rem; border:2px solid var(--border-color);">
                <iframe src="https://www.google.com/maps/embed?pb=!1m18!1m12!1m3!1d63426.23304423714!2d3.386221448100589!3d6.44464696048185!2m3!1f0!2f0!3f0!3m2!1i1024!2i768!4f13.1!3m3!1m2!1s0x103b8b1e424f3315%3A0x260c880424694b46!2sIkoyi%2C%20Lagos!5e0!3m2!1sen!2sng!4v1677678822558!5m2!1sen!2sng" width="100%" height="450" style="border:0;" allowfullscreen="" loading="lazy" referrerpolicy="no-referrer-when-downgrade"></iframe>
            </div>
        </div>
    </div></section>
    """
    return HTMLResponse(get_base_html("About Us", content, request, "/about"))


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    content = """
        <section class="section">
            <div class="container">
                <h2 class="section-title">Privacy Policy for Slogan Technologies LLC</h2>
                <p><strong>Last Updated:</strong> [Insert Date]</p>
                <p>Your privacy is important to us. This Privacy Policy explains how Slogan Technologies LLC ("we," "us," or "our") collects, uses, shares, and protects information in relation to our services, which include game development, artificial intelligence (AI), robotics, software development, and technology education (collectively, the "Services"). This policy applies to our website, applications, and any other interactions you may have with us.</p>
                <p>By using our Services, you agree to the collection and use of information in accordance with this policy. This policy is designed to comply with relevant regulations, including the General Data Protection Regulation (GDPR) and the Nigeria Data Protection Regulation (NDPR).</p>

                <h3>1. Information We Collect</h3>
                <p>We may collect the following types of information:</p>
                <ul>
                    <li><strong>Personal Identification Information:</strong> Name, email address, phone number, and mailing address that you provide when you fill out a contact form, create an account, or register for our educational programs.</li>
                    <li><strong>Payment Information:</strong> For paid services, subscriptions, or products, we use a third-party payment processor (e.g., Stripe). We do not store your credit card details. We only receive transaction confirmation and necessary user details to provide the service.</li>
                    <li><strong>Technical and Usage Data:</strong> Information collected automatically when you use our website or applications, such as your IP address, browser type, device information, operating system, pages visited, and usage patterns. We use tools like Google Analytics for this purpose.</li>
                    <li><strong>Service-Specific Data:</strong> Depending on the service you use, we may collect additional data. For example:
                        <ul>
                            <li><strong>Healthcare Solutions:</strong> Anonymized or pseudonymized data for medical research and AI model training, subject to explicit consent and strict data governance.</li>
                            <li><strong>Educational Platforms:</strong> Your progress, course completion data, and performance metrics.</li>
                            <li><strong>Games and Simulations:</strong> Gameplay data, in-game purchases, and user-generated content.</li>
                        </ul>
                    </li>
                     <li><strong>Communications:</strong> Records of our correspondence if you contact us for support or inquiries.</li>
                </ul>

                <h3>2. How We Use Your Information</h3>
                <p>We use the information we collect for various purposes, including:</p>
                <ul>
                    <li>To provide, operate, and maintain our Services.</li>
                    <li>To process transactions and manage your subscriptions.</li>
                    <li>To improve, personalize, and expand our Services.</li>
                    <li>To understand and analyze how you use our Services to optimize performance and user experience (A/B testing, analytics).</li>
                    <li>To develop new products, services, features, and functionality.</li>
                    <li>To communicate with you, either directly or through one of our partners, for customer service, to provide you with updates and other information relating to the Service, and for marketing and promotional purposes.</li>
                    <li>To ensure the security of our platforms, prevent fraud, and conduct security audits.</li>
                    <li>To comply with legal obligations.</li>
                </ul>

                <h3>3. How We Share Your Information</h3>
                <p>We do not sell your personal information. We may share your information in the following situations:</p>
                <ul>
                    <li><strong>With Service Providers:</strong> We may share data with third-party vendors who perform services on our behalf, such as cloud hosting (e.g., Amazon Web Services - AWS), payment processing, and analytics. These providers are obligated to protect your data and are restricted from using it for any other purpose.</li>
                    <li><strong>Data Monetization (Anonymized Data):</strong> As stated in our business model, we may analyze and sell anonymized and aggregated data insights. This data cannot be used to identify you personally.</li>
                    <li><strong>For Legal Reasons:</strong> We may disclose your information if required to do so by law or in response to valid requests by public authorities (e.g., a court or a government agency).</li>
                    <li><strong>Business Transfers:</strong> In the event of a merger, acquisition, or asset sale, your information may be transferred.</li>
                </ul>

                <h3>4. Data Security and Backup</h3>
                <p>We implement robust cybersecurity measures to protect your data, including data encryption (in transit and at rest), firewall protection, regular software updates, and employee training. We perform regular data backups to reliable cloud storage (e.g., AWS S3) and have a disaster recovery plan in place to ensure business continuity.</p>

                <h3>5. Your Data Protection Rights</h3>
                <p>Depending on your location, you may have the following rights regarding your personal data:</p>
                <ul>
                    <li>The right to access, update, or delete the information we have on you.</li>
                    <li>The right of rectification.</li>
                    <li>The right to object to our processing of your data.</li>
                    <li>The right of restriction.</li>
                    <li>The right to data portability.</li>
                    <li>The right to withdraw consent at any time.</li>
                </ul>
                <p>To exercise these rights, please contact us using the details below.</p>

                <h3>6. International Data Transfers</h3>
                <p>Your information may be transferred to — and maintained on — computers located outside of your state, province, country, or other governmental jurisdiction where the data protection laws may differ. Our primary operations are in the USA and Nigeria, and we will take all steps reasonably necessary to ensure that your data is treated securely.</p>

                <h3>7. Children's Privacy</h3>
                <p>Our Services are not intended for use by children under the age of 13. We do not knowingly collect personally identifiable information from children under 13.</p>

                <h3>8. Changes to This Privacy Policy</h3>
                <p>We may update our Privacy Policy from time to time. We will notify you of any changes by posting the new Privacy Policy on this page.</p>

                <h3>9. Contact Us</h3>
                <p>If you have any questions about this Privacy Policy, you can contact us:</p>
                <ul>
                    <li><strong>Address:</strong> 4351, Whiteplains road, Bronx, NY, 10466, USA</li>
                    <li><strong>Email:</strong> Laiakabash@hotmail.com, princelillwitty@gmail.com</li>
                    <li><strong>Phone:</strong> +1 914-310-9962, +2347065768073</li>
                </ul>
            </div>
        </section>
        """
    return HTMLResponse(get_base_html("Privacy Policy", content, request, "/privacy"))


@app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    content = """
     <section class="section">
         <div class="container">
             <h2 class="section-title">Terms of Service</h2>
             <p><strong>Last Updated:</strong> [Insert Date]</p>
             <p>Welcome to Slogan Technologies LLC! These Terms of Service ("Terms") govern your use of our website, applications, and services (collectively, the "Services") provided by Slogan Technologies LLC ("Slogan Technologies," "we," "us," or "our").</p>
             <p>By accessing or using our Services, you agree to be bound by these Terms. If you disagree with any part of the terms, then you may not access the Services.</p>

             <h3>1. Description of Services</h3>
             <p>Slogan Technologies provides a wide range of technology solutions, including but not limited to: Custom Software Development, Artificial Intelligence (AI) and Machine Learning (ML) Solutions, Game Development for entertainment and education, Robotics Development, Web Development, Cybersecurity consulting, and Technology Education programs.</p>

             <h3>2. User Accounts</h3>
             <p>To access certain features of our Services, you may be required to create an account. You are responsible for safeguarding your account password and for any activities or actions under your account. You agree to provide accurate, current, and complete information during the registration process and to update such information to keep it accurate.</p>

             <h3>3. Intellectual Property Rights</h3>
             <p>The Services and all of their original content, including but not limited to software, code, AI models, game assets, educational materials, text, graphics, and logos (the "Content"), are the exclusive property of Slogan Technologies LLC and its licensors. Our trademarks may not be used in connection with any product or service without our prior written consent. You are granted a limited, non-exclusive, non-transferable license to access and use the Services for your personal or internal business purposes, subject to these Terms.</p>

             <h3>4. Payments, Subscriptions, and Refunds</h3>
             <ul>
                 <li><strong>Freemium and Paid Services:</strong> Some of our Services are offered on a freemium basis, while others require payment, either as a one-time purchase or a recurring subscription.</li>
                 <li><strong>Billing:</strong> By providing a payment method, you expressly authorize us or our third-party payment processor (e.g., Stripe) to charge you for the Services. For subscriptions, you will be billed in advance on a recurring, periodic basis.</li>
                 <li><strong>Cancellations:</strong> You may cancel your subscription at any time. The cancellation will take effect at the end of the current billing cycle.</li>
                 <li><strong>Refunds:</strong> Payments are generally non-refundable except where required by law or at our sole discretion.</li>
             </ul>

             <h3>5. Prohibited Activities</h3>
             <p>You agree not to use the Services to:</p>
             <ul>
                 <li>Violate any applicable national or international law or regulation.</li>
                 <li>Reverse engineer, decompile, disassemble, or otherwise attempt to discover the source code of our software, games, or AI models.</li>
                 <li>Use automated systems (bots, scrapers) to access the Services in a manner that sends more request messages to our servers than a human can reasonably produce in the same period.</li>
                 <li>Infringe upon or violate our intellectual property rights or the intellectual property rights of others.</li>
                 <li>Engage in any fraudulent activity, including impersonating any person or entity.</li>
             </ul>

             <h3>6. Termination</h3>
             <p>We may terminate or suspend your account and bar access to the Services immediately, without prior notice or liability, for any reason whatsoever, including without limitation if you breach the Terms.</p>

             <h3>7. Limitation of Liability</h3>
             <p>To the fullest extent permitted by applicable law, in no event shall Slogan Technologies LLC, nor its directors, employees, partners, or agents, be liable for any indirect, incidental, special, consequential, or punitive damages, including without limitation, loss of profits, data, use, goodwill, or other intangible losses, resulting from your access to or use of or inability to access or use the Services.</p>

             <h3>8. Disclaimer of Warranties</h3>
             <p>Your use of the Service is at your sole risk. The Service is provided on an "AS IS" and "AS AVAILABLE" basis. The Service is provided without warranties of any kind, whether express or implied, including, but not limited to, implied warranties of merchantability, fitness for a particular purpose, non-infringement, or course of performance.</p>

             <h3>9. Governing Law</h3>
             <p>These Terms shall be governed and construed in accordance with the laws of the State of New York, United States, without regard to its conflict of law provisions. You agree to submit to the personal jurisdiction of the courts located in Bronx County, New York for the resolution of any disputes.</p>

             <h3>10. Changes to These Terms</h3>
             <p>We reserve the right, at our sole discretion, to modify or replace these Terms at any time. We will provide at least 30 days' notice prior to any new terms taking effect. By continuing to access or use our Services after those revisions become effective, you agree to be bound by the revised terms.</p>

             <h3>11. Contact Us</h3>
             <p>If you have any questions about these Terms, you can contact us:</p>
             <ul>
                 <li><strong>Address:</strong> 4351, Whiteplains road, Bronx, NY, 10466, USA</li>
                 <li><strong>Email:</strong> Laiakabash@hotmail.com, princelillwitty@gmail.com</li>
                 <li><strong>Phone:</strong> +1 914-310-9962, +2347065768073</li>
             </ul>
         </div>
     </section>
     """
    return HTMLResponse(get_base_html("Terms of Service", content, request, "/terms"))


@app.get("/careers", response_class=HTMLResponse)
async def careers_landing_page(request: Request):
    openings = [
        {"title": "Software Engineering Intern", "desc": "Build robust, scalable software that solves real-world problems and powers industries across Africa.", "link": "/careers/intern-software-engineer"},
        {"title": "AI & Game Engineering Intern", "desc": "Merge the magic of game development with the power of AI to craft intelligent worlds and immersive simulations.", "link": "/careers/intern-ai-game-engineer"},
        {"title": "Cybersecurity Intern", "desc": "Become a guardian of our digital frontier, defending our innovative products and sensitive data from modern threats.", "link": "/careers/intern-cybersecurity"}
    ]
    openings_html = "".join([f"""<div class="card"><a href="{o['link']}" class="stretched-link"><h3>{o['title']}</h3><p>{o['desc']}</p></a><style>.stretched-link::after {{ position: absolute; top: 0; right: 0; bottom: 0; left: 0; z-index: 1; content: ""; }}</style></div>""" for o in openings])
    content = f"""<section class="section"><div class="container"><h2 class="section-title">Join Our Mission</h2><p class="text-center mb-3" style="font-size: 1.2rem; max-width: 800px; margin: auto;">We are looking for passionate innovators, builders, and dreamers to help us forge the future of technology in Africa. If you are driven by complex challenges and want to make a tangible impact, explore our open roles below.</p><div class="card-grid" style="margin-top: 3rem;">{openings_html}</div></div></section>"""
    return HTMLResponse(get_base_html("Careers", content, request, "/careers"))

@app.get("/careers/intern-software-engineer", response_class=HTMLResponse)
async def career_swe_intern(request: Request):
    content = """<div class="container"><h2 class="section-title">Software Engineering Intern</h2><p>Are you passionate about building robust, scalable software that solves real-world problems? Do you want to do more than just write code—do you want to build the digital backbone for transforming industries across Africa? Slogan Technologies is looking for a brilliant Software Engineering Intern to join our mission.</p><h3 class="sub-title">Your Mission, Should You Choose to Accept It:</h3><ul><li>Collaborate on designing, developing, and deploying full-stack web and mobile applications.</li><li>Write clean, efficient, and well-documented code that powers our custom enterprise solutions.</li><li>Participate in our agile development process, including sprint planning, code reviews, and retrospectives.</li><li>Help build and maintain our CI/CD pipelines for automated testing and deployment.</li><li>Work on integrating our software with AI, robotics, and gaming platforms.</li></ul><h3 class="sub-title">What We're Looking For:</h3><ul><li>A deep passion for software development and a hunger to learn new technologies.</li><li>Solid understanding of data structures, algorithms, and software design principles.</li><li>Experience with programming languages like Python, JavaScript, Java, or similar.</li><li>Familiarity with web frameworks (e.g., FastAPI, Django, React, Vue) and databases.</li><li>A collaborative spirit and excellent communication skills.</li><li>Currently pursuing a degree in Computer Science, Engineering, or a related field.</li></ul><div class="call-to-action"><a href="/contact?subject=Application for Software Engineer Intern" class="btn">Apply to Build the Future</a></div></div>"""
    return HTMLResponse(get_base_html("Software Engineering Intern", content, request, "/careers/intern-software-engineer"))

@app.get("/careers/intern-ai-game-engineer", response_class=HTMLResponse)
async def career_ai_game_intern(request: Request):
    content = """<div class="container"><h2 class="section-title">AI & Game Engineering Intern</h2><p>Imagine creating game characters with minds of their own. Picture building immersive VR simulations that train doctors or robots that revolutionize farming. At Slogan Technologies, we merge the creative magic of game development with the analytical power of AI. We're seeking a visionary AI & Game Engineer Intern to join us on this exciting frontier.</p><h3 class="sub-title">Your Quest Awaits:</h3><ul><li>Develop and implement AI algorithms for non-player characters (NPCs), game mechanics, and procedural content generation.</li><li>Work with advanced game engines like Unity or Unreal Engine to build immersive games and simulations.</li><li>Design and program intelligent robotic systems, integrating machine learning and computer vision.</li><li>Contribute to creating interactive storytelling and VR/AR experiences.</li><li>Research and experiment with new AI techniques to push the boundaries of our products.</li></ul><h3 class="sub-title">Who We're Looking For:</h3><ul><li>A creative mind with a strong technical foundation and a love for games, AI, or robotics.</li><li>Proficiency in C++, C#, or Python.</li><li>Experience with a major game engine (Unity or Unreal) is a huge plus.</li><li>A solid grasp of linear algebra, physics, and AI/ML fundamentals.</li><li>A natural problem-solver who is excited by complex challenges.</li><li>Currently pursuing a degree in Computer Science, Game Design, Engineering, or a related field.</li></ul><div class="call-to-action"><a href="/contact?subject=Application for AI & Game Engineer Intern" class="btn">Start Your Quest</a></div></div>"""
    return HTMLResponse(get_base_html("AI & Game Engineer Intern", content, request, "/careers/intern-ai-game-engineer"))

@app.get("/careers/intern-cybersecurity", response_class=HTMLResponse)
async def career_cyber_intern(request: Request):
    content = """<div class="container"><h2 class="section-title">Cybersecurity Intern</h2><p>In a world driven by data and innovation, trust is our most valuable asset. At Slogan Technologies, we are building revolutionary products, and we need a vigilant protector to defend them. We are searching for a sharp and proactive Cybersecurity Intern to join our ranks and help secure our digital ecosystem.</p><h3 class="sub-title">Your Watchful Mission:</h3><ul><li>Assist in conducting security audits and vulnerability assessments on our applications and infrastructure.</li><li>Help implement and manage security measures like firewalls, intrusion detection systems, and data encryption.</li><li>Monitor our networks and systems for security threats and participate in incident response activities.</li><li>Contribute to the development of our disaster recovery and data backup strategies.</li><li>Research emerging cyber threats and help educate our team on security best practices.</li></ul><h3 class="sub-title">What We're Looking For:</h3><ul><li>An insatiable curiosity for how systems can be broken and a passion for how to fortify them.</li><li>A strong understanding of networking fundamentals (TCP/IP), operating systems, and core security principles.</li><li>Familiarity with common security vulnerabilities (e.g., OWASP Top 10).</li><li>Scripting skills in Python, Bash, or PowerShell are a plus.</li><li>An analytical mindset with meticulous attention to detail.</li><li>Currently pursuing a degree in Cybersecurity, Information Technology, Computer Science, or a related field.</li></ul><div class="call-to-action"><a href="/contact?subject=Application for Cybersecurity Intern" class="btn">Enlist to Defend Innovation</a></div></div>"""
    return HTMLResponse(get_base_html("Cybersecurity Intern", content, request, "/careers/intern-cybersecurity"))



@app.get("/courses", response_class=HTMLResponse)
async def courses_page(request: Request):
    with get_db_connection() as conn:
        courses = conn.execute("SELECT * FROM products WHERE category = 'course' ORDER BY required_plan").fetchall()
    courses_html = "".join([f"""
    <div class="card">
        <div class="card-image-placeholder"><img src="{c['image_url']}" alt="{c['name']}"></div>
        <h3>{c['name']}</h3><p>{c['description']}</p>
        <div class="mt-3" style="display: flex; justify-content: space-between; align-items: center;">
            <span style="font-weight: bold; text-transform: capitalize; color: var(--accent-color-secondary);">Requires: {c['required_plan']} Plan</span>
            <a href="/courses/{c['id']}" class="btn">View Course</a>
        </div>
    </div>
    """ for c in courses])
    content = f"""
    <section class="section"><div class="container">
        <h2 class="section-title">Our Courses</h2>
        <p class="text-center mb-3">From fundamentals to masterclasses, expand your skills in AI, Game Dev, and Robotics.</p>
        <div class="card-grid">{courses_html}</div>
    </div></section>
    """
    return HTMLResponse(get_base_html("Courses", content, request, "/courses"))


@app.get("/courses/{course_id}", response_class=HTMLResponse)
async def course_detail_page(request: Request, course_id: int):
    user = request.state.user
    with get_db_connection() as conn:
        course = conn.execute("SELECT * FROM products WHERE id = ? AND category = 'course'", (course_id,)).fetchone()
    if not course: raise HTTPException(status_code=404, detail="Course not found")
    course_details = json.loads(course['details'] or '{}')
    has_access = user_has_access(user.get('subscription_plan', 'none') if user else 'none', course['required_plan'])

    content_html = ""
    if has_access:
        content_html = f"""
        <div class="video-container" style="position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; max-width: 100%; background: #000; border-radius: 8px; margin-bottom: 20px;">
            <iframe src="{course_details.get('video_url', '')}" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;"></iframe>
        </div>
        <div class="course-text-content">
            <h3 style="color: var(--accent-color-secondary);">Course Materials</h3><p>{course_details.get('content', 'No materials for this course.')}</p>
        </div>
        """
    else:
        content_html = f"""
        <div class="card text-center" style="border-color: var(--accent-color-secondary);">
            <h3>Access Denied</h3>
            <p>This course requires a <strong style="text-transform: capitalize;">{course['required_plan']}</strong> subscription or higher.</p>
            <p>Your current plan: <strong style="text-transform: capitalize;">{user.get('subscription_plan', 'none') if user else 'None'}</strong>.</p>
            <a href="/subscriptions" class="btn btn-secondary mt-3">Upgrade Your Plan</a>
        </div>
        """
    content = f"""
    <section class="section"><div class="container" style="max-width: 1000px;">
        <h2 class="section-title">{course['name']}</h2>
        {content_html}
    </div></section>
    """
    return HTMLResponse(get_base_html(course['name'], content, request, f"/courses/{course_id}"))


@app.get("/blog", response_class=HTMLResponse)
async def blog_list_page(request: Request):
    with get_db_connection() as conn:
        posts = conn.execute(
            "SELECT p.*, u.full_name as author_name FROM blog_posts p LEFT JOIN users u ON p.author_id = u.id ORDER BY p.published_at DESC").fetchall()
    posts_html = "".join([f"""
    <div class="card">
        <a href="/blog/{p['slug']}" style="display:block; margin-bottom: 1rem;"><div class="card-image-placeholder"><img src="{p['image_url']}" alt="{p['title']}"></div></a>
        <h3><a href="/blog/{p['slug']}">{p['title']}</a></h3>
        <p><em>By {p['author_name'] or 'SloganTech'} on {datetime.datetime.fromisoformat(p['published_at']).strftime('%B %d, %Y')}</em></p>
        <p>{p['content'][:150]}...</p>
        <a href="/blog/{p['slug']}" class="btn mt-3">Read More</a>
    </div>
    """ for p in posts])
    content = f"""
    <section class="section"><div class="container">
        <h2 class="section-title">IntelliWeb Engine Blog</h2>
        <div class="card-grid">{posts_html if posts else '<p class="text-center">No posts yet. Check back soon!</p>'}</div>
    </div></section>
    """
    return HTMLResponse(get_base_html("Blog", content, request, "/blog"))


@app.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_detail_page(request: Request, slug: str):
    with get_db_connection() as conn:
        post = conn.execute(
            "SELECT p.*, u.full_name as author_name FROM blog_posts p LEFT JOIN users u ON p.author_id = u.id WHERE p.slug = ?",
            (slug,)).fetchone()
    if not post: raise HTTPException(status_code=404, detail="Post not found")
    content = f"""
    <section class="section"><div class="container" style="max-width: 900px;">
        <h1 class="text-center" style="font-size: 3rem;">{post['title']}</h1>
        <p class="text-center mb-3"><em>By {post['author_name'] or 'SloganTech'} on {datetime.datetime.fromisoformat(post['published_at']).strftime('%B %d, %Y')}</em></p>
        <img src="{post['image_url']}" alt="{post['title']}" style="width: 100%; border-radius: 8px; margin-bottom: 2rem;">
        <div class="blog-content" style="font-size: 1.1rem; line-height: 1.8;">{post['content'].replace(chr(10), "<br><br>")}</div>
        <p class="mt-3"><strong>Tags:</strong> {post['tags']}</p>
    </div></section>
    """
    return HTMLResponse(get_base_html(post['title'], content, request, f"/blog/{slug}"))


@app.get("/contact", response_class=HTMLResponse)
async def contact_page(request: Request):
    content = """
    <section class="section"><div class="container" style="max-width: 800px;">
        <h2 class="section-title">Get In Touch</h2>
         <form id="contactForm">
            <label for="name">Name</label><input type="text" id="name" name="name" required>
            <label for="email">Email</label><input type="email" id="email" name="email" required>
            <label for="subject">Subject</label><input type="text" id="subject" name="subject" required>
            <label for="message">Message</label><textarea id="message" name="message" rows="6" required></textarea>
            <button type="submit" class="btn" style="width:100%;">Send Message</button>
        </form>
    </div></section>
    <script>
        document.getElementById('contactForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target).entries());
            showToast('Sending message...', 'info');
            try {
                const response = await fetch('/api/contact', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
                });
                const result = await response.json();
                if (response.ok) {
                    showToast(result.message, 'success');
                    e.target.reset();
                } else { showToast(result.detail || 'Failed to send.', 'error'); }
            } catch (error) { showToast('Network error.', 'error'); }
        });
    </script>
    """
    return HTMLResponse(get_base_html("Contact", content, request, "/contact"))


# --- ======================== ---
# --- 10. ADMIN PANEL ENDPOINTS ---
# --- ======================== ---

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, current_user: dict = Depends(get_current_active_user)):
    if current_user.get("role") == "admin": return RedirectResponse(url="/admin")
    profile_pic_url = current_user.get('profile_picture_url') or '/static_placeholder/img/avatar_default.svg'
    content = f"""<section class="section"><div class="container"><div class="text-center"><img src="{profile_pic_url}" alt="Profile Picture" class="profile-picture"><h2 class="section-title" style="margin-bottom: 2rem;">Welcome, {current_user['full_name']}</h2></div><div class="card-grid" style="grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));"><div class="card text-center"><h3>Account Details</h3><p><strong>Subscription:</strong> <span style="text-transform: capitalize;">{current_user['subscription_plan']}</span></p><p><strong>Status:</strong> <span style="text-transform: capitalize;">{current_user['subscription_status'] or 'N/A'}</span></p><a href="/subscriptions" class="btn mt-3">Manage Plan</a></div><div class="card text-center"><h3>Profile Settings</h3><p>Update your name, email, and app preferences.</p><a href="/settings" class="btn btn-secondary mt-3">Go to Settings</a></div></div></div></section>"""
    return HTMLResponse(get_base_html("Dashboard", content, request, "/dashboard"))


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, current_user: dict = Depends(get_current_active_user)):
    profile_pic_url = current_user.get('profile_picture_url')
    content = f"""<section class="section"><div class="container" style="max-width: 900px;"><h2 class="section-title">User Settings</h2><div class="card mb-3"><h3>Profile Information</h3><form id="profileUpdateForm" enctype="multipart/form-data"><div class="text-center"><img src="{profile_pic_url or '/static_placeholder/img/avatar_default.svg'}" alt="Profile Picture" class="profile-picture"></div><label for="full_name">Full Name</label><input type="text" id="full_name" name="full_name" value="{current_user['full_name']}" required><label for="email">Email Address</label><input type="email" id="email" name="email" value="{current_user['email']}" required><label for="profile_picture_file">Upload New Profile Picture (Optional)</label><input type="file" id="profile_picture_file" name="profile_picture_file" accept="image/png, image/jpeg, image/gif"><button type="submit" class="btn mt-3">Update Profile</button></form></div><div class="card"><h3>Appearance & Preferences</h3><form><label for="theme-select">Color Theme</label><select id="theme-select"><option value="theme-cyan">Cyber Cyan</option><option value="theme-orange">Fusion Orange</option><option value="theme-purple">Galactic Purple</option></select><label for="language-select" class="mt-3">Language</label><select id="language-select"><option value="en-US">English (US)</option><option disabled>More Soon</option></select></form></div></div></section>"""
    js = """const themeSelect = document.getElementById('theme-select');
        themeSelect.value = localStorage.getItem('sloganTechTheme') || 'theme-cyan';
        themeSelect.addEventListener('change', (e) => applyTheme(e.target.value));
        document.getElementById('profileUpdateForm').addEventListener('submit', async function(e) { e.preventDefault();
            const formData = new FormData(e.target);
            showToast('Updating profile...', 'info');
            try {
                const r = await fetch('/api/user/update', { method: 'POST', body: formData });
                const res = await r.json();
                if (r.ok) { showToast(res.message, 'success'); setTimeout(() => window.location.reload(), 1500); }
                else { showToast(res.detail || 'Update failed.', 'error'); }
            } catch (err) { showToast('Network error.', 'error'); }
        });"""
    return HTMLResponse(get_base_html("Settings", content, request, "/settings", extra_js=js))


@app.get("/admin/blog", response_class=HTMLResponse)
async def admin_blog_list(request: Request, user: dict = Depends(is_admin)):
    with get_db_connection() as conn:
        posts = conn.execute("SELECT * FROM blog_posts ORDER BY published_at DESC").fetchall()
    rows = "".join([f"""
    <tr>
        <td>{p['id']}</td><td><a href="/blog/{p['slug']}" target="_blank">{p['title']}</a></td><td>{datetime.datetime.fromisoformat(p['published_at']).strftime('%Y-%m-%d')}</td>
        <td style="display:flex; gap: 10px;">
            <a href="/admin/blog/edit/{p['id']}" class="btn">Edit</a>
            <form action="/admin/blog/delete/{p['id']}" method="post" onsubmit="return confirm('Are you sure you want to delete this post?');">
                <button type="submit" class="btn btn-secondary">Delete</button>
            </form>
        </td>
    </tr>
    """ for p in posts])
    content = f"""
    <section class="section"><div class="container">
        <div style="display:flex; justify-content: space-between; align-items: center; margin-bottom: 2rem;">
            <h2 class="section-title" style="margin-bottom:0; text-align: left;">Manage Blog Posts</h2>
            <a href="/admin/blog/new" class="btn">New Post</a>
        </div>
        <div class="card" style="padding: 0;"><table class="table" style="width: 100%; border-collapse: collapse; color: white;">
            <thead><tr style="background: var(--bg-color-lighter);"><th>ID</th><th>Title</th><th>Published</th><th>Actions</th></tr></thead>
            <tbody>{rows}</tbody>
        </table></div>
        <style> .table th, .table td {{ padding: 15px; text-align: left; border-bottom: 1px solid var(--border-color); }} .table tbody tr:last-child td {{ border-bottom: none; }} </style>
    </div></section>
    """
    return HTMLResponse(get_base_html("Admin - Blog", content, request, "/admin/blog"))


@app.get("/admin/blog/new", response_class=HTMLResponse)
async def admin_blog_new_form(request: Request, user: dict = Depends(is_admin)):
    content = """
    <section class="section"><div class="container" style="max-width:900px;">
        <h2 class="section-title">Create New Post</h2>
        <form action="/admin/blog/new" method="post">
            <label for="title">Title</label><input type="text" name="title" required>
            <label for="image_url">Image URL</label><input type="text" name="image_url" placeholder="https://example.com/image.jpg">
            <label for="tags">Tags (comma-separated)</label><input type="text" name="tags" placeholder="AI, Tech, Gaming">
            <label for="content">Content (Markdown is not supported, use HTML or plain text)</label><textarea name="content" rows="15" required></textarea>
            <button type="submit" class="btn">Create Post</button>
        </form>
    </div></section>
    """
    return HTMLResponse(get_base_html("New Post", content, request, "/admin/blog/new"))


@app.post("/admin/blog/new")
async def admin_blog_create(request: Request, user: dict = Depends(is_admin), title: str = Form(),
                            content: str = Form(), image_url: str = Form(None), tags: str = Form(None)):
    new_slug = slugify(title)
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO blog_posts (title, slug, content, author_id, image_url, tags) VALUES (?, ?, ?, ?, ?, ?)",
            (title, new_slug, content, user['id'], image_url, tags))
        conn.commit()
    return RedirectResponse(url="/admin/blog", status_code=303)


@app.get("/admin/blog/edit/{post_id}", response_class=HTMLResponse)
async def admin_blog_edit_form(request: Request, post_id: int, user: dict = Depends(is_admin)):
    with get_db_connection() as conn:
        post = conn.execute("SELECT * FROM blog_posts WHERE id = ?", (post_id,)).fetchone()
    if not post: raise HTTPException(404)
    content = f"""
    <section class="section"><div class="container" style="max-width:900px;">
        <h2 class="section-title">Edit Post</h2>
        <form action="/admin/blog/edit/{post_id}" method="post">
            <label for="title">Title</label><input type="text" name="title" value="{post['title']}" required>
            <label for="image_url">Image URL</label><input type="text" name="image_url" value="{post['image_url'] or ''}">
            <label for="tags">Tags (comma-separated)</label><input type="text" name="tags" value="{post['tags'] or ''}">
            <label for="content">Content</label><textarea name="content" rows="15" required>{post['content']}</textarea>
            <button type="submit" class="btn">Save Changes</button>
        </form>
    </div></section>
    """
    return HTMLResponse(get_base_html("Edit Post", content, request, f"/admin/blog/edit/{post_id}"))


@app.post("/admin/blog/edit/{post_id}")
async def admin_blog_update(post_id: int, user: dict = Depends(is_admin), title: str = Form(), content: str = Form(),
                            image_url: str = Form(None), tags: str = Form(None)):
    new_slug = slugify(title)
    with get_db_connection() as conn:
        conn.execute("UPDATE blog_posts SET title=?, slug=?, content=?, image_url=?, tags=? WHERE id=?",
                     (title, new_slug, content, image_url, tags, post_id))
        conn.commit()
    return RedirectResponse(url="/admin/blog", status_code=303)


@app.post("/admin/blog/delete/{post_id}")
async def admin_blog_delete(post_id: int, user: dict = Depends(is_admin)):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM blog_posts WHERE id=?", (post_id,))
        conn.commit()
    return RedirectResponse(url="/admin/blog", status_code=303)


# --- ================== ---
# --- 11. API ENDPOINTS ---
# --- ================== ---

@app.post("/api/user/update")
async def update_user_profile(current_user: dict = Depends(get_current_active_user),
                              full_name: str = Form(...),
                              email: EmailStr = Form(...),
                              profile_picture_file: UploadFile = File(None)):
    new_profile_pic_url = current_user.get('profile_picture_url')

    if profile_picture_file and profile_picture_file.filename:
        if not firebase_service or not firebase_service.initialized:
            raise HTTPException(status_code=503, detail="File upload service is not configured.")

        file_contents = await profile_picture_file.read()
        content_type = profile_picture_file.content_type
        timestamp = int(time.time())
        destination_blob_name = f"profile_pictures/user_{current_user['id']}/{timestamp}_{profile_picture_file.filename}"

        uploaded_url = firebase_service.upload_file_from_bytes(file_contents, destination_blob_name, content_type)

        if uploaded_url:
            new_profile_pic_url = uploaded_url
        else:
            raise HTTPException(status_code=500, detail="Failed to upload profile picture to cloud storage.")

    with get_db_connection() as conn:
        if email != current_user['email']:
            if conn.execute("SELECT id FROM users WHERE email = ? AND id != ?", (email, current_user['id'])).fetchone():
                raise HTTPException(status_code=400, detail="Email already in use by another account.")
        conn.execute("UPDATE users SET full_name = ?, email = ?, profile_picture_url = ? WHERE id = ?",
                     (full_name, email, new_profile_pic_url, current_user['id']))
        conn.commit()
    return {"message": "Profile updated successfully!"}

@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def register_user_api(user: UserCreate):
    with get_db_connection() as conn:
        if conn.execute("SELECT id FROM users WHERE username = ? OR email = ?", (user.username, user.email)).fetchone():
            raise HTTPException(status_code=400, detail="Username or email already registered")
        hashed_password = get_password_hash(user.password)
        conn.execute("INSERT INTO users (username, email, hashed_password, full_name) VALUES (?, ?, ?, ?)",
                     (user.username, user.email, hashed_password, user.full_name))
        conn.commit()
    return {"message": "User created successfully"}


@app.post("/auth/token", response_model=Token)
async def login_for_access_token_api(response: Response, form_data: OAuth2PasswordRequestForm = Depends()):
    with get_db_connection() as conn:
        user = get_user(conn, form_data.username)
        if not user or not verify_password(form_data.password, user['hashed_password']):
            raise HTTPException(status_code=401, detail="Invalid username or password")
    delta = datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(data={"sub": user['username']}, expires_delta=delta)
    response.set_cookie(key="access_token", value=f"Bearer {token}", httponly=True, max_age=int(delta.total_seconds()),
                        samesite="Lax")
    return {"access_token": token, "token_type": "bearer"}


@app.get("/auth/logout")
async def logout_and_redirect_api():
    response = RedirectResponse(url="/")
    response.delete_cookie("access_token")
    return response


@app.get("/api/products/all", response_model=List[dict])
async def get_all_products_api():
    with get_db_connection() as conn:
        products = conn.execute(
            "SELECT id, name, category, description, price, stripe_price_id, image_url FROM products").fetchall()
    return [dict(p) for p in products]


@app.get("/api/payments/stripe-key")
async def get_stripe_key_api(): return {"publishableKey": STRIPE_PUBLISHABLE_KEY}


@app.post("/api/payments/create-checkout-session")
async def create_checkout_session_api(request: Request, current_user: dict = Depends(get_current_active_user)):
    try:
        line_items = None
        # Determine if the request is JSON or a form
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            json_data = await request.json()
            line_items = json_data.get('line_items')
        elif "application/x-www-form-urlencoded" in content_type:
            form_data = await request.form()
            price_id = form_data.get("price_id")
            if price_id:
                line_items = [{'price': price_id, 'quantity': 1}]

        if not line_items:
            raise HTTPException(status_code=400, detail="No items to purchase.")

        first_price_info = stripe.Price.retrieve(line_items[0]['price'])
        mode = "subscription" if first_price_info.recurring else "payment"

        stripe_customer_id = current_user.get('stripe_customer_id')
        if not stripe_customer_id:
            customer = stripe.Customer.create(email=current_user['email'], name=current_user.get('full_name'))
            stripe_customer_id = customer.id
            with get_db_connection() as conn:
                conn.execute("UPDATE users SET stripe_customer_id = ? WHERE id = ?",
                             (stripe_customer_id, current_user['id']))
                conn.commit()

        session = stripe.checkout.Session.create(
            customer=stripe_customer_id,
            payment_method_types=['card'],
            line_items=line_items,
            mode=mode,
            success_url=f"{request.base_url}payment/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{request.base_url}payment/cancel",
            metadata={'user_id': current_user['id']}
        )

        # This part of the logic was already correct
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({'id': session.id})
        else:
            return RedirectResponse(session.url, status_code=303)

    except Exception as e:
        print(f"Stripe Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/payments/stripe-webhook")
async def stripe_webhook_api(request: Request):
    payload, sig_header = await request.body(), request.headers.get('stripe-signature')
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        raise HTTPException(400, str(e))

    if event['type'] == 'checkout.session.completed':
        handle_checkout_session_completed(event['data']['object'])
    elif event['type'] == 'invoice.payment_succeeded':
        handle_invoice_paid(event['data']['object'])
    return JSONResponse(content={'status': 'success'})


def handle_checkout_session_completed(session):
    user_id = session.get('metadata', {}).get('user_id')
    if not user_id:
        print("Webhook Error: user_id not in session metadata")
        return

    if session.mode == 'subscription':
        # All variables related to subscription are now safely inside this block
        stripe_subscription_id = session.subscription
        subscription_data = stripe.Subscription.retrieve(stripe_subscription_id)
        price_id = subscription_data.items.data[0].price.id

        plan_map = {
            STRIPE_PRICE_ID_BASIC: 'basic',
            STRIPE_PRICE_ID_PREMIUM: 'premium',
            STRIPE_PRICE_ID_ULTIMATE: 'ultimate'
        }
        plan_name = plan_map.get(price_id, 'unknown')

        with get_db_connection() as conn:
            conn.execute(
                "UPDATE users SET subscription_plan = ?, subscription_status = 'active', subscription_id = ? WHERE id = ?",
                (plan_name, stripe_subscription_id, user_id)
            )
            conn.commit()
        print(f"User {user_id} subscribed to {plan_name} plan.")

    elif session.mode == 'payment':
        with get_db_connection() as conn:
            conn.execute("UPDATE orders SET status = 'completed' WHERE stripe_session_id = ?", (session.id,))
            conn.commit()
        print(f"One-time payment order for session {session.id} completed.")


def handle_invoice_paid(invoice):
    if sub_id := invoice.subscription:
        with get_db_connection() as conn:
            conn.execute("UPDATE users SET subscription_status = 'active' WHERE subscription_id = ?",
                         (sub_id,)).commit()


@app.post("/api/contact")
async def handle_contact_form_api(form_data: ContactFormModel):
    try:
        with get_db_connection() as conn:
            conn.execute("INSERT INTO contact_messages (name, email, subject, message) VALUES (?, ?, ?, ?)",
                         (form_data.name, form_data.email, form_data.subject, form_data.message)).commit()
        return {"message": "Message sent successfully! We will get back to you soon."}
    except Exception as e:
        raise HTTPException(500, f"Database error: {e}")


# --- ================= ---
# --- 12. APP LIFECYCLE ---
# --- ================= ---
@app.on_event("startup")
async def startup_event():
    print("--- SloganTech IntelliWeb Engine v2.3 Starting Up ---")
    global firebase_service
    init_db()
    firebase_service = FirebaseService(FIREBASE_CREDS_PATH)


if __name__ == "__main__":
    print("Starting server... Access at http://localhost:8000")
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
