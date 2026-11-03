# Sprint 3 delivery and manual acceptance

As of November 2, 2026. Test branch: `zeid_sprint3_integration`; combined draft PR:
https://github.com/mhs86/Taasheera/pull/28 → `dev`. The existing public site has not received this release.

## What was delivered across both agent sessions

The earlier session implemented the six tickets and opened the original PRs. The continuation combined
those features with the teammates' current branches, fixed their interactions, completed image publishing,
and tested the combined result. The existing sign-in/profile/passport/guided-questionnaire foundation
comes from earlier sprints; it was extended and checked, not rebuilt this sprint.

| Ticket | Earlier implementation | Follow-up in the integration |
|---|---|---|
| CMPS271-48 / US 13 | Pure completeness engine, owner-scoped check endpoint, Check my application panel | Checked against dashboard/archive and the assistant's check tool |
| CMPS271-88 / US 47 | Server loads current application's answers, question/step, reachable question IDs and completeness report | Added archived/read-only state to that context |
| CMPS271-90 / US 110 | Gemini tools propose answer changes, question navigation and completeness checks; normal answer endpoint saves only after Confirm | Preserved the shared database limiter when merging the router; refused archived change/navigation proposals |
| CMPS271-93 / US 111 | Owner-scoped conversations per application and one general conversation; server supplies prior messages to Gemini | Account erasure deletes all its conversations; application deletion deletes only its conversation; migration follows privacy/archive |
| CMPS271-87 / US 23 | General assistant mounted in the site layout; passport/application pages retain their own assistant | Added the separate welcome/account and admin shells that the site layout does not cover |
| CMPS271-190 | CI-gated main deployment workflow, OIDC trust template and setup instructions | Actions builds API/web images, publishes immutable commit tags to private ECR, deploys digests; current-main/passing-CI guards cover automatic/manual runs; host verifies labels before restart |

The integration also includes teammates' work: Dani's dashboard/detail/timeline/archive/delete and backup
scripts; Hariri's idle guard, OTP wording and shared rate limiter; Mohammad's production Google linking,
admin/monitoring/deletion/document-audit code. These features remain their authors' work.

Other completed work:
- Resolved shared models/router/layout/activity/API conflicts while retaining both features.
- Chained migrations: existing `e9776504c5f8` → privacy `f09c612e3a40` → archive `a7c3e91d5b20` → history `c4a8d2f61b93`.
- Earlier reviews: #20 approved, changes requested on #19/#22, shared-documentation concerns on #21.
  Hariri fixed cross-tab activity sharing and CloudFront IPv6 parsing; #19/#22 were then re-tested and approved.
- Set the six Jira tickets to In Progress + `in-review` (the workflow has no In Review status), with
  5/3/8/3/5/3 points for 48/88/90/93/87/190. The deployment subtask retains its parent's Sprint 2 field.
- Recorded Ahmad Zeid's takeover of deployment/AWS operations; actual administrative access needs handover.
- Verified 811 backend tests in CI including PostgreSQL, 224 frontend tests, lint/build, seven browser tests,
  live Gemini behavior with synthetic data, both production images and isolated nginx/API container startup.

## Scope to expect

- The completeness report covers questionnaire answers, the eligibility gate, and specified passport/profile
  mismatches. It does not validate supporting bank statements, generate embassy forms or establish visa eligibility.
- Full application context/tools apply inside that application's chat. Outside it, the general assistant gets
  the owner's latest confirmed passport and general conversation, not an automatic overview of every application.
- Answer changes need Confirm. Completeness is read-only and runs immediately; navigation needs its Go button.
  No submission tool exists. Passport/address answers have several fields and are edited through their forms.
- Stored history reloads text; old action cards and their confirmation state are not restored. The page loads
  the newest 50 messages and the model gets recent history, rather than an unlimited conversation.
- Gemini's wording/tool choice can vary. Verify facts, saved values and confirmation behavior, not exact prose.
- AWS templates/workflow code are ready for review. Real ECR publishing/OIDC deployment and external provider
  acceptance remain unverified until setup and the first live release.

## Start a local test with Gemini and separate data (macOS)

Your current checkout is already on the integration branch. Dependencies and your local Gemini key are
installed/configured on this machine. These commands use a separate ignored dataset, not the normal local DB.
Use synthetic accounts and specimens: the Gemini free tier may use submitted prompts for product improvement.

Terminal 1 — API:

```bash
cd /Users/ahmadzeid/Developer/Taasheera/backend
export TAASHEERA_MANUAL_DIR="$PWD/storage/sprint3-manual"
mkdir -p "$TAASHEERA_MANUAL_DIR"
export DATABASE_URL="sqlite:///$TAASHEERA_MANUAL_DIR/app.db"
export PASSPORT_STORAGE_DIR="$TAASHEERA_MANUAL_DIR/passports"
export ACTIVITY_LOG_DIR="$TAASHEERA_MANUAL_DIR/activity-logs"
.venv/bin/python dev.py run
```

