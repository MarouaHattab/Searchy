# Searchy Multimodal GraphRAG: Research & Evaluation Benchmark Report

**Date Generated**: 2026-11-05 01:39 UTC  
**Evaluation Scope**: 3 Questions across 24 Episodes (Season 1)  
**LLM Model**: nvidia/nemotron-3.5-bolt-e4b  
**Retrieval Pipeline**: Hybrid (Knowledge Graph + Semantic Vectors + BM25 Lexical)  

---

## 1. Executive Summary: Core Metrics

This evaluation establishes empirical quality across both **Method A (Standard Ragas Framework)** and **Method B (Domain-Specific Multimodal Claim Verification & Grounding)**.

| Metric Dimension | Metric Name | Score | Benchmark Target | Status |
| :--- | :--- | :---: | :---: | :---: |
| **Method A: Ragas** | Faithfulness | **0.7833** | ≥ 0.80 | ⚠️ REVIEW |
| **Method A: Ragas** | Answer Relevancy | **0.7224** | ≥ 0.75 | ⚠️ REVIEW |
| **Method A: Ragas** | Context Precision | **0.3611** | ≥ 0.70 | ⚠️ REVIEW |
| **Method A: Ragas** | Context Recall | **0.5556** | ≥ 0.70 | ⚠️ REVIEW |
| **Method B: Domain** | Claim Entailment Rate | **1.0000** | ≥ 0.85 | ✅ PASS |
| **Method B: Domain** | Citation Precision | **0.6570** | ≥ 0.70 | ⚠️ REVIEW |
| **Method B: Domain** | Target Episode Hit Rate | **100.0%** | ≥ 80.0% | ✅ PASS |
| **Method B: Domain** | Mean Reciprocal Rank (MRR) | **0.7778** | ≥ 0.65 | ✅ PASS |
| **Method B: Domain** | Lexical Ground Truth F1 | **0.5207** | ≥ 0.50 | ✅ PASS |

---

## 2. Category Performance Breakdown

Performance breakdown across the four multimodal query archetypes:

| Category | Questions | Claim Entailment | Citation Precision | Episode Hit Rate | Ragas Faithfulness | Ragas Relevancy |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Dialogue** | 2 | 1.0000 | 0.6522 | 100.0% | 0.6750 | 0.7424 |
| **Visual** | 1 | 1.0000 | 0.6667 | 100.0% | 1.0000 | 0.6824 |

---

## 3. Representative Qualitative Examples

### Example Q001 (visual)
**Question**: What is Rachel Green wearing when she first bursts into Central Perk in the pilot?  
**Ground Truth**: *Rachel Green arrives at Central Perk soaking wet and wearing a wedding dress after running away from her wedding to Barry.*  
**Searchy Response**:  
> Rachel arrives at Central Perk in a soaked wedding dress after leaving Barry at the altar [3] [3].  
**Verification Outcome**: 1/1 Claims Supported (100.0% Entailment)  

### Example Q002 (dialogue)
**Question**: What shoe and purse metaphor does Rachel use when explaining her life choice to her father on the phone?  
**Ground Truth**: *Rachel explains to her father that all her life people have told her she was a shoe, but what if she doesn't want to be a shoe and wants to be a purse or a hat instead.*  
**Searchy Response**:  
> Rachel uses the metaphor that "You're a shoe, but what if I want to be a purse" when explaining her decision to leave Barry to her father using the shoe metaphor [1] [4].  
**Verification Outcome**: 1/1 Claims Supported (100.0% Entailment)  

### Example Q003 (dialogue)
**Question**: What ice cream metaphor does Joey use to motivate Ross after Carol leaves him?  
**Ground Truth**: *Joey tells Ross that Carol was just one flavor of ice cream and urges him to realize there are many other flavors available, telling him to 'Grab a spoon'.*  
**Searchy Response**:  
> Joey says that saying there is only one flavor of ice cream for Ross is like saying there is only one flavor of ice cream for him [6] [693.40-697.03s]. He then tells Ross that there are many flavors available, such as those with jimmies, nuts, or whipped cream [6] [697.20-710.71s].  
**Verification Outcome**: 2/2 Claims Supported (100.0% Entailment)  
