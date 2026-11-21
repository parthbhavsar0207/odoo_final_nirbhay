# Champions Club - Sports Club Management Platform

A unified sports club management system built with **Django 5.2**, **PostgreSQL 16**, and server-rendered **Django Templates** enhanced with **HTMX** and **Alpine.js** for lightweight interactions.

---

## Team Roles & Ownership

| Team Member | Role & Ownership | Scope & Deliverables |
|---|---|---|
| **Nayan** | Backend: Memberships & Bookings | Owns `club/` app: `Member`, `MembershipPlan`, `Court`, `Booking`, `BookingParticipant`, and PostgreSQL GiST overlap constraints. |
| **Utkarsh** | Backend: Shop, Bar & Sales | Owns `commerce/` app: `Product`, `Sale`, `SaleItem`, atomic inventory decrement, and membership tier discounts. References Nayan's `Member`. |
| **Pratik** | Frontend & Styling | Owns `frontend/` app: templates (`frontend/templates/`), static assets (`frontend/static/`), responsive layouts, server-rendered views, HTMX/Alpine enhancements. Zero business logic in templates. |
| **Parth** | Integration, Setup & Delivery | Project scaffolding, settings, PostgreSQL 16 Docker Compose, migration coordination, seed data, and demo delivery. |

---

## Technology Stack

- **Runtime:** Python 3.12
- **Web Framework:** Django 5.2
- **Database:** PostgreSQL 16 (via Docker Compose on port `5433`)
- **Database Driver:** `psycopg` (binary)
- **Database Extensions:** `btree_gist` (enabled via Django migration `club/migrations/0001_initial.py`)
- **Timezone:** `Asia/Kolkata`
- **Frontend:** Django Templates with HTMX and Alpine.js (no separate React/Vite build step)

---

## Project Structure

```text
├── manage.py                     # Django administrative utility
├── config/                       # Project configuration & settings
│   ├── __init__.py
│   ├── asgi.py
│   ├── settings.py               # PostgreSQL (port 5433), Asia/Kolkata timezone, apps
│   ├── urls.py                   # Root URLs: dashboard, club, commerce
│   └── wsgi.py
├── club/                         # Nayan's membership, court & booking app
│   ├── apps.py
│   ├── models.py                 # Member, MembershipPlan, Court, Booking
│   ├── views.py                  # Member list, Booking list
│   ├── urls.py
│   └── migrations/
│       ├── __init__.py
│       └── 0001_initial.py       # Enables btree_gist extension (no CreateModel)
├── commerce/                     # Utkarsh's products, stock & sales app
│   ├── apps.py
│   ├── models.py                 # Product, Sale, SaleItem (references Member)
│   ├── views.py                  # Shop & Bar catalog
│   ├── urls.py
│   └── migrations/
├── frontend/                     # Pratik's dedicated frontend & UI app
│   ├── apps.py
│   ├── urls.py                   # Frontend routing (dashboard overview)
│   ├── views.py                  # Dashboard presentation & live KPI metrics
│   ├── templates/                # Server-rendered templates
│   │   ├── base.html             # Main layout with navigation
│   │   ├── dashboard/
│   │   │   └── index.html        # Landing page & integration checklist
│   │   ├── club/
│   │   │   ├── members.html      # Members directory
│   │   │   ├── member_form.html  # Member creation / edit form
│   │   │   ├── bookings.html     # Bookings list & schedule
│   │   │   ├── booking_form.html # Court booking form
│   │   │   ├── booking_detail.html # Booking detail & roster
│   │   │   └── public_availability.html # Live availability matrix
│   │   └── commerce/
│   │       └── index.html        # Shop & Bar catalog
│   └── static/                   # Static assets
│       ├── css/
│       │   └── style.css         # Modernist design system styles
│       └── js/
│           └── main.js           # HTMX CSRF helper & client scripts
├── scripts/                      # Developer utility scripts
│   ├── setup_dev.ps1             # Automated Windows PowerShell setup
│   └── wait_for_db.py            # PostgreSQL connectivity checker
├── docker-compose.yml            # PostgreSQL 16 container definition (port 5433:5432)
├── requirements.txt              # Pinned Python dependencies
├── .env.example                  # Safe configuration defaults (DB_PORT=5433)
├── .gitignore                    # Secrets, venv, and cache exclusions
├── README.md                     # Setup and running instructions
└── INTEGRATION_CONTRACT.md       # Shared schema, rules, and handoffs
```

---

## Local Setup & Quickstart (Windows PowerShell)

Follow these step-by-step instructions in **Windows PowerShell**:

### 1. Prerequisites
- **Python 3.12** installed and on your system `PATH`
- **Docker Desktop** installed and running (for PostgreSQL 16)
- **Git**

### 2. Set Up Virtual Environment & Dependencies
In your PowerShell terminal:

```powershell
# Create Python 3.12 virtual environment
python -m venv .venv

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Upgrade pip and install project dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 3. Create Local Environment File
Copy the example configuration file to create your local `.env`:

```powershell
Copy-Item .env.example .env
```

The default values connect to the PostgreSQL Docker container on port **5433**:
```env
DEBUG=True
SECRET_KEY=django-insecure-champions-club-scaffold-change-in-production
ALLOWED_HOSTS=localhost,127.0.0.1
DB_NAME=champions_club
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=127.0.0.1
DB_PORT=5433
TIME_ZONE=Asia/Kolkata
```

### 4. Start the Database
Start the PostgreSQL 16 container using Docker Compose:

```powershell
docker compose up -d
```

Verify that the container is healthy:
```powershell
docker compose ps
```

### 5. Apply Database Migrations
Run Django migrations to apply core tables and enable the `btree_gist` extension:

```powershell
python manage.py migrate
```

### 6. Start the Development Server
Launch the Django server:

```powershell
python manage.py runserver
```

Open your browser and navigate to:
**[http://127.0.0.1:8000/](http://127.0.0.1:8000/)**

You will see the **Champions Club Control Panel** with navigation for **Members**, **Bookings**, and **Shop/Bar**.

---

## Key Integration Guidelines

1. **Single Member Model:**
   `commerce.Sale` must reference Nayan's `club.Member` via ForeignKey. Never create a duplicate customer or member table.
2. **PostgreSQL Overlap Prevention:**
   The `btree_gist` extension is enabled via `club/migrations/0001_initial.py`. Nayan will implement the GiST exclusion constraint on `court_id` and timerange in the model migration.
3. **Migration Ordering:**
   Parth coordinates migration order. Any `commerce` migration that adds a ForeignKey to `club.Member` must explicitly include `('club', '<migration_name>')` in its `dependencies` list.
4. **No Business Rules in Templates:**
   Booking limits (max 2 per day), slot validations (60 min slots on 30 min boundaries), tier discounts, and stock changes must execute strictly in backend code or database constraints.
5. **Frontend Handoffs:**
   Before Pratik connects a template to a view, backend owners must provide:
   - Named URL pattern (e.g. `'club:member_list'`)
   - Template file path (e.g. `'club/members.html'`)
   - Context dictionary keys (e.g. `'members'`, `'page_title'`)
   - Form field names for POST submissions
