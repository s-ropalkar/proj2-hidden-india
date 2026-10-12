# Hidden India Explorer

A full-stack heritage marketplace that connects **explorers**, **artisans**, and **curators** across India. Discover regional crafts on an interactive map, personalize your feed with a cultural-interest quiz, book workshops, and shop authentic artifacts—while artisans manage their studio and admins verify applications.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | React 19, TypeScript, Vite 6 |
| **Styling** | Tailwind CSS v4, Lucide React icons |
| **Auth (client)** | React Context, JWT in `localStorage`, optional Google OAuth |
| **Backend** | Python 3, Flask 3, Flask-CORS |
| **Database** | MongoDB (`hidden_india`) via PyMongo |
| **Auth (server)** | PyJWT, bcrypt, role-based access (`user` / `artisan` / `admin`) |
| **Uploads** | Local `backend/uploads/` (portfolio, documents) |
| **Launcher** | Node.js `scripts/start.mjs` — one command starts API + UI + seed |

---

## Features

### Explorer (User)

- Register, login, forgot/reset password, optional Google Sign-In
- **Artistic Echoes Quiz** — captures interests, crafts, regions, budget, and workshop preferences
- **Personalized dashboard** — quiz-based welcome, recommended products & workshops, regional explore cards, full catalog with state/craft filters
- **Explore Map** — India states map with pins, zoom, craft filters, nearby artisans, region detail panels
- **Workshops** — browse, register (seat limits + duplicate checks), booking confirmation
- **Products** — view details, save to wishlist, buy now (orders)
- **Profile** — personal info, saved artifacts, orders, workshop bookings, notification center
- **Artisan application** — apply to become a verified artisan with portfolio upload
- Bottom navigation: Home, Explore, Saved, Profile

### Artisan

- Application workflow with **state–craft validation** (crafts must match the selected state catalog)
- Application status page (pending / approved / rejected) with curator feedback
- **Artisan dashboard** — manage products, workshops, and customer registrations
- Approve or update workshop bookings → persisted in DB + customer notification
- Studio profile, portfolio uploads, analytics (views, orders, registrations)

### Admin (Supervisor / Curator)

- Review artisan applications (approve → promotes user to `artisan` role + notification)
- **Platform analytics** — most explored state/region, top categories, workshop registrations, approved artisans, user counts
- Manage user and artisan status (active / blocked / suspended)
- Pending applications queue with curator notes

---

## Project Structure

```
hidden-india-explorer/
├── README.md
├── package.json                 # npm start — launches full stack
├── scripts/
│   └── start.mjs                # venv setup, seed, Flask + Vite
├── backend/
│   ├── app.py                   # Flask app factory
│   ├── routes.py                # REST API (~50 endpoints)
│   ├── auth.py                  # JWT, bcrypt, decorators
│   ├── db.py                    # MongoDB connection + indexes
│   ├── services.py              # Recommendations, quiz processing, hidden gems
│   ├── seed.py                  # Database seeding
│   ├── google_images_catalog.py # Product/workshop images from folder structure
│   ├── artisan_images_catalog.py# Artisan portraits from google-images/artisans
│   ├── region_crafts.py         # State–craft validation rules
│   ├── india_data.py            # State coords, zones, catalog metadata
│   ├── state_artisans.py        # Regional artisan name roster
│   ├── requirements.txt
│   ├── .env.example
│   └── uploads/                 # Runtime file uploads
└── final_hidden_india/          # React frontend
    ├── public/images/           # Static assets (map, logo, catalog, artisans)
    ├── google-images/           # Source image folders for seeding
    │   ├── artisans/            # Portrait folders per state → DB artisans
    │   └── google-images/       # State/craft product & workshop images
    └── src/
        ├── App.tsx              # Screen router (ScreenId, no React Router)
        ├── api.ts               # Typed HTTP client
        ├── context/AuthContext.tsx
        ├── lib/utils.ts         # Images, map pins, craft filters
        └── components/          # UI screens (dashboard, map, admin, etc.)
```

---

## Prerequisites

- **Node.js** 18+ and npm
- **Python** 3.10+
- **MongoDB** running locally or Atlas URI  
  Default: `mongodb://localhost:27017/hidden_india`

---

## Quick Start

### 1. Clone and install

```bash
cd final_hidden_india   # project root (repo folder name may vary)
npm start
```

`npm start` will:

1. Install frontend dependencies (if needed)
2. Create a Python venv and install backend deps
3. Copy `backend/.env.example` → `backend/.env` if missing
4. Seed the catalog from `google-images/` folders
5. Start Flask on **port 5000** and Vite on **port 3000**

