The task failed because frontend/node_modules was added to the change set (3500+ files). Fix it:
1. Create frontend/.gitignore containing: node_modules, dist, coverage. Also make sure the root .gitignore ignores frontend/node_modules.
2. Run `git rm -r --cached frontend/node_modules` (and the same for frontend/dist if present) so nothing from them is tracked.
3. Before every commit run `git status --short | grep node_modules`; it must print nothing. The change set must contain only source files, package.json, package-lock.json, Dockerfile, nginx.conf and tests.
4. Then continue from where you stopped and submit as a new PR from the current new branch, following all earlier HARD RULES (no deletions of existing files, git diff --stat in the PR description, backend tests still 58 passed).
