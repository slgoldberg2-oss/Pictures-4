"""
StreetShot — Cook County PIN → InstantStreetView → Crop/Upload → PDF
---------------------------------------------------------------------
API:
  POST /lookup-pin      { pin } → { pin14, lat, lon, address, isv_url }
  POST /build-pdf       { pages: [{label, png_b64}] } → PDF file

Deployed via Dockerfile on Railway.
"""

import base64
import io
import os
import traceback
import urllib.parse

import requests
from flask import Flask, jsonify, render_template, request, send_file

app = Flask(__name__)
PORT = int(os.environ.get("PORT", 5000))

# Primary: OData endpoint (as specified by user)
ODATA_BASE   = "https://datacatalog.cookcountyil.gov/api/odata/v4/pabr-t5kh"
# Fallback: SODA JSON endpoint
SOCRATA_BASE = "https://datacatalog.cookcountyil.gov/resource/pabr-t5kh.json"


# ─────────────────────────────────────────────────────────────
# PIN helpers
# ─────────────────────────────────────────────────────────────

def normalize_pin(raw: str) -> str:
    return raw.replace("-", "").replace(" ", "").zfill(14)


def lookup_pin(pin14: str) -> dict:
    """
    Query Cook County Parcel Universe via OData (primary) then SODA (fallback).
    Returns { pin14, lat, lon, address, isv_url } or raises ValueError.

    InstantStreetView URL format: @lat,lon,<heading>h,<pitch>p,<zoom>z
    """
    print(f"[PIN] Looking up: {pin14}")
    headers = {"Accept": "application/json"}
    row = None

    # ── OData (user-requested endpoint) ──────────────────────
    try:
        url = (
            f"{ODATA_BASE}?"
            f"$filter=pin14 eq '{pin14}'"
            f"&$select=pin14,lat,lon,prop_address_full"
            f"&$top=1"
        )
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        values = resp.json().get("value", [])
        if values:
            row = values[0]
            print(f"[PIN] OData hit — fields: {list(row.keys())}")
    except Exception as e:
        print(f"[PIN] OData attempt failed: {e}")

    # ── SODA fallback ─────────────────────────────────────────
    if not row:
        for soda_url in [
            f"{SOCRATA_BASE}?pin14={urllib.parse.quote(pin14)}&$limit=1",
            f"{SOCRATA_BASE}?$where=pin14='{pin14}'&$limit=1",
        ]:
            try:
                resp = requests.get(soda_url, headers=headers, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                if data and isinstance(data, list) and data:
                    row = data[0]
                    print(f"[PIN] SODA hit — fields: {list(row.keys())}")
                    break
            except Exception as e:
                print(f"[PIN] SODA attempt failed: {e}")

    if not row:
        raise ValueError(f"PIN {pin14} not found in Cook County database")

    # ── Extract coordinates ───────────────────────────────────
    lat = (row.get("lat") or row.get("latitude") or
           row.get("centroid_lat") or row.get("y_coordinate"))
    lon = (row.get("lon") or row.get("longitude") or
           row.get("centroid_lon") or row.get("x_coordinate"))

    if not lat and "location" in row:
        loc = row["location"]
        if isinstance(loc, dict):
            lat = loc.get("latitude") or loc.get("lat")
            lon = loc.get("longitude") or loc.get("lon")

    if not lat or not lon:
        raise ValueError(
            f"PIN {pin14} found but coordinates missing. "
            f"Available fields: {list(row.keys())}"
        )

    lat_f = float(lat)
    lon_f = float(lon)

    address = (
        row.get("prop_address_full") or
        row.get("property_address") or
        row.get("address") or
        f"PIN {pin14}"
    )

    # ISV format: @lat,lon,0h,0p,1z
    isv_url = f"https://www.instantstreetview.com/@{lat_f},{lon_f},0h,0p,1z"

    return {
        "pin14":   pin14,
        "lat":     lat_f,
        "lon":     lon_f,
        "address": str(address),
        "isv_url": isv_url,
    }


# ─────────────────────────────────────────────────────────────
# PDF builder
# ─────────────────────────────────────────────────────────────

def build_combined_pdf(pages: list) -> bytes:
    """
    pages = [{ label: str, png_b64: str }, ...]
    Returns bytes of a multi-page PDF, one image per page.
    """
    from PIL import Image
    from reportlab.lib.colors import Color, HexColor
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as pdf_canvas

    buf = io.BytesIO()
    first_png  = base64.b64decode(pages[0]["png_b64"])
    first_img  = Image.open(io.BytesIO(first_png))
    iw, ih     = first_img.size
    c = pdf_canvas.Canvas(buf, pagesize=(iw, ih))

    for i, page in enumerate(pages):
        png_bytes = base64.b64decode(page["png_b64"])
        label     = page.get("label", "")
        img       = Image.open(io.BytesIO(png_bytes))
        pw, ph    = img.size
        c.setPageSize((pw, ph))

        BAR = 44
        # Dark header bar
        c.setFillColor(HexColor("#12100e"))
        c.rect(0, ph - BAR, pw, BAR, fill=1, stroke=0)
        # Gold accent line
        c.setFillColor(HexColor("#c8903a"))
        c.rect(0, ph - BAR - 1, pw, 1, fill=1, stroke=0)

        # Counter
        c.setFillColor(HexColor("#7a6a50"))
        c.setFont("Helvetica", 9)
        c.drawString(14, ph - BAR + 12, f"Page {i+1} of {len(pages)}")

        # Label
        c.setFillColor(HexColor("#ede0c8"))
        c.setFont("Helvetica-Bold", 13)
        c.drawString(14, ph - 26, label)

        # Photo (below bar)
        c.drawImage(
            ImageReader(io.BytesIO(png_bytes)),
            0, 0, width=pw, height=ph - BAR
        )

        if i < len(pages) - 1:
            c.showPage()

    c.save()
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/lookup-pin", methods=["POST"])
def lookup_pin_route():
    data    = request.get_json(silent=True) or {}
    raw_pin = data.get("pin", "").strip()
    if not raw_pin:
        return jsonify({"error": "No PIN provided"}), 400
    try:
        result = lookup_pin(normalize_pin(raw_pin))
        return jsonify(result)
    except Exception as e:
        print(f"[LOOKUP ERROR] {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 404


@app.route("/build-pdf", methods=["POST"])
def build_pdf():
    data  = request.get_json(silent=True) or {}
    pages = data.get("pages", [])
    if not pages:
        return jsonify({"error": "No pages provided"}), 400
    try:
        pdf_bytes = build_combined_pdf(pages)
        print(f"[PDF] Built {len(pages)} pages — {len(pdf_bytes):,} bytes")
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=False,
            download_name="streetview_properties.pdf",
        )
    except Exception as e:
        print(f"[PDF ERROR] {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{'─'*54}")
    print("  StreetShot — Cook County PIN → Street View PDF")
    print(f"  http://localhost:{PORT}")
    print(f"{'─'*54}\n")
    app.run(host="0.0.0.0", port=PORT, debug=False)
