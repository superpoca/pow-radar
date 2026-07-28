from __future__ import annotations

import logging

from sqlalchemy.orm import sessionmaker

import typer

from .analyzer import calculate_score, event_hash, mining_ready
from .config import Settings
from .db import Alert, Project, Score, Signal, StatusChange, get_db, update_status, utcnow
from .github import collect as collect_projects
from .github import discover as discover_projects
from .telegram import send

app = typer.Typer(no_args_is_help=True)
log = logging.getLogger(__name__)
MANUAL_CHECKLIST = [
    "Verify that source and release artifacts match.",
    "Verify that node, wallet, miner, and PoW prerequisites are complete.",
    "Verify that premine and developer allocation are transparent.",
    "Verify that independent third-party validation exists.",
    "Do not download or execute unknown binaries or scripts.",
]


def setup() -> tuple[Settings, sessionmaker]:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.from_env()
    return settings, get_db(settings.database_url)


@app.command("init-db")
def init_db() -> None:
    settings, _session_factory = setup()
    print(f"database initialized: {settings.database_url}")


@app.command("discover")
def discover() -> None:
    settings, session_factory = setup()
    with session_factory() as session:
        print(f"discovered {discover_projects(session, settings)}")


@app.command("collect")
def collect() -> None:
    settings, session_factory = setup()
    with session_factory() as session:
        print(f"collected {collect_projects(session, settings)}")


@app.command("score")
def score() -> None:
    settings, session_factory = setup()
    with session_factory() as session:
        print(f"scored {run_score(session, settings.rules())}")


@app.command("detect-signals")
def detect_signals() -> None:
    settings, session_factory = setup()
    with session_factory() as session:
        print(f"signals {run_detect_signals(session, settings.rules())}")


@app.command("send-alerts")
def send_alerts() -> None:
    settings, session_factory = setup()
    with session_factory() as session:
        print(f"alerts {send_pending_alerts(session, settings)}")


@app.command("daily-report")
def daily_report() -> None:
    settings, session_factory = setup()
    with session_factory() as session:
        print(render_report(session, title="PoW Radar Daily Report"))


@app.command("weekly-report")
def weekly_report() -> None:
    settings, session_factory = setup()
    with session_factory() as session:
        print(render_report(session, title="PoW Radar Weekly Report"))


@app.command("run-all")
def run_all() -> None:
    settings, session_factory = setup()
    with session_factory() as session:
        discovered = discover_projects(session, settings)
        collected = collect_projects(session, settings)
        scored = run_score(session, settings.rules())
        signals = run_detect_signals(session, settings.rules())
        alerts = send_pending_alerts(session, settings)
    print(f"discovered={discovered} collected={collected} scored={scored} signals={signals} alerts={alerts}")


def run_score(session, rules: dict) -> int:
    count = 0
    thresholds = rules.get("thresholds", {})
    archive_days = rules.get("status_windows", {}).get("archive_days", 180)
    for project in session.query(Project).all():
        metadata = project.metadata_json or {}
        result = calculate_score(metadata, rules)
        session.add(
            Score(
                project_id=project.id,
                team=result.team,
                development=result.development,
                gpu=result.gpu,
                timing=result.timing,
                total=result.total,
                hard_rejected=result.hard_rejected,
                reject_reason=result.reject_reason,
                explanation=result.explanation,
            )
        )
        if result.hard_rejected:
            project.risk_level = "HIGH"
            reason = [result.reject_reason or "hard_reject"]
            if metadata.get("inactive_days", 0) >= archive_days:
                update_status(session, project, "ARCHIVED", reason)
            else:
                update_status(session, project, "REJECTED", reason)
        else:
            project.risk_level = "LOW" if result.total >= thresholds.get("qualified", 75) else "MEDIUM"
            qualified = (
                result.total >= thresholds.get("qualified", 75)
                and result.team >= thresholds.get("minimum_team", 18)
                and result.gpu >= thresholds.get("minimum_gpu", 16)
            )
            update_status(session, project, "QUALIFIED" if qualified else "WATCHLIST", [f"score={result.total:.1f}"])
        count += 1
    session.commit()
    return count


def run_detect_signals(session, rules: dict) -> int:
    count = 0
    for project in session.query(Project).filter(Project.status.not_in(["REJECTED", "ARCHIVED"])).all():
        metadata = project.metadata_json or {}
        analysis = metadata.get("analysis") or {}
        severity, next_status, reasons = classify_project(project, metadata, analysis)
        if not severity:
            continue
        details = {
            "signals": {
                "pow": analysis.get("pow", False),
                "gpu": analysis.get("gpu", False),
                "miner": analysis.get("miner", False),
                "node": analysis.get("node", False),
                "wallet": analysis.get("wallet", False),
                "parameter": analysis.get("parameter", False),
                "launch": analysis.get("launch", False),
            },
            "evidence": analysis.get("sources", {}),
            "risk_flags": {
                "premine": analysis.get("premine", False),
                "remote_exec": analysis.get("remote_exec", False),
            },
            "reasons": reasons,
            "manual_review": MANUAL_CHECKLIST,
        }
        signature = event_hash(project.full_name, severity, next_status, details)
        if session.query(Signal).filter_by(event_hash=signature).one_or_none() is None:
            session.add(
                Signal(
                    project_id=project.id,
                    signal_type="mining_readiness",
                    severity=severity,
                    confidence=0.90 if severity == "P0" else (0.70 if severity == "P1" else 0.50),
                    details=details,
                    event_hash=signature,
                )
            )
            count += 1
        update_status(session, project, next_status, reasons)
    session.commit()
    return count


