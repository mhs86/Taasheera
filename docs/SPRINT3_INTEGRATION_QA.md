# Sprint 3 integration check — November 2, 2026

`zeid_sprint3_integration` combines the pending Sprint 3 branches for testing. It does not change
`dev`, `main` or the live deployment. Original feature PRs remain the units for review.

## Changes checked together

- #17: applications dashboard, detail/timeline, archive/restore/delete.
- #18: private database/passport backup and restore tooling.
- #19: idle-session warning/sign-out, including the new BroadcastChannel activity sharing.
- #20: password recovery wording matching the emailed-code flow.
- #21: production Google linking, admin grants, monitoring, document audit and account erasure;
  its updated AGENTS.md preserves the team's shared rules.
- #22: shared database assistant limits, including the unbracketed CloudFront IPv6 parser fix.
- #23 → #24 → #26 → #27: completeness, full assistant context/confirmed actions, stored history,
  and the general assistant.
- #25: main deployment workflow, now completed with private ECR image publication on this branch.

## Integration fixes

1. Keep both the database limiter and the assistant tools/history in the merged router.
2. Chain privacy `f09c612e3a40` → archive `a7c3e91d5b20` → history `c4a8d2f61b93` after the existing
   `e9776504c5f8` revision. Existing unversioned-schema adoption and schema drift checks pass.
3. Delete assistant rows before their traveler/application parent. Account erasure removes all its
   conversations; application deletion removes only that application's conversation. Regression tests
   enforce foreign keys and verify other applications/travelers/general conversations survive.
4. Tell the assistant an archived application is read-only and refuse change/navigation proposals
   until restored. Completeness checks remain available; normal answer saves still enforce archive rules.
5. Mount the general assistant in the separate welcome/account and admin shells too. The original
   site-layout mount did not cover those routes. Keep it outside auth form CSS and key it by account ID.
6. Actions publishes immutable commit-tagged API/web images to separate EC2 ECR repositories and
   deploys digest references. Current-main/successful-push-CI guards apply to manual runs too and are
   repeated after builds. Host pulls/label checks precede stopping services; existing private configuration,
   pre-migration backup and readiness checks stay in place. Operator default image tags follow the release.

## Verification

- Backend: **772 passed, 39 skipped**. Full run with loopback access, needed by the preview port test.
  Skips are the optional PostgreSQL cases; no disposable PostgreSQL server was configured locally.
- Frontend: **224 passed**; ESLint and production build passed.
- Browser suite: **7 passed**, using installed Chrome and isolated preview storage. Covers real
  registration/login/session restore, applications, specimen upload, access audit, deletion and admin flows.
- Additional live Gemini browser smoke, synthetic data only: general assistant on FAQ; conversation reload;
  change-purpose tool proposal leaves the saved answer unchanged until Confirm; confirmation saves through
  the normal answer API; completeness through both panel/tool; application/history survive reload; no page
  errors and no horizontal overflow at 390 px.
- Al Hariri's IPv6 and cross-tab regression tests pass as part of the integrated suites. No additional
  GitHub reviews/comments were posted during this integration check.
- CloudFormation lint, verified actionlint, all AWS shell syntax and `git diff --check` passed.
- No local Docker engine was available: image builds/startup must pass the existing Linux CI smoke checks.
  ECR publication and a live OIDC deployment remain unverified until owner provisioning.

Run backend checks from `backend/` with `python -m pytest -q`; frontend checks from `frontend/` with
`npm test`, `npm run lint`, `npm run build`, and `npm run test:e2e`. Browser tests need their Python
interpreter in `TAASHEERA_TEST_PYTHON`; an installed browser can be selected with
`PLAYWRIGHT_CHROMIUM_EXECUTABLE`. Full live assistant prompts are network-dependent and use only specimens.

## Remaining acceptance and coordination

- Review/merge the feature PRs with the sprint's assigned reviewers. If integrating separately,
  reparent migrations as each lands; never merge competing migration heads. Reconcile AGENTS.md
  decisions rather than dropping one branch's entries. The integration branch demonstrates the resolutions.
- AWS/repository owner: provision production environment/main-only deployment rules, production OIDC
  role, private image repositories/host pull permissions, and `AWS_MAIN_DEPLOY_ROLE_ARN` as described in
  `deploy/aws/README.md`. No cloud resources or permissions were changed by this check.
- After a tested main release, validate real HTTPS deployment and let Dani enable required checks.
- Jira: all six tickets now belong to Sprint 3 (101), are In Progress with the `in-review` label,
  and have the plan's points (27 total). The workflow has no In Review status. Sprint 3 on the live
  board is October 30–November 13, replacing the proposal's dates. Points read-back was verified:

  | Ticket | Story | Points | Current status |
  |---|---|---:|---|
  | CMPS271-48 | US 13 completeness | 5 | In Progress / in-review |
  | CMPS271-88 | US 47 assistant context | 3 | In Progress / in-review |
  | CMPS271-90 | US 110 assistant actions | 8 | In Progress / in-review |
  | CMPS271-93 | US 111 chat history | 3 | In Progress / in-review |
  | CMPS271-87 | US 23 assistant everywhere | 5 | In Progress / in-review |
  | CMPS271-190 | Main deployment | 3 | In Progress / in-review; live acceptance awaits owner setup |
