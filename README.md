# CampusRide - Campus Ride-Share Matching System

Match students who **offer** rides with students who **request** rides, based on pickup/drop locations, route,
timing and available seats. Includes messaging, ride history and ratings.

This repository holds the team's **core domain library** (pure Python, fully unit-tested) plus the project
documents. It implements the service layer from the SAD: auth, rides, matching, booking, messaging,
ratings/history, notifications and admin. API/UI layers sit on top of it later.

**Stack as built:** Python 3.12, Flask for the web UI, in-memory service objects, pytest for
tests, GitHub Actions for CI.

> The SRS/SAD specify FastAPI and PostgreSQL/PostGIS. Sprint-2 delivered a server-rendered
> Flask UI over the same service layer instead, so that the sprint produced a working product
> to demonstrate. Every departure from the submitted documents is recorded, with its reason and
> its effect on the requirements, in [`docs/DEVIATIONS.md`](docs/DEVIATIONS.md).

| Document | File |
|---|---|
| Software Requirements Specification | [`docs/CampusRide_SRS.docx`](docs/CampusRide_SRS.docx) |
| Software Architecture & Design | [`docs/CampusRide_SAD.docx`](docs/CampusRide_SAD.docx) |
| Software Test Plan | [`docs/CampusRide_Test_Plan.docx`](docs/CampusRide_Test_Plan.docx) |
| Test Cases (updated for the sprints) | [`docs/CampusRide_Test_Cases_v2.docx`](docs/CampusRide_Test_Cases_v2.docx) |
| Unit Test Report | [`docs/CampusRide_Unit_Test_Report.docx`](docs/CampusRide_Unit_Test_Report.docx) |
| System Validation Report | [`docs/CampusRide_System_Validation_Report.docx`](docs/CampusRide_System_Validation_Report.docx) |
| Code Coverage Report | [`docs/CampusRide_Code_Coverage_Report.docx`](docs/CampusRide_Code_Coverage_Report.docx) |
| Branch Coverage Report | [`docs/CampusRide_Branch_Coverage_Report.docx`](docs/CampusRide_Branch_Coverage_Report.docx) |
| Deviations from SRS/SAD | [`docs/DEVIATIONS.md`](docs/DEVIATIONS.md) |

An index of all of them, with what each one contains, is in [`docs/README.md`](docs/README.md).

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
src/campusride/      models.py, errors.py (base) + one module per feature
src/campusride/web/  Flask UI added in Sprint-2 (app.py, templates/, static/)
tests/               one test file per feature (test case IDs in comments, e.g. TC-Match-01)
scripts/             coverage measurement and report generation
.github/workflows/   ci.yml - runs pytest and coverage on every pull request and on main
docs/                SRS, SAD, Test Plan, Part-3 test reports, deviations record
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

## Run it

The web UI (this is what the Sprint-2 demonstration video shows):

```bash
PYTHONPATH=src python -m campusride.web
# then open http://127.0.0.1:5000
# demo admin: admin@example.edu / Admin#2026a
# any institutional address ending in .edu can register
```

The console walkthrough of the full rider journey:

```bash
PYTHONPATH=src python -m campusride
```

## Tests and coverage

```bash
pytest                                   # 139 tests
coverage run -m pytest && coverage report   # statement + branch coverage (.coveragerc)
PYTHONPATH=src python scripts/generate_reports.py   # regenerate the Part-3 reports
```

The suite runs on every pull request and on every push to `main`. Coverage is currently 100%
of statements and 100% of branches; `.coveragerc` fails the build below 70%, the target set by
CRS-NF-010.
