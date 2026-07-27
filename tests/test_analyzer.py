from app.analyzer import analyze_text, calculate_score, mining_ready


def rules():
    return {
        "thresholds": {"qualified": 75, "minimum_team": 18, "minimum_gpu": 16},
        "hard_reject": {"inactive_days": 90, "core_similarity": 0.9, "require_pow": True, "reject_malicious_script": True},
    }


def keywords():
    return {
        "pow_terms": ["proof of work", "genesis", "difficulty"],
        "gpu_terms": ["cuda", "opencl"],
        "launch_terms": ["mainnet", "testnet", "release candidate"],
        "risk_terms": ["premine", "curl | bash"],
    }


def test_pow_gpu_signals():
    result = analyze_text(
        {
            "src/cuda_miner.cu": "proof of work kernel",
            "config/genesis.yaml": "difficulty: 1",
            "docs/testnet.md": "testnet launch",
        },
        keywords(),
    )
    assert result["pow"] and result["gpu"] and result["launch"]
    assert "src/cuda_miner.cu" in result["sources"]["miner"]
    assert "config/genesis.yaml" in result["sources"]["parameter"]


def test_low_change_fork_rejected():
    score = calculate_score({"is_fork": True, "core_similarity": 0.95, "has_pow": True}, rules())
    assert score.hard_rejected
    assert score.reject_reason == "low_change_fork"


def test_malicious_script_rejected():
    score = calculate_score({"has_pow": True, "malicious_script": True}, rules())
    assert score.hard_rejected
    assert score.reject_reason == "malicious_script"


def test_qualified_score_thresholds():
    score = calculate_score(
        {
            "contributors": 4,
            "author_history_years": 4,
            "technical_discussion": True,
            "reproducible_release": True,
            "core_files": 18,
            "commits_30d": 9,
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
        },
        rules(),
    )
    assert not score.hard_rejected
    assert score.team >= 18
    assert score.gpu >= 16
    assert score.total >= 75


def test_mining_ready_is_conservative_and_not_readme_only():
    assert not mining_ready(
        {
            "node": True,
            "pow_parameters": True,
            "miner": True,
            "wallet": True,
            "required_sources": {
                "node": ["README.md"],
                "pow_parameters": ["README.md"],
                "miner": ["README.md"],
                "wallet": ["README.md"],
            },
            "official_release": True,
            "independent_build": True,
            "genesis_confirmed": True,
        }
    )
    assert mining_ready(
        {
            "node": True,
            "pow_parameters": True,
            "miner": True,
            "wallet": True,
            "required_sources": {
                "node": ["src/node.cpp"],
                "pow_parameters": ["config/genesis.yaml"],
                "miner": ["src/miner.rs"],
                "wallet": ["config/wallet.toml"],
            },
            "official_release": True,
            "independent_build": True,
            "genesis_confirmed": True,
        }
    )
