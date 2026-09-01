# VERIFIED — Legal Metrology Compliance Scanner

Automated compliance checking for packaged commodity labels against the
**Legal Metrology (Packaged Commodities) Rules, 2011**.

## Tech Stack
| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+ · FastAPI · SQLAlchemy · SQLite |
| Frontend | React 18 · Vite · Tailwind CSS v3 |

---

## Getting Started

### Backend (FastAPI)

```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate — Windows
venv\Scripts\activate

# Activate — Mac / Linux
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start server
uvicorn main:app --reload --port 8000
```

API → http://localhost:8000  
Swagger docs → http://localhost:8000/docs

---

### Frontend (React + Vite)

```bash
cd frontend
npm install
npm run dev
```

App → http://localhost:5173

---

## Project Structure

```
backend/
  main.py         FastAPI entry point
  config.py       Settings
  database.py     SQLAlchemy + SQLite
  models.py       ORM models
  auth/           JWT auth router + helpers
  scan/           Compliance engine + scan routes
  dashboard/      Analytics endpoints
  requirements.txt

frontend/
  src/
    components/   SiteHeader, SiteFooter, StatusBadge
    pages/        Home, Check, Login, Dashboard, Result
    api/          Axios client
  tailwind.config.js
  vite.config.js
```

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

> Legal authority: Legal Metrology (Packaged Commodities) Rules, 2011
> SIH 2026
