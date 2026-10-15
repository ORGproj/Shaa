# Security hardening and production checklist

This application handles student records, academic results, attendance and payment information. Treat it as sensitive personal data.

## Included protections

- Passwords are stored as Werkzeug password hashes, not plaintext.
- All state-changing form requests require a session CSRF token.
- Login failures are throttled by IP + username in each application process (5 failures per 5 minutes).
- Accounts are also locked **temporarily** (default 15 minutes, `LOGIN_LOCKOUT_MINUTES`) after 10 failed passwords from any address within that window. The lock is stored in the database, expires by itself, and an administrator can unlock earlier. The account threshold is higher than the per-IP limit so a single attacking address cannot lock a victim out on its own.
- Payment amounts are stored as exact decimals (`NUMERIC(12,2)`), never floating point.
- Login regenerates the session by clearing it before setting the authenticated user.
- Role-based route checks restrict registrar, accounting, academic and admin features. Admins can also grant or remove view, create, edit and delete access per module for each account.
- Message attachments (PNG, JPG, WEBP, PDF; up to 5 per message) are checked by extension and file signature, stored under random names outside the web root, and downloadable only by the sender and recipient of that message.
- Uploads are size-limited and checked for an allowed extension and image signature; generated filenames prevent path traversal.
- Responses include clickjacking, MIME-sniffing, referrer and permissions policy headers; production adds HSTS and secure session cookies.
- Production startup requires an explicit strong SECRET_KEY; demo accounts and sample data are not seeded in production by default.
- Newly set/changed passwords must be at least 12 characters.

## Required before production use

1. Configure `SECRET_KEY` with a unique random value of at least 32 characters. Never commit it to source control.
2. Set `APP_ENV=production`, use HTTPS, and keep the database private.
3. For the first deployment only, set `BOOTSTRAP_ADMIN_USERNAME` and `BOOTSTRAP_ADMIN_PASSWORD` (12+ characters) before the first empty database startup. After the first admin account is created, remove both variables and redeploy. If you remove them before the initial startup, no admin user will be created.
4. Do not set `SEED_DEMO_DATA=1` in production. The setting intentionally populates sample student/course data.
5. Use a managed PostgreSQL database, least-privilege database credentials, automated backups, and test restoring a backup.
6. Configure durable private object storage for student/profile images; the local upload directory may be ephemeral on hosted platforms. Avoid public access to uploaded documents.
7. Restrict admin access, remove unused accounts promptly, and never share accounts or passwords.
8. Review applicable privacy obligations before using real student data (including the Philippine Data Privacy Act where applicable). Limit data collection and access to legitimate school purposes.
9. Use a shared rate-limit store (e.g. Redis) and centralized monitoring if deploying multiple workers/instances; the per-IP login throttle is in-memory per worker (the account lock is in the database and is shared).
10. Run dependency updates and security testing before each public release. Configure error monitoring without logging passwords, session cookies, or sensitive student data.

## First admin account on Render

The included Render Blueprint generates `SECRET_KEY` and configures production mode. Before the first deploy, add `BOOTSTRAP_ADMIN_USERNAME` and `BOOTSTRAP_ADMIN_PASSWORD` as secret environment variables in Render. Use a unique username and a long, unique password (preferably 16+ random characters). After the first successful deployment, confirm you can log in, remove those two variables, and redeploy. Do not use the old development demo credentials on the public site.

## Local development

The default development mode seeds demo users for local testing. Never expose a development server publicly. Set `APP_ENV=production` when testing production behavior; that requires `SECRET_KEY` and disables demo-user/sample-data seeding by default.
