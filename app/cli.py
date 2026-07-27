import logging, typer
from datetime import datetime, timezone
from .config import Settings
from .db import get_db, Project, Score, Signal, Alert
from .github import discover, collect
from .analyzer import analyze_text, calculate_score, event_hash, mining_ready
from .telegram import send

app=typer.Typer(no_args_is_help=True); log=logging.getLogger(__name__)
def setup(): logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"); s=Settings.from_env(); return s,get_db(s.database_url)
@app.command()
def discover_cmd(): s,DB=setup(); db=DB(); print(f"discovered {discover(db,s)}")
@app.command()
def collect_cmd(): s,DB=setup(); db=DB(); print(f"collected {collect(db,s)}")
@app.command()
def score_cmd():
    s,DB=setup(); db=DB(); rules=s.rules(); n=0
    for p in db.query(Project).all():
        d={"is_fork":p.is_fork,"core_similarity":p.metadata_json.get("core_similarity",0),"inactive_days":p.metadata_json.get("inactive_days",0),"contributors":p.metadata_json.get("contributors",0),"commits_30d":p.metadata_json.get("commits_30d",0),"core_files":p.metadata_json.get("core_files",0),"has_pow":p.metadata_json.get("has_pow",False),"has_gpu":p.metadata_json.get("has_gpu",False),"has_miner":p.metadata_json.get("has_miner",False),"buildable_node":p.metadata_json.get("buildable_node",False),"mainnet_window":p.metadata_json.get("mainnet_window",False),"parameters_frozen":p.metadata_json.get("parameters_frozen",False),"fair_launch":p.metadata_json.get("fair_launch",False),"launch_signal":p.metadata_json.get("launch_signal",False)}
        r=calculate_score(d,rules); db.add(Score(project_id=p.id,team=r.team,development=r.development,gpu=r.gpu,timing=r.timing,total=r.total,hard_rejected=r.hard_rejected,reject_reason=r.reject_reason,explanation=r.explanation)); p.risk_level="HIGH" if r.hard_rejected else ("LOW" if r.total>=75 else "MEDIUM"); p.status="REJECTED" if r.hard_rejected else ("QUALIFIED" if r.total>=rules["thresholds"]["qualified"] and r.team>=rules["thresholds"]["minimum_team"] and r.gpu>=rules["thresholds"]["minimum_gpu"] else "WATCHLIST"); n+=1
    db.commit(); print(f"scored {n}")
@app.command("detect-signals")
def detect_signals():
    s,DB=setup(); db=DB(); keys=s.keywords(); n=0
    for p in db.query(Project).filter(Project.status.not_in(["REJECTED","ARCHIVED"])).all():
        files={"README.md":p.description or "", p.full_name:" ".join(keys["pow_terms"]+keys["gpu_terms"]+keys["launch_terms"])}; a=analyze_text(files,keys); sev="P2"; ready=mining_ready({"node":a["node"],"pow_parameters":a["parameter"],"miner":a["miner"],"wallet":a["wallet"],"official_release":bool(p.latest_release),"independent_build":False,"independent_mining_test":False,"mainnet_confirmed":False,"genesis_confirmed":False})
        if ready: sev="P0"; p.status="MINING-READY"
        elif a["launch"] and a["miner"]: sev="P1"; p.status="PRE-MINE"
        h=event_hash(p.full_name,sev,a); db.add(Signal(project_id=p.id,signal_type="mining_readiness",severity=sev,confidence=0.5 if sev!="P0" else 0.9,details=a,event_hash=h)); n+=1
    db.commit(); print(f"signals {n}")
@app.command("send-alerts")
def send_alerts():
    s,DB=setup(); db=DB(); n=0
    for sig in db.query(Signal).filter(Signal.severity.in_(["P0","P1","P2"])).all():
        if db.query(Alert).filter_by(event_hash=sig.event_hash).first(): continue
        p=db.get(Project,sig.project_id); msg=f"{sig.severity} PoW Radar\n{p.full_name}\n状态: {p.status}\n评分: {db.query(Score).filter_by(project_id=p.id).order_by(Score.created_at.desc()).first().total if db.query(Score).filter_by(project_id=p.id).first() else 'N/A'}\n信号: {sig.details}\n请人工核对源码、release、节点、钱包和预挖。"; sent=send(s,msg); db.add(Alert(project_id=p.id,severity=sig.severity,event_hash=sig.event_hash,message=msg)); n+=1
    db.commit(); print(f"alerts {n}")
@app.command("run-all")
def run_all(): discover_cmd(); collect_cmd(); score_cmd(); detect_signals(); send_alerts()
@app.command("daily-report")
def daily_report():
    s,DB=setup(); db=DB(); print("# PoW Radar Daily Report\n");
    for p in db.query(Project).filter(Project.status.in_(["QUALIFIED","PRE-MINE","MINING-READY"])).all(): print(f"- {p.full_name}: {p.status}, {p.risk_level}")
@app.command("weekly-report")
def weekly_report(): daily_report()
def main(): app()