def classify_project(project: Project, metadata: dict, analysis: dict) -> tuple[str | None, str, list[str]]:
    if not analysis:
        return None, project.status, []

    ready = mining_ready(
        {
            "node": analysis.get("node", False),
            "pow_parameters": analysis.get("parameter", False),
            "miner": analysis.get("miner", False),
            "wallet": analysis.get("wallet", False),
            "required_sources": {
                "node": analysis.get("sources", {}).get("node", []),
                "pow_parameters": analysis.get("sources", {}).get("parameter", []),
                "miner": analysis.get("sources", {}).get("miner", []),
                "wallet": analysis.get("sources", {}).get("wallet", []),
            },
            "official_release": bool(project.latest_release),
            "independent_build": metadata.get("buildable_node", False),
            "independent_mining_test": metadata.get("has_miner", False) and metadata.get("has_gpu", False),
            "mainnet_confirmed": metadata.get("mainnet_window", False),
            "genesis_confirmed": metadata.get("parameters_frozen", False),
        }
    )
    reasons: list[str] = []
    if ready:
        reasons.extend(["static PoW/GPU signals verified", "node/miner/wallet/parameters present", "multiple independent evidence flags present"])
        return "P0", "MINING-READY", reasons
    if metadata.get("mainnet_window") and analysis.get("miner") and analysis.get("node"):
        reasons.extend(["launch window detected", "miner and node signals present"])
        return "P1", "PRE-MINE", reasons
    if metadata.get("mainnet_window") and metadata.get("parameters_frozen") and metadata.get("has_miner"):
        reasons.extend(["mainnet parameters look stable", "miner path present"])
        return "P1", "PRE-MINE", reasons
    launch_sources = analysis.get("sources", {}).get("launch", [])
    if any("testnet" in source.lower() for source in launch_sources):
        reasons.append("testnet signal detected")
        return "P2", "TESTNET", reasons
    if analysis.get("launch") or analysis.get("pow") or analysis.get("gpu"):
        reasons.append("candidate mining signals detected")
        return "P2", project.status if project.status != "DISCOVERED" else "WATCHLIST", reasons
    return None, project.status, []


def send_pending_alerts(session, settings: Settings) -> int:
    """Deliver pending alerts and only deduplicate successfully delivered ones."""
    count = 0
    for signal in session.query(Signal).filter(Signal.severity.in_(["P0", "P1", "P2"])).all():
        if session.query(Alert).filter_by(event_hash=signal.event_hash).one_or_none() is not None:
            continue
        project = session.get(Project, signal.project_id)
        if project is None:
            continue
        latest_score = (
            session.query(Score).filter_by(project_id=project.id).order_by(Score.created_at.desc()).first()
        )
        message = render_alert(project, signal, latest_score.total if latest_score else None)
        if not send(settings, message):
            log.warning("Alert delivery failed for %s; leaving it pending for retry", project.full_name)
            continue
        session.add(
            Alert(
                project_id=project.id,
                severity=signal.severity,
                event_hash=signal.event_hash,
                message=message,
                sent_at=utcnow(),
                delivery_status="SENT",
            )
        )
        count += 1
    session.commit()
    return count


def render_alert(project: Project, signal: Signal, score_total: float | None) -> str:
    risks = signal.details.get("risk_flags", {})
    evidence = signal.details.get("evidence", {})
    signal_lines = [f"- {name}: {'yes' if value else 'no'}" for name, value in signal.details.get("signals", {}).items()]
    evidence_lines = [
        f"- {name}: {', '.join(paths) if paths else 'none'}"
        for name, paths in evidence.items()
        if paths
    ]
    risk_lines = [f"- {name}: {'yes' if value else 'no'}" for name, value in risks.items()]
    return "\n".join(
        [
            f"{signal.severity} PoW Radar",
            f"项目: {project.full_name}",
            f"状态: {project.status}",
            f"评分: {score_total if score_total is not None else 'N/A'}",
            "信号:",
            *(signal_lines or ["- none"]),
            "证据:",
            *(evidence_lines or ["- none"]),
            "风险:",
            *(risk_lines or ["- none"]),
            "人工复核建议:",
            *[f"- {item}" for item in signal.details.get("manual_review", MANUAL_CHECKLIST)],
        ]
    )


def render_report(session, *, title: str) -> str:
    lines = [f"# {title}", ""]
    for project in session.query(Project).filter(Project.status.in_(["QUALIFIED", "TESTNET", "PRE-MINE", "MINING-READY", "ACTIVE-MINING"])).order_by(Project.stars.desc()).all():
        latest_score = session.query(Score).filter_by(project_id=project.id).order_by(Score.created_at.desc()).first()
        score_text = f"{latest_score.total:.1f}" if latest_score else "N/A"
        lines.append(f"- {project.full_name}: status={project.status}, risk={project.risk_level}, score={score_text}")
    recent_changes = session.query(StatusChange).order_by(StatusChange.created_at.desc()).limit(10).all()
    if recent_changes:
        lines.extend(["", "## Recent status changes"])
        for change in recent_changes:
            lines.append(f"- project_id={change.project_id}: {change.old_status} -> {change.new_status} ({', '.join(change.reason or [])})")
    return "\n".join(lines)


def main() -> None:
    app()
