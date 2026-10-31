""".env：KEY=VALUE 解析，系统环境变量优先，不覆盖。"""
import os

from lolhex import config

KEYS = ("ARAMHEX_TEST_URL", "ARAMHEX_TEST_KEY", "ARAMHEX_TEST_MODEL")


def test_env_file_fills_missing_keys_only(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        '# 注释\nARAMHEX_TEST_URL="https://x.test/v1"\nARAMHEX_TEST_KEY=abc=def\n\nARAMHEX_TEST_MODEL= m \n',
        encoding="utf-8")
    monkeypatch.setattr(config, "program_dir", lambda: tmp_path)
    os.environ["ARAMHEX_TEST_MODEL"] = "from-env"  # 系统环境变量已设：不被 .env 覆盖
    try:
        config.load_env_file()
        assert os.environ["ARAMHEX_TEST_URL"] == "https://x.test/v1"
        assert os.environ["ARAMHEX_TEST_KEY"] == "abc=def"
        assert os.environ["ARAMHEX_TEST_MODEL"] == "from-env"
    finally:
        for k in KEYS:
            os.environ.pop(k, None)


def test_missing_env_file_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "program_dir", lambda: tmp_path)
    config.load_env_file()  # 没有 .env 不报错
    assert "ARAMHEX_TEST_URL" not in os.environ
