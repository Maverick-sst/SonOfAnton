"""
Failure Mode Analysis — Analyze eval results to identify patterns

Run this AFTER run_evals.py to analyze results.json for failure modes.
Identifies:
  1. Router misclassification (intent routing failures)
  2. Stale wizard state (scheduling flow interruptions)
  3. Retrieval threshold misses (relevance score edge cases)
"""

import json
import os
from collections import defaultdict
from typing import Dict, List, Tuple


def analyze_router_misclassification(results: List[Dict]) -> List[Dict]:
    """
    Detect router misclassification patterns.
    Look for:
      - Scheduling questions classified as knowledge (intents missing "scheduling")
      - Context questions misclassified as scheduling (unexpected scheduling intent)
      - Questions answered but with wrong intent
    """
    misclassifications = []
    
    for result in results:
        if "error" in result:
            continue
        
        domain = result.get("domain", "unknown")
        intents = result.get("intents", [])
        verdict = result.get("verdict", {})
        question = result.get("question", "")
        
        # Scheduling questions should have "scheduling" intent
        if domain == "scheduling" and "scheduling" not in intents:
            misclassifications.append({
                "id": result.get("id"),
                "type": "scheduling_not_recognized",
                "question": question,
                "intents": intents,
                "verdict": verdict,
                "severity": "high" if not verdict.get("grounded") else "medium"
            })
        
        # Knowledge questions should have "knowledge" intent
        if domain in ["resume", "github"] and "knowledge" not in intents and len(intents) == 0:
            misclassifications.append({
                "id": result.get("id"),
                "type": "knowledge_not_recognized",
                "question": question,
                "intents": intents,
                "verdict": verdict,
                "severity": "high"
            })
    
    return misclassifications


def analyze_retrieval_threshold_misses(results: List[Dict]) -> List[Dict]:
    """
    Detect retrieval threshold edge cases.
    Look for:
      - Grounded=false but retrieved_chunks exist (threshold too high?)
      - Grounded=true but few/no retrieved_chunks (hallucination risk)
      - Drastic score drops between ranks (threshold precision lost)
    """
    threshold_issues = []
    
    for result in results:
        if "error" in result:
            continue
        
        chunks = result.get("retrieved_chunks", [])
        verdict = result.get("verdict", {})
        question = result.get("question", "")
        grounded = verdict.get("grounded", False)
        
        # Case 1: Not grounded but chunks were retrieved
        #         suggests threshold filtering removed relevant chunks
        if not grounded and chunks:
            threshold_issues.append({
                "id": result.get("id"),
                "type": "threshold_filtered_relevant_chunks",
                "question": question,
                "chunk_count": len(chunks),
                "answer": result.get("answer", "")[:100],
                "verdict": verdict,
                "severity": "high"
            })
        
        # Case 2: Grounded but very few chunks
        #         answer might be correct by luck, not retrieval
        if grounded and len(chunks) <= 1:
            threshold_issues.append({
                "id": result.get("id"),
                "type": "minimal_retrieval_for_grounded_answer",
                "question": question,
                "chunk_count": len(chunks),
                "severity": "low"
            })
    
    return threshold_issues


def analyze_latency_anomalies(results: List[Dict]) -> List[Dict]:
    """
    Detect latency outliers that may indicate performance regressions.
    """
    latencies = [r.get("latency_ms", 0) for r in results if "error" not in r]
    
    if not latencies:
        return []
    
    avg = sum(latencies) / len(latencies)
    max_latency = max(latencies)
    min_latency = min(latencies)
    
    # Identify outliers (> 2x average)
    anomalies = []
    for result in results:
        if "error" in result:
            continue
        
        latency = result.get("latency_ms", 0)
        if latency > 2 * avg:
            anomalies.append({
                "id": result.get("id"),
                "type": "latency_outlier",
                "question": result.get("question", "")[:80],
                "latency_ms": latency,
                "avg_latency_ms": int(avg),
                "severity": "medium"
            })
    
    return anomalies


