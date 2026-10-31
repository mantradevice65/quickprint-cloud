# 🖨️ QuickPrint Kiosk — Smart Self-Service Printing System

> **Automated QR Code Self-Service Printing & Cloud Kiosk Solution for Cyber Cafes, Xerox Shops, CSC Centers & Print Hubs**

---

## 📌 Overview

**QuickPrint Kiosk** is a commercial-grade, end-to-end self-service printing kiosk system designed for Cyber Cafes, Xerox Centers, CSC / Karnataka One centers, and Stationery Shops.

Instead of customers crowding at the counter transferring files via WhatsApp or USB pen drives, customers simply **scan the QR code** on the counter with their mobile phone, upload their documents/photos, crop and enhance them with CamScanner-quality tools, select print settings, and pay via UPI or Cash. The order is automatically processed and printed silently on the store's physical printer!

---

## ✨ Key Features

### 1. 💎 100% Pristine Lossless Image & Document Quality
* **Zero Client-Side Degradation:** Camera photos and scanned documents are uploaded directly without browser downsampling or lossy compression.
* **300.0 DPI Print Standard:** All uploaded images and generated PDFs are rendered and converted at 300.0 DPI with maximum JPEG/PNG fidelity.
* **No Bleaching / No Blurriness:** Fine text, barcodes, Aadhaar numbers, and official stamps remain razor-sharp.

### 2. ⚡ Ultra-Fast Instant Cached Preview (Selected Pages Only)
* **Only Selected Pages:** The preview modal strictly displays only the pages chosen for printing (e.g. if Pages 1 and 3 are selected from a 10-page document, only Pages 1 and 3 are in the preview; unselected pages are completely skipped).
* **6 Millisecond Page Switching:** Rendered pages are cached on disk as high-performance JPEGs with smart adjacent prefetching (pre-loading next & previous pages into browser memory).
* **In-Preview Skip Button:** Customers can tap `❌ Skip Page` directly inside the preview modal to remove a page from the print list with real-time price adjustment.

### 3. ✂️ 8-Point Perspective & Document Crop with Top Loupe
* **C-Level Homography Transform:** Uses native bicubic PIL perspective transformation using 8 mathematical homography coefficients — completely eliminating triangle fragmentation artifacts.
* **Top-Docked Magnifier Loupe:** When dragging corner crop dots, the circular magnifier loupe docks at the **TOP** (`top: 14px`) with smart auto-flipping (switches between top-right and top-left depending on touch position) so fingers never block the document or preview.
* **Clean & Quality Presets:**
  * `🔄 Original`: Default untouched mode.
  * `🪄 Magic Clean`: CamScanner-grade multi-scale RGB illumination division that removes shadows and yellow tints while preserving ink with a 1.15 gamma power curve.
  * `📄 Deep B&W`: Ultra-high contrast monochrome.
  * `🌈 Color Boost`: Vibrancy and contrast enhancement for photos.
  * `⚙️ Sliders`: Custom fine-tuning for brightness, contrast, and sharpness.

### 4. 🪪 ID Card Mode (Front & Back Enlarged A4 Merge)
* Upload Front and Back sides of Aadhaar, PAN card, Driving License, or Voter ID.
* Crop each side with standard 3:2 ID Card aspect ratio.
* Merges both sides onto a single A4 page with proper commercial margins.

### 5. 📑 2-in-1 Side-by-Side Print Mode
* Upload two documents or two pages to merge side-by-side on a single A4 sheet.

### 6. 🎨 Automatic Color & Page Count Detection
* Intelligent PyMuPDF & NumPy RGB pixel variance analysis scans documents page-by-page.
* Automatically distinguishes Black & White vs Color pages, charging accurate rates per page (e.g. ₹5 B&W, ₹10 Color).

### 7. 💳 Dual Payment Options (UPI & Cash on Counter)
* **Razorpay / UPI Dynamic QR:** Auto-generates instant payment QR code with the exact calculated amount and shopkeeper's UPI VPA.
* **Cash on Counter:** Allows customers who prefer paying physical cash to place the order with a single tap.
* **Tracking ID:** Every order generates a unique tracking code (e.g. `QP-17A42B`) with live status tracking.

