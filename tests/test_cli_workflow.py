from app.cli import run_detect_signals, run_score, send_pending_alerts
from app.db import Project, Signal, StatusChange, get_db


def test_send_alerts_deduplicates_by_event_hash(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'pow-radar.db'}"
    session_factory = get_db(db_url)
    sent_messages = []

    class SettingsStub:
        telegram_token = None
        telegram_chat_id = None

    monkeypatch.setattr("app.cli.send", lambda settings, message: sent_messages.append(message) or False)

    with session_factory() as session:
        project = Project(full_name="owner/repo", status="PRE-MINE", metadata_json={})
        session.add(project)
        session.commit()
        session.add(
            Signal(
                project_id=project.id,
                signal_type="mining_readiness",
                severity="P1",
                confidence=0.7,
                details={"signals": {}, "evidence": {}, "risk_flags": {}, "manual_review": []},
                event_hash="same-hash",
            )
        )
        session.commit()
        assert send_pending_alerts(session, SettingsStub()) == 1
        assert send_pending_alerts(session, SettingsStub()) == 0
        assert len(sent_messages) == 1


def test_status_change_recorded_and_signal_created(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'pow-radar.db'}"
    session_factory = get_db(db_url)
    rules = {
        "thresholds": {"qualified": 75, "minimum_team": 18, "minimum_gpu": 16},
        "hard_reject": {"inactive_days": 90, "core_similarity": 0.9, "require_pow": True, "reject_malicious_script": True},
        "status_windows": {"archive_days": 180},
    }
    metadata = {
        "contributors": 4,
        "author_history_years": 3,
        "technical_discussion": True,
        "reproducible_release": True,
        "core_files": 16,
        "commits_30d": 8,
        "has_tests": True,
        "roadmap_present": True,
        "buildable_node": True,
        "has_pow": True,
        "has_miner": True,
        "has_gpu": True,
        "anti_asic": True,
        "mainnet_window": True,
        "parameters_frozen": True,
        "fair_launch": True,
        "low_visibility": True,
        "launch_signal": True,
        "analysis": {
            "pow": True,
            "gpu": True,
            "launch": True,
            "miner": True,
            "node": True,
            "wallet": True,
            "parameter": True,
            "premine": False,
            "remote_exec": False,
            "sources": {
                "node": ["src/node.cpp"],
                "parameter": ["config/genesis.yaml"],
                "miner": ["src/miner.rs"],
                "wallet": ["config/wallet.toml"],
                "launch": ["config/mainnet.yaml"],
            },
        },
    }

    with session_factory() as session:
        session.add(Project(full_name="owner/repo", metadata_json=metadata))
        session.commit()
        assert run_score(session, rules) == 1
        assert run_detect_signals(session, rules) == 1
        project = session.query(Project).filter_by(full_name="owner/repo").one()
        assert project.status == "MINING-READY"
        assert session.query(StatusChange).count() >= 1