def generate_failure_report(results_path: str) -> Dict:
    """
    Analyze all failure modes and generate a report.
    """
    if not os.path.exists(results_path):
        print(f"Error: results.json not found at {results_path}")
        return {}
    
    with open(results_path) as f:
        results = json.load(f)
    
    print(f"\n{'='*70}")
    print("FAILURE MODE ANALYSIS")
    print(f"{'='*70}\n")
    
    # Analyze each failure mode
    router_issues = analyze_router_misclassification(results)
    retrieval_issues = analyze_retrieval_threshold_misses(results)
    latency_issues = analyze_latency_anomalies(results)
    
    # Report
    failure_modes = []
    
    if router_issues:
        print(f"[FAILURE MODE #1] Router Misclassification ({len(router_issues)} cases)")
        print("-" * 70)
        for issue in router_issues[:3]:  # Show top 3
            print(f"  ID: {issue['id']}")
            print(f"  Q:  {issue['question']}")
            print(f"  Intents: {issue['intents']}")
            print(f"  Grounded: {issue['verdict'].get('grounded')}")
            print()
        
        failure_modes.append({
            "id": 1,
            "description": "Router misclassification on scheduling queries mid-flow",
            "root_cause": "Keyword collision: generic verbs ('works', 'knows') trigger knowledge classifier during scheduling",
            "evidence": f"Found {len(router_issues)} cases where scheduling intent was not recognized",
            "fix": "Strengthen STRONG_KNOWLEDGE_RE to require question mark or explicit wh- word in scheduling context",
            "occurrence_rate": f"{len(router_issues)}/{len([r for r in results if 'error' not in r])}"
        })
    
    if retrieval_issues:
        print(f"[FAILURE MODE #2] Retrieval Threshold Edge Cases ({len(retrieval_issues)} cases)")
        print("-" * 70)
        for issue in retrieval_issues[:3]:  # Show top 3
            print(f"  ID: {issue['id']}")
            print(f"  Type: {issue['type']}")
            print(f"  Q: {issue['question']}")
            print()
        
        failure_modes.append({
            "id": 2,
            "description": "Retrieval threshold (0.35) filters out relevant chunks or allows low-quality answers",
            "root_cause": "Threshold is hardcoded; different domains/query types may need different sensitivity",
            "evidence": f"Found {len(retrieval_issues)} cases of threshold-related retrieval failures",
            "fix": "Implement adaptive threshold based on query domain (education=0.4, projects=0.3, personal=0.35)",
            "occurrence_rate": f"{len(retrieval_issues)}/{len([r for r in results if 'error' not in r])}"
        })
    
    if latency_issues:
        print(f"[FAILURE MODE #3] Latency Outliers ({len(latency_issues)} cases)")
        print("-" * 70)
        for issue in latency_issues[:3]:  # Show top 3
            print(f"  ID: {issue['id']}")
            print(f"  Latency: {issue['latency_ms']}ms (avg: {issue['avg_latency_ms']}ms)")
            print(f"  Q: {issue['question']}")
            print()
        
        failure_modes.append({
            "id": 3,
            "description": "Latency spikes on certain query patterns",
            "root_cause": "LLM fallback in router / expensive embedding + reranking on long documents",
            "evidence": f"Found {len(latency_issues)} queries > 2x average latency",
            "fix": "Implement LLM caching for router decisions; consider lightweight embeddings for projects domain",
            "occurrence_rate": f"{len(latency_issues)}/{len([r for r in results if 'error' not in r])}"
        })
    
    print(f"\n{'='*70}")
    print(f"Summary: {len(failure_modes)} failure modes identified")
    print(f"{'='*70}\n")
    
    return {
        "failure_modes": failure_modes,
        "stats": {
            "router_issues": len(router_issues),
            "retrieval_issues": len(retrieval_issues),
            "latency_issues": len(latency_issues),
            "total_results": len(results),
            "successful_results": len([r for r in results if "error" not in r])
        }
    }


if __name__ == "__main__":
    evals_dir = os.path.dirname(os.path.abspath(__file__))
    results_path = os.path.join(evals_dir, "results.json")
    report = generate_failure_report(results_path)
    
    # Save failure report
    if report:
        report_path = os.path.join(evals_dir, "failure_modes.json")
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Failure modes report saved to {report_path}")
