import os
import sys
import json
import uuid
import sqlite3
import shutil
import io
import time
import hmac
import hashlib
import urllib.request
import urllib.error
import base64
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, render_template, send_from_directory, send_file
from werkzeug.utils import secure_filename
from PIL import Image, ImageDraw, ImageOps, ImageEnhance

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
    "heic", "heif", "cdr", "psd", "txt", "docx", "doc", "xlsx", "xls", "pptx", "ppt", "rtf", "odt"
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
    "auto_print": True,
    "enable_cash_payment": True
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

# ==================== Core Helpers & Image Processors ====================

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
            rgb_img = img.convert("HSV")
            s_channel = rgb_img.split()[1]
            if s_channel.getextrema()[1] > 30:
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
            
            im.thumbnail((400, 400))
            im.save(str(thumbnail_path), "PNG")
            
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

    # Fallback copy
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

def generate_id_card_a4(front_img_path, back_img_path, output_pdf_path):
    """Merges Front and Back ID cards onto a single A4 page with enlarged size and cutting borders."""
    A4_W, A4_H = 2480, 3508
    page = Image.new("RGB", (A4_W, A4_H), "white")
    draw = ImageDraw.Draw(page)

    front = Image.open(front_img_path).convert("RGB")
    back = Image.open(back_img_path).convert("RGB")

    target_w = 1550
    max_h_per_card = 1250

    f_w, f_h = front.size
    f_target_h = int(target_w * (f_h / f_w))
    f_target_w = target_w
    if f_target_h > max_h_per_card:
        f_target_w = int(max_h_per_card * (f_w / f_h))
        f_target_h = max_h_per_card
    front_resized = front.resize((f_target_w, f_target_h), Image.Resampling.LANCZOS)

    b_w, b_h = back.size
    b_target_h = int(target_w * (b_h / b_w))
    b_target_w = target_w
    if b_target_h > max_h_per_card:
        b_target_w = int(max_h_per_card * (b_w / b_h))
        b_target_h = max_h_per_card
    back_resized = back.resize((b_target_w, b_target_h), Image.Resampling.LANCZOS)

    gap = 160
    total_content_h = f_target_h + b_target_h + gap
    y_front = max(100, (A4_H - total_content_h) // 2)
    y_back = y_front + f_target_h + gap

    x_front = (A4_W - f_target_w) // 2
    x_back = (A4_W - b_target_w) // 2

    page.paste(front_resized, (x_front, y_front))
    page.paste(back_resized, (x_back, y_back))

    # Border lines for clean cutting
    draw.rectangle([x_front - 2, y_front - 2, x_front + f_target_w + 1, y_front + f_target_h + 1], outline="#94a3b8", width=3)
    draw.rectangle([x_back - 2, y_back - 2, x_back + b_target_w + 1, y_back + b_target_h + 1], outline="#94a3b8", width=3)

    page.save(str(output_pdf_path), "PDF", resolution=300.0)
    return page

def load_doc_as_image(path):
    """Loads PDF (first page) or Image as PIL Image."""
    ext = str(path).split(".")[-1].lower()
    if ext == "pdf":
        doc = fitz.open(str(path))
        pix = doc[0].get_pixmap(dpi=200)
        im = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        doc.close()
        return im
    else:
        return Image.open(str(path)).convert("RGB")

def process_half_image(im, target_w=2200, target_h=1550):
    """Processes an image or document page so it fits half of an A4 sheet with clean margins."""
    if im.height > im.width * 1.12:
        im = im.rotate(270, expand=True)

    im_w, im_h = im.size
    im_ar = im_w / im_h

    if 1.15 <= im_ar <= 1.80:
        return im.resize((target_w, target_h), Image.Resampling.LANCZOS)

    scale = max(target_w / im_w, target_h / im_h)
    new_w = int(im_w * scale)
    new_h = int(im_h * scale)
    resized = im.resize((new_w, new_h), Image.Resampling.LANCZOS)

    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))

