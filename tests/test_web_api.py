from __future__ import annotations

from io import BytesIO
from datetime import date, timedelta

from docx import Document
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
            "requirement_total_count": 20,
            "requirement_done_count": 7,
            "updated_by": "web_tester",
            "note": None,
        },
    )
    assert progress_resp.status_code == 201
    assert progress_resp.json()["progress_percent"] == 35.0
    assert progress_resp.json()["requirement_total_count"] == 20
    assert progress_resp.json()["requirement_done_count"] == 7

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
    assert dashboard_goal["requirement_total_count"] == 20
    assert dashboard_goal["requirement_done_count"] == 7


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
            "note": "用于支付模块缺陷修复",
            "owner_participant_id": owner_id,
            "goal_type": "issue",
            "issue_module": "支付",
            "issue_total_di": 80,
            "issue_target_di": 10,
            "milestone_date": _iso(3),
            "deadline": _iso(6),
        },
    )
    assert goal_resp.status_code == 201
    goal = goal_resp.json()
    assert goal["goal_type"] == "issue"
    assert goal["issue_total_di"] == 80
    assert goal["issue_target_di"] == 10
    assert goal["weight"] == 1.0
    assert goal["note"] == "用于支付模块缺陷修复"

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
    assert progress_resp.json()["progress_percent"] == 85.71
    assert progress_resp.json()["remaining_di"] == 20

    dashboard_resp = client.get(
        f"/api/projects?as_of={date.today().isoformat()}",
        headers=admin_headers,
    )
    dashboard_goal = dashboard_resp.json()["projects"][0]["phases"][0]["goals"][0]
    assert dashboard_goal["goal_type"] == "issue"
    assert dashboard_goal["remaining_di"] == 20
    assert dashboard_goal["progress_percent"] == 85.71
    assert dashboard_goal["issue_target_di"] == 10
    assert dashboard_goal["note"] == "用于支付模块缺陷修复"


def test_web_api_task_goal_progress_by_percent(settings):
    app = create_app(settings)
    client = TestClient(app)
    admin_headers = _bootstrap_admin(client)

    project_resp = client.post(
        "/api/projects",
        headers=admin_headers,
        json={
            "name": "Task API",
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
            "objective": "Track basic tasks",
        },
    )
    phase = phase_resp.json()
    owner_id = project["participants"][0]["id"]

    goal_resp = client.post(
        "/api/goals",
        headers=admin_headers,
        json={
            "phase_id": phase["id"],
            "title": "Basic Task Goal",
            "note": "跟进客户对账与回执",
            "owner_participant_id": owner_id,
            "goal_type": "task",
            "milestone_date": _iso(3),
            "deadline": _iso(6),
        },
    )
    assert goal_resp.status_code == 201
    goal = goal_resp.json()
    assert goal["goal_type"] == "task"
    assert goal["note"] == "跟进客户对账与回执"

    progress_resp = client.post(
        "/api/progress",
        headers=admin_headers,
        json={
            "goal_id": goal["id"],
            "date": date.today().isoformat(),
            "progress_percent": 55,
            "progress_state": "delayed",
            "risk_note": "外部依赖延期",
            "updated_by": "web_tester",
            "note": None,
        },
    )
    assert progress_resp.status_code == 201
    assert progress_resp.json()["progress_percent"] == 55.0
    assert progress_resp.json()["requirement_total_count"] is None
    assert progress_resp.json()["requirement_done_count"] is None
    assert progress_resp.json()["progress_state"] == "delayed"
    assert progress_resp.json()["risk_note"] == "外部依赖延期"

    dashboard_resp = client.get(
        f"/api/projects?as_of={date.today().isoformat()}",
        headers=admin_headers,
    )
    dashboard_goal = dashboard_resp.json()["projects"][0]["phases"][0]["goals"][0]
    assert dashboard_goal["goal_type"] == "task"
    assert dashboard_goal["progress_percent"] == 55.0
    assert dashboard_goal["note"] == "跟进客户对账与回执"
    assert dashboard_goal["progress_state"] == "delayed"
    assert dashboard_goal["risk_note"] == "外部依赖延期"


