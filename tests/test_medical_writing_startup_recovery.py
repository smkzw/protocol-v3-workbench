from __future__ import annotations


def test_durable_startup_recovery_runs_through_registered_worker(monkeypatch) -> None:
    from services.api.app import main

    calls: list[str] = []
    monkeypatch.setattr(
        main.mw_durable_worker,
        "recover",
        lambda: calls.append("worker_recover") or 0,
    )
    monkeypatch.setattr(
        main.writing_reference_translation_batch_service,
        "recover_pending_batches",
        lambda: [],
    )

    main._recover_durable_mw_jobs()

    assert calls == ["worker_recover"]
