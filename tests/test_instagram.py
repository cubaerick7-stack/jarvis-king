import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows"))
import instagram as IG  # noqa: E402


def load_jarvis():
    spec = importlib.util.spec_from_file_location("jig", ROOT / "windows" / "jarvis_ai.py")
    j = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(j)
    return j


def test_without_token_says_how(monkeypatch, capsys):
    monkeypatch.delenv("INSTAGRAM_TOKEN", raising=False)
    j = load_jarvis()
    assert j.ig_status() is False
    assert "INSTAGRAM_TOKEN" in capsys.readouterr().out


def test_status_and_comments(monkeypatch, capsys):
    j = load_jarvis()
    monkeypatch.setattr(j.IG, "profile", lambda: {"username": "joao", "followers_count": 120, "media_count": 9})
    monkeypatch.setattr(j.IG, "recent_posts", lambda n=5: [{"id": "m1", "caption": "praia", "like_count": 30,
                                                            "comments_count": 2}])
    monkeypatch.setattr(j.IG, "comments", lambda mid: [{"id": "c1", "username": "ana", "text": "linda!"}])
    assert j.ig_status() is True and j.ig_comments(1) is True
    out = capsys.readouterr().out
    assert "@joao: 120 seguidores" in out and "@ana: linda!" in out


def test_reply_and_post_always_ask(monkeypatch):
    j = load_jarvis()
    sent = []
    j._ig_comments = [{"id": "c1", "username": "ana", "text": "linda!"}]
    monkeypatch.setattr(j, "confirm", lambda q: False)
    monkeypatch.setattr(j.IG, "reply_comment", lambda *a: sent.append(a))
    monkeypatch.setattr(j.IG, "publish_image", lambda *a: sent.append(a))
    assert j.ig_reply(1, "obrigado") is False
    assert j.ig_post("https://x.com/a.jpg", "oi") is False
    assert sent == []  # disse não: nada saiu
    monkeypatch.setattr(j, "confirm", lambda q: True)
    assert j.ig_reply(1, "obrigado") is True and sent == [("c1", "obrigado")]


def test_post_needs_public_link(capsys):
    j = load_jarvis()
    assert j.ig_post("C:/fotos/a.jpg") is False
    assert "link público" in capsys.readouterr().out


def test_token_never_in_repo_files():
    for path in (ROOT / "windows").glob("*.py"):
        assert "EAA" not in path.read_text(encoding="utf-8") or path.name == "instagram.py"
