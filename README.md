# VERIFIED – Legal Metrology Compliance Scanner

> Automated compliance verification for packaged commodity labels under the  
> **Legal Metrology (Packaged Commodities) Rules, 2011 (PCR-2011)**  
> and the **2017 Country of Origin Amendment**.

---

## What It Does

VERIFIED scans product labels — via pasted text, e-commerce product URLs, or uploaded label photos — and checks them against all 8 mandatory fields required by Indian law (PCR-2011, Rule 6). It produces a compliance score, field-by-field results with legal references, downloadable reports, and a regulator dashboard.

---

## Features

### 🔍 Three Scan Modes
| Mode | How it works |
|------|-------------|
| **Paste Text** | Paste raw label text directly into the scanner |
| **Product URL** | Enter any e-commerce URL — the scanner fetches and analyses the page |
| **Label Image** | Upload a photo of the product label — multi-pass OCR extracts and structures the text |

### 🌐 E-Commerce URL Intelligence (Product URL Mode)
- **Supported platforms:** Amazon India, Flipkart, JioMart, Meesho, Myntra, and any generic URL
- **Static + browser fallback:** Tries fast HTTP fetch first; falls back to Playwright/Chromium headless browser for JS-heavy pages
- **OCR on product images:** Automatically downloads and runs OCR on packaging images (up to 4)
- **Multi-pass image preprocessing:** Upscale → contrast enhance → bottom crop → mid crop — 4 variants per image
- **Structured data extraction:** JSON-LD, OpenGraph, and platform-specific JSON blob parsing
- **Pre-OCR web entity extraction:** Extracts compliance fields from webpage text before even running OCR, then merges with OCR results for maximum accuracy
- **Real-time progress steps:** Live step-by-step progress shown in the UI

### 📸 Label Image OCR
- **Multi-pass preprocessing:** 4 image variants (full, contrast-enhanced, bottom-crop 45%, mid-crop 40%)
- **Layout-preserving OCR:** Groups text into lines by Y-position (not flat space-joined) so multi-line patterns like `Manufacturer:\nAddress:` are correctly parsed
- **EasyOCR** (primary) with pytesseract fallback
- **Auto-structured output:** OCR → entity extraction → `Field: Value` compliance-ready format
- **Drag-and-drop** image upload with thumbnail preview

### ✅ PCR-2011 Compliance Engine
Checks all **8 mandatory fields** defined in Rule 6(1):

| Field | Legal Reference | Description |
|-------|----------------|-------------|
| **F01** | Rule 6(1)(a) | Manufacturer / Importer Name & Address |
| **F02** | Rule 6(1)(b) | Net Quantity / Net Weight / Net Volume |
| **F03** | Rule 6(1)(c) | Month & Year of Manufacture / Packing |
| **F04** | Rule 6(1)(d) | Best Before / Expiry Date |
| **F05** | Rule 6(1)(e) | Maximum Retail Price (MRP) |
| **F06** | Rule 6(1)(f) | Consumer Care / Grievance Contact |
| **F07** | Rule 6(1)(g) + 2017 Amdt. | Country of Origin |
| **F08** | FSS Act 2006 + LMPCR 2011 | FSSAI Licence / Importer Registration |

- **Compliance score:** 0–100 with PASS / PARTIAL / FAIL verdict
- **Address-to-country inference:** Automatically infers Country of Origin from manufacturer/importer address (e.g. "Himachal Pradesh" → India, "Shanghai" → China) — covers all 28 states, 8 UTs, 50+ cities, and 25+ countries
- **Importer phrase detection:** Handles all Indian label variants: `Imported in India by`, `Imported & Marketed by`, `Mkt. by`, `Mfd. in Italy by`, etc.

### 📊 Regulator Dashboard
- Login-protected enforcement portal
- Summary metrics: total scans, pass/fail counts, average compliance score
- Historical scan table with search and filter
- Full field-level results for any past scan

### 🔡 Font Size Analysis
- Upload label image + provide package dimensions
- Checks minimum character height against PCR-2011 requirements (based on package area)
- Returns per-word measurements in mm and compliance verdict

### 📄 Reports
- **Download .txt** — plain text compliance report
- **Download PDF** — formatted PDF via ReportLab
- **Copy link** — shareable scan URL

---

## Tech Stack
|-------|-----------|
| Backend | Python 3.11+ · FastAPI · SQLAlchemy · SQLite |
| Frontend | React 18 · Vite · Tailwind CSS v3 |

---

## Tech Stack

### Backend
| Component | Technology |
|-----------|-----------|
| Framework | FastAPI + Uvicorn |
| Database | SQLite + SQLAlchemy ORM |
| Authentication | JWT (python-jose) + bcrypt |
| OCR (primary) | EasyOCR (PyTorch-based, no Tesseract required) |
| OCR (fallback) | pytesseract (optional) |
| Image processing | Pillow + OpenCV (headless) |
| HTML scraping | BeautifulSoup4 + lxml |
| HTTP client | httpx[http2] |
| Browser automation | Playwright + Chromium (for JS-heavy pages) |
| PDF generation | ReportLab |
| Migrations | Alembic |

### Frontend
| Component | Technology |
|-----------|-----------|
| Framework | React 18 + Vite 5 |
| Styling | Tailwind CSS v3 |
| Routing | React Router v6 |
| HTTP client | Axios |
| Charts | Recharts |
| PDF (client-side) | jsPDF |

---

## Getting Started

### Prerequisites
- Python 3.11+
- Node.js 18+

### 1. Backend Setup

```bash
cd backend

# Create and activate virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser (for JS-heavy e-commerce URLs)
playwright install chromium

# Start the server
uvicorn main:app --reload --port 8000
```

