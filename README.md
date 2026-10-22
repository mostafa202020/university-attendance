# Attendance Tracker — Complete Starter

A mobile-friendly Flask application for university attendance. Students check in using first name, surname, and a session code manually written on the board. No PIN or student account is required.

## Features

- Teacher login and protected administration routes.
- Course and fixed group creation.
- CSV/XLSX roster import.
- Session creation with Course/Lab, date, manual code, opening and closing times.
- All enrolled students initialized as absent when a session is created.
- Server-side code/time/group validation and duplicate check-in rejection.
- Teacher attendance dashboard and manual corrections with reasons.
- Git-inspired commit/event history for check-ins and corrections.
- Reports based on closed sessions and CSV export.
- SQLite default; configure PostgreSQL using `DATABASE_URL`.

## Local setup — Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:FLASK_SECRET_KEY = "replace-with-a-long-random-secret"
$env:SESSION_CODE_SECRET = "use-a-different-long-random-secret"
$env:TEACHER_USERNAME = "teacher"
$env:TEACHER_PASSWORD = "choose-a-strong-password"

flask --app app init-db
flask --app app run --host 0.0.0.0 --port 5000
```

Open `http://127.0.0.1:5000`, select Teacher login, and use the username/password set in your environment. Create a course, add groups, import each group's roster, and create a session.

For testing, run:

```powershell
pip install pytest
pytest -q
```

## Roster file

CSV or XLSX first worksheet with headers such as:

```csv
first_name,surname
Amine,Benali
Sara,Mansouri
Yacine,Haddad
```

The import screen previews the file and asks you to upload the same file again to confirm. Existing enrollments are preserved. Duplicate names are problematic because student identification uses first name and surname only; resolve duplicates in a group before the session.

## Phone access on local Wi-Fi

Find the teacher computer's local IPv4 address (for example, using `ipconfig`). Students on the same Wi-Fi can open:

`http://TEACHER-LAN-IP:5000/check-in/SESSION_ID`

Allow inbound access through the local firewall if needed. For internet access, deploy with HTTPS and a production WSGI server. Do not expose Flask's development server publicly.

## Security and production checklist

- Change all secrets and teacher credentials.
- Use HTTPS, PostgreSQL, a production WSGI server, and database backups.
- Add rate limiting for session-code guesses before public deployment.
- Configure teacher session expiration and CSRF protection for production.
- The default teacher login is intentionally simple; environment variables must be set before deployment.
- Because there are no student accounts/PINs, name + shared session code cannot conclusively prove identity or prevent impersonation.
- Store all times consistently. The starter treats server/session datetimes as server-local-naive timestamps and labels check-in display as UTC only when the server is configured to UTC. For production, configure the host to UTC or refactor to timezone-aware datetime handling.

## Limitations

This is a feature-complete prototype for the requested check-in workflow, not a security-audited production system. Add CSRF protection, rate limiting, better duplicate-name resolution, and a migration strategy before production use.
