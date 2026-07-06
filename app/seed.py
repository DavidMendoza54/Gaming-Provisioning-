from sqlalchemy import select

from app.database import SessionLocal
from app.models import Template


TEMPLATES = [
    {
        "name": "Tiny Python HTTP App",
        "image": "tiny-python-http-app:local",
        "exposed_port": 8000,
        "default_cpu": 1,
        "default_memory_mb": 128,
        "description": "A safe starter app that returns a small HTTP response.",
        "enabled": True,
    },
    {
        "name": "Tiny Browser Game",
        "image": "tiny-browser-game:local",
        "exposed_port": 8000,
        "default_cpu": 1,
        "default_memory_mb": 128,
        "description": "A small browser-playable reaction game for portfolio demos.",
        "enabled": True,
    },
]


def seed() -> None:
    with SessionLocal() as session:
        for template_data in TEMPLATES:
            existing = session.scalar(select(Template).where(Template.name == template_data["name"]))
            if existing:
                for key, value in template_data.items():
                    setattr(existing, key, value)
                print(f"Updated template: {existing.name}")
                continue

            session.add(Template(**template_data))
            print(f"Seeded template: {template_data['name']}")

        session.commit()


if __name__ == "__main__":
    seed()