> **First run:** EasyOCR downloads ~100 MB of model weights automatically. Subsequent runs load from cache.

| URL | Description |
|-----|-------------|
| http://localhost:8000 | API root |
| http://localhost:8000/docs | Swagger / OpenAPI docs |

### 2. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

App → http://localhost:5173

---

## Default Credentials (Dashboard)

| Field | Value |
|-------|-------|
| **Email** | `admin@verified.in` |
| **Password** | `Admin@123` |

> The admin account is auto-created on first backend startup.  
> To create additional accounts: `POST /api/auth/register`

---

## API Endpoints

### Authentication `/api/auth`
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/register` | Create a new regulator account |
| POST | `/api/auth/login` | Login — returns JWT access token |

### Compliance Scan `/api`
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/scan` | Run compliance check on text |
| GET | `/api/scan/{id}` | Retrieve a past scan by ID |
| GET | `/api/scan/{id}/report.txt` | Download plain-text compliance report |
| GET | `/api/scan/{id}/report.pdf` | Download PDF compliance report |
| POST | `/api/bulk` | Batch scan via CSV upload (max 200 rows) |
| POST | `/api/ocr` | Upload label image → structured compliance text |

### URL Scanner `/api/url-scan`
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/url-scan/start` | Start async URL scan job |
| GET | `/api/url-scan/status/{id}` | Poll scan status + live progress steps |
| GET | `/api/url-scan/result/{id}` | Full result with images + OCR data |
| POST | `/api/url-scan/{id}/manual-ocr` | Run OCR on selected images |

### Dashboard `/api/dashboard`
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/dashboard/summary` | Aggregate stats (totals, pass rate, avg score) |
| GET | `/api/dashboard/recent` | Recent scans list |
| GET | `/api/dashboard/scans` | All scans (paginated, filterable) |

### Font Analysis `/api/font`
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/font/analyse` | Font size compliance check from label image |

---

## Project Structure

```
VERIFIED-Legal-Metrology-Compliance-Scanner/
├── backend/
│   ├── main.py                      # FastAPI app + OCR/URL endpoints
│   ├── config.py                    # App settings (JWT, DB URL)
│   ├── database.py                  # SQLAlchemy engine + session
│   ├── models.py                    # ORM: Scan, FieldResult, Violation, User
│   ├── schemas.py                   # Pydantic request/response schemas
│   ├── requirements.txt
│   │
│   ├── auth/                        # JWT authentication
│   ├── scan/                        # Text compliance engine + rules.json
│   ├── url_scanner/                 # E-commerce URL intelligence
│   │   ├── adapters/                # Platform extractors
│   │   │   ├── amazon.py
│   │   │   ├── flipkart.py
│   │   │   ├── jiomart.py
│   │   │   ├── meesho.py
│   │   │   ├── myntra.py
│   │   │   └── generic.py
│   │   └── intelligence/
│   │       └── entity_extractor.py  # NLP + country-of-origin inference
│   ├── ocr/                         # Label image OCR service
│   ├── font_analysis/               # Font size compliance
│   ├── dashboard/                   # Regulator dashboard API
│   └── report/                      # PDF generation (ReportLab)
│
└── frontend/
    └── src/
        ├── pages/
        │   ├── Home.jsx             # Landing page
        │   ├── Check.jsx            # Scanner (Paste Text / URL / Image)
        │   ├── Result.jsx           # Compliance result + field breakdown
        │   ├── Dashboard.jsx        # Regulator dashboard
        │   ├── Login.jsx            # Regulator login
        │   ├── FontAnalysis.jsx     # Font size analysis tool
        │   └── Rules.jsx            # PCR-2011 rules reference
        └── components/
            ├── FieldCard.jsx        # Field result card
            ├── StampBadge.jsx       # PASS / PARTIAL / FAIL stamp
            └── StatusBadge.jsx
```

---

## How the URL Scanner Works

```
URL Input
  │
  ├─ 1. Platform Detection     → Amazon / Flipkart / JioMart / Meesho / Myntra / Generic
  ├─ 2. Page Fetch (HTTP)      → Stealth headers, HTTP/2
  ├─ 3. Adapter Extraction     → Platform JSON blobs, structured fields
  ├─ 4. Image Collection       → Score & rank packaging images by CDN pattern
  ├─ 5. Pre-OCR Web Extraction → Entity extraction from page text
  ├─ 6. Browser Fallback       → Playwright/Chromium if needed
  ├─ 7. Image OCR (parallel)   → 4 images × 4 preprocessing variants
  ├─ 8. Entity Merge           → Web baseline + OCR override
  ├─ 9. Data Fusion            → Normalised unified model
  ├─ 10. Compliance Text Build  → Structured "Field: Value" text
  └─ 11. Result                 → Score, 8 fields, evidence, violations
```

---

## Legal References

| Rule | Description |
|------|-------------|
| LM(PC)R 2011, Rule 6(1) | Mandatory declarations on packages |
| LM(PC)R 2017 Amendment | Country of Origin requirement |
| FSS Act 2006 | FSSAI licence requirement |
| LM(PC)R 2011, Rule 18 | Minimum font size for declarations |

---

## Team

| Ref | Name |
|-----|------|
| VF-01 | Kirtan Thakkar |
| VF-02 | Vyas Vraj |
| VF-03 | Om Bhoi |
| VF-04 | Suthar Darshan |
| VF-05 | Patel Pal |
| VF-06 | Riddhi Parmar |

---

> **Legal authority:** Legal Metrology (Packaged Commodities) Rules, 2011  
> **Built for:** Smart India Hackathon 2026