def generate_2in1_a4(doc1_path, doc2_path, output_pdf_path):
    """Places two documents on a single A4 sheet: Top Half and Bottom Half (2-in-1 Print)."""
    A4_W, A4_H = 2480, 3508
    page = Image.new("RGB", (A4_W, A4_H), "white")
    draw = ImageDraw.Draw(page)

    im1 = load_doc_as_image(doc1_path)
    im2 = load_doc_as_image(doc2_path)

    target_w = 2200
    target_h = 1550

    top_im = process_half_image(im1, target_w, target_h)
    bot_im = process_half_image(im2, target_w, target_h)

    x1 = (A4_W - target_w) // 2
    y1 = (A4_H // 2 - target_h) // 2
    page.paste(top_im, (x1, y1))

    x2 = x1
    y2 = (A4_H // 2) + y1
    page.paste(bot_im, (x2, y2))

    draw.rectangle([x1 - 2, y1 - 2, x1 + target_w + 1, y1 + target_h + 1], outline="#cbd5e1", width=2)
    draw.rectangle([x2 - 2, y2 - 2, x2 + target_w + 1, y2 + target_h + 1], outline="#cbd5e1", width=2)

    for x in range(80, A4_W - 80, 40):
        draw.line([(x, A4_H // 2), (x + 20, A4_H // 2)], fill="#94a3b8", width=3)

    page.save(str(output_pdf_path), "PDF", resolution=300.0)
    return page

def apply_camscanner_filter(input_image_path, output_image_path):
    """CamScanner Magic Filter with OpenCV or PIL fallback."""
    try:
        import cv2
        import numpy as np

        img = cv2.imread(str(input_image_path))
        if img is not None:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            ksize = max(15, min(img.shape[:2]) // 35)
            if ksize % 2 == 0:
                ksize += 1
            dilated = cv2.dilate(gray, np.ones((ksize, ksize), np.uint8))
            bg_blur = cv2.medianBlur(dilated, ksize)
            diff = 255 - cv2.absdiff(gray, bg_blur)
            norm = cv2.normalize(diff, None, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_8UC1)
            _, thresh = cv2.threshold(norm, 215, 255, cv2.THRESH_TRUNC)
            result = cv2.normalize(thresh, None, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX)
            cv2.imwrite(str(output_image_path), result, [cv2.IMWRITE_JPEG_QUALITY, 95])
            return True
    except Exception:
        pass

    # Pure PIL high-speed fallback
    try:
        im = Image.open(str(input_image_path)).convert("L")
        im = ImageOps.autocontrast(im, cutoff=2)
        enhancer = ImageEnhance.Contrast(im)
        im = enhancer.enhance(1.8)
        im = im.point(lambda p: 255 if p > 210 else (0 if p < 45 else p))
        im.save(str(output_image_path), "JPEG", quality=95)
        return True
    except Exception as ex:
        print("PIL filter error:", ex)
        return False

# ==================== Customer Routes ====================

@app.route("/")
@app.route("/customer")
def customer_page():
    cfg = load_config()
    return render_template(
        "customer.html",
        config=cfg,
        shop_name=cfg.get("shop_name", "Karnataka One"),
        upi_id=cfg.get("upi_id", "k1afzalpur@ybl"),
        upi_name=cfg.get("upi_name", "Ameer Solapur"),
        rate_bw=cfg.get("rate_bw", 5.0),
        rate_color=cfg.get("rate_color", 10.0),
        counter_name=cfg.get("counter_name", "Counter 1"),
        razorpay_enabled=cfg.get("razorpay_enabled", True),
        razorpay_key_id=cfg.get("razorpay_key_id", "rzp_live_TtMiUNzNPJvQ0W"),
        enable_cash_payment=cfg.get("enable_cash_payment", True)
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
        "razorpay_key_id": cfg.get("razorpay_key_id", "rzp_live_TtMiUNzNPJvQ0W"),
        "enable_cash_payment": cfg.get("enable_cash_payment", True)
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

# --- Tab 1: Normal Multi-Document Upload ---
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
            # Accept all standard images/documents gracefully
            ext = "png" if "image" in str(f.content_type).lower() else "pdf"
            
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

# --- Tab 2: ID Card Upload (Front & Back Enlarged) ---
@app.route("/api/upload_id_card", methods=["POST"])
def upload_id_card():
    if "front" not in request.files or "back" not in request.files:
        return jsonify({"error": "Both Front and Back photos are required"}), 400
        
    front_file = request.files["front"]
    back_file = request.files["back"]
    
    if front_file.filename == "" or back_file.filename == "":
        return jsonify({"error": "Please select both Front and Back photos"}), 400
        
    job_id = f"JOB-{uuid.uuid4().hex[:6].upper()}"
    front_path = UPLOAD_FOLDER / f"{job_id}_front.png"
    back_path = UPLOAD_FOLDER / f"{job_id}_back.png"
    
    front_file.save(str(front_path))
    back_file.save(str(back_path))
    
    final_pdf_path = UPLOAD_FOLDER / f"{job_id}.pdf"
    thumbnail_path = THUMBNAIL_FOLDER / f"{job_id}.png"
    
    try:
        a4_im = generate_id_card_a4(front_path, back_path, final_pdf_path)
        thumb = a4_im.copy()
        thumb.thumbnail((400, 600))
        thumb.save(str(thumbnail_path), "PNG")
    except Exception as e:
        return jsonify({"error": f"Failed to generate ID card layout: {str(e)}"}), 500

    cfg = load_config()
    rate_bw = float(cfg.get("rate_bw", 5.0))
    rate_color = float(cfg.get("rate_color", 10.0))

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT INTO jobs (id, batch_id, customer_name, filename, pdf_path, original_type, page_count, print_type, copies, page_range, total_price, status, printer_used, utr, created_at, color_pages)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        job_id,
        None,
        "Customer",
        "ID Card (Front & Back)",
        str(final_pdf_path),
        "id_card",
        1,
        "bw",
        1,
        "all",
        rate_bw,
        "awaiting_payment",
        "",
        "",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ""
    ))
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "job_id": job_id,
        "filename": "ID Card (Front & Back)",
        "page_count": 1,
        "rate_bw": rate_bw,
        "rate_color": rate_color,
        "thumbnail_url": f"/thumbnails/{job_id}.png"
    })

# --- Tab 3: 2-in-1 Upload (Top & Bottom Half) ---
@app.route("/api/upload_2in1", methods=["POST"])
def upload_2in1():
    if "doc1" not in request.files or "doc2" not in request.files:
        return jsonify({"error": "Both Top and Bottom documents are required"}), 400
        
    f1 = request.files["doc1"]
    f2 = request.files["doc2"]
    
    if f1.filename == "" or f2.filename == "":
        return jsonify({"error": "Please select both documents"}), 400
        
    job_id = f"JOB-{uuid.uuid4().hex[:6].upper()}"
    ext1 = f1.filename.split(".")[-1].lower() if "." in f1.filename else "png"
    ext2 = f2.filename.split(".")[-1].lower() if "." in f2.filename else "png"
    
    p1 = UPLOAD_FOLDER / f"{job_id}_doc1.{ext1}"
    p2 = UPLOAD_FOLDER / f"{job_id}_doc2.{ext2}"
    
    f1.save(str(p1))
    f2.save(str(p2))
    
    final_pdf_path = UPLOAD_FOLDER / f"{job_id}.pdf"
    thumbnail_path = THUMBNAIL_FOLDER / f"{job_id}.png"
    
    try:
        a4_im = generate_2in1_a4(p1, p2, final_pdf_path)
        thumb = a4_im.copy()
        thumb.thumbnail((400, 600))
        thumb.save(str(thumbnail_path), "PNG")
    except Exception as e:
        return jsonify({"error": f"Failed to generate 2-in-1 layout: {str(e)}"}), 500

    cfg = load_config()
    rate_bw = float(cfg.get("rate_bw", 5.0))
    rate_color = float(cfg.get("rate_color", 10.0))

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT INTO jobs (id, batch_id, customer_name, filename, pdf_path, original_type, page_count, print_type, copies, page_range, total_price, status, printer_used, utr, created_at, color_pages)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        job_id,
        None,
        "Customer",
        "2-in-1 Print",
        str(final_pdf_path),
        "2in1",
        1,
        "bw",
        1,
        "all",
        rate_bw,
        "awaiting_payment",
        "",
        "",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ""
    ))
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "job_id": job_id,
        "filename": "2-in-1 Print",
        "page_count": 1,
        "rate_bw": rate_bw,
        "rate_color": rate_color,
        "thumbnail_url": f"/thumbnails/{job_id}.png"
    })

