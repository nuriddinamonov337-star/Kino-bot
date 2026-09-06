from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_railway_uses_non_docker_bot_command_and_migration() -> None:
    config = (ROOT / "railway.toml").read_text(encoding="utf-8")
    assert 'builder = "NIXPACKS"' in config
    assert 'startCommand = "python -m app.bot"' in config
    assert 'preDeployCommand = "alembic upgrade head"' in config


def test_railway_worker_command_is_documented_separately() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "python -m app.workers.reels" in readme
    assert "Docker'siz Railway deployment" in readme


def test_env_template_does_not_require_docker_hostnames() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "DATABASE_URL=" in env_example
    assert "REDIS_URL=" in env_example
    assert "@postgres:5432" not in env_example
    assert "redis://redis:" not in env_example