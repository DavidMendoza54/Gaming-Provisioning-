from sqlalchemy import select

from app.database import SessionLocal
from app.models import Template


def seed() -> None:
    with SessionLocal() as session:
        existing = session.scalar(select(Template).where(Template.name == "Tiny Python HTTP App"))
        if existing:
            print("Template already exists: Tiny Python HTTP App")
            return

        template = Template(
            name="Tiny Python HTTP App",
            image="tiny-python-http-app:local",
            exposed_port=8000,
            default_cpu=1,
            default_memory_mb=128,
            description="A safe starter app that returns a small HTTP response.",
            enabled=True,
        )
        session.add(template)
        session.commit()
        print("Seeded template: Tiny Python HTTP App")


if __name__ == "__main__":
    seed()

