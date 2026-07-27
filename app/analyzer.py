from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import re

CODE_SUFFIXES = {".c", ".cc", ".cpp", ".cu", ".go", ".h", ".hpp", ".py", ".rs", ".sol", ".ts"}
DOC_SUFFIXES = {".md", ".rst", ".txt"}
CONFIG_SUFFIXES = {".conf", ".ini", ".json", ".toml", ".yaml", ".yml"}
SCRIPT_SUFFIXES = {".bat", ".ps1", ".sh"}
BUILD_FILES = {"cargo.toml", "cmakelists.txt", "dockerfile", "go.mod", "makefile", "package.json", "pyproject.toml"}


@dataclass(slots=True)
class ScoreResult:
    team: float
    development: float
    gpu: float
    timing: float
    total: float
    hard_rejected: bool
    reject_reason: str | None
    explanation: dict


def analyze_text(files: dict[str, str], keywords: dict) -> dict:
    sources: dict[str, list[str]] = {
        "pow": [],
        "gpu": [],
        "launch": [],
        "risk": [],
        "miner": [],
        "node": [],
        "wallet": [],
        "parameter": [],
        "premine": [],
        "remote_exec": [],
    }

    pow_terms = [term.lower() for term in keywords.get("pow_terms", [])]
    gpu_terms = [term.lower() for term in keywords.get("gpu_terms", [])]
    launch_terms = [term.lower() for term in keywords.get("launch_terms", [])]
    risk_terms = [term.lower() for term in keywords.get("risk_terms", [])]

    for path, content in files.items():
        lowered_path = path.lower()
        lowered_content = (content or "").lower()
        blob = f"{lowered_path}\n{lowered_content}"
        kind = source_kind(path)
        if _contains_any(blob, pow_terms):
            sources["pow"].append(path)
        if _contains_any(blob, gpu_terms):
            sources["gpu"].append(path)
        if _contains_any(blob, launch_terms):
            sources["launch"].append(path)
        if _contains_any(blob, risk_terms):
            sources["risk"].append(path)
        if re.search(r"miner|stratum|pool", blob):
            sources["miner"].append(path)
        if re.search(r"node|daemon|p2p|seed node|bootstrap", blob):
            sources["node"].append(path)
        if re.search(r"wallet|address|keystore|mnemonic", blob):
            sources["wallet"].append(path)
        if re.search(r"\b(difficulty|block\s*reward|genesis|epoch|target|nonce)\b", blob):
            sources["parameter"].append(path)
        if re.search(r"\b(pre-?mine|developer fee|allocat(ed|ion)|premint)\b", blob):
            sources["premine"].append(path)
        # This intentionally targets executable/static code paths only. README or doc examples
        # may still mention dangerous commands, so human review remains required for more
        # sophisticated obfuscation such as variable substitution or base64-wrapped payloads.
        if kind in {"script", "code"} and re.search(
            r"(curl|wget).*(\||&&)\s*(bash|sh)|invoke-expression|iex\s*\(|powershell\s+-(enc|encodedcommand)",
            blob,
        ):
            sources["remote_exec"].append(path)

    normalized_sources = {name: _unique(values) for name, values in sources.items()}
    evidence_sources = _unique(
        normalized_sources["pow"]
        + normalized_sources["gpu"]
        + normalized_sources["miner"]
        + normalized_sources["node"]
        + normalized_sources["wallet"]
        + normalized_sources["parameter"]
    )
    return {
        "pow": bool(normalized_sources["pow"]),
        "gpu": bool(normalized_sources["gpu"]),
        "launch": bool(normalized_sources["launch"]),
        "risk": bool(normalized_sources["risk"]),
        "miner": bool(normalized_sources["miner"]),
        "node": bool(normalized_sources["node"]),
        "wallet": bool(normalized_sources["wallet"]),
        "parameter": bool(normalized_sources["parameter"]),
        "premine": bool(normalized_sources["premine"]),
        "remote_exec": bool(normalized_sources["remote_exec"]),
        "sources": normalized_sources,
        "evidence_sources": evidence_sources,
    }


