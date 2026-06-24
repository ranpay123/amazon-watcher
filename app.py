import os
import time
import json
import re
import threading
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from flask import Flask, request, jsonify, render_template
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_PASS = os.environ.get("GMAIL_PASS", "")
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", GMAIL_USER)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

DATA_FILE = "products.json"
CHECK_INTERVAL = 60

def load_products():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return []

def save_products(products):
    with open(DATA_FILE, "w") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)

def extract_asin(url):
    patterns = [
        r"/dp/([A-Z0-9]{10})",
        r"/gp/product/([A-Z0-9]{10})",
        r"/ASIN/([A-Z0-9]{10})",
        r"asin=([A-Z0-9]{10})",
    ]
    for p in patterns:
        m = re.search(p, url, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    return None

def resolve_pokehood(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            if "amazon.com" in a["href"] and "/dp/" in a["href"]:
                return a["href"]
    except Exception:
        pass
    return None

def check_amazon_product(asin):
    url = f"https://www.amazon.com/dp/{asin}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        title_el = soup.select_one("#productTitle")
        title = title_el.get_text(strip=True) if title_el else asin

        price = None
        for sel in [
            "#priceblock_ourprice", "#priceblock_dealprice",
            "#price_inside_buybox", "#apex_desktop .a-price .a-offscreen",
            ".a-price .a-offscreen", ".a-price[data-a-color='price'] .a-offscreen",
            "#corePrice_feature_div .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-offscreen",
            "#buybox .a-price .a-offscreen",
            "#newBuyBoxPrice",
        ]:
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(strip=True).replace("$", "").replace(",", "").strip()
                try:
                    price = float(txt.split()[0])
                    break
                except (ValueError, IndexError):
                    pass

        add_to_cart = soup.select_one("#add-to-cart-button")
        buy_now = soup.select_one("#buy-now-button")
        unavailable = soup.select_one("#outOfStock, #availability .a-color-error")
        in_stock = (add_to_cart is not None or buy_now is not None) and unavailable is None

        return {"in_stock": in_stock, "price": price, "title": title, "asin": asin}
    except Exception as e:
        return {"in_stock": False, "price": None, "title": asin, "asin": asin, "error": str(e)}

def send_email(subject, body_html):
    if not GMAIL_USER or not GMAIL_PASS:
        print(f"[NOTIFY] {subject}")
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = GMAIL_USER
        msg["To"] = NOTIFY_EMAIL
        msg.attach(MIMEText(body_html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_USER, GMAIL_PASS)
            s.sendmail(GMAIL_USER, NOTIFY_EMAIL, msg.as_string())
        print(f"[EMAIL SENT] {subject}")
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")

def notify_product(product, status):
    asin = product["asin"]
    title = status.get("title", asin)
    price = status.get("price")
    buy_url = f"https://www.amazon.com/dp/{asin}/"
    price_str = f"${price:.2f}" if price else "׳‘׳“׳•׳§ ׳‘׳׳׳–׳•׳"
    subject = f"נ¢ {title[:40]} ג€” ׳™׳© ׳׳׳׳™! {price_str}"
    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto;padding:20px">
      <h2 style="color:#e47911">נ›’ ׳׳•׳¦׳¨ ׳–׳׳™׳ ׳׳¨׳›׳™׳©׳”!</h2>
      <p style="font-size:16px"><strong>{title}</strong></p>
      <p>׳׳—׳™׳¨: <strong style="color:#B12704;font-size:18px">{price_str}</strong></p>
      <p>׳׳—׳™׳¨ ׳׳§׳¡׳™׳׳•׳ ׳©׳”׳’׳“׳¨׳×: ${product['max_price']:.2f}</p>
      <br>
      <a href="{buy_url}" style="background:#e47911;color:white;padding:14px 28px;text-decoration:none;border-radius:6px;font-size:18px;font-weight:bold;display:inline-block">
        נ›’ ׳§׳ ׳” ׳¢׳›׳©׳™׳• ׳‘׳׳׳–׳•׳
      </a>
    </div>
    """
    send_email(subject, body)

def watcher_loop():
    print("[WATCHER] Started")
    while True:
        products = load_products()
        for p in products:
            if p.get("paused"):
                continue
            asin = p.get("asin")
            if not asin:
                continue
            status = check_amazon_product(asin)
            now = datetime.now().strftime("%H:%M:%S")
            print(f"[{now}] {asin} | stock={status['in_stock']} price={status.get('price')}")

            p["last_check"] = now
            p["last_price"] = status.get("price")
            p["last_title"] = status.get("title", asin)
            p["last_stock"] = status["in_stock"]

            max_price = float(p.get("max_price", 9999))
            price = status.get("price")
            # ׳©׳׳— ׳׳™׳™׳ ׳¨׳§ ׳׳: ׳™׳© ׳׳׳׳™ + ׳׳—׳™׳¨ ׳–׳׳™׳ + ׳׳—׳™׳¨ ׳‘׳˜׳•׳•׳—
            price_ok = (price is not None) and (price <= max_price)

            if status["in_stock"] and price_ok and not p.get("notified"):
                p["notified"] = True
                notify_product(p, status)
            elif not status["in_stock"]:
                p["notified"] = False

        save_products(products)
        time.sleep(CHECK_INTERVAL)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/products", methods=["GET"])
def get_products():
    return jsonify(load_products())

@app.route("/api/products", methods=["POST"])
def add_product():
    data = request.json
    url = data.get("url", "").strip()
    max_price = float(data.get("max_price", 9999))

    if "pokehood.com" in url:
        amazon_url = resolve_pokehood(url)
        if amazon_url:
            url = amazon_url
        else:
            return jsonify({"error": "׳׳ ׳”׳¦׳׳—׳×׳™ ׳׳׳¦׳•׳ ׳׳™׳ ׳§ ׳׳׳–׳•׳ ׳‘׳“׳£ Pokehood"}), 400

    asin = extract_asin(url)
    if not asin:
        return jsonify({"error": "׳׳ ׳–׳•׳”׳” ASIN ׳×׳§׳™׳ ׳‘׳׳™׳ ׳§"}), 400

    products = load_products()
    for p in products:
        if p["asin"] == asin:
            return jsonify({"error": f"׳׳•׳¦׳¨ {asin} ׳›׳‘׳¨ ׳§׳™׳™׳ ׳‘׳¨׳©׳™׳׳”"}), 400

    status = check_amazon_product(asin)
    product = {
        "asin": asin,
        "url": f"https://www.amazon.com/dp/{asin}",
        "max_price": max_price,
        "added": datetime.now().strftime("%d/%m %H:%M"),
        "last_title": status.get("title", asin),
        "last_price": status.get("price"),
        "last_stock": status.get("in_stock", False),
        "last_check": datetime.now().strftime("%H:%M:%S"),
        "notified": False,
        "paused": False,
    }
    products.append(product)
    save_products(products)
    return jsonify(product)

@app.route("/api/products/<asin>", methods=["DELETE"])
def delete_product(asin):
    products = [p for p in load_products() if p["asin"] != asin]
    save_products(products)
    return jsonify({"ok": True})

@app.route("/api/products/<asin>/pause", methods=["POST"])
def toggle_pause(asin):
    products = load_products()
    for p in products:
        if p["asin"] == asin:
            p["paused"] = not p.get("paused", False)
    save_products(products)
    return jsonify({"ok": True})

@app.route("/api/products/<asin>/check", methods=["POST"])
def manual_check(asin):
    status = check_amazon_product(asin)
    return jsonify(status)

@app.route("/api/products/<asin>/reset", methods=["POST"])
def reset_notified(asin):
    products = load_products()
    for p in products:
        if p["asin"] == asin:
            p["notified"] = False
    save_products(products)
    return jsonify({"ok": True})

if __name__ == "__main__":
    t = threading.Thread(target=watcher_loop, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
