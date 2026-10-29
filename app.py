import os
import sys
import json
import uuid
import sqlite3
import shutil
import io
import hmac
import hashlib
import urllib.request
import urllib.error
import base64
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, render_template, send_from_directory, send_file
from werkzeug.utils import secure_filename
from PIL import Image

os.environ["PYMUPDF_DISABLE_LAYOUT"] = "1"
import fitz  # PyMuPDF
import qrcode

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent
template_dir = BASE_DIR / "templates"
static_dir = BASE_DIR / "static"
app = Flask(__name__, template_folder=str(template_dir), static_folder=str(static_dir))

UPLOAD_FOLDER = BASE_DIR / "uploads"
THUMBNAIL_FOLDER = BASE_DIR / "thumbnails"
DB_FILE = BASE_DIR / "jobs.db"
CONFIG_FILE = BASE_DIR / "config.json"

UPLOAD_FOLDER.mkdir(exist_ok=True, parents=True)
THUMBNAIL_FOLDER.mkdir(exist_ok=True, parents=True)

app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB max

ALLOWED_EXTENSIONS = {
    "pdf", "png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif",
    "heic", "heif", "cdr", "psd", "txt", "docx", "doc"
}

DEFAULT_CONFIG = {
    "shop_name": "Karnataka One",
    "upi_id": "k1afzalpur@ybl",
    "upi_name": "Ameer Solapur",
    "rate_bw": 5.0,
    "rate_color": 10.0,
    "counter_name": "Counter 1",
    "razorpay_enabled": True,
    "razorpay_key_id": "rzp_live_TtMiUNzNPJvQ0W",
    "razorpay_key_secret": "1Ktgu63RiXsb2gGH8iTPaHKK",
    "kiosk_api_key": "k1_quickprint_secret_2026",
    "auto_print": True
}

def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                merged = DEFAULT_CONFIG.copy()
                merged.update(cfg)
                return merged
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            batch_id TEXT,
            customer_name TEXT,
            filename TEXT,
            pdf_path TEXT,
            original_type TEXT,
            page_count INTEGER,
            print_type TEXT,
            copies INTEGER,
            page_range TEXT,
            total_price REAL,
            status TEXT,
            printer_used TEXT,
            utr TEXT,
            created_at TEXT,
            color_pages TEXT,
            is_magic_filtered INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

init_db()

def analyze_pdf_color(pdf_path):
    """Detects color vs black/white pages in PDF."""
    try:
        doc = fitz.open(str(pdf_path))
        bw_count = 0
        color_count = 0
        color_pages = []
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=50)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            # Sample check for color saturation
            is_color = False
            rgb_img = img.convert("HSV")
            s_channel = rgb_img.split()[1]
            if s_channel.getextrema()[1] > 30:
                is_color = True
            if is_color:
                color_count += 1
                color_pages.append(i + 1)
            else:
                bw_count += 1
        doc.close()
        return (color_count > 0), bw_count, color_count, color_pages
    except Exception:
        return False, 1, 0, []

def process_uploaded_document(raw_path, final_pdf_path, thumbnail_path, ext):
    """Converts uploaded file into a standard printable PDF and generates thumbnail."""
    page_count = 1
    is_locked = False
    is_image = False
    bw_count = 1
    color_count = 0
    color_pages = []

    ext = ext.lower()

    if ext == "pdf":
        shutil.copy(str(raw_path), str(final_pdf_path))
        try:
            doc = fitz.open(str(final_pdf_path))
            if doc.needs_pass or doc.is_encrypted:
                is_locked = True
                page_count = 0
                doc.close()
            else:
                page_count = len(doc)
                if page_count > 0:
                    pix = doc[0].get_pixmap(dpi=130)
                    pix.save(str(thumbnail_path))
                doc.close()
                _, bw_count, color_count, color_pages = analyze_pdf_color(final_pdf_path)
        except Exception as e:
            print("Error processing PDF:", e)
        return page_count, is_locked, False, bw_count, color_count, color_pages

    # Image formats
    if ext in ["png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif", "heic", "heif"]:
        is_image = True
        try:
            im = Image.open(str(raw_path))
            if im.mode != "RGB":
                im = im.convert("RGB")
            im.save(str(final_pdf_path), "PDF", resolution=150.0)
            
            # Thumbnail
            im.thumbnail((400, 400))
            im.save(str(thumbnail_path), "PNG")
            
            # Check color
            rgb_img = im.convert("HSV")
            if rgb_img.split()[1].getextrema()[1] > 30:
                color_count = 1
                bw_count = 0
                color_pages = [1]
            else:
                color_count = 0
                bw_count = 1
                color_pages = []
        except Exception as ex:
            print("Image conversion error:", ex)
        return 1, False, True, bw_count, color_count, color_pages

    # CorelDRAW (.cdr) thumbnail preview extraction
    if ext == "cdr":
        try:
            import zipfile
            with zipfile.ZipFile(str(raw_path), "r") as z:
                for cand in ["previews/page1.png", "previews/thumbnail.png", "metadata/thumbnail.png"]:
                    if cand in z.namelist():
                        cim = Image.open(io.BytesIO(z.read(cand)))
                        if cim.mode != "RGB":
                            cim = cim.convert("RGB")
                        cim.save(str(final_pdf_path), "PDF", resolution=150.0)
                        cim.thumbnail((400, 400))
                        cim.save(str(thumbnail_path), "PNG")
                        return 1, False, True, 1, 0, []
        except Exception as zex:
            print("CDR zip extract warning:", zex)

    # Fallback text or unsupported
    try:
        shutil.copy(str(raw_path), str(final_pdf_path))
    except Exception:
        pass
    return 1, False, False, 1, 0, []

