# Addons Integration Guide

This project now includes a reproducible addon workflow for:

- affaan-m/everything-claude-code
- firecrawl/firecrawl
- GoogleCloudPlatform/generative-ai

## 1) Clone all addons

From project root on Windows PowerShell:

powershell -ExecutionPolicy Bypass -File scripts/setup_external_addons.ps1

To pull latest updates later:

powershell -ExecutionPolicy Bypass -File scripts/setup_external_addons.ps1 -Update

All clones are stored under the local addons/ folder and ignored by git.

## 2) Firecrawl usage for source discovery

Install the SDK:

pip install firecrawl-py

Set API key (PowerShell):

$env:FIRECRAWL_API_KEY = "fc-..."

Seed or expand your runtime source list:

python scripts/firecrawl_seed_sources.py --query "india pothole dashcam youtube" --limit 25 --output video_sources_youtube_runtime.txt

## 3) Where each addon fits in this project

- everything-claude-code: agent workflow and memory scaffolding for repeatable engineering loops.
- firecrawl: web search/scrape data intake to improve source diversity for SSL cycles.
- GoogleCloudPlatform/generative-ai: reference patterns for evaluation, RAG, and production GenAI workflows.

## 4) Recommended operational pattern

1. Run addon bootstrap once per machine.
2. Use Firecrawl seeding before each realworld SSL cycle to refresh candidate video/source links.
3. Track query terms used per cycle in logs to compare which search profiles improve precision/recall.
