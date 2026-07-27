import pytest
from app.analyzer import analyze_text, calculate_score, mining_ready

def rules(): return {"hard_reject":{"inactive_days":90,"core_similarity":.9}}
def test_pow_gpu_signals():
    x=analyze_text({"src/cuda_miner.cu":"proof of work genesis"},{"pow_terms":["proof of work"],"gpu_terms":["cuda"],"launch_terms":["genesis"],"risk_terms":[]})
    assert x["pow"] and x["gpu"] and x["launch"]
def test_low_change_fork_rejected():
    r=calculate_score({"is_fork":True,"core_similarity":.95,"has_pow":True},rules()); assert r.hard_rejected and r.reject_reason=="low_change_fork"
def test_mining_ready_is_conservative():
    assert not mining_ready({"node":True,"pow_parameters":True,"miner":True,"wallet":True,"official_release":True})
    assert mining_ready({"node":True,"pow_parameters":True,"miner":True,"wallet":True,"official_release":True,"independent_build":True,"genesis_confirmed":True})
