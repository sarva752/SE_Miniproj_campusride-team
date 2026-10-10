#!/usr/bin/env bash
# One-time setup by the repository OWNER (team lead). Run in Git Bash / macOS / Linux terminal.
#
# Prerequisites: git, GitHub CLI (https://cli.github.com), and `gh auth login` already done.
#
# Usage:
#   OWNER=your-github-username REPO=campusride-team \
#   COLLABORATORS="teammate1 teammate2 teammate3" \
#   ./scripts/setup_github.sh
#
# VISIBILITY defaults to public (branch protection on PRIVATE repos needs a paid GitHub plan).
set -euo pipefail

: "${OWNER:?set OWNER (your GitHub username or org)}"
: "${REPO:?set REPO (repository name)}"
: "${COLLABORATORS:?set COLLABORATORS (space separated GitHub usernames)}"
VISIBILITY="${VISIBILITY:-public}"

echo "==> Step 1: create ONE common repository $OWNER/$REPO ($VISIBILITY) and push the scaffold"
if [ ! -d .git ]; then
  git init -b main
  git add .
  git commit -m "chore: initial scaffold (models, CI, docs, starter patches)"
fi
gh repo create "$OWNER/$REPO" "--$VISIBILITY" --source=. --remote=origin --push \
  --description "CampusRide - Campus Ride-Share Matching System (SE mini project)"

echo "==> Step 2: add every teammate as a collaborator (Write access)"
for user in $COLLABORATORS; do
  gh api -X PUT "repos/$OWNER/$REPO/collaborators/$user" -f permission=push --silent
  echo "    invited $user (they must accept the email/notification invite)"
done

echo "==> Merge settings: delete feature branches after merge, allow squash merges"
gh repo edit "$OWNER/$REPO" --delete-branch-on-merge --enable-squash-merge --enable-merge-commit --enable-rebase-merge

echo "==> Steps 3 & 4: CI is in .github/workflows/ci.yml; protect main (PR + approval + passing 'test' check)"
cat > /tmp/protection.json <<JSON
{
  "required_status_checks": { "strict": true, "contexts": ["test"] },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false
  },
  "restrictions": null,
  "required_conversation_resolution": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
gh api -X PUT "repos/$OWNER/$REPO/branches/main/protection" --input /tmp/protection.json --silent
echo "    main is now protected."

echo
echo "Done. Next: every teammate accepts the invite, clones (not forks) and follows CONTRIBUTING.md."
echo "Check: Settings > Branches > main  and  Actions tab (first CI run appears after the first PR/push)."
