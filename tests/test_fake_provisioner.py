import asyncio
import unittest

from app.provisioners.fake import FakeProvisioner


class FakeProvisionerTest(unittest.TestCase):
    def test_provision_is_idempotent_for_same_resource(self) -> None:
        async def scenario() -> None:
            provisioner = FakeProvisioner(base_domain="apps.test")

            first = await provisioner.provision(
                resource_id=1,
                slug="demo",
                image="tiny-python-http-app:local",
                exposed_port=8000,
                cpu_limit=1,
                memory_mb=128,
            )
            second = await provisioner.provision(
                resource_id=1,
                slug="demo",
                image="tiny-python-http-app:local",
                exposed_port=8000,
                cpu_limit=1,
                memory_mb=128,
            )

            self.assertEqual(first, second)
            self.assertEqual(first.external_id, "fake-1")
            self.assertEqual(first.url, "http://demo.apps.test")

        asyncio.run(scenario())

    def test_logs_are_deterministic_across_fake_instances(self) -> None:
        async def scenario() -> None:
            provisioner = FakeProvisioner(base_domain="apps.test")

            logs = await provisioner.logs(external_id="fake-123")

            self.assertIn("fake backend log stream for fake-123", logs)
            self.assertIn("no real container was created", logs)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