def parse_page_selection(page_range_str, total_pages):
    """Parses page range e.g. '1,3,5-7' into list of page numbers."""
    if not page_range_str or page_range_str.strip().lower() in ("all", "*"):
        return list(range(1, total_pages + 1))
    selected = set()
    for part in page_range_str.split(","):
        part = part.strip()
        if "-" in part:
            try:
                start_p, end_p = part.split("-", 1)
                s = max(1, int(start_p))
                e = min(total_pages, int(end_p))
                if s <= e:
                    selected.update(range(s, e + 1))
            except Exception:
                pass
        elif part.isdigit():
            p = int(part)
            if 1 <= p <= total_pages:
                selected.add(p)
    res = sorted(list(selected))
    return res if res else list(range(1, total_pages + 1))

# ==================== Customer Routes ====================

@app.route("/")
@app.route("/customer")
def customer_page():
    cfg = load_config()
    return render_template(
        "customer.html",
        shop_name=cfg.get("shop_name", "Karnataka One"),
        upi_id=cfg.get("upi_id", "k1afzalpur@ybl"),
        upi_name=cfg.get("upi_name", "Ameer Solapur"),
        rate_bw=cfg.get("rate_bw", 5.0),
        rate_color=cfg.get("rate_color", 10.0),
        counter_name=cfg.get("counter_name", "Counter 1"),
        razorpay_enabled=cfg.get("razorpay_enabled", True),
        razorpay_key_id=cfg.get("razorpay_key_id", "rzp_live_TtMiUNzNPJvQ0W")
    )

@app.route("/api/config", methods=["GET"])
def api_get_config():
    cfg = load_config()
    return jsonify({
        "shop_name": cfg.get("shop_name", "Karnataka One"),
        "upi_id": cfg.get("upi_id", "k1afzalpur@ybl"),
        "upi_name": cfg.get("upi_name", "Ameer Solapur"),
        "rate_bw": cfg.get("rate_bw", 5.0),
        "rate_color": cfg.get("rate_color", 10.0),
        "counter_name": cfg.get("counter_name", "Counter 1"),
        "razorpay_enabled": cfg.get("razorpay_enabled", True),
        "razorpay_key_id": cfg.get("razorpay_key_id", "rzp_live_TtMiUNzNPJvQ0W")
    })

@app.route("/api/qr")
def get_qr():
    url = request.host_url
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

