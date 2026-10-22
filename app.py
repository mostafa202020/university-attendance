import os
import hmac
import hashlib
import csv
import io
from datetime import datetime, date, timedelta, timezone
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session as web_session, make_response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import UniqueConstraint, Index
from sqlalchemy.exc import IntegrityError

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def clean_name(value):
    return " ".join((value or "").strip().split())


def norm_code(value):
    return "".join((value or "").strip().upper().split())


def name_key(value):
    return clean_name(value).casefold()


def digest_code(code, secret):
    return hmac.new(secret.encode(), norm_code(code).encode(), hashlib.sha256).hexdigest()


def create_app(test_config=None):
    app = Flask(__name__)

    database_url = os.environ.get("DATABASE_URL", "sqlite:///attendance.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace(
            "postgres://", "postgresql+psycopg://", 1
        )
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace(
            "postgresql://", "postgresql+psycopg://", 1
        )

    app.config.update(
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY", "local-dev-change-this-secret"),
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_CODE_SECRET=os.environ.get(
            "SESSION_CODE_SECRET", "local-dev-change-this-code-secret"
        ),
        TEACHER_USERNAME=os.environ.get("TEACHER_USERNAME", "teacher"),
        TEACHER_PASSWORD=os.environ.get("TEACHER_PASSWORD", "ChangeMe123!"),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    db.init_app(app)

    class Course(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(160), nullable=False)
        semester = db.Column(db.String(100), nullable=False, default="Semester 1")
        groups = db.relationship("StudentGroup", back_populates="course", cascade="all, delete-orphan")
        __table_args__ = (UniqueConstraint("name", "semester", name="uq_course_semester_name"),)

    class StudentGroup(db.Model):
        __tablename__ = "student_groups"
        id = db.Column(db.Integer, primary_key=True)
        course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
        name = db.Column(db.String(100), nullable=False)
        course = db.relationship("Course", back_populates="groups")
        enrollments = db.relationship("Enrollment", back_populates="group", cascade="all, delete-orphan")
        sessions = db.relationship("AttendanceSession", back_populates="group", cascade="all, delete-orphan")
        __table_args__ = (UniqueConstraint("course_id", "name", name="uq_group_course_name"),)

    class Student(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        first_name = db.Column(db.String(100), nullable=False)
        surname = db.Column(db.String(100), nullable=False)
        enrollments = db.relationship("Enrollment", back_populates="student", cascade="all, delete-orphan")

    class Enrollment(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        group_id = db.Column(db.Integer, db.ForeignKey("student_groups.id"), nullable=False)
        student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
        group = db.relationship("StudentGroup", back_populates="enrollments")
        student = db.relationship("Student", back_populates="enrollments")
        __table_args__ = (UniqueConstraint("group_id", "student_id", name="uq_enrollment_group_student"),)

    class AttendanceSession(db.Model):
        __tablename__ = "attendance_sessions"
        id = db.Column(db.Integer, primary_key=True)
        group_id = db.Column(db.Integer, db.ForeignKey("student_groups.id"), nullable=False)
        session_type = db.Column(db.String(10), nullable=False)
        session_date = db.Column(db.Date, nullable=False)
        title = db.Column(db.String(160), nullable=True)
        code_hash = db.Column(db.String(64), nullable=False)
        opens_at = db.Column(db.DateTime, nullable=False)
        closes_at = db.Column(db.DateTime, nullable=False)
        is_open = db.Column(db.Boolean, nullable=False, default=True)
        created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
        group = db.relationship("StudentGroup", back_populates="sessions")
        attendances = db.relationship("Attendance", back_populates="session", cascade="all, delete-orphan")
        commits = db.relationship("AttendanceCommit", back_populates="session", cascade="all, delete-orphan")

    class Attendance(db.Model):
        __tablename__ = "attendance"
        id = db.Column(db.Integer, primary_key=True)
        session_id = db.Column(db.Integer, db.ForeignKey("attendance_sessions.id"), nullable=False)
        student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
        status = db.Column(db.String(10), nullable=False, default="ABSENT")
        checked_in_at = db.Column(db.DateTime, nullable=True)
        updated_at = db.Column(db.DateTime, nullable=False, default=utcnow)
        session = db.relationship("AttendanceSession", back_populates="attendances")
        student = db.relationship("Student")
        __table_args__ = (
            UniqueConstraint("session_id", "student_id", name="uq_attendance_session_student"),
            Index("ix_attendance_session_status", "session_id", "status"),
        )

    class AttendanceCommit(db.Model):
        __tablename__ = "attendance_commits"
        id = db.Column(db.Integer, primary_key=True)
        session_id = db.Column(db.Integer, db.ForeignKey("attendance_sessions.id"), nullable=False)
        message = db.Column(db.String(240), nullable=False)
        created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
        session = db.relationship("AttendanceSession", back_populates="commits")
        events = db.relationship("AttendanceEvent", back_populates="commit", cascade="all, delete-orphan")

    class AttendanceEvent(db.Model):
        __tablename__ = "attendance_events"
        id = db.Column(db.Integer, primary_key=True)
        commit_id = db.Column(db.Integer, db.ForeignKey("attendance_commits.id"), nullable=False)
        student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
        old_status = db.Column(db.String(10), nullable=False)
        new_status = db.Column(db.String(10), nullable=False)
        reason = db.Column(db.String(300), nullable=True)
        commit = db.relationship("AttendanceCommit", back_populates="events")
        student = db.relationship("Student")

    app.models = {
        "Course": Course, "StudentGroup": StudentGroup, "Student": Student,
        "Enrollment": Enrollment, "AttendanceSession": AttendanceSession,
        "Attendance": Attendance, "AttendanceCommit": AttendanceCommit, "AttendanceEvent": AttendanceEvent,
    }

    def teacher_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not web_session.get("teacher_logged_in"):
                return redirect(url_for("teacher_login", next=request.path))
            return view(*args, **kwargs)
        return wrapped

    @app.context_processor
    def inject_globals():
        return {"teacher_logged_in": bool(web_session.get("teacher_logged_in"))}

    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    @app.get("/")
    def index():
        sessions = AttendanceSession.query.order_by(AttendanceSession.session_date.desc(), AttendanceSession.id.desc()).all()
        return render_template("index.html", sessions=sessions)

    @app.route("/teacher/login", methods=["GET", "POST"])
    def teacher_login():
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            expected_user = app.config["TEACHER_USERNAME"]
            expected_password = app.config["TEACHER_PASSWORD"]
            if hmac.compare_digest(username, expected_user) and hmac.compare_digest(password, expected_password):
                web_session.clear()
                web_session["teacher_logged_in"] = True
                flash("Signed in successfully.")
                next_url = request.args.get("next") or request.form.get("next") or url_for("teacher_dashboard")
                if not next_url.startswith("/") or next_url.startswith("//"):
                    next_url = url_for("teacher_dashboard")
                return redirect(next_url)
            flash("Invalid username or password.")
        return render_template("login.html", next=request.args.get("next", ""))

    @app.post("/teacher/logout")
    @teacher_required
    def teacher_logout():
        web_session.clear()
        flash("You have been signed out.")
        return redirect(url_for("index"))

    @app.get("/teacher")
    @teacher_required
    def teacher_dashboard():
        courses = Course.query.order_by(Course.semester, Course.name).all()
        groups = StudentGroup.query.order_by(StudentGroup.course_id, StudentGroup.name).all()
        sessions = AttendanceSession.query.order_by(AttendanceSession.session_date.desc(), AttendanceSession.id.desc()).all()
        return render_template("teacher_dashboard.html", courses=courses, groups=groups, sessions=sessions)

    @app.route("/teacher/courses/new", methods=["GET", "POST"])
    @teacher_required
    def course_new():
        if request.method == "POST":
            name = clean_name(request.form.get("name"))
            semester = clean_name(request.form.get("semester")) or "Semester 1"
            if not name:
                flash("Course name is required.")
            else:
                course = Course(name=name, semester=semester)
                db.session.add(course)
                try:
                    db.session.commit()
                    flash("Course created.")
                    return redirect(url_for("teacher_dashboard"))
                except IntegrityError:
                    db.session.rollback()
                    flash("This course already exists in that semester.")
        return render_template("course_form.html")

    @app.route("/teacher/courses/<int:course_id>/groups/new", methods=["GET", "POST"])
    @teacher_required
    def group_new(course_id):
        course = db.get_or_404(Course, course_id)
        if request.method == "POST":
            name = clean_name(request.form.get("name"))
            if not name:
                flash("Group name is required.")
            else:
                db.session.add(StudentGroup(course_id=course.id, name=name))
                try:
                    db.session.commit()
                    flash("Group created.")
                    return redirect(url_for("teacher_dashboard"))
                except IntegrityError:
                    db.session.rollback()
                    flash("This group already exists for the course.")
        return render_template("group_form.html", course=course)

    @app.route("/teacher/groups/<int:group_id>/import", methods=["GET", "POST"])
    @teacher_required
    def import_students(group_id):
        group = db.get_or_404(StudentGroup, group_id)
        preview = []
        errors = []
        if request.method == "POST":
            uploaded = request.files.get("file")
            if not uploaded or not uploaded.filename:
                flash("Choose a CSV or XLSX file.")
                return redirect(request.url)
            filename = uploaded.filename.lower()
            try:
                if filename.endswith(".csv"):
                    content = uploaded.read().decode("utf-8-sig")
                    sample = content[:4096]
                    try:
                        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
                    except csv.Error:
                        dialect = csv.excel
                    reader = csv.DictReader(io.StringIO(content), dialect=dialect)
                    if not reader.fieldnames:
                        raise ValueError("CSV must have a header row.")
                    headers = {h.strip().casefold(): h for h in reader.fieldnames if h}
                    first_col = next((headers[k] for k in ("first_name", "firstname", "first name", "name") if k in headers), None)
                    surname_col = next((headers[k] for k in ("surname", "last_name", "lastname", "last name", "family name") if k in headers), None)
                    if not first_col or not surname_col:
                        raise ValueError("CSV needs first_name and surname columns.")
                    raw_rows = [(r.get(first_col, ""), r.get(surname_col, "")) for r in reader]
                elif filename.endswith(".xlsx"):
                    from openpyxl import load_workbook
                    wb = load_workbook(uploaded, read_only=True, data_only=True)
                    ws = wb.active
                    all_rows = list(ws.iter_rows(values_only=True))
                    if not all_rows:
                        raise ValueError("The Excel file is empty.")
                    header_values = [str(v or "").strip().casefold() for v in all_rows[0]]
                    first_i = next((header_values.index(k) for k in ("first_name", "firstname", "first name", "name") if k in header_values), None)
                    surname_i = next((header_values.index(k) for k in ("surname", "last_name", "lastname", "last name", "family name") if k in header_values), None)
                    if first_i is None or surname_i is None:
                        raise ValueError("Excel needs first_name and surname columns in the first row.")
                    raw_rows = [(r[first_i] if first_i < len(r) else "", r[surname_i] if surname_i < len(r) else "") for r in all_rows[1:]]
                else:
                    raise ValueError("Unsupported file. Upload .csv or .xlsx.")
                seen = set()
                for line_no, (first, surname) in enumerate(raw_rows, start=2):
                    first, surname = clean_name(str(first or "")), clean_name(str(surname or ""))
                    if not first and not surname:
                        continue
                    if not first or not surname:
                        errors.append(f"Row {line_no}: both first name and surname are required.")
                        continue
                    key = (name_key(first), name_key(surname))
                    if key in seen:
                        errors.append(f"Row {line_no}: duplicate name in the uploaded file: {first} {surname}.")
                        continue
                    seen.add(key)
                    existing = []
                    for enrollment in group.enrollments:
                        student = enrollment.student
                        if name_key(student.first_name) == key[0] and name_key(student.surname) == key[1]:
                            existing.append(student)
                    if existing:
                        preview.append({"first": first, "surname": surname, "action": "Already enrolled"})
                    else:
                        preview.append({"first": first, "surname": surname, "action": "Will add"})
                if errors:
                    return render_template("import_students.html", group=group, preview=preview, errors=errors, pending_rows=None)
                # Commit after preview confirmation; browser posts parsed rows in hidden fields.
                if request.form.get("confirm_import") == "yes":
                    added = 0
                    for row in preview:
                        if row["action"] != "Will add":
                            continue
                        student = Student(first_name=row["first"], surname=row["surname"])
                        db.session.add(student)
                        db.session.flush()
                        db.session.add(Enrollment(group_id=group.id, student_id=student.id))
                        added += 1
                    db.session.commit()
                    flash(f"Import completed: {added} student(s) added. Existing enrollments were preserved.")
                    return redirect(url_for("teacher_dashboard"))
                return render_template("import_students.html", group=group, preview=preview, errors=[], pending_rows=None)
            except Exception as exc:
                db.session.rollback()
                errors.append(str(exc))
                return render_template("import_students.html", group=group, preview=preview, errors=errors, pending_rows=None)
        return render_template("import_students.html", group=group, preview=None, errors=[], pending_rows=None)

    @app.route("/teacher/sessions/new", methods=["GET", "POST"])
    @teacher_required
    def session_new():
        groups = StudentGroup.query.join(Course).order_by(Course.name, StudentGroup.name).all()
        if request.method == "POST":
            try:
                group_id = int(request.form.get("group_id", ""))
                group = db.get_or_404(StudentGroup, group_id)
                session_type = (request.form.get("session_type") or "").upper()
                if session_type not in {"COURSE", "LAB"}:
                    raise ValueError("Choose Course or Lab.")
                session_date = date.fromisoformat(request.form.get("session_date", ""))
                title = clean_name(request.form.get("title")) or None
                code = norm_code(request.form.get("session_code"))
                if len(code) < 4 or len(code) > 40:
                    raise ValueError("Session code must contain between 4 and 40 characters.")
                opens_at = datetime.fromisoformat(request.form.get("opens_at", ""))
                closes_at = datetime.fromisoformat(request.form.get("closes_at", ""))
                if closes_at <= opens_at:
                    raise ValueError("The closing time must be after the opening time.")
                session_obj = AttendanceSession(
                    group_id=group.id, session_type=session_type, session_date=session_date,
                    title=title, code_hash=digest_code(code, app.config["SESSION_CODE_SECRET"]),
                    opens_at=opens_at, closes_at=closes_at, is_open=True,
                )
                db.session.add(session_obj)
                db.session.flush()
                # Initialize all enrolled students as absent.
                for enrollment in group.enrollments:
                    db.session.add(Attendance(session_id=session_obj.id, student_id=enrollment.student_id, status="ABSENT"))
                db.session.add(AttendanceCommit(session_id=session_obj.id, message="Initial attendance register created"))
                db.session.commit()
                flash(f"Session created. Write the session code you entered on the board: {code}")
                return redirect(url_for("teacher_session", session_id=session_obj.id))
            except (ValueError, TypeError) as exc:
                db.session.rollback()
                flash(str(exc) or "Please check the session details.")
        return render_template("session_form.html", groups=groups, today=date.today().isoformat())

    @app.get("/check-in/<int:session_id>")
    def checkin_page(session_id):
        session_obj = db.get_or_404(AttendanceSession, session_id)
        return render_template("checkin.html", session=session_obj, error=None)

    @app.post("/check-in/<int:session_id>")
    def checkin_submit(session_id):
        session_obj = db.get_or_404(AttendanceSession, session_id)
        first_name = clean_name(request.form.get("first_name"))
        surname = clean_name(request.form.get("surname"))
        submitted_code = norm_code(request.form.get("session_code"))

        def fail(message, status=400):
            return render_template("checkin.html", session=session_obj, error=message,
                                   first_name=first_name, surname=surname), status

        if not first_name or not surname or not submitted_code:
            return fail("Enter your first name, surname, and the code written on the board.")
        now = utcnow()
        if not session_obj.is_open or now < session_obj.opens_at or now > session_obj.closes_at:
            return fail("Check-in is closed or outside the allowed time window.", 403)
        submitted_hash = digest_code(submitted_code, app.config["SESSION_CODE_SECRET"])
        if not hmac.compare_digest(submitted_hash, session_obj.code_hash):
            return fail("Incorrect session code. Check the code on the board.", 403)

        enrolled = Enrollment.query.filter_by(group_id=session_obj.group_id).all()
        matches = [
            e.student for e in enrolled
            if name_key(e.student.first_name) == name_key(first_name)
            and name_key(e.student.surname) == name_key(surname)
        ]
        if not matches:
            return fail("No matching student was found in this group's roster. Check the spelling or contact the teacher.", 404)
        if len(matches) > 1:
            return fail("This name matches more than one student in the group. Please contact the teacher.", 409)

        student = matches[0]
        attendance = Attendance.query.filter_by(session_id=session_obj.id, student_id=student.id).first()
        if attendance is None:
            attendance = Attendance(session_id=session_obj.id, student_id=student.id, status="ABSENT")
            db.session.add(attendance)
            db.session.flush()
        if attendance.status == "PRESENT":
            return fail("Your attendance has already been recorded for this session.", 409)
        attendance.status = "PRESENT"
        attendance.checked_in_at = now
        attendance.updated_at = now
        commit = AttendanceCommit(session_id=session_obj.id, message=f"Student check-in: {student.first_name} {student.surname}")
        db.session.add(commit)
        db.session.flush()
        db.session.add(AttendanceEvent(commit_id=commit.id, student_id=student.id,
                                       old_status="ABSENT", new_status="PRESENT", reason="Student smartphone check-in"))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return fail("Attendance may already have been recorded. Please refresh or contact the teacher.", 409)
        return render_template("checkin_success.html", session=session_obj, student=student, checked_in_at=now)

    @app.get("/teacher/sessions/<int:session_id>")
    @teacher_required
    def teacher_session(session_id):
        session_obj = db.get_or_404(AttendanceSession, session_id)
        enrollments = Enrollment.query.filter_by(group_id=session_obj.group_id).all()
        rows = []
        for e in enrollments:
            record = Attendance.query.filter_by(session_id=session_obj.id, student_id=e.student_id).first()
            rows.append((e.student, record.status if record else "ABSENT", record.checked_in_at if record else None))
        rows.sort(key=lambda x: (x[0].surname.casefold(), x[0].first_name.casefold()))
        commits = AttendanceCommit.query.filter_by(session_id=session_obj.id).order_by(AttendanceCommit.created_at.desc()).all()
        return render_template("teacher_session.html", session=session_obj, rows=rows, commits=commits)

    @app.post("/teacher/sessions/<int:session_id>/close")
    @teacher_required
    def close_session(session_id):
        session_obj = db.get_or_404(AttendanceSession, session_id)
        session_obj.is_open = False
        db.session.commit()
        flash("Check-in closed.")
        return redirect(url_for("teacher_session", session_id=session_id))

    @app.post("/teacher/sessions/<int:session_id>/open")
    @teacher_required
    def open_session(session_id):
        session_obj = db.get_or_404(AttendanceSession, session_id)
        session_obj.is_open = True
        db.session.commit()
        flash("Check-in reopened. The original time window still applies.")
        return redirect(url_for("teacher_session", session_id=session_id))

    @app.post("/teacher/sessions/<int:session_id>/correct")
    @teacher_required
    def correct_attendance(session_id):
        session_obj = db.get_or_404(AttendanceSession, session_id)
        student_id = request.form.get("student_id", type=int)
        new_status = (request.form.get("status") or "").upper()
        reason = clean_name(request.form.get("reason"))
        if new_status not in {"PRESENT", "ABSENT"}:
            flash("Invalid attendance status.")
            return redirect(url_for("teacher_session", session_id=session_id))
        enrollment = Enrollment.query.filter_by(group_id=session_obj.group_id, student_id=student_id).first()
        if not enrollment:
            flash("Student is not enrolled in this group.")
            return redirect(url_for("teacher_session", session_id=session_id))
        record = Attendance.query.filter_by(session_id=session_id, student_id=student_id).first()
        if record is None:
            record = Attendance(session_id=session_id, student_id=student_id, status="ABSENT")
            db.session.add(record)
            db.session.flush()
        old_status = record.status
        if old_status == new_status:
            flash("Attendance already has that status.")
            return redirect(url_for("teacher_session", session_id=session_id))
        record.status = new_status
        record.updated_at = utcnow()
        if new_status == "ABSENT":
            record.checked_in_at = None
        commit = AttendanceCommit(session_id=session_id, message="Teacher correction")
        db.session.add(commit)
        db.session.flush()
        db.session.add(AttendanceEvent(commit_id=commit.id, student_id=student_id, old_status=old_status,
                                       new_status=new_status, reason=reason or "Teacher correction"))
        db.session.commit()
        flash("Attendance correction saved in history.")
        return redirect(url_for("teacher_session", session_id=session_id))

    @app.get("/teacher/reports")
    @teacher_required
    def reports():
        courses = Course.query.order_by(Course.semester, Course.name).all()
        course_id = request.args.get("course_id", type=int)
        selected_course = db.session.get(Course, course_id) if course_id else None
        sessions_query = AttendanceSession.query.join(StudentGroup).join(Course)
        if selected_course:
            sessions_query = sessions_query.filter(StudentGroup.course_id == selected_course.id)
        finalized_sessions = sessions_query.filter(AttendanceSession.is_open.is_(False)).order_by(AttendanceSession.session_date).all()
        relevant_group_ids = {s.group_id for s in finalized_sessions}
        group_filter = request.args.get("group_id", type=int)
        if group_filter:
            finalized_sessions = [s for s in finalized_sessions if s.group_id == group_filter]
            relevant_group_ids = {s.group_id for s in finalized_sessions}
        stats = {}
        for sess in finalized_sessions:
            for enrollment in Enrollment.query.filter_by(group_id=sess.group_id).all():
                key = (enrollment.student.id, sess.group_id)
                stats.setdefault(key, {"student": enrollment.student, "group": sess.group, "course": sess.group.course,
                                       "course_present": 0, "course_total": 0, "lab_present": 0, "lab_total": 0})
                record = Attendance.query.filter_by(session_id=sess.id, student_id=enrollment.student_id).first()
                present = bool(record and record.status == "PRESENT")
                kind = "course" if sess.session_type == "COURSE" else "lab"
                stats[key][kind + "_total"] += 1
                stats[key][kind + "_present"] += int(present)
        rows = []
        for stat in stats.values():
            total = stat["course_total"] + stat["lab_total"]
            present = stat["course_present"] + stat["lab_present"]
            stat["total"] = total
            stat["present"] = present
            stat["percentage"] = round(present * 100 / total, 2) if total else None
            rows.append(stat)
        rows.sort(key=lambda r: (r["course"].name.casefold(), r["group"].name.casefold(),
                                 r["student"].surname.casefold(), r["student"].first_name.casefold()))
        groups = StudentGroup.query.order_by(StudentGroup.name).all()
        return render_template("reports.html", courses=courses, groups=groups, rows=rows,
                               selected_course_id=course_id, selected_group_id=group_filter)

    @app.get("/teacher/reports.csv")
    @teacher_required
    def reports_csv():
        response = make_response()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Course", "Group", "First name", "Surname", "Course present", "Course sessions",
                         "Lab present", "Lab sessions", "Total present", "Total sessions", "Attendance %"])
        sessions = AttendanceSession.query.filter_by(is_open=False).all()
        stats = {}
        for sess in sessions:
            for e in Enrollment.query.filter_by(group_id=sess.group_id).all():
                key = (sess.group_id, e.student_id)
                s = stats.setdefault(key, {"course": sess.group.course.name, "group": sess.group.name,
                                           "student": e.student, "cp": 0, "ct": 0, "lp": 0, "lt": 0})
                rec = Attendance.query.filter_by(session_id=sess.id, student_id=e.student_id).first()
                present = bool(rec and rec.status == "PRESENT")
                prefix = "c" if sess.session_type == "COURSE" else "l"
                s[prefix + "t"] += 1
                s[prefix + "p"] += int(present)
        for s in sorted(stats.values(), key=lambda x: (x["course"], x["group"], x["student"].surname, x["student"].first_name)):
            total = s["ct"] + s["lt"]
            present = s["cp"] + s["lp"]
            writer.writerow([s["course"], s["group"], s["student"].first_name, s["student"].surname,
                             s["cp"], s["ct"], s["lp"], s["lt"], present, total,
                             f"{present * 100 / total:.2f}" if total else ""])
        response.data = "\ufeff" + output.getvalue()
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        response.headers["Content-Disposition"] = "attachment; filename=attendance-report.csv"
        return response

    @app.cli.command("init-db")
    def init_db():
        with app.app_context():
            db.create_all()
        print("Database tables created.")

    @app.cli.command("demo-data")
    def demo_data():
        with app.app_context():
            db.create_all()
            if Course.query.first():
                print("Data already exists; skipping demo data.")
                return
            course = Course(name="Software Engineering", semester="Semester 1")
            group = StudentGroup(name="Group 1", course=course)
            students = [Student(first_name="Amine", surname="Benali"),
                        Student(first_name="Sara", surname="Mansouri"),
                        Student(first_name="Yacine", surname="Haddad")]
            db.session.add_all([course, group, *students])
            db.session.flush()
            for student in students:
                db.session.add(Enrollment(group_id=group.id, student_id=student.id))
            now = utcnow()
            code = "K7M4P9"
            sess = AttendanceSession(group_id=group.id, session_type="COURSE", session_date=date.today(),
                                     title="Demo session", code_hash=digest_code(code, app.config["SESSION_CODE_SECRET"]),
                                     opens_at=now - timedelta(minutes=5), closes_at=now + timedelta(hours=1), is_open=True)
            db.session.add(sess)
            db.session.flush()
            for student in students:
                db.session.add(Attendance(session_id=sess.id, student_id=student.id, status="ABSENT"))
            db.session.add(AttendanceCommit(session_id=sess.id, message="Initial attendance register created"))
            db.session.commit()
            print(f"Demo session ID: {sess.id}; board code: {code}")
            print("Demo teacher login uses configured TEACHER_USERNAME / TEACHER_PASSWORD.")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
