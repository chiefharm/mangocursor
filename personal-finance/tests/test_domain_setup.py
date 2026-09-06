"""Domain install must not steal the live Vigbo site on rost-i-razvitie.ru."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "setup_domain.sh"


def test_setup_domain_defaults_to_kassa_subdomain() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "kassa.rost-i-razvitie.ru" in text
    assert "FINANCE_DOMAIN_FORCE" in text
    assert "python3-certbot-nginx" in text


def test_install_calls_setup_domain() -> None:
    text = (ROOT / "deploy" / "install_on_vps.sh").read_text(encoding="utf-8")
    assert "setup_domain.sh" in text
    assert "kassa.rost-i-razvitie.ru" in text


def test_setup_domain_bash_syntax() -> None:
    subprocess.check_call(["bash", "-n", str(SCRIPT)])
    subprocess.check_call(["bash", "-n", str(ROOT / "deploy" / "install_on_vps.sh")])