# --- PDF Page Rendering for Mobile Cropping ---
@app.route("/api/render_pdf_page", methods=["POST"])
def render_pdf_page():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["file"]
    page_num = int(request.form.get("page", 0))
    
    try:
        doc = fitz.open(stream=file.read(), filetype="pdf")
        if len(doc) == 0:
            return jsonify({"error": "Empty PDF"}), 400
        page_idx = min(page_num, len(doc) - 1)
        pix = doc[page_idx].get_pixmap(dpi=200)
        png_bytes = pix.tobytes("png")
        data_uri = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
        doc.close()
        return jsonify({
            "success": True,
            "data_url": data_uri,
            "total_pages": len(doc)
        })
    except Exception as e:
        return jsonify({"error": f"Failed to render PDF: {str(e)}"}), 500

# --- CamScanner Magic Filter ---
@app.route("/api/image/magic_filter", methods=["POST"])
def api_magic_filter():
    data = request.json or {}
    job_id = data.get("job_id", "").strip()
    apply_filter = bool(data.get("apply", True))

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT original_type FROM jobs WHERE id = ?", (job_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return jsonify({"success": False, "error": "Job not found"}), 404

    orig_ext = row[0]
    raw_path = UPLOAD_FOLDER / f"{job_id}_raw.{orig_ext}"
    final_pdf_path = UPLOAD_FOLDER / f"{job_id}.pdf"
    thumbnail_path = THUMBNAIL_FOLDER / f"{job_id}.png"

    if not raw_path.exists():
        return jsonify({"success": False, "error": "Original file not found"}), 404

    try:
        if apply_filter:
            filtered_img_path = UPLOAD_FOLDER / f"{job_id}_filtered.jpg"
            success = apply_camscanner_filter(raw_path, filtered_img_path)
            if not success:
                return jsonify({"success": False, "error": "Filter failed"}), 500
            
            im = Image.open(filtered_img_path).convert("RGB")
            thumb_im = im.copy()
            thumb_im.thumbnail((400, 400))
            thumb_im.save(str(thumbnail_path), "PNG")
            im.save(str(final_pdf_path), "PDF", resolution=150.0)
            is_filtered = 1
        else:
            im = Image.open(raw_path).convert("RGB")
            thumb_im = im.copy()
            thumb_im.thumbnail((400, 400))
            thumb_im.save(str(thumbnail_path), "PNG")
            im.save(str(final_pdf_path), "PDF", resolution=150.0)
            is_filtered = 0

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE jobs SET is_magic_filtered = ? WHERE id = ?", (is_filtered, job_id))
        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "job_id": job_id,
            "is_magic_filtered": is_filtered == 1,
            "thumbnail_url": f"/thumbnails/{job_id}.png?t={int(time.time())}"
        })
    except Exception as ex:
        return jsonify({"success": False, "error": str(ex)}), 500