def test_admin_can_update_project_and_participants(settings):
    app = create_app(settings)
    client = TestClient(app)
    admin_headers = _bootstrap_admin(client)

    project_resp = client.post(
        "/api/projects",
        headers=admin_headers,
        json={
            "name": "Project Old",
            "deadline": _iso(40),
            "participants": [
                {"name": "Owner", "email": "owner@example.com"},
                {"name": "Dev", "email": "dev@example.com"},
            ],
        },
    )
    assert project_resp.status_code == 201
    project = project_resp.json()
    project_id = project["id"]
    owner_id = project["participants"][0]["id"]

    phase_resp = client.post(
        "/api/phases",
        headers=admin_headers,
        json={
            "project_id": project_id,
            "name": "Phase A",
            "objective": "Objective",
        },
    )
    assert phase_resp.status_code == 201
    phase_id = phase_resp.json()["id"]

    goal_resp = client.post(
        "/api/goals",
        headers=admin_headers,
        json={
            "phase_id": phase_id,
            "title": "Goal A",
            "owner_participant_id": owner_id,
            "milestone_date": _iso(3),
            "deadline": _iso(6),
            "weight": 1,
        },
    )
    assert goal_resp.status_code == 201

    update_resp = client.put(
        f"/api/projects/{project_id}",
        headers=admin_headers,
        json={
            "name": "Project New",
            "deadline": _iso(45),
            "participants": [
                {"name": "Owner Renamed", "email": "owner@example.com"},
                {"name": "QA", "email": "qa@example.com"},
            ],
        },
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["name"] == "Project New"
    assert updated["deadline"] == _iso(45)
    assert len(updated["participants"]) == 2
    participant_emails = {item["email"] for item in updated["participants"]}
    assert participant_emails == {"owner@example.com", "qa@example.com"}
    owner = next(item for item in updated["participants"] if item["email"] == "owner@example.com")
    assert owner["name"] == "Owner Renamed"

    remove_owner_resp = client.put(
        f"/api/projects/{project_id}",
        headers=admin_headers,
        json={
            "participants": [
                {"name": "QA", "email": "qa@example.com"},
            ],
        },
    )
    assert remove_owner_resp.status_code == 400
    assert "存在负责人目标" in remove_owner_resp.json()["detail"]


def test_report_preview_dispatch_preferences_and_send_now(settings):
    app = create_app(settings)
    client = TestClient(app)
    admin_headers = _bootstrap_admin(client)

    project_resp = client.post(
        "/api/projects",
        headers=admin_headers,
        json={
            "name": "Report API",
            "deadline": _iso(30),
            "participants": [{"name": "Owner", "email": "owner@example.com"}],
        },
    )
    assert project_resp.status_code == 201
    project = project_resp.json()

    phase_resp = client.post(
        "/api/phases",
        headers=admin_headers,
        json={
            "project_id": project["id"],
            "name": "Report Phase",
            "objective": "Report Objective",
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
            "title": "Report Goal",
            "owner_participant_id": owner_id,
            "milestone_date": _iso(2),
            "deadline": _iso(5),
            "weight": 1,
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
            "requirement_total_count": 20,
            "requirement_done_count": 6,
            "progress_state": "delayed",
            "risk_note": "供应商联调延迟",
            "updated_by": "web_tester",
            "note": None,
        },
    )
    assert progress_resp.status_code == 201

    preview_resp = client.get(
        f"/api/reports/preview?period=daily&date={date.today().isoformat()}",
        headers=admin_headers,
    )
    assert preview_resp.status_code == 200
    preview = preview_resp.json()
    assert preview["period"] == "daily"
    assert "项目日报" in preview["subject"]
    assert "owner@example.com" in preview["default_recipients"]
    assert isinstance(preview["markdown"], str) and preview["markdown"]
    assert isinstance(preview["html"], str) and preview["html"]
    assert "目标概览图表" in preview["markdown"]
    assert "目标明细（汇总）" in preview["markdown"]
    assert "风险项目" in preview["markdown"]
    assert "class=\"report-chart-card\"" in preview["markdown"]
    assert "| 项目 | 阶段 | 目标 | 负责人 | 完成率 | 进度状态 | 权重 | 里程碑 | 截止日期 | 风险项目 |" in preview["markdown"]
    assert "**30.00%**" in preview["markdown"]
    assert "进度delay；供应商联调延迟" in preview["markdown"]
    assert "<!DOCTYPE html>" in preview["html"]
    assert "report-chart-card" in preview["html"]

    render_html_resp = client.post(
        "/api/reports/render-html",
        headers=admin_headers,
        json={"markdown": preview["markdown"], "subject": preview["subject"]},
    )
    assert render_html_resp.status_code == 200
    assert "report-doc" in render_html_resp.json()["html"]

    export_docx_resp = client.get(
        f"/api/reports/export-docx?period=daily&date={date.today().isoformat()}",
        headers=admin_headers,
    )
    assert export_docx_resp.status_code == 200
    assert export_docx_resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "attachment;" in export_docx_resp.headers["content-disposition"]
    assert export_docx_resp.content.startswith(b"PK")
    exported_doc = Document(BytesIO(export_docx_resp.content))
    exported_text = "\n".join(item.text for item in exported_doc.paragraphs)
    assert "项目日报" in exported_text
    assert "目标概览图表" in exported_text

    update_pref = client.put(
        "/api/report-dispatch/preferences/daily",
        headers=admin_headers,
        json={
            "send_time": "18:30",
            "recipients": ["owner@example.com"],
            "enabled": True,
        },
    )
    assert update_pref.status_code == 200
    pref = update_pref.json()["preference"]
    assert pref["period"] == "daily"
    assert pref["send_time"] == "18:30"
    assert pref["recipients"] == ["owner@example.com"]
    assert pref["enabled"] is True

    list_pref = client.get("/api/report-dispatch/preferences", headers=admin_headers)
    assert list_pref.status_code == 200
    daily_pref = next(item for item in list_pref.json()["preferences"] if item["period"] == "daily")
    assert daily_pref["send_time"] == "18:30"

    send_now_resp = client.post(
        "/api/reports/send-now",
        headers=admin_headers,
        json={
            "period": "daily",
            "run_date": date.today().isoformat(),
            "markdown": "# 手工日报\n\n测试内容。",
            "recipients": ["owner@example.com"],
            "skip_today_schedule": True,
        },
    )
    assert send_now_resp.status_code == 200
    send_now = send_now_resp.json()
    assert send_now["status"] == "failed"
    assert send_now["skip_today_schedule"] is True
    assert send_now["recipients"] == ["owner@example.com"]

    list_pref_after_send = client.get("/api/report-dispatch/preferences", headers=admin_headers)
    assert list_pref_after_send.status_code == 200
    daily_after = next(item for item in list_pref_after_send.json()["preferences"] if item["period"] == "daily")
    assert daily_after["skip_once_date"] == date.today().isoformat()


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


def test_admin_can_update_and_delete_phase_goal(settings):
    app = create_app(settings)
    client = TestClient(app)
    admin_headers = _bootstrap_admin(client)

    project_resp = client.post(
        "/api/projects",
        headers=admin_headers,
        json={
            "name": "CRUD Project",
            "deadline": _iso(40),
            "participants": [{"name": "Owner", "email": "owner@example.com"}],
        },
    )
    assert project_resp.status_code == 201
    project = project_resp.json()

    phase_resp = client.post(
        "/api/phases",
        headers=admin_headers,
        json={
            "project_id": project["id"],
            "name": "Phase Old",
            "objective": "old objective",
        },
    )
    assert phase_resp.status_code == 201
    phase_id = phase_resp.json()["id"]

    update_phase_resp = client.put(
        f"/api/phases/{phase_id}",
        headers=admin_headers,
        json={"name": "Phase New", "objective": "new objective"},
    )
    assert update_phase_resp.status_code == 200
    assert update_phase_resp.json()["name"] == "Phase New"

    owner_id = project["participants"][0]["id"]
    goal_resp = client.post(
        "/api/goals",
        headers=admin_headers,
        json={
            "phase_id": phase_id,
            "title": "Goal Old",
            "owner_participant_id": owner_id,
            "milestone_date": _iso(3),
            "deadline": _iso(8),
            "weight": 1,
        },
    )
    assert goal_resp.status_code == 201
    goal_id = goal_resp.json()["id"]

    update_goal_resp = client.put(
        f"/api/goals/{goal_id}",
        headers=admin_headers,
        json={"title": "Goal New", "weight": 2},
    )
    assert update_goal_resp.status_code == 200
    assert update_goal_resp.json()["title"] == "Goal New"
    assert update_goal_resp.json()["weight"] == 2

    delete_goal_resp = client.delete(f"/api/goals/{goal_id}", headers=admin_headers)
    assert delete_goal_resp.status_code == 204

    delete_phase_resp = client.delete(f"/api/phases/{phase_id}", headers=admin_headers)
    assert delete_phase_resp.status_code == 204


def test_web_api_smtp_settings_tab_api(settings):
    app = create_app(settings)
    client = TestClient(app)
    admin_headers = _bootstrap_admin(client)

    get_resp = client.get("/api/settings/smtp", headers=admin_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["smtp_port"] == 587

    put_resp = client.put(
        "/api/settings/smtp",
        headers=admin_headers,
        json={
            "smtp_host": "smtp.mail.local",
            "smtp_port": 465,
            "smtp_user": "bot@example.com",
            "smtp_pass": "secret-pass",
            "mail_from": "pm-bot@example.com",
        },
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["smtp_host"] == "smtp.mail.local"
    assert put_resp.json()["smtp_port"] == 465

    check_resp = client.get("/api/settings/smtp", headers=admin_headers)
    assert check_resp.status_code == 200
    payload = check_resp.json()
    assert payload["smtp_host"] == "smtp.mail.local"
    assert payload["smtp_port"] == 465
    assert payload["smtp_user"] == "bot@example.com"
    assert payload["smtp_pass"] == "secret-pass"
    assert payload["mail_from"] == "pm-bot@example.com"


def test_web_api_smtp_settings_requires_admin(settings):
    app = create_app(settings)
    client = TestClient(app)
    admin_headers = _bootstrap_admin(client)

    project_resp = client.post(
        "/api/projects",
        headers=admin_headers,
        json={
            "name": "SMTP Role",
            "deadline": _iso(20),
            "participants": [{"name": "Owner", "email": "owner@example.com"}],
        },
    )
    owner_pid = project_resp.json()["participants"][0]["id"]
    create_owner = client.post(
        "/api/auth/users",
        headers=admin_headers,
        json={
            "username": "owner1",
            "password": "owner123",
            "role": "owner",
            "participant_id": owner_pid,
        },
    )
    assert create_owner.status_code == 201
    owner_headers = _login(client, "owner1", "owner123")

    unauthorized_get = client.get("/api/settings/smtp", headers=owner_headers)
    assert unauthorized_get.status_code == 403

    unauthorized_put = client.put(
        "/api/settings/smtp",
        headers=owner_headers,
        json={
            "smtp_host": "smtp.mail.local",
            "smtp_port": 587,
            "smtp_user": "",
            "smtp_pass": "",
            "mail_from": "",
        },
    )
    assert unauthorized_put.status_code == 403
