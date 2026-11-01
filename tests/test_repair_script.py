from __future__ import annotations

from scripts import repair_transfer_groups


def test_backup_flag_without_a_path_is_a_clear_error_not_a_traceback(capsys):
    assert repair_transfer_groups.main(["repair", "--backup"]) == 1
    assert "--backup" in capsys.readouterr().out


def test_a_backup_path_that_does_not_exist_is_reported(capsys, tmp_path):
    assert repair_transfer_groups.main(["repair", "--backup", str(tmp_path / "nope.db")]) == 1
    assert "No backup" in capsys.readouterr().out


def test_the_rebuild_refuses_to_run_before_the_bank_categories_are_filled_in(monkeypatch, capsys):
    from contextlib import contextmanager
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from datetime import date
    from backend.models import Account, Base, Transaction

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    @contextmanager
    def scope():
        with Session(engine) as session:
            yield session
            session.commit()

    with Session(engine) as seed:
        seed.add(Account(name="JC"))
        seed.commit()
        seed.add(Transaction(account_id=1, date=date(2026, 1, 1), amount=-1.0, raw_description="x", source="bank_import"))
        seed.commit()
    monkeypatch.setattr(repair_transfer_groups, "session_scope", scope)
    monkeypatch.setattr(repair_transfer_groups, "create_tables", lambda: None)

    assert repair_transfer_groups.main(["repair"]) == 1
    assert "backfill_bank_category" in capsys.readouterr().out
    assert repair_transfer_groups.main(["repair", "--force"]) == 0
