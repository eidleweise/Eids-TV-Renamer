from tvrenamer.renamer.transaction import (
    build_transaction,
    write_journal_atomically,
    execute_transaction,
)


def test_transaction_success(tmp_path):
    src = tmp_path / "srcdir"
    dst = tmp_path / "dstdir"
    src.mkdir()
    dst.mkdir()
    f1 = src / "file1.txt"
    f1.write_text("hello")
    plan = [(str(f1), str(dst / "file1.txt"))]
    journal = build_transaction(plan)
    journal_path = write_journal_atomically(journal, str(tmp_path))
    execute_transaction(journal_path)
    assert not f1.exists()
    assert (dst / "file1.txt").read_text() == "hello"


def test_transaction_failure_and_rollback(tmp_path):
    src = tmp_path / "srcdir"
    dst = tmp_path / "dstdir"
    src.mkdir()
    dst.mkdir()
    f1 = src / "file1.txt"
    f2 = src / "file2.txt"
    f1.write_text("one")
    f2.write_text("two")
    plan = [(str(f1), str(dst / "file1.txt")), (str(f2), str(dst / "file2.txt"))]
    journal = build_transaction(plan)
    journal_path = write_journal_atomically(journal, str(tmp_path))
    try:
        # simulate failure after first op
        execute_transaction(journal_path, simulate_fail_after=1)
    except Exception:
        # after rollback both originals should still exist and destinations not
        assert f1.exists()
        assert f2.exists()
        assert not (dst / "file1.txt").exists()
        assert not (dst / "file2.txt").exists()
    else:
        raise AssertionError("Expected simulated failure")
