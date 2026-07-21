from pathlib import Path
import re


CI_WORKFLOW = Path(".github/workflows/ci.yml")
DEPENDABOT_CONFIG = Path(".github/dependabot.yml")


def test_ci_runs_the_same_quality_checks_used_locally() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "python -m ruff check" in workflow
    assert "python -m pytest" in workflow
    assert "--cov=app" in workflow
    assert "--cov-fail-under=80" in workflow
    assert "TEST_DATABASE_URL:" in workflow
    assert "image: postgres:16-alpine" in workflow
    assert "python -m alembic upgrade head" in workflow
    assert "docker compose -f docker-compose.yml config --quiet" in workflow
    assert "docker build --tag tiny-provisioner:ci ." in workflow
    assert "curl --fail" in workflow


def test_ci_uses_least_privilege_and_immutable_actions() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    action_references = re.findall(r"^\s*uses:\s*([^\s]+)", workflow, flags=re.MULTILINE)

    assert "permissions:\n  contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert action_references
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference) for reference in action_references)


def test_dependabot_tracks_python_and_action_dependencies() -> None:
    config = DEPENDABOT_CONFIG.read_text(encoding="utf-8")

    assert "package-ecosystem: pip" in config
    assert "package-ecosystem: github-actions" in config
    assert config.count("interval: weekly") == 2
