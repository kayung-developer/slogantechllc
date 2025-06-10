# Slogan Technologies - IntelliWeb Engine v2.3

![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)
![Framework](https://img.shields.io/badge/framework-FastAPI-05998b.svg)
![Database](https://img.shields.io/badge/database-SQLite-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

The IntelliWeb Engine is a powerful, feature-rich, single-file web application built with FastAPI. It serves as the complete backend and frontend server for the Slogan Technologies LLC website, showcasing a variety of modern web development practices within a monolithic file structure.

This project demonstrates a full-stack application including user authentication, e-commerce via Stripe, subscription management, a blog, dynamic frontend rendering, and cloud file storage integration with Firebase.

## ✨ Key Features

*   **User Authentication**: Secure user registration and login system using JWT (JSON Web Tokens) and password hashing.
*   **Role-Based Access Control**: Differentiated access for regular users and administrators.
*   **E-Commerce & Subscriptions**:
    *   **Stripe Integration**: Secure payment processing for both one-time purchases and recurring subscriptions.
    *   **Tiered Subscription Plans**: Multi-level subscription model (`basic`, `premium`, `ultimate`) with access control for protected content (e.g., courses).
    *   **Shopping Cart**: A client-side shopping cart for physical/digital products.
*   **User Dashboard & Settings**:
    *   Personalized user dashboard.
    *   Profile update functionality (full name, email).
    *   Profile picture uploads to **Firebase Cloud Storage**.
*   **Dynamic Theming**: Live theme switching (Cyan, Orange, Purple) with user preferences saved to `localStorage`.
*   **Content Management**:
    *   A complete blog system with an admin panel for creating, editing, and deleting posts.
    *   Dynamic pages for Services, About, Careers, and more.
*   **Admin Panel**: A secure area for administrators to manage site content, such as blog posts.
*   **Single-File Architecture**: The entire application logic, including HTML templates and CSS/JS assets, is contained within a single `main.py` file.

## 🚀 Tech Stack

*   **Backend**: [FastAPI](https://fastapi.tiangolo.com/)
*   **Server**: [Uvicorn](https://www.uvicorn.org/)
*   **Database**: [SQLite](https://www.sqlite.org/index.html) (for simplicity and portability)
*   **Authentication**: [python-jose](https://github.com/mpdavis/python-jose) for JWT, [passlib](https://passlib.readthedocs.io/en/stable/) with `bcrypt` for hashing.
*   **Payments**: [Stripe API](https://stripe.com/docs/api)
*   **File Storage**: [Firebase Admin SDK](https://firebase.google.com/docs/admin/setup) (for Cloud Storage)
*   **Frontend**: Server-side rendered HTML, with vanilla CSS and JavaScript embedded directly in the Python code.

## 📋 Getting Started

Follow these instructions to get a local copy up and running.

### Prerequisites

*   Python 3.8 or newer
*   A Firebase project with Cloud Storage enabled
*   A Stripe account with API keys

### Installation

1.  **Clone the repository:**
    ```sh
    git clone <your-repository-url>
    cd <repository-directory>
    ```

2.  **Create and activate a virtual environment:**
    ```sh
    # For Windows
    python -m venv venv
    .\venv\Scripts\activate

    # For macOS/Linux
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install the required dependencies:**
    ```sh
    pip install "fastapi[all]" uvicorn passlib bcrypt python-jose stripe firebase-admin python-multipart
    ```
    Alternatively, create a `requirements.txt` file with the content below and run `pip install -r requirements.txt`.

    ```txt
    # requirements.txt
    fastapi
    uvicorn[standard]
    pydantic
    passlib[bcrypt]
    python-jose[cryptography]
    stripe
    firebase-admin
    python-multipart
    ```

### Configuration

1.  **Firebase Credentials:**
    *   Go to your Firebase project settings.
    *   Navigate to "Service accounts" and generate a new private key.
    *   This will download a JSON file. Rename it to `firebase-credentials.json` and place it in the root directory of the project.

2.  **Environment Variables:**
    *   Create a file named `.env` in the root directory.
    *   Copy the contents of `.env.example` below into your `.env` file and fill in your actual credentials.

    **`.env.example`**:
    ```ini
    # A strong, randomly generated secret key for JWT encoding
    # You can generate one with: openssl rand -hex 32
    SECRET_KEY="09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"

    # --- Stripe Configuration ---
    # Get these from your Stripe Dashboard (Developers -> API keys)
    STRIPE_SECRET_KEY="sk_test_..."
    STRIPE_PUBLISHABLE_KEY="pk_test_..."

    # Create webhook in Stripe Dashboard (Developers -> Webhooks)
    # The endpoint URL will be http://localhost:8000/api/payments/stripe-webhook
    STRIPE_WEBHOOK_SECRET="whsec_..."

    # Create products and prices in your Stripe Dashboard and paste the Price IDs here
    STRIPE_PRICE_ID_BASIC="price_..."
    STRIPE_PRICE_ID_PREMIUM="price_..."
    STRIPE_PRICE_ID_ULTIMATE="price_..."
    ```

### Running the Application

1.  **Start the server:**
    ```sh
    uvicorn main:app --reload
    ```

2.  **Access the application:**
    Open your web browser and navigate to `http://localhost:8000`.

3.  **Database Initialization:**
    The application will automatically create a `slogan_tech.db` file and seed it with initial data (admin user, products, blog posts) on the first run.

    *   **Default Admin Login:**
        *   **Username:** `admin`
        *   **Password:** `admin1234`

## 🏗️ Project Structure

Even though this is a single-file application, it is logically organized into distinct sections for maintainability.

*   **1. Configuration and Constants**: Defines all application-wide constants, environment variable loading, and initial setup for libraries like Stripe and Passlib.
*   **2. Helper Functions**: Contains small, reusable utility functions like `slugify` and `user_has_access`.
*   **3. Firebase Integration**: A dedicated class `FirebaseService` to handle all interactions with Firebase, specifically for file uploads. It gracefully handles cases where credentials are not found.
*   **4. Database Setup & Utilities**: Manages the SQLite database connection, schema initialization (`init_db`), and data seeding (`seed_data`).
*   **5. Authentication & Security**: Contains all functions related to security, including password hashing/verification, JWT creation, and dependency functions (`get_current_user`, `is_admin`) for protecting endpoints.
*   **6. Pydantic Models**: Defines the data shapes for request bodies (e.g., `UserCreate`, `ContactFormModel`), ensuring data validation.
*   **7. Frontend Assets (Embedded)**: A unique section where global CSS and JavaScript are stored as multi-line strings. This keeps the project self-contained.
*   **8. FastAPI App & HTML Helpers**: Initializes the `FastAPI` app instance and contains the core HTML templating function (`get_base_html`) that constructs the page layout.
*   **9. Page Endpoints**: All the primary, user-facing routes (e.g., `/`, `/about`, `/login`, `/dashboard`). These endpoints render and return HTML pages.
*   **10. Admin Panel Endpoints**: Secure routes prefixed with `/admin` that are accessible only to admin users for content management.
*   **11. API Endpoints**: All other backend routes, typically prefixed with `/api` or `/auth`, that handle data operations, process forms, and interact with third-party services like Stripe. These endpoints return JSON data.
*   **12. App Lifecycle**: Manages application startup events, such as initializing the database and Firebase service.

## 📝 Recent Changes (v2.3)

*   **IMPLEMENTED**: New `/services` page with a detailed, icon-driven layout.
*   **IMPLEMENTED**: New `/settings` page on the user dashboard.
*   **FEATURE**: Live Theme Switching (Cyan, Orange, Purple) with settings saved to localStorage.
*   **FEATURE**: User profile update functionality (Full Name, Email) and profile picture uploads via Firebase.
*   **ENHANCED**: Completely revamped `/about` page with new Mission, Vision, and Core Values.
*   **ENHANCED**: Dashboard updated with a link to the new Settings page.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details.