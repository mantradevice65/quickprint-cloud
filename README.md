# QuickPrint SaaS - Cloud Multi-Tenant Platform 🖨️☁️
> **Commercial Multi-Tenant SaaS Backend for Automated Print Kiosks, Cyber Cafes & Xerox Shops**

[![Production Status](https://img.shields.io/badge/Production-Live%20Online-brightgreen.svg)](https://print.fruitsgenerator.co.in)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/Framework-Flask%203.x-lightgrey.svg)](https://flask.palletsprojects.com/)
[![Deployment](https://img.shields.io/badge/Host-Render.com-46E3B7.svg)](https://render.com)
[![License](https://img.shields.io/badge/License-Commercial%20SaaS-red.svg)](#)

---

## 📌 Executive Summary | सारांश

**QuickPrint SaaS** is a cloud-native, multi-tenant platform that enables a master administrator to sell automated print kiosk subscriptions to multiple print shops, xerox centers, and cyber cafes under an annual, monthly, or lifetime license model.

### 🌟 Core Capabilities
1. **Multi-Tenant Shop Isolation:** Every registered shop gets their own unique portal URL (e.g., `https://print.fruitsgenerator.co.in/s/sharma-xerox`), custom branding, independent rates (B&W/Color), and their own UPI/Razorpay payment gateway.
2. **Direct Bank Settlement (Zero Commission Hassle):** Customer payments flow 100% directly into each shopkeeper's bank account or Razorpay merchant account.
3. **Hardware Print Privacy:** Each shop's local PC client uses a cryptographically generated `Kiosk Setup Key` (`KP_KIOSK_...`) to fetch and print **only** orders placed for their specific store.
4. **Automated License Control:** 1-Click creation of 30-Day, 90-Day, 180-Day, 365-Day (1-Year), or Lifetime licenses. When a subscription lapses, customer uploads and kiosk sync are gracefully paused with clear expiry notices.
5. **Instant A4 Counter Poster Generator:** Auto-generates high-resolution, print-ready A4 posters for any store with custom branding, rate card, and unique QR code.
6. **Master Control Center (Super Admin):** Password-protected dashboard (`/super-admin`) providing real-time telemetry, license management, shop onboarding, and revenue metrics.

---

## 🏗️ Architecture & Data Flow

```
                      ┌──────────────────────────────────────────────┐
                      │             Customer Mobile Phone            │
                      │  (Scans Store Counter QR Code via Camera)    │
                      └──────────────────────┬───────────────────────┘
                                             │ HTTPS
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │     QUICKPRINT SAAS CLOUD SERVER             │
                      │       (print.fruitsgenerator.co.in)          │
                      │                                              │
                      │  ┌────────────────────────────────────────┐  │
                      │  │  Multi-Tenant Router & Subscriptions   │  │
                      │  │  /s/<shop_slug> & /super-admin         │  │
                      │  └───────────────────┬────────────────────┘  │
                      │                      │                       │
                      │  ┌───────────────────▼────────────────────┐  │
                      │  │  SQLite Database (jobs.db)             │  │
                      │  │  - shops (Credentials, Expiry, Keys)   │  │
                      │  │  - jobs  (shop_slug, PDF, Status)      │  │
                      │  └───────────────────┬────────────────────┘  │
                      └──────────────────────┼───────────────────────┘
                                             │ Polling with x-api-key (every 3s)
                      ┌──────────────────────▼───────────────────────┐
                      │              Shopkeeper's PC                 │
                      │                                              │
                      │  ┌────────────────────────────────────────┐  │
                      │  │ QuickPrint Desktop Client              │  │
                      │  │ - CloudSyncWorker Thread               │  │
                      │  │ - Zero-File Key Connector Tool         │  │
                      │  └───────────────────┬────────────────────┘  │
                      │                      │ Spool                 │
                      │                      ▼                       │
                      │  ┌────────────────────────────────────────┐  │
                      │  │ Physical Printer (Canon / HP / Epson)  │  │
                      │  │ 📄 Document prints automatically!      │  │
                      │  └────────────────────────────────────────┘  │
                      └──────────────────────────────────────────────┘
```

---

## 🔐 Master Control Center (Super Admin)

- **URL:** [https://print.fruitsgenerator.co.in/super-admin](https://print.fruitsgenerator.co.in/super-admin)
- **Master Password:** `Admin_1977`

### Admin Capabilities
- **Live Business KPIs:** Total active kiosks, total orders processed, platform revenue, and upcoming license expirations.
- **Register New Kiosk:** Form to input Shop Name, Slug, Owner Phone, B&W/Color pricing, UPI ID, Razorpay keys, and Subscription validity (1 Year, Monthly, Lifetime).
- **Setup Key Modal:** View and copy the unique `KP_KIOSK_...` secret key for any shopkeeper.
- **1-Click Renewal:** Extend any shop's license by +30 days, +90 days, +180 days, +365 days, or convert to Lifetime.
- **Active / Suspend Toggle:** Temporarily halt kiosk operations with a single click if payment is pending.
- **Direct Poster Access:** Open and print counter posters with one click.

---

## 🏬 Shopkeeper Onboarding (3 Simple Steps)

### Step 1: Register in Super Admin
1. Open `/super-admin` and click **"+ Register New Kiosk"**.
2. Enter the shop details and click **Save Kiosk**.
3. Copy their unique **Kiosk Setup Key** (`KP_KIOSK_...`).

### Step 2: Print Counter Poster
1. In the Super Admin table, click **"Poster"** for the shop.
2. Press `Ctrl + P` to print the high-res A4 poster and hand it to the shopkeeper.

### Step 3: Connect Shop PC (Zero-File Method)
On the shopkeeper's PC:
- **Option A (Screen UI):** Open QuickPrint -> Click **Settings & Rates** -> Paste key into **Cloud Kiosk Connection** -> Click **Save Changes**.
- **Option B (1-Click Shortcut):** Double-click **"Connect Kiosk Cloud Key"** on the desktop, paste the key, and press Enter.

---

## 📡 API Reference

### Customer Endpoints
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/s/<shop_slug>` | Customer web portal tailored to the store's branding and rates |
| `GET` | `/s/<shop_slug>/qr` | Returns PNG QR code pointing directly to the store |
| `GET` | `/s/<shop_slug>/poster` | Renders print-ready A4 counter poster with rate card |
| `POST` | `/api/upload` | Uploads and converts document; associates with `shop_slug` |
| `POST` | `/api/order/submit_batch` | Submits print order under the store's pricing |
| `POST` | `/api/razorpay/create_order` | Generates Razorpay order using store's merchant keys |
| `POST` | `/api/razorpay/verify_payment`| Verifies payment signature and marks order paid |

### Kiosk Client Endpoints (Authenticated by `x-api-key`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/kiosk/pending_jobs` | Fetches pending orders strictly for the authenticated shop |
| `GET` | `/api/kiosk/download/<id>` | Downloads PDF print file; enforces tenant verification |
| `POST`| `/api/kiosk/ack_job/<id>` | Updates order status (e.g. `completed` or `printing`) |

### Super Admin Endpoints (Session Protected)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/super/login` | Authenticates master password |
| `POST` | `/api/super/logout` | Destroys admin session |
| `GET` | `/api/super/shops` | Returns list of all kiosks with subscription status |
| `POST` | `/api/super/shops/create` | Registers new shop and generates API key |
| `POST` | `/api/super/shops/<slug>/renew` | Extends subscription duration |
| `POST` | `/api/super/shops/<slug>/toggle` | Suspends or reactivates shop |
| `DELETE`| `/api/super/shops/<slug>` | Deletes shop (protected for root store) |

---

## 🚀 Deployment Guide (Render.com)

1. Repository: `mantradevice65/quickprint-cloud.git` (Branch: `main`)
2. Environment: Python 3.11+
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `gunicorn app:app --workers 2 --timeout 120 --bind 0.0.0.0:$PORT`
5. Custom Domain: `print.fruitsgenerator.co.in` (Cloudflare CNAME pointing to Render URL)
