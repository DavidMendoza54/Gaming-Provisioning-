from app.provisioners.base import Provisioner
from app.provisioners.docker import DockerProvisioner
from app.provisioners.fake import FakeProvisioner
from app.provisioners.ssh import SSHProvisioner
from app.settings import get_settings


def make_provisioner() -> Provisioner:
    settings = get_settings()
    if settings.provisioner_backend == "fake":
        return FakeProvisioner(base_domain=settings.app_base_domain)
    if settings.provisioner_backend == "docker":
        return DockerProvisioner(
            base_domain=settings.app_base_domain,
            public_scheme=settings.app_public_scheme,
            network_name=settings.docker_network_name,
            traefik_dynamic_config_path=settings.traefik_dynamic_config_path,
            traefik_cert_resolver=settings.traefik_cert_resolver,
        )
    if settings.provisioner_backend == "ssh":
        return SSHProvisioner(
            host=settings.ssh_host,
            user=settings.ssh_user,
            key_path=settings.ssh_key_path,
            base_domain=settings.app_base_domain,
            public_scheme=settings.app_public_scheme,
            port=settings.ssh_port,
            remote_command=settings.ssh_remote_command,
            timeout_seconds=settings.ssh_timeout_seconds,
            strict_host_key_checking=settings.ssh_strict_host_key_checking,
        )
    raise RuntimeError(f"Unknown provisioner backend: {settings.provisioner_backend}")