# --- Image Cropping ---
@app.route("/api/image/crop", methods=["POST"])
def api_crop_image():
    if "image" not in request.files:
        return jsonify({"success": False, "error": "No image uploaded"}), 400
    job_id = request.form.get("job_id", "").strip()
    if not job_id:
        return jsonify({"success": False, "error": "No job_id provided"}), 400

    cropped_file = request.files["image"]

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT original_type FROM jobs WHERE id = ?", (job_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return jsonify({"success": False, "error": "Job not found"}), 404

    orig_ext = row[0]
    raw_path = UPLOAD_FOLDER / f"{job_id}_raw.{orig_ext}"
    final_pdf_path = UPLOAD_FOLDER / f"{job_id}.pdf"
    thumbnail_path = THUMBNAIL_FOLDER / f"{job_id}.png"

    try:
        im = Image.open(cropped_file.stream)
        thumb_im = im.copy()
        thumb_im.thumbnail((400, 400))
        thumb_im.save(str(thumbnail_path), "PNG")

        save_im = im.copy()
        if orig_ext.lower() in ("jpg", "jpeg") and save_im.mode in ("RGBA", "P"):
            save_im = save_im.convert("RGB")
        save_im.save(str(raw_path))

        pdf_im = im.copy()
        if pdf_im.mode != "RGB":
            pdf_im = pdf_im.convert("RGB")
        pdf_im.save(str(final_pdf_path), "PDF", resolution=150.0)

        return jsonify({
            "success": True,
            "job_id": job_id,
            "thumbnail_url": f"/thumbnails/{job_id}.png?t={int(time.time())}"
        })
    except Exception as ex:
        return jsonify({"success": False, "error": str(ex)}), 500