Terminal 2 — frontend:

```bash
cd /Users/ahmadzeid/Developer/Taasheera/frontend
npm run dev
```

Open http://127.0.0.1:5173/sign-in . Leave both terminals running; Ctrl+C stops each process.
`dev.py run` applies migrations and loads the existing key from ignored `backend/.env.local` without printing it.
This is an empty dataset: your usual local accounts and the preview's seeded accounts are not copied.
Create `sprint3-a@example.com` and `sprint3-b@example.com`, plus a separate `sprint3-admin@example.com` if testing admin.
Use a test-only password such as `Sprint3-Test-Only-123!` and remember it for the deletion checks.

If a required port is occupied, stop the server you started in its owning terminal. Do not blindly free ports.
For a fresh clone, install the backend `requirements-dev.lock`, run `dev.py setup` once, and run `npm ci`
in frontend first. Tesseract must be on PATH for OCR. The assistant returns an unavailable message without
its key; the existing `preview.py run --seed-demo` deliberately disables Gemini, so it cannot test live tools.

## Synthetic passport and example answers

Generate the built-in ICAO specimen in a third terminal:

```bash
cd /Users/ahmadzeid/Developer/Taasheera/backend
.venv/bin/python -c 'from pathlib import Path; from scripts.specimen_passport import synthetic_passport; Path("/tmp/taasheera-sprint3-specimen.jpg").write_bytes(synthetic_passport())'
```

The specimen is fictional Anna Maria Eriksson of Utopia and has an expired 2012 date. To finish the full
questionnaire, change its expiry to **2031-05-01** in the review before confirming. This is deliberately a
manual correction of synthetic data, not a new OCR result. You may set both country codes to `LBN` for the
example below. Edited fields should be labeled Edited.

Example full application (valid relative to November 2, 2026):

| Question | Synthetic answer |
|---|---|
| Opening steps | Schengen area → Short stay (type C) → Just me |
| Main destination / purpose / longer than 90 days | France / Tourism / No |
| Passport | Confirmed specimen; expiry 2031-05-01; nationality/issuing country LBN |
| Issue date | 2024-05-01 |
| Different surname at birth | Skip |
| Birth place/country / marital status | Beirut / Lebanon / Single |
| Home address | 1 Example Street, Beirut, Lebanon; optional fields blank |
| Phone / occupation | +961 71 123 456 / I'm retired |
| Arrival / departure | 2027-03-10 / 2027-03-20 |
| Entries / accommodation | Once / With family or friends |
| Host | Lina Example, 2 Rue Exemple, Paris |
| Funding / previous fingerprints | I am / No |

Use future trip dates within six months of the day you test; keep departure within 90 days and at least
three months before passport expiry. Choose an occupation/accommodation branch and answer its follow-ups.

## Acceptance walkthrough

1. **Start application A.** Sign in as A, visit `/apply`, choose the opening steps above and answer France,
   Tourism, No. Refresh: these answers and the current question should survive. Resume also works from `/dashboard`.

2. **Full context.** In the application's Ask box, ask: "Which country and purpose did I choose, and what am I
   answering next?" It should refer to France/Tourism and the actual current question without asking you to repeat them.

3. **Propose/dismiss/confirm.** Ask "Change my trip purpose from tourism to business."
   Expect a proposed change showing Tourism → Business, with Confirm change and Not now. Before confirming, the
   saved purpose must remain Tourism. Choose Not now: it remains Tourism. Ask again and Confirm change: the normal
   saved answer becomes Business and survives reload. A model reply without a proposal must not write an answer.

4. **Navigation.** Ask "Take me to the purpose question." Click Go to this question. The answered question opens
   for editing; navigation alone must not replace its value. Asking for an unreachable later question must not skip
   the questionnaire's order. Passport/address edits should use their multi-field forms.

5. **Missing answers/check tool.** While unfinished, click Check my application: missing visible answers are Must fix.
   Ask "Run the completeness check now." Its report should describe the same current gaps. A fresh application with
   Yes at the >90-day question should stop at the eligibility gate; the assistant check should explain that blocker.

6. **Passport and full completion.** At the passport question choose Upload a photo, upload the generated specimen,
   review/correct it as described, click Confirm these details, then Continue your application. Finish the remaining
   questions with the example answers. Check again: no missing answers. Refresh and confirm the answers still exist.
   With trip dates answered, ask for a departure before arrival: the invalid date must not be saved or offered as a
   valid change. The app has no embassy Submit action to test at this stage.

