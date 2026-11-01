# Integrate the exact production release into dev

Prepared on 1 November 2026 on `mohammad_prod_to_dev_sprint3`.

- Target parent: dev `0b7372c31056d2813ba57d36c9eaaf8154df8f84`.
- Production parent: `4fa4666fa96e86d08144c527504906306d2556b0`.
- Production evidence supplied by the owner: successful SSM deployment
  `85000b96-3623-48f2-a0bf-68e4bef7fd31`, 31 October 2026, 16:54 Beirut time.
- The later source-branch commit `00516d4` is excluded. It introduced separate
  admin-only operator tooling after the deployed revision.

The source histories merge without conflicts. Existing dev changes to the Account
link in the desktop/mobile header and their interaction tests are preserved.
Application/API code otherwise comes from the pinned production revision.
This merge changes no live AWS settings, runtime data, passwords or admin roles.

## Verification

The merged source passed 698 backend tests with SQLite and PostgreSQL 17 (no
skips), 165 frontend tests, all seven Chromium browser tests, frontend lint and
the production TypeScript/Vite build. Shell syntax checks passed. Application
and migration sources match the production parent; dev's header/layout changes
are preserved. These checks used synthetic data and isolated preview storage.

## Why the Windows commands failed

The branch switch was blocked by modified and untracked files in the Windows
checkout. Subsequent pull/merge commands therefore ran on its original branch.
The workspace here is a separate Linux environment; it cannot edit or stash files
under `C:\Users\Moka`. Its merge work is prepared in an isolated worktree.
No Windows files were deleted, reset, stashed or overwritten.

## Open the prepared merge on Windows without touching that checkout

Run this from Windows Command Prompt. The new sibling folder must not already
exist. These commands fetch the prepared merge and open it in another worktree:

```cmd
cd /d C:\Users\Moka\Desktop\CMPS271\Taasheera && ^
git fetch origin refs/heads/mohammad_prod_to_dev_sprint3:refs/remotes/origin/mohammad_prod_to_dev_sprint3 && ^
git worktree add --detach ..\Taasheera-dev-prod origin/mohammad_prod_to_dev_sprint3 && ^
cd /d C:\Users\Moka\Desktop\CMPS271\Taasheera-dev-prod
```

The original folder and its uncommitted/untracked files remain intact. The new
worktree contains the completed merge, so another `git merge` is unnecessary.
Use the isolated preview instructions in `docs/LOCAL_FEATURE_TESTING.md` to test
it. The preview uses its own database and does not change existing local settings.

Remote dev/main and production are not updated by preparing or publishing this
integration branch. Run the checks before completing integration. A Git merge
does not copy production private configuration, database roles or SES identities.