# --- Password-Protected PDF Unlock ---
@app.route("/api/pdf/unlock", methods=["POST"])
def api_unlock_pdf():
    data = request.json or {}
    job_id = data.get("job_id", "").strip()
    password = data.get("password", "").strip()
    if not job_id or not password:
        return jsonify({"success": False, "error": "Job ID aur Password zaroori hain"}), 400

    pdf_path = UPLOAD_FOLDER / f"{job_id}.pdf"
    thumbnail_path = THUMBNAIL_FOLDER / f"{job_id}.png"
    if not pdf_path.exists():
        return jsonify({"success": False, "error": "Document nahi mila"}), 404

    try:
        doc = fitz.open(str(pdf_path))
        if not (doc.needs_pass or doc.is_encrypted):
            page_count = len(doc)
            doc.close()
            return jsonify({"success": True, "message": "Pehle se unlocked hai", "page_count": page_count})

        auth_res = doc.authenticate(password)
        if auth_res <= 0:
            doc.close()
            return jsonify({"success": False, "error": "Galat password! Dobara koshish karein. (Aadhaar example: Naam ke 4 bade akshar + Janm saal, jaise AMER1992)"})

        unlocked_tmp = UPLOAD_FOLDER / f"{job_id}_unlocked.pdf"
        doc.save(str(unlocked_tmp))
        page_count = len(doc)
        if page_count > 0:
            pix = doc[0].get_pixmap(dpi=130)
            pix.save(str(thumbnail_path))
        doc.close()

        shutil.move(str(unlocked_tmp), str(pdf_path))
        _, bw_count, color_count, color_pages = analyze_pdf_color(pdf_path)
        color_pages_str = ",".join(map(str, color_pages)) if color_pages else ""

        cfg = load_config()
        rate_bw = float(cfg.get("rate_bw", 5.0))
        total_price = round(page_count * rate_bw, 2)

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""
            UPDATE jobs
            SET page_count = ?, status = 'awaiting_payment', total_price = ?, color_pages = ?
            WHERE id = ?
        """, (page_count, total_price, color_pages_str, job_id))
        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "job_id": job_id,
            "page_count": page_count,
            "bw_count": bw_count,
            "color_count": color_count,
            "color_pages": color_pages,
            "total_price": total_price,
            "thumbnail_url": f"/thumbnails/{job_id}.png?t={int(time.time())}"
        })
    except Exception as ex:
        return jsonify({"success": False, "error": f"Unlock error: {str(ex)}"}), 500

# --- Jobs list for status polling ---
@app.route("/api/jobs", methods=["GET"])
def api_get_jobs():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id, batch_id, status FROM jobs ORDER BY created_at DESC LIMIT 50")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({"jobs": rows})

# ==================== Order Submission ====================

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
    
    # Mark as pending_kiosk_sync so PC picks it up immediately
    c.execute("""
        UPDATE jobs
        SET customer_name = ?, print_type = ?, copies = ?, page_range = ?, total_price = ?, status = 'pending_kiosk_sync', utr = ?
        WHERE id = ?
    """, (customer_name, print_type, copies, page_range, total_price, utr, job_id))
    conn.commit()
    conn.close()
    
    tracking_id = f"QP-{job_id.replace('JOB-', '')}"
    return jsonify({
        "success": True,
        "job_id": job_id,
        "tracking_id": tracking_id,
        "total_price": total_price,
        "status": "pending_kiosk_sync"
    })

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
            SET batch_id = ?, customer_name = ?, print_type = ?, copies = ?, page_range = ?, total_price = ?, status = 'pending_kiosk_sync', utr = ?
            WHERE id = ?
        """, (batch_id, customer_name, print_type, copies, page_range, item_cost, utr, job_id))
        
    conn.commit()
    conn.close()
    tracking_id = f"QP-{batch_id.replace('BATCH-', '')}"
    return jsonify({
        "success": True,
        "batch_id": batch_id,
        "tracking_id": tracking_id,
        "total_price": round(total_price, 2),
        "status": "pending_kiosk_sync"
    })

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
                "key_id": key_id,
                "shop_name": cfg.get("shop_name", "Karnataka One")
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
    
    total_cost = 0.0
    batch_id = None
    target_job_id = None
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
            total_cost += cost
            c.execute("""
                UPDATE jobs
                SET batch_id = ?, customer_name = ?, print_type = ?, copies = ?, page_range = ?, total_price = ?, status = 'pending_kiosk_sync', utr = ?
                WHERE id = ?
            """, (batch_id, customer_name, print_type, copies, page_range, cost, utr_string, job_id))
    else:
        target_job_id = data.get("job_id")
        page_range = str(data.get("page_range", "all")).strip() or "all"
        c.execute("SELECT page_count, pdf_path FROM jobs WHERE id = ?", (target_job_id,))
        row = c.fetchone()
        if row:
            orig_p_cnt, pdf_path = row
            sel_pages = parse_page_selection(page_range, orig_p_cnt)
            cost = round(len(sel_pages) * rate * copies, 2)
            total_cost = cost
            c.execute("""
                UPDATE jobs
                SET customer_name = ?, print_type = ?, copies = ?, page_range = ?, total_price = ?, status = 'pending_kiosk_sync', utr = ?
                WHERE id = ?
            """, (customer_name, print_type, copies, page_range, cost, utr_string, target_job_id))
            
    conn.commit()
    conn.close()
    
    tracking_id = f"QP-{batch_id.replace('BATCH-', '')}" if order_type == "batch" else f"QP-{target_job_id.replace('JOB-', '')}"
    return jsonify({
        "success": True,
        "payment_id": payment_id,
        "batch_id": batch_id,
        "job_id": target_job_id,
        "tracking_id": tracking_id,
        "total_price": round(total_cost, 2),
        "status": "pending_kiosk_sync",
        "message": "Payment verified! Your order is queued and will print at the counter."
    })

