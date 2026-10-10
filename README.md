# CampusRide - Campus Ride-Share Matching System

Match students who **offer** rides with students who **request** rides, based on pickup/drop locations, route,
timing and available seats. Includes messaging, ride history and ratings.

This repository holds the team's **core domain library** (pure Python, fully unit-tested) plus the project
documents. It implements the service layer from the SAD: auth, rides, matching, booking, messaging,
ratings/history, notifications and admin. API/UI layers sit on top of it later.

**Stack (same in SRS/SAD/Test Plan):** Python 3.12, FastAPI for the API layer, SQLAlchemy + PostgreSQL/PostGIS, pytest for tests, GitHub Actions for CI.

| Document | File |
|---|---|
| Software Requirements Specification | `docs/CampusRide_SRS.docx` |
| Software Architecture & Design | `docs/CampusRide_SAD.docx` |
| Software Test Plan | `docs/CampusRide_Test_Plan.docx` |

## Quick start

```bash
git clone https://github.com/<OWNER>/<REPO>.git      # clone - do NOT fork
cd <REPO>

python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

pip install -r requirements.txt
pytest                      # run all tests locally before every push
```

## Project layout

```
src/campusride/      models.py, errors.py (base)  + one module per feature
tests/               one test file per feature (test case IDs in comments, e.g. TC-Match-01)
.github/workflows/   ci.yml - runs pytest on every pull request and on main
starter_patches/     ready-made feature code, one patch per feature branch (see CONTRIBUTING.md)
docs/                SRS, SAD, Test Plan
```

## Team workflow (every feature, every time)

```
main
 |  git pull
 v
feature/<name>          (new branch, never work on main)
 |  add code + test
 v
pytest                  (must pass locally)
 |  git add . ; git commit ; git push -u origin feature/<name>
 v
Pull Request -> main
 |
 v
GitHub Actions: test    (must be green)
 |
 v
1 teammate approval
 |
 v
merge -> main
 |
 v
everyone: git checkout main ; git pull
```

Full rules and commands: see [CONTRIBUTING.md](CONTRIBUTING.md).

## Run the end-to-end demo (after `feature/end-to-end-demo` is merged)

```bash
PYTHONPATH=src python -m campusride
```
