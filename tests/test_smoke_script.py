from pathlib import Path


def test_smoke_script_documents_full_lifecycle() -> None:
    script = Path("scripts/smoke_test.py").read_text()

    assert "/auth/register" in script
    assert "/resources" in script
    assert "/stop" in script
    assert "/start" in script
    assert "DELETE" in script
    assert "target_state=\"deleted\"" in script
    assert "--check-workload-url" in script
    assert "--workload-proxy-url" in script
    assert "Host" in script
    assert "--pause-before-delete" in script
    assert "exc.code in expected" in script
    assert "smoke account:" in script
    assert "Workload URL did not become reachable" in script
