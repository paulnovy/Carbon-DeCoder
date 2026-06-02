from app.db.models import Run, RunEvent, RunLogLine, RunStep, TaxonomyHit, VariantCall
from app.store import memory_store as store


def _reset_core():
    store.runs.replace_all([], None)
    store.run_events.replace_all([], None)
    store.run_steps.replace_all([], None)
    store.run_logs.replace_all([], None)
    store.variants.replace_all([], None)
    store.taxonomy_hits.replace_all([], None)


def test_mark_stale_running_runs_interrupts_running_only(monkeypatch):
    _reset_core()
    monkeypatch.setattr(store, "_DB_ACTIVE", False)

    running = Run(id="run_running", project_id="p", sample_id="s", mode="full", status="running", reference_id="GRCh38_chr20")
    queued = Run(id="run_queued", project_id="p", sample_id="s", mode="full", status="queued", reference_id="GRCh38_chr20")
    store.runs.append_local(running)
    store.runs.append_local(queued)

    store._mark_stale_running_runs()

    assert running.status == "interrupted"
    assert queued.status == "queued"
    assert any(e.run_id == "run_running" and e.event_type == "pipeline_interrupted_on_startup" for e in store.run_events)
    assert any(s.run_id == "run_running" and s.step_name == "process_recovery" for s in store.run_steps)


def test_mark_stale_running_runs_interrupts_paused_active_process(monkeypatch):
    _reset_core()
    persisted = []
    monkeypatch.setattr(store, "_DB_ACTIVE", True)
    monkeypatch.setattr(store, "_merge_row", lambda orm_cls, row: persisted.append((orm_cls.__tablename__, row)))

    paused = Run(
        id="run_paused",
        project_id="p",
        sample_id="s",
        mode="full",
        status="paused",
        reference_id="GRCh38_chr20",
        parameters={"pause_previous_status": "running"},
    )
    store.runs.append_local(paused)

    store._mark_stale_running_runs()

    assert paused.status == "interrupted"
    assert "pause_previous_status" not in paused.parameters
    assert ("runs", paused.model_dump()) in persisted
    assert any(e.run_id == "run_paused" and e.event_type == "pipeline_interrupted_on_startup" for e in store.run_events)


def test_mark_stale_running_runs_preserves_stage_boundary_pause(monkeypatch):
    _reset_core()
    persisted = []
    monkeypatch.setattr(store, "_DB_ACTIVE", True)
    monkeypatch.setattr(store, "_merge_row", lambda orm_cls, row: persisted.append((orm_cls.__tablename__, row)))

    paused = Run(
        id="run_stage_boundary",
        project_id="p",
        sample_id="s",
        mode="full",
        status="paused",
        reference_id="GRCh38_chr20",
        parameters={
            "pause_previous_status": "running",
            "pause_reason": "stage_boundary_pause",
            "pause_mode": "stage_boundary",
            "pause_next_stage": "coverage",
        },
    )
    store.runs.append_local(paused)

    store._mark_stale_running_runs()

    assert paused.status == "paused"
    assert paused.parameters["pause_next_stage"] == "coverage"
    assert persisted == []
    assert not any(e.run_id == "run_stage_boundary" for e in store.run_events)


def test_init_db_enables_db_writes_before_stale_recovery(monkeypatch):
    seen_active = []
    monkeypatch.setattr(store, "USE_DB", True)
    monkeypatch.setattr(store, "_DB_ACTIVE", False)
    monkeypatch.setattr(store, "_sql_init_db", lambda: None)
    monkeypatch.setattr(store, "_init_lists_from_db", lambda **kwargs: seen_active.append(store._DB_ACTIVE))

    assert store.init_db() is True

    assert seen_active == [True]


def test_batch_add_variants_appends_without_table_sync(monkeypatch):
    _reset_core()
    calls = []
    monkeypatch.setattr(store, "_bulk_merge_rows", lambda orm_cls, rows: calls.append((orm_cls.__tablename__, rows)))

    items = [
        VariantCall(
            id=f"var_{i}",
            sample_id="S1",
            run_id="run_1",
            reference_id="GRCh38_chr20",
            chrom="chr20",
            pos=100 + i,
            ref="A",
            alt="C",
        )
        for i in range(3)
    ]

    store.add_variants(items)

    assert [v.id for v in store.variants] == ["var_0", "var_1", "var_2"]
    assert calls == [("variant_calls", [v.model_dump() for v in items])]


def test_batch_add_taxonomy_hits_uses_bulk_merge(monkeypatch):
    _reset_core()
    calls = []
    monkeypatch.setattr(store, "_bulk_merge_rows", lambda orm_cls, rows: calls.append((orm_cls.__tablename__, rows)))

    items = [
        TaxonomyHit(
            id=f"tax_{i}",
            sample_id="S1",
            run_id="run_1",
            reference_id="GRCh38_chr20",
            organism=f"organism_{i}",
            kingdom="virus",
            read_count=i + 1,
            confidence=0.9,
            evidence_score=0.8,
            tools=["kraken2"],
        )
        for i in range(2)
    ]

    store.add_taxonomy_hits(items)

    assert [t.id for t in store.taxonomy_hits] == ["tax_0", "tax_1"]
    assert calls == [("taxonomy_hits", [t.model_dump() for t in items])]


def test_run_log_row_persistence_uses_synthetic_primary_key(monkeypatch):
    _reset_core()
    calls = []
    monkeypatch.setattr(store, "_merge_row", lambda orm_cls, row: calls.append((orm_cls.__tablename__, row)))

    log = RunLogLine(run_id="run_1", line_no=7, message="hello")
    store.add_run_log_line(log)

    assert store.run_logs[-1] is log
    assert calls[0][0] == "run_logs"
    assert calls[0][1]["run_id"] == "run_1"
    assert calls[0][1]["line_no"] == 7
    assert calls[0][1]["id"].startswith("log_")
