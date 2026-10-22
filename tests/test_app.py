from datetime import date, timedelta
import pytest
from app import create_app, db, utcnow, digest_code


@pytest.fixture()
def app_and_session():
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "SESSION_CODE_SECRET": "test-code-secret",
        "TEACHER_USERNAME": "teacher",
        "TEACHER_PASSWORD": "test-password",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
    })
    with app.app_context():
        db.create_all()
        m = app.models
        course = m["Course"](name="Software Engineering", semester="S1")
        group = m["StudentGroup"](name="Group 1", course=course)
        student = m["Student"](first_name="Amine", surname="Benali")
        db.session.add_all([course, group, student])
        db.session.flush()
        db.session.add(m["Enrollment"](group_id=group.id, student_id=student.id))
        now = utcnow()
        session = m["AttendanceSession"](
            group_id=group.id, session_type="COURSE", session_date=date.today(),
            title="Test", code_hash=digest_code("K7M4P9", app.config["SESSION_CODE_SECRET"]),
            opens_at=now - timedelta(minutes=1), closes_at=now + timedelta(minutes=20), is_open=True
        )
        db.session.add(session)
        db.session.flush()
        db.session.add(m["Attendance"](session_id=session.id, student_id=student.id, status="ABSENT"))
        db.session.commit()
        sid = session.id
    yield app, sid
    with app.app_context():
        db.drop_all()


def test_valid_checkin(app_and_session):
    app, sid = app_and_session
    response = app.test_client().post(f"/check-in/{sid}", data={
        "first_name": "Amine", "surname": "Benali", "session_code": "K7M4P9"
    })
    assert response.status_code == 200
    with app.app_context():
        record = app.models["Attendance"].query.one()
        assert record.status == "PRESENT"
        assert record.checked_in_at is not None


def test_wrong_code_rejected(app_and_session):
    app, sid = app_and_session
    response = app.test_client().post(f"/check-in/{sid}", data={
        "first_name": "Amine", "surname": "Benali", "session_code": "wrong"
    })
    assert response.status_code == 403


def test_duplicate_checkin_rejected(app_and_session):
    app, sid = app_and_session
    client = app.test_client()
    data = {"first_name": "Amine", "surname": "Benali", "session_code": "K7M4P9"}
    assert client.post(f"/check-in/{sid}", data=data).status_code == 200
    assert client.post(f"/check-in/{sid}", data=data).status_code == 409


def test_teacher_routes_require_login(app_and_session):
    app, _ = app_and_session
    response = app.test_client().get("/teacher")
    assert response.status_code == 302
    assert "/teacher/login" in response.location


def test_teacher_login(app_and_session):
    app, _ = app_and_session
    client = app.test_client()
    response = client.post("/teacher/login", data={"username": "teacher", "password": "test-password"})
    assert response.status_code == 302
    assert client.get("/teacher").status_code == 200
