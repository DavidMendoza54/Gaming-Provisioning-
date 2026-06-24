from app.provisioners.base import Provisioner
from app.provisioners.docker import DockerProvisioner
from app.provisioners.fake import FakeProvisioner
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
        )
    raise RuntimeError(f"Unknown provisioner backend: {settings.provisioner_backend}")
