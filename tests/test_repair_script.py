from __future__ import annotations

from scripts import repair_transfer_groups


def test_backup_flag_without_a_path_is_a_clear_error_not_a_traceback(capsys):
    assert repair_transfer_groups.main(["repair", "--backup"]) == 1
    assert "--backup" in capsys.readouterr().out


def test_a_backup_path_that_does_not_exist_is_reported(capsys, tmp_path):
    assert repair_transfer_groups.main(["repair", "--backup", str(tmp_path / "nope.db")]) == 1
    assert "No backup" in capsys.readouterr().out