def calculate_score(data: dict, rules: dict) -> ScoreResult:
    hard_reject = rules.get("hard_reject", {})
    reasons = {"team": [], "development": [], "gpu": [], "timing": []}
    reject_reason = None

    if data.get("inactive_days", 0) >= hard_reject.get("inactive_days", 90):
        reject_reason = "inactive_core_code"
    if data.get("is_fork") and data.get("core_similarity", 0) >= hard_reject.get("core_similarity", 0.90):
        reject_reason = "low_change_fork"
    if hard_reject.get("require_pow", True) and not data.get("has_pow", False):
        reject_reason = reject_reason or "no_verifiable_pow"
    if hard_reject.get("reject_malicious_script", True) and data.get("malicious_script", False):
        reject_reason = "malicious_script"

    team = 0.0
    contributors = data.get("contributors", 0)
    author_history_years = data.get("author_history_years", 0)
    if contributors >= 2:
        team += min(contributors, 4) * 4
        reasons["team"].append(f"{contributors} active contributors")
    if author_history_years:
        team += min(author_history_years, 4) * 2
        reasons["team"].append(f"owner history proxy {author_history_years}y")
    if data.get("technical_discussion"):
        team += 6
        reasons["team"].append("technical issue or PR activity detected")
    if data.get("reproducible_release"):
        team += 4
        reasons["team"].append("build metadata or release workflow present")
    team = min(team, 30)

    development = 0.0
    core_files = data.get("core_files", 0)
    commits_30d = data.get("commits_30d", 0)
    if core_files:
        development += min(core_files / 2, 10)
        reasons["development"].append(f"{core_files} core files discovered")
    if commits_30d:
        development += min(commits_30d, 6)
        reasons["development"].append(f"{commits_30d} commits in last 30d")
    if data.get("has_tests"):
        development += 5
        reasons["development"].append("tests present")
    if data.get("roadmap_present"):
        development += 2
        reasons["development"].append("roadmap or milestone docs present")
    if data.get("buildable_node"):
        development += 2
        reasons["development"].append("node build metadata present")
    development = min(development, 25)

    gpu = 0.0
    if data.get("has_pow"):
        gpu += 6
        reasons["gpu"].append("verifiable PoW signal found")
    if data.get("has_miner"):
        gpu += 7
        reasons["gpu"].append("miner signal found")
    if data.get("has_gpu"):
        gpu += 6
        reasons["gpu"].append("GPU backend signal found")
    if data.get("buildable_node"):
        gpu += 3
        reasons["gpu"].append("node build path present")
    if data.get("anti_asic"):
        gpu += 3
        reasons["gpu"].append("anti-ASIC or GPU fairness note found")
    gpu = min(gpu, 25)

    timing = 0.0
    if data.get("mainnet_window"):
        timing += 5
        reasons["timing"].append("mainnet window or launch term found")
    if data.get("parameters_frozen"):
        timing += 4
        reasons["timing"].append("genesis or PoW parameter signals found")
    if data.get("fair_launch"):
        timing += 4
        reasons["timing"].append("no obvious premine risk in static files")
    if data.get("low_visibility"):
        timing += 3
        reasons["timing"].append("visibility still low enough for early entry")
    if data.get("launch_signal"):
        timing += 4
        reasons["timing"].append("launch readiness signals detected")
    timing = min(timing, 20)

    total = team + development + gpu + timing
    explanation = {
        "team": reasons["team"],
        "development": reasons["development"],
        "gpu": reasons["gpu"],
        "timing": reasons["timing"],
        "reject_reason": reject_reason,
    }
    return ScoreResult(team, development, gpu, timing, total, bool(reject_reason), reject_reason, explanation)


def event_hash(*parts: object) -> str:
    encoded_parts = []
    for part in parts:
        if isinstance(part, (dict, list, tuple)):
            encoded_parts.append(json.dumps(part, ensure_ascii=False, sort_keys=True))
        else:
            encoded_parts.append(str(part))
    payload = "|".join(encoded_parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def mining_ready(data: dict) -> bool:
    required_keys = ("node", "pow_parameters", "miner", "wallet")
    required_sources = data.get("required_sources") or {}
    if required_sources:
        required = all(_has_verifiable_source(required_sources.get(key, [])) for key in required_keys)
    else:
        required = all(data.get(key, False) for key in required_keys)
    evidence = sum(
        bool(data.get(key))
        for key in (
            "official_release",
            "independent_build",
            "independent_mining_test",
            "mainnet_confirmed",
            "genesis_confirmed",
        )
    )
    return required and evidence >= 3


def _has_verifiable_source(sources: list[str]) -> bool:
    return any(source_kind(path) in {"code", "config", "script", "release"} for path in sources)


def source_kind(path: str) -> str:
    lower = path.lower()
    name = Path(lower).name
    suffix = Path(lower).suffix
    if name.startswith("readme"):
        return "readme"
    if "release" in lower or "changelog" in lower:
        return "release"
    if name in BUILD_FILES or suffix in CONFIG_SUFFIXES:
        return "config"
    if suffix in SCRIPT_SUFFIXES:
        return "script"
    if suffix in DOC_SUFFIXES:
        return "docs"
    if suffix in CODE_SUFFIXES:
        return "code"
    return "other"


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
