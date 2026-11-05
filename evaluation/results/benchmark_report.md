# Searchy Multimodal GraphRAG: Research & Evaluation Benchmark Report

**Date Generated**: 2026-11-05 01:08 UTC  
**Evaluation Scope**: 3 Questions across 24 Episodes (Season 1)  
**LLM Model**: nvidia/nemotron-3.5-bolt-e4b  
**Retrieval Pipeline**: Hybrid (Knowledge Graph + Semantic Vectors + BM25 Lexical)  

---

## 1. Executive Summary: Core Metrics

This evaluation establishes empirical quality across both **Method A (Standard Ragas Framework)** and **Method B (Domain-Specific Multimodal Claim Verification & Grounding)**.

| Metric Dimension | Metric Name | Score | Benchmark Target | Status |
| :--- | :--- | :---: | :---: | :---: |
| **Method A: Ragas** | Faithfulness | **0.1667** | ≥ 0.80 | ⚠️ REVIEW |
| **Method A: Ragas** | Answer Relevancy | **0.8072** | ≥ 0.75 | ✅ PASS |
| **Method A: Ragas** | Context Precision | **0.0000** | ≥ 0.70 | ⚠️ REVIEW |
| **Method A: Ragas** | Context Recall | **0.0000** | ≥ 0.70 | ⚠️ REVIEW |
| **Method B: Domain** | Claim Entailment Rate | **0.5556** | ≥ 0.85 | ⚠️ REVIEW |
| **Method B: Domain** | Citation Precision | **0.3527** | ≥ 0.70 | ⚠️ REVIEW |
| **Method B: Domain** | Target Episode Hit Rate | **100.0%** | ≥ 80.0% | ✅ PASS |
| **Method B: Domain** | Mean Reciprocal Rank (MRR) | **0.7778** | ≥ 0.65 | ✅ PASS |
| **Method B: Domain** | Lexical Ground Truth F1 | **0.4789** | ≥ 0.50 | ⚠️ REVIEW |

---

## 2. Category Performance Breakdown

Performance breakdown across the four multimodal query archetypes:

| Category | Questions | Claim Entailment | Citation Precision | Episode Hit Rate | Ragas Faithfulness | Ragas Relevancy |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Dialogue** | 2 | 0.3333 | 0.1956 | 100.0% | 0.0000 | 0.8411 |
| **Visual** | 1 | 1.0000 | 0.6667 | 100.0% | 0.5000 | 0.7393 |

---

## 3. Representative Qualitative Examples

### Example Q001 (visual)
**Question**: What is Rachel Green wearing when she first bursts into Central Perk in the pilot?  
**Ground Truth**: *Rachel Green arrives at Central Perk soaking wet and wearing a wedding dress after running away from her wedding to Barry.*  
**Searchy Response**:  
> Rachel Green arrived at Central Perk in a soaked wedding dress after leaving her fiancé Barry at the altar and reunited with Monica [3] .  
**Verification Outcome**: 1/1 Claims Supported (100.0% Entailment)  

### Example Q002 (dialogue)
**Question**: What shoe and purse metaphor does Rachel use when explaining her life choice to her father on the phone?  
**Ground Truth**: *Rachel explains to her father that all her life people have told her she was a shoe, but what if she doesn't want to be a shoe and wants to be a purse or a hat instead.*  
**Searchy Response**:  
> Rachel uses the metaphor that "You're a shoe, but what if I want to be a purse?" when explaining her decision to her father over the phone [1]. This statement was made while Rachel was in a white wedding dress at Central Perk after leaving her fiancé Barry at the altar [1]. You're a shoe!' Then today I stopped and said, 'What if I don't wanna be a shoe?'" [4].  
**Verification Outcome**: 2/3 Claims Supported (66.7% Entailment)  

### Example Q003 (dialogue)
**Question**: What ice cream metaphor does Joey use to motivate Ross after Carol leaves him?  
**Ground Truth**: *Joey tells Ross that Carol was just one flavor of ice cream and urges him to realize there are many other flavors available, telling him to 'Grab a spoon'.*  
**Searchy Response**:  
> Joey uses the metaphor that saying there is only one flavor of ice cream for Ross is like saying there is only one flavor of ice cream for him, and then tells Ross that there are many flavors available, such as those with jimmies, nuts, or whipped cream [6] [6].  
**Verification Outcome**: 0/1 Claims Supported (0.0% Entailment)  
