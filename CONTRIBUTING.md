# Contributing to CampusRide

These rules are enforced by GitHub branch protection on `main` and by CI.

## The 10 team rules

| # | Rule | How we do it |
|---|---|---|
| 1 | One common repository | `https://github.com/<OWNER>/<REPO>` - **clone**, don't fork |
| 2 | Everyone is a collaborator | Owner: Settings > Collaborators > Add people (Write access) |
| 3 | CI runs tests automatically | `.github/workflows/ci.yml` - job name **`test`** |
| 4 | `main` is protected | Branch protection: PR required, status check `test` required, no force pushes |
| 5 | One branch per feature | `feature/<short-name>` created from the latest `main` |
| 6 | Every feature has tests | New code in `src/campusride/x.py` -> tests in `tests/test_x.py` |
| 7 | Run tests locally before pushing | `pytest` must be green |
| 8 | Pull Request + 1 approval | Request a review from a teammate; the author cannot approve their own PR |
| 9 | Merge only when CI is green and review approved | The merge button stays disabled otherwise |
| 10 | Everyone pulls latest `main` after a merge | `git checkout main && git pull` |

## One-time setup (each teammate)

```bash
git clone https://github.com/<OWNER>/<REPO>.git
cd <REPO>
python -m venv .venv
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
pytest                          # should pass
git config user.name  "Your Name"
git config user.email "your-github-email@example.com"   # must match your GitHub account so commits count
```

## Daily flow for a feature

```bash
git checkout main
git pull origin main                       # always start from the latest main
git checkout -b feature/<name>             # e.g. feature/matching

# ... write code in src/campusride/ and tests in tests/ ...

pytest                                     # all green? then continue
git add .
git commit -m "feat(matching): rank offers by compatibility score (CRS-F-021)"
git push -u origin feature/<name>          # push the FEATURE branch, never main
```

Then on GitHub: **Compare & pull request** -> base `main`, fill the PR template, request a reviewer.
Wait for `test` to turn green and for one approval, then **Merge pull request** and delete the branch.

After **any** merge, everybody syncs:

```bash
git checkout main
git pull origin main
```

## Ready-made feature code (`starter_patches/`)

The project code is split into one patch per feature so that **each teammate commits their own work** on their own
branch. To use your assigned patch:

```bash
git checkout main && git pull
git checkout -b feature/<name>
git apply starter_patches/<NN-name>.patch     # adds src/campusride/<x>.py and tests/test_<x>.py
pytest                                        # must pass
git add .
git commit -m "feat(<name>): <what it does> (CRS-F-xxx)"
git push -u origin feature/<name>
```

Read the code and tests before committing - you will be asked to explain your feature. Improve it, add more tests,
or extend it; that is encouraged.

| Patch | Branch | Requirements | Suggested owner |
|---|---|---|---|
| 01-auth | `feature/auth` | CRS-F-001..003, CRS-SR-002 | Member C |
| 02-ride-offers-requests | `feature/ride-offers-requests` | CRS-F-010, 012, 014, 015 | Member B |
| 03-matching | `feature/matching` | CRS-F-020, 021, 023 | Member B |
| 04-booking | `feature/booking` | CRS-F-024, 030..035 | Member A |
| 05-messaging | `feature/messaging` | CRS-F-040, 042..044, CRS-SR-006 | Member A |
| 06-ratings-history | `feature/ratings-history` | CRS-F-050..053 | Member B |
| 07-notifications | `feature/notifications` | CRS-F-060..062 | Member A |
| 08-admin-moderation | `feature/admin-moderation` | CRS-F-006, 070..074 | Member C |
| 09-end-to-end-demo | `feature/end-to-end-demo` | integration of all above | Member C (**merge last**) |

Patches 01-08 are independent (they only add new files), so they can be merged in any order without conflicts.
Patch 09 needs 01-07 merged first. When all are merged, Member C deletes `starter_patches/` in a final PR.

## Commit and PR conventions

- Commit message: `type(scope): summary (CRS-F-xxx)` with type = `feat`, `test`, `fix`, `docs`, `chore`.
- Small commits, one idea each. Never commit `.venv/`, `__pycache__/` or secrets (`.gitignore` covers them).
- PR title = the feature; description lists requirement IDs and test evidence.
- Reviewer checks: tests exist and are meaningful, code is readable, requirement IDs are referenced.
- Balanced contributions: everyone owns three feature branches, writes their tests, and reviews a teammate's PRs (A reviews B, B reviews C, C reviews A).

## If you already forked the repository

You can continue, but keep your fork in sync with the team repository:

```bash
git remote add upstream https://github.com/<OWNER>/<REPO>.git     # once
git fetch upstream
git checkout main
git merge upstream/main          # or: git rebase upstream/main
git push origin main             # updates your fork's main
```

Create feature branches from this updated `main`, push them to your fork, and open the Pull Request from
`your-fork:feature/<name>` to `<OWNER>/<REPO>:main`. Prefer cloning the team repository directly - it avoids the
extra syncing and lets CI and branch protection work exactly as designed.
