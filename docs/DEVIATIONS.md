# Deviations from the submitted SRS / SAD / Test Plan

Part-2 (item 2.i) requires that any deviation from the submitted design documents is
recorded and explained at the final demo. This file is that record. Each entry states what
the documents promised, what was actually built, why, and what it affects.

The documents themselves were **not** rewritten after submission — they stand as the
Part-1 deliverable. This file is the delta, and the System Validation Report states the
requirement-by-requirement effect.

| ID | Area | Documented | Delivered | Impact |
|---|---|---|---|---|
| DEV-01 | Presentation layer | FastAPI REST API + separate front end | Server-rendered **Flask** web UI over the same service layer | Medium |
| DEV-02 | Persistence | SQLAlchemy + PostgreSQL/PostGIS | In-memory Python objects | Medium |
| DEV-03 | Geospatial matching | PostGIS distance queries | Equirectangular projection in `geo.py` | Low |
| DEV-04 | Email / OTP delivery | SMTP with MailHog stub | OTP shown on screen in demo mode | Low |
| DEV-05 | Scope | 8 feature areas fully delivered | 6 requirements carried to the backlog | Low |

---

## DEV-01 — Flask web UI instead of a FastAPI REST API

**Documented.** The SAD (§3.6, §4.3) specifies FastAPI with a documented OpenAPI contract and
an endpoint catalogue; the SRS lists FastAPI in the operating environment.

**Delivered.** `src/campusride/web/` is a Flask application that renders HTML pages server-side
(Jinja templates in `web/templates/`). There is no JSON API and no OpenAPI document.

**Why.** Sprint-1 delivered the service layer — all business rules live in `auth.py`,
`rides.py`, `matching.py`, `booking.py`, `messaging.py`, `ratings.py`, `notifications.py` and
`admin.py`, independent of any transport. Sprint-2 had to produce a *working product* for the
demonstration video. A REST API alone demonstrates nothing a marker can watch, and building an
API plus a separate front end inside one sprint would have meant shipping both half-finished.
A server-rendered UI over the existing services gave a complete, demonstrable product within
the sprint.

**What it affects.**

- The service layer is untouched by this decision: `web/app.py` holds no business rules, only
  parsing, session handling and template rendering. The layered architecture in SAD §3.5 is
  preserved; only the outermost adapter differs.
- The endpoint catalogue in SAD §4.3 maps to routes rather than JSON endpoints. The mapping is
  one-to-one in behaviour: `POST /requests` became `POST /requests/new`,
  `PUT /bookings/{id}/accept` became `POST /bookings/<id>/accept`, and so on.
- **CRS-NF-010** is only partly met: unit-test coverage exceeds the target, but no OpenAPI
  specification is published because there is no API to describe.
- Test cases needed to be added. The Part-1 Test Plan assumed an API under test, so it had no
  cases for CSRF tokens, HTML output escaping, session cookies or server-side page guards.
  **TC-Web-01 … TC-Web-18** were written in Part-3 to cover the interface that was actually
  built; they are listed in `CampusRide_Test_Cases_v2.docx`.
- A JSON API can be added later over the same services without touching business logic; this
  deviation does not block it.

## DEV-02 — In-memory state instead of PostgreSQL

**Documented.** SAD §3.6 and §4.1.1 specify SQLAlchemy models on PostgreSQL with PostGIS.

**Delivered.** Each service keeps its data in Python dictionaries; `AppState` in `web/app.py`
holds one instance of each service for the process. Data resets when the server restarts.

**Why.** The data design in SAD §4.1.1 was implemented as dataclasses with the same fields,
keys and status values, so the model is real even though the store is not. Adding a database
would have consumed Sprint-2 without changing any behaviour the demonstration shows, and the
repository stays runnable with `pip install -r requirements.txt` and nothing else — no server,
no migration, no connection string. The team judged a demonstrable product the higher value.

**What it affects.**

- **CRS-NF-005** (backup/restore) and **CRS-NF-011** (retention and archival) cannot be
  validated; both are recorded as Deferred in the System Validation Report.
