# StreetShot — Cook County Property Street View PDF Generator

## What it does

1. Enter up to 5 Cook County 14-digit PINs (Subject + Comparables 1–4)
2. App looks up each PIN in the Cook County Assessor OData database
3. A direct InstantStreetView link is generated for each property
4. For each property, choose **Crop** or **User Upload**:
   - **Crop**: Open the ISV link, take a screenshot, paste/load it, drag to crop
   - **User Upload**: Upload any photo file from your device
5. Once photos are finalized, download a single combined PDF

---

## Run Locally

```bash
pip install -r requirements.txt
python app.py
```
Open: http://localhost:5000

---

## Deploy to Railway

1. Push this repo to GitHub
2. railway.app → New Project → Deploy from GitHub repo
3. Select repo — Dockerfile is auto-detected
4. Live in ~4 minutes

---

## File Structure

```
streetshot/
├── app.py               # Flask server (PIN lookup + PDF builder)
├── templates/
│   └── index.html       # Full UI (PIN entry, crop/upload, PDF)
├── Dockerfile           # Railway deployment
├── requirements.txt
└── .gitignore
```

---

## Data Source

Cook County Parcel Universe:
- Primary: `https://datacatalog.cookcountyil.gov/api/odata/v4/pabr-t5kh`
- Fallback: `https://datacatalog.cookcountyil.gov/resource/pabr-t5kh.json`

InstantStreetView: `https://www.instantstreetview.com/@{lat},{lon},0h,0p,1z`
