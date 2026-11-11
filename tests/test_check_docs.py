"""文档一致性检查 —— 钉住那些「代码早改了、文档没跟上」的说法。"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import check_docs  # noqa: E402


def _repo(tmp_path, text):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "旧文档.md").write_text(text, encoding="utf-8")
    return tmp_path


def test_stale_ota_claim_is_caught(tmp_path):
    repo = _repo(tmp_path, "本项目不做 OTA。\n")
    hits = check_docs.scan(repo / "docs" / "旧文档.md")
    assert hits
    assert "不做 OTA" in hits[0][1]


def test_current_wording_passes(tmp_path):
    repo = _repo(tmp_path, "OTA 只由人点，设备不自己升级。\n")
    assert check_docs.scan(repo / "docs" / "旧文档.md") == []


def test_allow_marker_skips_the_line(tmp_path):
    repo = _repo(tmp_path, "以前写过不做 OTA。  # check-docs: allow\n")
    assert check_docs.scan(repo / "docs" / "旧文档.md") == []


def test_main_returns_one_when_stale(tmp_path, monkeypatch):
    repo = _repo(tmp_path, "本项目不支持 OTA。\n")
    monkeypatch.setattr(check_docs, "ROOT", repo)
    assert check_docs.main(["--quiet"]) == 1


def test_main_returns_zero_when_clean(tmp_path, monkeypatch):
    repo = _repo(tmp_path, "现在支持 OTA。\n")
    monkeypatch.setattr(check_docs, "ROOT", repo)
    assert check_docs.main(["--quiet"]) == 0