- **CRS-SR-008** (encryption at rest) is likewise a property of a database that does not exist
  here.
- Concurrency is still exercised: `BookingService` guards seat changes with a lock, and
  TC-Match-06 fires 100 simultaneous acceptances against a 3-seat offer to prove no
  overbooking. That test would need re-running against row-level locking once a database is
  introduced.
- Migration path: the dataclasses in `models.py` map field-for-field onto the SAD's table
  design, so moving to SQLAlchemy is a repository-layer change behind the existing service
  interfaces.

## DEV-03 — Local projection instead of PostGIS for distance

**Documented.** SAD §4.1.2 assumes PostGIS geography operations for distance and
point-to-route projection.

**Delivered.** `geo.py` projects latitude/longitude onto a local plane (equirectangular,
anchored at the route's first point) and computes distance and along-route position in that
plane.

**Why.** It follows from DEV-02 — without PostGIS the projection has to live in Python. Over a
campus-sized service area (a few kilometres) the error from the flat-earth approximation is
well below the matching radius, so ranking is unaffected.

**What it affects.** Accuracy only, and not materially at this scale. The matching rules,
scoring formula and weights are exactly as specified in SAD §4.1.2; TC-Match-03 pins the score
formula against fixed inputs so a future swap to PostGIS can be checked against the same
expectations.

## DEV-04 — OTP shown on screen instead of emailed

**Documented.** The Test Plan assumes an email stub (MailHog) that the tester reads the OTP
from.

**Delivered.** In demo mode (`SHOW_OTP = True`) the verification code is flashed on the page
after registration. Production mode (`SHOW_OTP = False`) does not reveal it.

**Why.** No mail server is available in the demo environment or in CI, and registration is the
entry point to every other flow — without a visible code the product cannot be demonstrated at
all.

**What it affects.**

- The OTP rules themselves are unchanged and fully tested: single use, expiry, wrong-code
  rejection (TC-Auth-02).
- The configuration flag is itself tested — **TC-Web-18** asserts that production mode shows no
  code on screen and seeds no demo administrator, so the demo convenience cannot reach a real
  deployment unnoticed.
- **CRS-F-004** (password reset by email link) is not implemented, for the same reason.

## DEV-05 — Requirements carried to the backlog

Six requirements in the SRS were not built within the two sprints. They are listed here rather
than quietly dropped, and each appears as Deferred in the System Validation Report.

| Requirement | Description | Reason |
|---|---|---|
| CRS-F-004 | Password reset by email link | No mail transport (see DEV-04) |
| CRS-F-005 | Profile editing and phone-visibility rules | Not reached in either sprint |
| CRS-F-011 | Edit or cancel a posted offer | Not reached in Sprint-2 |
| CRS-F-013 | Edit a posted request | Not reached in Sprint-2 |
| CRS-F-025 | Driver-initiated invitations to riders | Not reached in Sprint-2 |
| CRS-F-036 | Trusted-contact share link | Not reached in Sprint-2 |

Cancelling a *booking* (CRS-F-033) is implemented and tested; it is editing the **offer** and
**request** records that was deferred.

---

## Effect on the Test Plan

The Test Plan was not rewritten. The changes it needed are recorded in
`CampusRide_Test_Cases_v2.docx`:

1. **18 cases added** (TC-Web-01 … TC-Web-18) for the interface built in Sprint-2.
2. **9 cases strengthened** with negative and boundary tests during Part-3 (TC-Auth-02,
   TC-Book-01/02/04/06, TC-Ride-06, TC-Match-03/05, TC-Hist-01).
3. **Appendix C** (automated test mapping) is superseded by Section 3 of the updated test case
   document, which lists all 88 cases and the test functions that execute them.

## Summary

Every deviation moves work *from* infrastructure *to* demonstrable product behaviour. No
business rule in the SRS was weakened or reinterpreted to make a test pass: the rules in the
service layer match the SRS, and the requirements that could not be met are recorded as
Deferred with the reason, rather than being marked complete.
