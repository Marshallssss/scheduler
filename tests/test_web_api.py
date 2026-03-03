from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from scheduler.web_app import create_app


def _iso(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _bootstrap_admin(client: TestClient, username: str = "admin", password: str = "admin123") -> dict:
    resp = client.post(
        "/api/auth/bootstrap-admin",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 201
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _login(client: TestClient, username: str, password: str) -> dict:
    resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_web_frontend_index_and_health(settings):
    app = create_app(settings)
    client = TestClient(app)

    index_resp = client.get("/")
    assert index_resp.status_code == 200
    assert "项目排程与进度管理平台" in index_resp.text

    health_resp = client.get("/api/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "ok"


def test_web_requires_login(settings):
    app = create_app(settings)
    client = TestClient(app)

    unauthorized = client.get(f"/api/projects?as_of={date.today().isoformat()}")
    assert unauthorized.status_code == 401


def test_web_api_project_goal_progress_flow(settings):
    app = create_app(settings)
    client = TestClient(app)
    admin_headers = _bootstrap_admin(client)

    project_resp = client.post(
        "/api/projects",
        headers=admin_headers,
        json={
            "name": "Web Project",
            "deadline": _iso(40),
            "participants": [
                {"name": "Owner", "email": "owner@example.com"},
                {"name": "Dev", "email": "dev@example.com"},
            ],
        },
    )
    assert project_resp.status_code == 201
    project = project_resp.json()

    phase_resp = client.post(
        "/api/phases",
        headers=admin_headers,
        json={
            "project_id": project["id"],
            "name": "Phase A",
            "objective": "Deliver first milestone",
        },
    )
    assert phase_resp.status_code == 201
    phase = phase_resp.json()

    owner_id = project["participants"][0]["id"]
    goal_resp = client.post(
        "/api/goals",
        headers=admin_headers,
        json={
            "phase_id": phase["id"],
            "title": "Goal 1",
            "owner_participant_id": owner_id,
            "milestone_date": _iso(5),
            "deadline": _iso(10),
            "weight": 2,
        },
    )
    assert goal_resp.status_code == 201
    goal = goal_resp.json()

    progress_resp = client.post(
        "/api/progress",
        headers=admin_headers,
        json={
            "goal_id": goal["id"],
            "date": date.today().isoformat(),
            "progress_percent": 35,
            "updated_by": "web_tester",
            "note": None,
        },
    )
    assert progress_resp.status_code == 201

    dashboard_resp = client.get(
        f"/api/projects?as_of={date.today().isoformat()}",
        headers=admin_headers,
    )
    assert dashboard_resp.status_code == 200
    payload = dashboard_resp.json()

    assert len(payload["projects"]) == 1
    dashboard_project = payload["projects"][0]
    assert dashboard_project["summary"]["total_goals"] == 1
    assert dashboard_project["summary"]["completed_goals"] == 0
    assert dashboard_project["summary"]["progress_percent"] == 35.0

    dashboard_goal = dashboard_project["phases"][0]["goals"][0]
    assert dashboard_goal["title"] == "Goal 1"
    assert dashboard_goal["progress_percent"] == 35.0


def test_web_api_progress_rollback_requires_note(settings):
    app = create_app(settings)
    client = TestClient(app)
    admin_headers = _bootstrap_admin(client)

    project_resp = client.post(
        "/api/projects",
        headers=admin_headers,
        json={
            "name": "Rollback API",
            "deadline": _iso(30),
            "participants": [{"name": "Owner", "email": "owner@example.com"}],
        },
    )
    project = project_resp.json()

    phase_resp = client.post(
        "/api/phases",
        headers=admin_headers,
        json={
            "project_id": project["id"],
            "name": "Phase A",
            "objective": "Target",
        },
    )
    phase = phase_resp.json()

    owner_id = project["participants"][0]["id"]
    goal_resp = client.post(
        "/api/goals",
        headers=admin_headers,
        json={
            "phase_id": phase["id"],
            "title": "Goal",
            "owner_participant_id": owner_id,
            "milestone_date": _iso(3),
            "deadline": _iso(6),
            "weight": 1,
        },
    )
    goal = goal_resp.json()

    first = client.post(
        "/api/progress",
        headers=admin_headers,
        json={
            "goal_id": goal["id"],
            "date": date.today().isoformat(),
            "progress_percent": 80,
            "updated_by": "web_tester",
            "note": None,
        },
    )
    assert first.status_code == 201

    rollback = client.post(
        "/api/progress",
        headers=admin_headers,
        json={
            "goal_id": goal["id"],
            "date": date.today().isoformat(),
            "progress_percent": 60,
            "updated_by": "web_tester",
            "note": None,
        },
    )
    assert rollback.status_code == 400
    assert "回退" in rollback.json()["detail"]


def test_web_api_issue_goal_progress_by_remaining_di(settings):
    app = create_app(settings)
    client = TestClient(app)
    admin_headers = _bootstrap_admin(client)

    project_resp = client.post(
        "/api/projects",
        headers=admin_headers,
        json={
            "name": "Issue API",
            "deadline": _iso(30),
            "participants": [{"name": "Owner", "email": "owner@example.com"}],
        },
    )
    project = project_resp.json()

    phase_resp = client.post(
        "/api/phases",
        headers=admin_headers,
        json={
            "project_id": project["id"],
            "name": "Phase A",
            "objective": "Fix issues",
        },
    )
    phase = phase_resp.json()
    owner_id = project["participants"][0]["id"]

    goal_resp = client.post(
        "/api/goals",
        headers=admin_headers,
        json={
            "phase_id": phase["id"],
            "title": "Issue Goal",
            "owner_participant_id": owner_id,
            "goal_type": "issue",
            "issue_module": "支付",
            "issue_total_di": 80,
            "milestone_date": _iso(3),
            "deadline": _iso(6),
            "weight": 3,
        },
    )
    assert goal_resp.status_code == 201
    goal = goal_resp.json()
    assert goal["goal_type"] == "issue"
    assert goal["issue_total_di"] == 80

    progress_resp = client.post(
        "/api/progress",
        headers=admin_headers,
        json={
            "goal_id": goal["id"],
            "date": date.today().isoformat(),
            "remaining_di": 20,
            "updated_by": "web_tester",
            "note": None,
        },
    )
    assert progress_resp.status_code == 201
    assert progress_resp.json()["progress_percent"] == 75.0
    assert progress_resp.json()["remaining_di"] == 20

    dashboard_resp = client.get(
        f"/api/projects?as_of={date.today().isoformat()}",
        headers=admin_headers,
    )
    dashboard_goal = dashboard_resp.json()["projects"][0]["phases"][0]["goals"][0]
    assert dashboard_goal["goal_type"] == "issue"
    assert dashboard_goal["remaining_di"] == 20
    assert dashboard_goal["progress_percent"] == 75.0


def test_owner_permissions(settings):
    app = create_app(settings)
    client = TestClient(app)
    admin_headers = _bootstrap_admin(client)

    project_resp = client.post(
        "/api/projects",
        headers=admin_headers,
        json={
            "name": "Permission Project",
            "deadline": _iso(60),
            "participants": [
                {"name": "OwnerA", "email": "a@example.com"},
                {"name": "OwnerB", "email": "b@example.com"},
            ],
        },
    )
    assert project_resp.status_code == 201
    project = project_resp.json()
    owner_a = project["participants"][0]["id"]
    owner_b = project["participants"][1]["id"]

    phase_resp = client.post(
        "/api/phases",
        headers=admin_headers,
        json={
            "project_id": project["id"],
            "name": "Phase P",
            "objective": "Obj",
        },
    )
    assert phase_resp.status_code == 201
    phase_id = phase_resp.json()["id"]

    goal_a_resp = client.post(
        "/api/goals",
        headers=admin_headers,
        json={
            "phase_id": phase_id,
            "title": "GoalA",
            "owner_participant_id": owner_a,
            "milestone_date": _iso(4),
            "deadline": _iso(8),
            "weight": 1,
        },
    )
    goal_b_resp = client.post(
        "/api/goals",
        headers=admin_headers,
        json={
            "phase_id": phase_id,
            "title": "GoalB",
            "owner_participant_id": owner_b,
            "milestone_date": _iso(5),
            "deadline": _iso(9),
            "weight": 1,
        },
    )
    assert goal_a_resp.status_code == 201
    assert goal_b_resp.status_code == 201
    goal_a = goal_a_resp.json()["id"]
    goal_b = goal_b_resp.json()["id"]

    create_user_resp = client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={
            "username": "owner1",
            "password": "owner123",
            "role": "owner",
            "participant_id": owner_a,
        },
    )
    assert create_user_resp.status_code == 201

    owner_headers = _login(client, "owner1", "owner123")

    forbidden_project_create = client.post(
        "/api/projects",
        headers=owner_headers,
        json={
            "name": "blocked",
            "deadline": _iso(20),
            "participants": [{"name": "x", "email": "x@example.com"}],
        },
    )
    assert forbidden_project_create.status_code == 403

    owner_projects = client.get(f"/api/projects?as_of={date.today().isoformat()}", headers=owner_headers)
    assert owner_projects.status_code == 200
    assert len(owner_projects.json()["projects"]) == 1

    forbidden_progress = client.post(
        "/api/progress",
        headers=owner_headers,
        json={
            "goal_id": goal_b,
            "date": date.today().isoformat(),
            "progress_percent": 20,
            "updated_by": "owner1",
            "note": None,
        },
    )
    assert forbidden_progress.status_code == 403

    allowed_progress = client.post(
        "/api/progress",
        headers=owner_headers,
        json={
            "goal_id": goal_a,
            "date": date.today().isoformat(),
            "progress_percent": 45,
            "updated_by": "owner1",
            "note": None,
        },
    )
    assert allowed_progress.status_code == 201