# ==================== Live Order Tracking API ====================

@app.route("/api/order/track/<path:query_id>", methods=["GET"])
def api_track_order(query_id):
    query_id = query_id.strip()
    clean_id = query_id.upper()
    if clean_id.startswith("QP-"):
        clean_suffix = clean_id[3:]
    elif clean_id.startswith("JOB-"):
        clean_suffix = clean_id[4:]
    elif clean_id.startswith("BATCH-"):
        clean_suffix = clean_id[6:]
    else:
        clean_suffix = clean_id

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT id, batch_id, customer_name, filename, original_type, page_count, print_type, copies, page_range, total_price, status, utr, created_at
        FROM jobs
        WHERE id = ? 
           OR id LIKE ?
           OR batch_id = ?
           OR batch_id LIKE ?
           OR utr = ?
           OR utr LIKE ?
        ORDER BY created_at DESC LIMIT 1
    """, (
        query_id, f"%{clean_suffix}%",
        query_id, f"%{clean_suffix}%",
        query_id, f"%{clean_suffix}%"
    ))
    row = c.fetchone()
    conn.close()
    
    if not row:
        return jsonify({"found": False, "error": "Order not found. Please verify your Tracking ID."}), 404
        
    data = dict(row)
    tracking_id = f"QP-{data['batch_id'].replace('BATCH-', '')}" if data.get('batch_id') else f"QP-{data['id'].replace('JOB-', '')}"
    data["tracking_id"] = tracking_id
    data["found"] = True
    return jsonify(data)

# ==================== Kiosk Sync API (For Shop PC) ====================

@app.route("/api/kiosk/pending_jobs", methods=["GET"])
def kiosk_pending_jobs():
    """Returns list of all paid/confirmed orders waiting to be synced & printed by the shop PC."""
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
        WHERE status IN ('pending_kiosk_sync', 'paid')
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
    if new_status == "completed":
        new_status = "printed"
    
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
