# CampusRide — project documents

Every document for the mini-project, by the deliverable that asked for it.

## Part-1 — Requirements and design

| Document | File | Contents |
|---|---|---|
| Software Requirements Specification | [`CampusRide_SRS.docx`](CampusRide_SRS.docx) | IEEE format; FRs (§4) and NFRs (§5); security objectives and requirements (§5.1); UML use-case diagrams (§7.1); requirements traceability matrix (§8) |
| Software Architecture & Design | [`CampusRide_SAD.docx`](CampusRide_SAD.docx) | Component diagram (§3.3), architecture pattern and ADRs (§3.5), traceability (§3.8), security architecture with STRIDE (§3.9), four UML sequence diagrams (§4.2), API design (§4.3), error handling (§4.4) |
| Software Test Plan | [`CampusRide_Test_Plan.docx`](CampusRide_Test_Plan.docx) | IEEE format; features to be tested (§3), not tested (§4), approach (§5), security validation (§5.1), traceability (§13), 70-case catalogue (Appendix A) |

## Part-3 — Testing and quality assurance

| Report | File | Headline |
|---|---|---|
| Test Case Document (updated) | [`CampusRide_Test_Cases_v2.docx`](CampusRide_Test_Cases_v2.docx) | 88 cases — the original 70 plus 18 added for the Sprint-2 web UI |
| Unit Test Report | [`CampusRide_Unit_Test_Report.docx`](CampusRide_Unit_Test_Report.docx) | 139 tests, 139 passing, 0 failures |
| System Validation Report | [`CampusRide_System_Validation_Report.docx`](CampusRide_System_Validation_Report.docx) | 63 requirements: 36 validated, 8 partially validated, 19 deferred with reasons |
| Code Coverage Report | [`CampusRide_Code_Coverage_Report.docx`](CampusRide_Code_Coverage_Report.docx) | 100% statement coverage (target for CRS-NF-010 is 70%) |
| Branch Coverage Report | [`CampusRide_Branch_Coverage_Report.docx`](CampusRide_Branch_Coverage_Report.docx) | 100% branch coverage across 153 decision points |

## Cross-cutting

| Document | File | Why it exists |
|---|---|---|
| Deviations record | [`DEVIATIONS.md`](DEVIATIONS.md) | Part-2 (2.i) and Part-4 require every departure from the submitted SRS/SAD to be documented and explained at the demo |

## Regenerating the reports

The five Part-3 documents are generated from an actual test run — no figure in them is typed
by hand. After a code change, regenerate them with:

```bash
PYTHONPATH=src python scripts/generate_reports.py
```

That runs the full suite, measures statement and branch coverage, and rewrites the five
documents. Coverage in CI comes from `coverage.py` driven by `.coveragerc`; the offline
measurement in `scripts/measure_coverage.py` applies the same definitions for environments
without network access.