### 2. Open the app

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:5000/api/health |

If port 3000 is busy, Vite may use **3001** — check the terminal output.

### 3. Demo accounts (after seed)

| Role | Email | Password |
|------|-------|----------|
| Admin | `admin@hiddenindia.in` | `Admin@123` |
| Explorer | `aryan@explorer.in` | `Explorer@123` |

---

## Manual Setup (optional)

### Backend only

```bash
cd backend
python -m venv venv
# Windows
venv\Scripts\pip install -r requirements.txt
copy .env.example .env
venv\Scripts\python seed.py
venv\Scripts\python app.py
```

### Frontend only

```bash
cd final_hidden_india
npm install
cp .env.example .env    # optional — Google OAuth
npm run dev
```

### Re-seed / refresh catalog

```bash
cd backend
venv\Scripts\python seed.py --force    # Windows
# python seed.py --force               # macOS/Linux
```

Stop the dev server before force-seeding if you see Windows file-lock errors on `public/images/`.

---

## Environment Variables

### Backend (`backend/.env`)

| Variable | Description |
|----------|-------------|
| `MONGO_URI` | MongoDB connection string |
| `JWT_SECRET` | Secret for signing access tokens |
| `JWT_ACCESS_HOURS` | Token lifetime (default 24) |
| `PORT` | Flask port (default 5000) |
| `FLASK_DEBUG` | `1` for dev reload |
| `CORS_ORIGINS` | Allowed frontend origins |
| `GOOGLE_CLIENT_ID` | Optional — must match frontend for Google login |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Default admin created on seed |

### Frontend (`final_hidden_india/.env`)

| Variable | Description |
|----------|-------------|
| `VITE_GOOGLE_CLIENT_ID` | Optional Google OAuth client ID |

API calls use the Vite dev proxy: `/api/*` → `http://localhost:5000`.

---

## Data & Image Catalog

The database is populated from local image folders—not hardcoded lists.

### Products & workshops

Path: `final_hidden_india/google-images/google-images/{State}/{CraftFolder}/`

- Each product image → one catalog product
- `Workshops_*` folders → workshop entries with thumbnails
- Images are copied to `public/images/catalog/` and served by Vite

### Artisan portraits

Path: `final_hidden_india/google-images/artisans/{state_folder}/`

- **Only artisans with images in this folder** are seeded into MongoDB
- One artisan per portrait image; avatars served from `public/images/artisans/`
- Products in the same state are linked to those artisans

After adding or changing images, run `python seed.py --force`.

---

## API Overview

Base URL: `http://localhost:5000/api`

| Area | Examples |
|------|----------|
| **Auth** | `POST /auth/register`, `/login`, `/google`, `GET /auth/me` |
| **User** | `POST /users/me/quiz`, `GET /users/me/recommendations`, `/saved`, `/orders`, `/notifications` |
| **Catalog** | `GET /products`, `/workshops`, `/artisans`, `/map/regions`, `/regions/:state` |
| **Workshops** | `POST /workshops/:id/register` |
| **Artisan** | `POST /artisan/apply`, `GET /artisan/profile`, CRUD `/artisan/products`, `/artisan/workshops` |
| **Admin** | `GET /admin/analytics`, `/admin/applications`, `PATCH /admin/applications/:id` |
| **Health** | `GET /health` |

All protected routes expect `Authorization: Bearer <token>`.

---

## Architecture

```
Browser (React :3000)
    │  fetch /api/*  →  Vite proxy
    ▼
Flask API (:5000)
    │  @login_required / @role_required
    ▼
MongoDB (hidden_india)
```

**Navigation:** `App.tsx` uses a `ScreenId` union and `useState` (no React Router). Deep links to profile tabs use `localStorage` (e.g. `profileTab: Notifications`).

**Key collections:** `users`, `artisans`, `products`, `workshops`, `orders`, `workshop_registrations`, `notifications`, `artisan_applications`, `regions`, `saved_items`.

---

## Scripts

| Command | Description |
|---------|-------------|
| `npm start` | Full stack (backend + frontend + seed) |
| `npm run backend` | Flask API only (Windows path) |
| `npm run frontend` | Vite dev server only |
| `npm run seed` | Run seed script only |
| `cd final_hidden_india && npm run build` | Production frontend build |
| `cd final_hidden_india && npm run lint` | TypeScript check |

---

## License

Apache-2.0 (see SPDX headers in source files).
#   h i d d e n _ i n d i a  
 #   h i d d e n _ i n d i a  
 #   p r o j 2 - h i d d e n - i n d i a  
 