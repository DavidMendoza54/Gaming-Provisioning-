from app.seed import TEMPLATES


def test_seed_includes_browser_game_template() -> None:
    names = {template["name"] for template in TEMPLATES}
    images = {template["image"] for template in TEMPLATES}

    assert "Tiny Browser Game" in names
    assert "tiny-browser-game:local" in images
