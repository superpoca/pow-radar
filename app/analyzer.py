from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib, re

@dataclass
class ScoreResult:
    team: float; development: float; gpu: float; timing: float; total: float
    hard_rejected: bool; reject_reason: str | None; explanation: dict

def analyze_text(files: dict[str, str], keywords: dict) -> dict:
    text = "\n".join(f"{p}\n{v}" for p, v in files.items()).lower()
    paths = " ".join(files).lower()
    has = lambda terms: any(t.lower() in text or t.lower() in paths for t in terms)
    return {"pow": has(keywords["pow_terms"]), "gpu": has(keywords["gpu_terms"]), "launch": has(keywords["launch_terms"]), "risk": has(keywords["risk_terms"]), "miner": bool(re.search(r"miner|stratum", text + paths)), "node": bool(re.search(r"node|daemon|p2p", text + paths)), "wallet": bool(re.search(r"wallet|address", text + paths)), "parameter": bool(re.search(r"difficulty|block.?reward|genesis", text))}

def calculate_score(data: dict, rules: dict) -> ScoreResult:
    reasons = {"team": [], "development": [], "gpu": [], "timing": []}
    reject = None
    if data.get("inactive_days", 0) >= rules["hard_reject"]["inactive_days"]: reject = "inactive_core_code"
    if data.get("is_fork") and data.get("core_similarity", 0) >= rules["hard_reject"]["core_similarity"]: reject = "low_change_fork"
    if not data.get("has_pow", False): reject = reject or "no_verifiable_pow"
    if data.get("malicious_script", False): reject = "malicious_script"
    team = min(30, data.get("contributors", 0) * 2 + min(data.get("author_history_years", 0), 4) + (4 if data.get("technical_discussion") else 0))
    dev = min(25, data.get("core_files", 0) // 10 + data.get("commits_30d", 0) // 5 + (5 if data.get("has_tests") else 0))
    gpu = min(25, (8 if data.get("has_pow") else 0) + (8 if data.get("has_miner") else 0) + (6 if data.get("has_gpu") else 0) + (3 if data.get("buildable_node") else 0))
    timing = min(20, (5 if data.get("mainnet_window") else 0) + (4 if data.get("parameters_frozen") else 0) + (4 if data.get("fair_launch") else 0) + (3 if data.get("low_visibility") else 0) + (4 if data.get("launch_signal") else 0))
    total = team + dev + gpu + timing
    explanation = {"team": reasons["team"], "development": reasons["development"], "gpu": reasons["gpu"], "timing": reasons["timing"]}
    return ScoreResult(team, dev, gpu, timing, total, bool(reject), reject, explanation)

def event_hash(*parts): return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()

def mining_ready(data: dict) -> bool:
    required = all(data.get(k, False) for k in ("node", "pow_parameters", "miner", "wallet"))
    evidence = sum(bool(data.get(k)) for k in ("official_release", "independent_build", "independent_mining_test", "mainnet_confirmed", "genesis_confirmed"))
    return required and evidence >= 3
