from pathlib import Path


def test_remote_ssh_setup_documents_security_shape() -> None:
    runbook = Path("docs/REMOTE_SSH_SETUP.md").read_text()

    assert "provisioner" in runbook
    assert "Do not SSH as `root`" in runbook
    assert "PasswordAuthentication no" in runbook
    assert "PermitRootLogin no" in runbook
    assert "Do not store the private key in Git" in runbook
    assert "tiny-provisioner-remote logs" in runbook


def test_remote_install_helper_installs_expected_command() -> None:
    installer = Path("scripts/install_remote_provisioner.sh").read_text()

    assert "set -euo pipefail" in installer
    assert "/usr/local/bin/tiny-provisioner-remote" in installer
    assert "docker network create" in installer
    assert "ssh:localhost:missing-demo" in installer
