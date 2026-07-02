# Deployment & security checklist

Everything you need to take TheCustomDuelist live safely on Render. Work top to
bottom — the **Before you go live** checklist at the end is the short version.

---

## 1. Required environment variables

Set these in the Render dashboard (Environment → Environment Variables).

| Variable | Required? | What it does |
| --- | --- | --- |
| `SECRET_KEY` | **Yes** | Signs session cookies. The app **refuses to boot** in production without it (a default key would let anyone forge an admin session). Generate one: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| `DATABASE_URL` | **Yes** | Render Postgres connection string. `postgres://` is rewritten to `postgresql://` automatically. Without it the app falls back to a local SQLite file, which is **ephemeral** on Render. |
| `SITE_CONTACT_EMAIL` | **Yes** | The abuse / DMCA contact shown on the policy pages. Use a real, monitored inbox. |
| `FLASK_DEBUG` | No | Leave **unset** in production. Setting it to `1` relaxes cookie security and enables in-browser tracebacks — dev only. |

Bootstrap the first admin without a shell by setting
`BOOTSTRAP_ADMIN_USERNAME` and `BOOTSTRAP_ADMIN_PASSWORD` once; they no-op after
an admin exists. Remove them afterward.

---

## 2. Durable upload storage

Uploaded images must live somewhere durable. There are two supported options —
you only need one.

### Option A: a persistent disk (what this deployment uses)

If you mount a Render **persistent disk** over the uploads directory
(`static/uploads`), the default `local` backend is already durable — images
survive every deploy and restart. In that case, just acknowledge it so the app
doesn't warn about ephemeral storage:

```
UPLOADS_ON_PERSISTENT_DISK=1
```

Notes for the disk setup: a service with a disk runs as a **single instance**
(disks can't be shared across instances) and deploys aren't zero-downtime — both
fine at this scale. Make sure Render disk **snapshots/backups** are enabled,
since the disk is a single copy.

### Option B: object storage (S3 / Cloudflare R2)

Render's filesystem is **ephemeral by default** (no disk): without one, every
uploaded image is deleted on each deploy/restart, and the app warns at startup.
If you're not using a disk, switch to object storage. `boto3` is already in
`requirements.txt`.

```
UPLOAD_BACKEND=s3
S3_BUCKET=your-bucket
S3_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com   # R2; omit for AWS S3
S3_PUBLIC_BASE=https://cdn.yourdomain.com                    # public URL base for objects
S3_REGION=auto                                               # "auto" for R2; a region for S3
AWS_ACCESS_KEY_ID=...                                        # read by boto3
AWS_SECRET_ACCESS_KEY=...
```

Give the credentials write access to that one bucket only. Test with a real
upload before launch — the S3 path can't be exercised without live credentials.

---

## 3. Rate-limit storage (Redis) — recommended

Rate limits default to in-memory, which **resets on every restart** and isn't
shared across workers/instances, weakening brute-force protection. Point them at
Redis in production:

```
RATELIMIT_STORAGE_URI=redis://:password@host:6379/0
```

---

## 4. Trust & safety (the uploads liability story)

The upload pipeline already re-encodes every image through Pillow, which strips
metadata and neutralises malware/polyglots — good protection for your site and
visitors. It does **not** judge what an image *depicts*. For that:

### a. Automated image scanning (the code seam)
Wire an external classifier into the upload path (runs on the sanitised bytes,
before storage). The endpoint gets the image as the POST body and must reply
`200` with JSON `{"allowed": true|false}`.

```
IMAGE_SCAN_ENABLED=1
IMAGE_SCAN_WEBHOOK_URL=https://your-scanner.example.com/check
IMAGE_SCAN_TIMEOUT=10
IMAGE_SCAN_FAIL_OPEN=0     # 0 = refuse uploads if the scanner is down (default, safer)
```

### b. Cloudflare CSAM Scanning Tool (free, and independent of the code)
If you front the site with Cloudflare, enable the CSAM Scanning Tool in the
dashboard (Caching → Configuration). It hash-matches served images against known
CSAM databases and files reports automatically. This is the recommended baseline
and needs no code changes. Microsoft PhotoDNA and Thorn Safer are alternatives
that can sit behind the webhook above.

### c. Pre-moderation (hold uploads for approval)
Off by default (instant publishing). Turn it on to hold non-staff uploads until
a moderator approves them in **Moderation → Pending review**:

```
REQUIRE_UPLOAD_REVIEW=1
```

Approving is an unhide; rejecting keeps it hidden as a takedown. Staff (moderator
/ admin) uploads publish immediately.

### d. Policy pages & legal
Review and edit these before launch (they ship with sensible defaults and
`[bracketed]` placeholders):
`/terms`, `/acceptable-use`, `/privacy`, `/report-abuse` (linked in the footer).

- Fill in your legal name/entity and the designated **DMCA agent** (register one
  with your national copyright office; US: the Copyright Office DMCA directory).
- Registration now requires accepting the Terms + Acceptable Use Policy.
- **Legal obligation:** in the US, once you have *actual knowledge* of CSAM you
  must report it to NCMEC's CyberTipline and preserve records — do not download
  or "investigate" the material yourself. Confirm the exact rules for your
  jurisdiction. Have a written procedure ready before you accept public uploads.

---

## 5. Error monitoring (optional)

```
SENTRY_DSN=https://...ingest.sentry.io/...
```

Then add `sentry-sdk` to `requirements.txt` (kept out by default to avoid the
dependency). The app initialises Sentry automatically when the DSN is set and
the package is installed; it's a no-op otherwise.

---

## 6. Keep dependencies patched

Versions are pinned in `requirements.txt`. Periodically run `pip-audit` (or
enable GitHub Dependabot) and bump deliberately after re-testing — don't float
versions, so a fresh build can't silently pull a vulnerable release.

---

## 7. Recommended follow-up (not yet built): account email & password reset

`User.email` exists but there's no email flow. Before or soon after launch,
consider adding email verification and password reset — both need an email/SMTP
provider (e.g. Postmark, SES, Resend), which is a deployment decision. Without
it, a user who forgets their password has no self-service recovery, and you have
no way to contact a user about their content.

---

## Before you go live — checklist

- [ ] `SECRET_KEY` set (app refuses to boot otherwise).
- [ ] `DATABASE_URL` points at Render Postgres (not SQLite).
- [ ] `FLASK_DEBUG` is unset.
- [ ] Uploads are durable: either a persistent disk over `static/uploads`
      (+ `UPLOADS_ON_PERSISTENT_DISK=1`), or `UPLOAD_BACKEND=s3` with working
      `S3_*` creds. Test an upload survives a redeploy.
- [ ] `RATELIMIT_STORAGE_URI` points at Redis.
- [ ] `SITE_CONTACT_EMAIL` is a real, monitored inbox.
- [ ] Policy pages reviewed; DMCA agent + legal entity filled in.
- [ ] CSAM scanning enabled (Cloudflare tool and/or `IMAGE_SCAN_*` webhook).
- [ ] Decided on `REQUIRE_UPLOAD_REVIEW` (on = safest for public uploads).
- [ ] Written procedure for handling illegal-content reports (incl. NCMEC).
- [ ] First admin created; `BOOTSTRAP_ADMIN_*` removed.
- [ ] `pip-audit` clean / Dependabot enabled.