7. **Consistency warnings.** In a second tab visit `/account` and set profile surname to DIFFERENT (passport remains
   ERIKSSON). Return to A and Check again: expect a Check warning about the mismatch; the application copy must not
   silently change. Restore the matching surname. Optional: change the saved passport expiry on `/passport/:id`
   after it was copied into A; the check warns that the latest confirmed passport differs.

8. **History and owner isolation.** Ask something distinctive in A. Create application B under the same account and
   ask a different question. Switching between them must load separate conversations. Ask a general question from
   `/faq`; that conversation should reload from another general page, not appear in A or B. Reload, sign out/in and
   restart the API with the same commands: saved text should return. Sign in as the second traveler account: it must
   not see A's conversations/applications. Opening A's copied application URL should show not found.

9. **Assistant locations.** Check `/`, `/faq`, `/dashboard`, `/sign-in` while signed in, and `/account`: one general
   launcher should be available. Passport and application pages use their own assistant rather than a duplicate.
   Signed-out pages should show no general launcher. Admin pages have the launcher after admin access is verified.

10. **Archive and stale confirmations.** Keep A open in one tab; archive it from `/dashboard` in another. It moves
    to Archived; a fresh open is read-only and offers restoration. If the first tab still has a pending proposal,
    Confirm must be refused by the backend while archived. Restore A: answering works again.

11. **Application deletion.** Give both A and B conversations and also keep a general conversation. Delete a disposable
    application from `/dashboard`: Cancel must preserve it; Yes, delete removes it and its conversation. The other
    application, general conversation and separately uploaded passport remain. Backend regression tests verify that
    physical chat rows are removed even with foreign keys enforced, beyond what the UI alone can prove.

12. **Account deletion.** Use a disposable traveler with an application and chat. From `/account`, choose Delete my
    account, confirm the current password and type DELETE. The app signs out; signing in again should fail. Another
    traveler's data must remain. Account erasure includes general/application chat rows; backend tests check every
    related record/file, not just the disappearance of the login screen. Never use your everyday account for this test.

13. **Idle tabs.** Open the same traveler in two tabs. Real activity in tab A must keep quiet tab B from signing out
    the shared session. With all tabs idle, the default warning is at 28 minutes and sign-out at 30. Stay signed in
    should dismiss the warning. Mouse movement alone does not count. Automated tests cover the clocks/cross-tab path
    without requiring a 30-minute wait; IPv6 bucket separation is also an automated proxy-parser check.

## Admin checks in the same manual dataset

Register `sprint3-admin@example.com`, then promote it from a third terminal using the same database:

```bash
cd /Users/ahmadzeid/Developer/Taasheera/backend
TAASHEERA_MANUAL_DIR="$PWD/storage/sprint3-manual"
DATABASE_URL="sqlite:///$TAASHEERA_MANUAL_DIR/app.db" \
ACTIVITY_LOG_DIR="$TAASHEERA_MANUAL_DIR/activity-logs" \
.venv/bin/python manage.py set-role --email sprint3-admin@example.com --role admin
```

Sign in/reload as that account. `/admin` has user search/detail/suspend/reactivate/role/delete controls;
`/backoffice` has application counts and safe error metadata. Confirm a normal traveler is refused both.
Delete only a disposable traveler, and check self/admin deletion protections. On the traveler's `/account`,
Refresh access history should show passport reads/review/extraction; check that another traveler has a separate log.
These admin/dashboard/audit features were built by teammates and checked during integration.

## First production deployment acceptance (after AWS setup/review/merge)

Follow `deploy/aws/README.md` for the production environment, OIDC role, private repositories, host pull policy
and `AWS_MAIN_DEPLOY_ROLE_ARN`. Release through reviewed `dev` → `main`. Verify that the workflow deploys the
current tested main SHA, publishes/reuses both image tags, passes pinned digests to EC2, creates the private
pre-migration backup, migrates successfully and passes `/health/ready` through HTTPS.

On the CloudFront site, repeat a small synthetic journey: email login, real Google sign-in/linking, reset code
actually arriving and working once, passport upload/review, an assistant-confirmed edit, history reload and dashboard.
Local checks do not prove real SES delivery, OAuth console configuration, the deployed Gemini key or live AWS access.
Nightly backup/restore and monitoring require their documented external provisioning; rehearse restores separately
from the live data. A green local test is not evidence that those services have been activated.

## Recorded verification

811 backend tests passed in CI including PostgreSQL; 224 frontend tests, lint/build and seven browser tests passed.
Live Gemini was checked with synthetic data, including confirmation before saving and history reload. Production
API/web images and isolated Compose migration/nginx/auth/application/completeness/history smoke checks passed.
The integration handoff is `docs/SPRINT3_INTEGRATION_QA.md`. Team review, AWS access/setup and first real release
acceptance remain the completion steps for the deployment work.
