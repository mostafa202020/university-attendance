# Attendance Tracker — Render deployment

## Deploy on Render

1. Push the contents of this folder to a GitHub repository.
2. Create a Render PostgreSQL database.
3. Create a Render Web Service connected to the repository.
4. Set:
   - Build command: `pip install -r requirements.txt`
   - Start command: `flask --app app init-db && gunicorn app:app`
5. Add these environment variables in Render:
   - `DATABASE_URL`: Render PostgreSQL **Internal Database URL**
   - `TEACHER_USERNAME`: your chosen teacher login
   - `TEACHER_PASSWORD`: a strong password
   - `FLASK_SECRET_KEY`: a long random secret
   - `SESSION_CODE_SECRET`: a different long random secret

Generate random secrets on your computer with:
`python -c "import secrets; print(secrets.token_urlsafe(48))"`

Use a separate generated value for each secret. Do not commit secrets to GitHub.

## Local run

Install dependencies with `pip install -r requirements.txt`, then run
`flask --app app init-db` and `flask --app app run`.

The `/health` endpoint returns `{"status":"ok"}` for a basic availability check.

## Important

This is a starter application and should receive security hardening and runtime testing
before it is used for real student records. Keep the database URL and credentials secret.
