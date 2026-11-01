import json

import pytest

from oni_ai.cli import main


def test_cli_init_search_and_demo(tmp_path, capsys):
    path = tmp_path / "knowledge.sqlite3"
    assert main(["init-db", str(path)]) == 0
    capsys.readouterr()
    assert main(["search", str(path), "Tile"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result[0]["facts"]["construction_materials"]["value"] == "UNKNOWN"
    assert main(["mock-demo"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["provenance"] == "MOCK_SYNTHETIC_NOT_GAME_DATA"


def test_cli_no_live_mode(capsys):
    with pytest.raises(SystemExit) as error:
        main(["connect"])
    assert error.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_cli_init_failure_is_readable(tmp_path, capsys):
    path = tmp_path / "existing.sqlite3"
    path.write_text("do not change", encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        main(["init-db", str(path)])
    assert error.value.code == 2
    assert path.read_text(encoding="utf-8") == "do not change"
    assert "error:" in capsys.readouterr().err