@app.route("/api/upload", methods=["POST"])
def upload_file():
    file_list = []
    if "files" in request.files:
        file_list = request.files.getlist("files")
    elif "file" in request.files:
        file_list = request.files.getlist("file")
        
    if not file_list or len(file_list) == 0:
        return jsonify({"error": "No file uploaded"}), 400
        
    cfg = load_config()
    rate_bw = float(cfg.get("rate_bw", 5.0))
    rate_color = float(cfg.get("rate_color", 10.0))
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    results = []
    for f in file_list:
        if not f or f.filename == "":
            continue
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            continue
            
        job_id = f"JOB-{uuid.uuid4().hex[:6].upper()}"
        safe_name = secure_filename(f.filename) or f"{job_id}.{ext}"
        
        raw_path = UPLOAD_FOLDER / f"{job_id}_raw.{ext}"
        f.save(str(raw_path))
        
        final_pdf_path = UPLOAD_FOLDER / f"{job_id}.pdf"
        thumbnail_path = THUMBNAIL_FOLDER / f"{job_id}.png"

        try:
            page_count, is_locked, is_image, bw_count, color_count, color_pages = process_uploaded_document(
                raw_path, final_pdf_path, thumbnail_path, ext
            )
        except Exception as proc_ex:
            print(f"Error processing {safe_name}:", proc_ex)
            continue

        color_pages_str = ",".join(map(str, color_pages)) if color_pages else ""
        initial_status = "locked" if is_locked else "awaiting_payment"

        c.execute("""
            INSERT INTO jobs (id, batch_id, customer_name, filename, pdf_path, original_type, page_count, print_type, copies, page_range, total_price, status, printer_used, utr, created_at, color_pages)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job_id,
            None,
            "Customer",
            safe_name,
            str(final_pdf_path),
            ext,
            page_count,
            "bw",
            1,
            "all",
            round(page_count * rate_bw, 2),
            initial_status,
            "",
            "",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            color_pages_str
        ))
        
        results.append({
            "job_id": job_id,
            "filename": safe_name,
            "original_type": ext,
            "page_count": page_count,
            "is_locked": is_locked,
            "is_image": is_image,
            "bw_count": bw_count,
            "color_count": color_count,
            "color_pages": color_pages,
            "rate_bw": rate_bw,
            "rate_color": rate_color,
            "thumbnail_url": f"/thumbnails/{job_id}.png" if not is_locked else "/static/locked_pdf.png",
            "raw_url": f"/uploads/{job_id}_raw.{ext}" if is_image else "",
            "pdf_url": f"/uploads/{job_id}.pdf"
        })
        
    conn.commit()
    conn.close()
    
    if not results:
        return jsonify({"error": "No valid files could be processed."}), 400
        
    resp = {
        "success": True,
        "job_id": results[0]["job_id"],
        "filename": results[0]["filename"],
        "page_count": results[0]["page_count"],
        "is_locked": results[0].get("is_locked", False),
        "is_image": results[0].get("is_image", False),
        "bw_count": results[0].get("bw_count", 1),
        "color_count": results[0].get("color_count", 0),
        "color_pages": results[0].get("color_pages", []),
        "rate_bw": rate_bw,
        "rate_color": rate_color,
        "thumbnail_url": results[0]["thumbnail_url"],
        "raw_url": results[0]["raw_url"],
        "pdf_url": results[0]["pdf_url"],
        "files": results
    }
    return jsonify(resp)

@app.route("/api/render_pdf_page", methods=["POST"])
def render_pdf_page():
    data = request.json or {}
    job_id = data.get("job_id")
    page_num = int(data.get("page", 1)) - 1
    pdf_path = UPLOAD_FOLDER / f"{job_id}.pdf"
    if not pdf_path.exists():
        return jsonify({"error": "PDF not found"}), 404
    try:
        doc = fitz.open(str(pdf_path))
        if page_num < 0 or page_num >= len(doc):
            doc.close()
            return jsonify({"error": "Invalid page number"}), 400
        page = doc[page_num]
        pix = page.get_pixmap(dpi=120)
        img_bytes = pix.tobytes("png")
        doc.close()
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        return jsonify({"image": f"data:image/png;base64,{b64}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/order/submit", methods=["POST"])
def submit_order():
    data = request.json or {}
    job_id = data.get("job_id")
    customer_name = data.get("customer_name", "Customer").strip() or "Customer"
    print_type = data.get("print_type", "bw")
    copies = int(data.get("copies", 1))
    page_range = data.get("page_range", "all").strip() or "all"
    utr = data.get("utr", "").strip()
    
    cfg = load_config()
    rate_bw = float(cfg.get("rate_bw", 5.0))
    rate_color = float(cfg.get("rate_color", 10.0))
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT page_count, pdf_path, color_pages FROM jobs WHERE id = ?", (job_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Job not found"}), 404
        
    page_count, pdf_path, cp_str = row
    selected_pages = parse_page_selection(page_range, page_count)
    active_pages = len(selected_pages)
    
    rate = rate_bw if print_type == "bw" else rate_color
    total_price = round(active_pages * rate * copies, 2)
    
    c.execute("""
        UPDATE jobs
        SET customer_name = ?, print_type = ?, copies = ?, page_range = ?, total_price = ?, status = 'awaiting_payment', utr = ?
        WHERE id = ?
    """, (customer_name, print_type, copies, page_range, total_price, utr, job_id))
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "job_id": job_id, "total_price": total_price})

@app.route("/api/order/submit_batch", methods=["POST"])
def submit_batch_order():
    data = request.json or {}
    items = data.get("items", [])
    customer_name = data.get("customer_name", "Customer").strip() or "Customer"
    print_type = data.get("print_type", "bw")
    copies = int(data.get("copies", 1))
    utr = data.get("utr", "").strip()
    
    cfg = load_config()
    rate_bw = float(cfg.get("rate_bw", 5.0))
    rate_color = float(cfg.get("rate_color", 10.0))
    rate = rate_bw if print_type == "bw" else rate_color
    
    batch_id = f"BATCH-{uuid.uuid4().hex[:6].upper()}"
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    total_price = 0.0
    for item in items:
        job_id = item.get("job_id")
        page_range = item.get("page_range", "all")
        c.execute("SELECT page_count FROM jobs WHERE id = ?", (job_id,))
        row = c.fetchone()
        if not row:
            continue
        p_cnt = row[0]
        sel_pages = parse_page_selection(page_range, p_cnt)
        item_cost = round(len(sel_pages) * rate * copies, 2)
        total_price += item_cost
        
        c.execute("""
            UPDATE jobs
            SET batch_id = ?, customer_name = ?, print_type = ?, copies = ?, page_range = ?, total_price = ?, status = 'awaiting_payment', utr = ?
            WHERE id = ?
        """, (batch_id, customer_name, print_type, copies, page_range, item_cost, utr, job_id))
        
    conn.commit()
    conn.close()
    return jsonify({"success": True, "batch_id": batch_id, "total_price": round(total_price, 2)})

# ==================== Razorpay Routes ====================

@app.route("/api/razorpay/create_order", methods=["POST"])
def api_razorpay_create_order():
    data = request.json or {}
    amount_inr = float(data.get("amount", 0.0))
    job_id = data.get("job_id", "")
    customer_name = data.get("customer_name", "Customer").strip()
    
    if amount_inr <= 0:
        return jsonify({"error": "Invalid payment amount"}), 400
        
    cfg = load_config()
    key_id = cfg.get("razorpay_key_id", "rzp_live_TtMiUNzNPJvQ0W")
    key_secret = cfg.get("razorpay_key_secret", "1Ktgu63RiXsb2gGH8iTPaHKK")
    
    amount_paise = int(round(amount_inr * 100))
    receipt_id = f"rcpt_{job_id[:14]}" if job_id else f"rcpt_{uuid.uuid4().hex[:10]}"
    
    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "receipt": receipt_id,
        "notes": {
            "job_id": job_id,
            "customer_name": customer_name,
            "shop": cfg.get("shop_name", "Karnataka One")
        }
    }
    
    auth_str = base64.b64encode(f"{key_id}:{key_secret}".encode("utf-8")).decode("utf-8")
    req = urllib.request.Request(
        "https://api.razorpay.com/v1/orders",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_str}"
        },
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            return jsonify({
                "success": True,
                "order_id": resp_data.get("id"),
                "amount": amount_paise,
                "currency": "INR",
                "key_id": key_id
            })
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        print("[-] Razorpay Create Order HTTPError:", err_msg)
        return jsonify({"error": f"Razorpay API Error: {err_msg}"}), 500
    except Exception as ex:
        print("[-] Razorpay Create Order Exception:", ex)
        return jsonify({"error": str(ex)}), 500

@app.route("/api/razorpay/verify_payment", methods=["POST"])
def api_razorpay_verify_payment():
    data = request.json or {}
    order_id = data.get("razorpay_order_id", "").strip()
    payment_id = data.get("razorpay_payment_id", "").strip()
    signature = data.get("razorpay_signature", "").strip()
    order_type = data.get("order_type", "single")
    customer_name = data.get("customer_name", "Customer").strip() or "Customer"
    print_type = data.get("print_type", "bw")
    copies = int(data.get("copies", 1))
    
    if not order_id or not payment_id or not signature:
        return jsonify({"error": "Missing Razorpay verification parameters"}), 400
        
    cfg = load_config()
    key_secret = cfg.get("razorpay_key_secret", "1Ktgu63RiXsb2gGH8iTPaHKK")
    
    # Signature verification
    msg = f"{order_id}|{payment_id}".encode("utf-8")
    expected = hmac.new(key_secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return jsonify({"error": "Invalid signature verification failed"}), 400
        
    utr_string = f"RZP:{payment_id}"
    rate_bw = float(cfg.get("rate_bw", 5.0))
    rate_color = float(cfg.get("rate_color", 10.0))
    rate = rate_bw if print_type == "bw" else rate_color
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    if order_type == "batch":
        items = data.get("items", [])
        batch_id = f"BATCH-{uuid.uuid4().hex[:6].upper()}"
        for it in items:
            job_id = it.get("job_id")
            page_range = str(it.get("page_range", "all")).strip() or "all"
            c.execute("SELECT page_count, pdf_path FROM jobs WHERE id = ?", (job_id,))
            row = c.fetchone()
            if not row:
                continue
            orig_p_cnt, pdf_path = row
            sel_pages = parse_page_selection(page_range, orig_p_cnt)
            cost = round(len(sel_pages) * rate * copies, 2)
            c.execute("""
                UPDATE jobs
                SET batch_id = ?, customer_name = ?, print_type = ?, copies = ?, page_range = ?, total_price = ?, status = 'pending_kiosk_sync', utr = ?
                WHERE id = ?
            """, (batch_id, customer_name, print_type, copies, page_range, cost, utr_string, job_id))
    else:
        job_id = data.get("job_id")
        page_range = str(data.get("page_range", "all")).strip() or "all"
        c.execute("SELECT page_count, pdf_path FROM jobs WHERE id = ?", (job_id,))
        row = c.fetchone()
        if row:
            orig_p_cnt, pdf_path = row
            sel_pages = parse_page_selection(page_range, orig_p_cnt)
            cost = round(len(sel_pages) * rate * copies, 2)
            c.execute("""
                UPDATE jobs
                SET customer_name = ?, print_type = ?, copies = ?, page_range = ?, total_price = ?, status = 'pending_kiosk_sync', utr = ?
                WHERE id = ?
            """, (customer_name, print_type, copies, page_range, cost, utr_string, job_id))
            
    conn.commit()
    conn.close()
    
    return jsonify({
        "success": True,
        "payment_id": payment_id,
        "message": "Payment verified! Your order is queued and will print at the counter."
    })

# ==================== Kiosk Sync API (For Shop PC) ====================

@app.route("/api/kiosk/pending_jobs", methods=["GET"])
def kiosk_pending_jobs():
    """Returns list of all paid orders waiting to be synced & printed by the shop PC."""
    cfg = load_config()
    kiosk_key = cfg.get("kiosk_api_key", "k1_quickprint_secret_2026")
    req_key = request.headers.get("x-api-key") or request.args.get("api_key")
    if req_key != kiosk_key:
        return jsonify({"error": "Unauthorized"}), 401
        
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT id, batch_id, customer_name, filename, original_type, page_count, print_type, copies, page_range, total_price, status, utr, created_at, color_pages
        FROM jobs
        WHERE status = 'pending_kiosk_sync'
        ORDER BY created_at ASC
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({"pending_jobs": rows, "count": len(rows)})

@app.route("/api/kiosk/download/<job_id>", methods=["GET"])
def kiosk_download_job(job_id):
    """Allows the shop PC to download the PDF for printing."""
    cfg = load_config()
    kiosk_key = cfg.get("kiosk_api_key", "k1_quickprint_secret_2026")
    req_key = request.headers.get("x-api-key") or request.args.get("api_key")
    if req_key != kiosk_key:
        return jsonify({"error": "Unauthorized"}), 401
        
    fpath = UPLOAD_FOLDER / f"{job_id}.pdf"
    if not fpath.exists():
        # Check database for exact path
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT pdf_path, filename FROM jobs WHERE id = ?", (job_id,))
        row = c.fetchone()
        conn.close()
        if row and row[0] and os.path.exists(row[0]):
            return send_file(row[0], as_attachment=True, download_name=f"{job_id}.pdf")
        return jsonify({"error": "PDF file not found"}), 404
        
    return send_file(str(fpath), as_attachment=True, download_name=f"{job_id}.pdf")

@app.route("/api/kiosk/ack_job/<job_id>", methods=["POST"])
def kiosk_ack_job(job_id):
    """Shop PC acknowledges receipt and printing of the job."""
    cfg = load_config()
    kiosk_key = cfg.get("kiosk_api_key", "k1_quickprint_secret_2026")
    req_key = request.headers.get("x-api-key") or request.args.get("api_key")
    if req_key != kiosk_key:
        return jsonify({"error": "Unauthorized"}), 401
        
    data = request.json or {}
    new_status = data.get("status", "printed")
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE jobs SET status = ? WHERE id = ?", (new_status, job_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "job_id": job_id, "status": new_status})

@app.route("/api/health")
def health_check():
    return jsonify({"status": "ok", "service": "QuickPrint 24/7 Cloud Queue", "time": datetime.now().isoformat()})

@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(str(UPLOAD_FOLDER), filename)

@app.route("/thumbnails/<path:filename>")
def serve_thumbnail(filename):
    return send_from_directory(str(THUMBNAIL_FOLDER), filename)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