### 8. 🔄 24/7 Kiosk Cloud Sync & Silent Printing
* Background worker queries the cloud queue `/api/kiosk/sync`.
* Automatically downloads pending print jobs and executes silent printing via **SumatraPDF** without requiring human intervention.

---

## 🚀 Installation & Running

### Option 1: 1-Click Windows Setup (Recommended)
1. Double-click **`installer_output\QuickPrint_Setup.exe`** (or from your Desktop).
2. Follow the wizard. It installs all dependencies, sets up the Windows Service, creates Desktop shortcuts, and configures auto-start.
3. Open **QuickPrint Desktop App** from the Desktop icon.

### Option 2: Portable Batch Runner
1. Double-click **`Start_QuickPrint.bat`**.
2. The script automatically detects the compiled binary, `uv`, or Python 3.11 environment, launches the backend, and opens `http://localhost:5000/dashboard` in your default browser.

### Option 3: Source Code Execution
```bash
# Using uv (fastest, zero setup)
uv run python app.py

# Using standard Python
pip install -r requirements.txt
python app.py
```

---

## 🛠️ Management & Utility Scripts

* **`Start_QuickPrint.bat`**: Launches the local kiosk server and opens the dashboard.
* **`Set_Kiosk_Key.bat`**: Enter your shop slug / kiosk key (e.g. `karnataka-one`, `khan-xerox`) to connect the local printer engine to your cloud kiosk queue.
* **`QuickPrint_Process_Manager.bat`**: Interactive diagnostic console to start, stop, restart, view logs, test printer, and verify kiosk status.
* **`Build_Installer.bat`**: Rebuilds the PyInstaller binary and compiles the Inno Setup installer.

---

## ⚙️ Configuration (`config.json`)

```json
{
  "shop_name": "Karnataka One",
  "shop_slug": "karnataka-one",
  "cloud_url": "https://print.fruitsgenerator.co.in",
  "rate_bw": 5.0,
  "rate_color": 10.0,
  "upi_id": "9742443529@ybl",
  "upi_name": "Ameer Hamza",
  "auto_print": true,
  "printer_name": ""
}
```

* `shop_slug`: The unique URL identifier for your kiosk (e.g. `/s/karnataka-one`).
* `rate_bw`: Rate per page for Black & White printing.
* `rate_color`: Rate per page for Color printing.
* `auto_print`: Set `true` for automatic silent printing upon payment confirmation.
* `printer_name`: Leave blank to use the Windows Default Printer, or specify an exact printer name.

---

## 📂 Project Directory Structure

```text
d:\QR Code Print\
├── app.py                         # Core Flask application backend & API
├── config.json                    # Kiosk settings and pricing configuration
├── installer.iss                  # Inno Setup 6 installer script
├── QuickPrint.spec                # PyInstaller packaging specification
├── requirements.txt               # Python package dependencies
│
├── Start_QuickPrint.bat           # 1-Click launcher
├── Set_Kiosk_Key.bat              # Kiosk key configuration utility
├── QuickPrint_Process_Manager.bat # Process manager and diagnostics
├── Build_Installer.bat            # Automated build script
│
├── dist\QuickPrint\               # Compiled zero-dependency executable
├── installer_output\              # Generated QuickPrint_Setup.exe installer
├── QuickPrint_Source_Code\        # Clean production source distribution
├── quickprint_cloud\              # Cloud deployment repository
│
├── templates\
│   ├── customer.html              # Customer mobile UI, crop modal & preview
│   ├── dashboard.html             # Storekeeper admin & print queue dashboard
│   ├── counter_poster.html        # Printable QR code counter poster
│   └── super_admin.html           # Multi-kiosk cloud administration
│
├── static\
│   ├── css\cropper.min.css        # Cropper styling
│   └── js\cropper.min.js          # Core cropper library
│
└── uploads\                       # Temporary document storage (auto-purged)
```

---

## 🔒 Security & Privacy Compliance
* **Automatic File Purging:** All uploaded customer documents and temporary cache files are automatically purged from storage within 7 days.
* **Compliance Modals:** Built-in Terms & Conditions, Privacy Policy, Refund & Cancellation, and Contact Us dialogs meeting RBI & Razorpay regulatory requirements.
* **Encrypted Cloud Tunneling:** Cloudflare named tunnels ensure end-to-end TLS encryption with zero open incoming router ports.

---

© 2026 QuickPrint Solutions. All rights reserved.
