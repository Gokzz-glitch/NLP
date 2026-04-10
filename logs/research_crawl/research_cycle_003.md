# Research Crawl Digest - Cycle 3
Timestamp: 2026-04-08T20:42:32.609744

## Source: https://raw.githubusercontent.com/affaan-m/everything-claude-code/main/README.md
```text
[![npm ecc-agentshield](https://img.shields.io/npm/dw/ecc-agentshield?label=ecc-agentshield%20weekly%20downloads&logo=npm)](https://www.npmjs.com/package/ecc-agentshield)
**The performance optimization system for AI agent harnesses. From an Anthropic hackathon winner.**
Not just configs. A complete system: skills, instincts, memory optimization, continuous learning, security scanning, and research-first development. Production-ready agents, skills, hooks, rules, MCP configurations, and legacy command shims evolved over 10+ months of intensive daily use building real products.
Works across **Claude Code**, **Codex**, **Cursor**, **OpenCode**, **Gemini**, and other AI agent harnesses.
<img src="./assets/images/security/security-guide-header.png" alt="The Shorthand Guide to Everything Agentic Security" />
<td align="center"><b>Security Guide</b><br/>Attack vectors, sandboxing, sanitization, CVEs, AgentShield.</td>
| Subagent Orchestration | The context problem, iterative retrieval pattern |
- **Public surface synced to the live repo** — metadata, catalog counts, plugin manifests, and install-facing docs now match the actual OSS surface: 38 agents, 156 skills, and 72 legacy command shims.
- **Ecosystem hardening** — AgentShield, ECC Tools cost controls, billing portal work, and website refreshes continue to ship around the core plugin instead of drifting into separate silos.
- **6 new agents** — `typescript-reviewer`, `pytorch-build-resolver`, `java-build-resolver`, `java-reviewer`, `kotlin-reviewer`, `kotlin-build-resolver` expand language coverage to 10 languages.
- **CI hardening** — 19 test failure fixes, catalog count enforcement, install manifest validation, and full test suite green.
- **Harness-first release** — ECC is now explicitly framed as an agent harness performance system, not just a config pack.
- **Codex app + CLI support** — Direct `AGENTS.md`-based Codex support, installer targeting, and Codex docs
- **992 internal tests** — Expanded validation and regression coverage across plugin, hooks, skills, and packaging
### v1.6.0 — Codex CLI, AgentShield & Marketplace (Feb 2026)
- **AgentShield integration** — `/security-scan` skill runs AgentShield directly from Claude Code; 1282 tests, 102 rules
- **978 internal tests** — Expanded validation suite across agents, skills, commands, hooks, and rules
- **PM2 & multi-agent orchestration** — 6 new commands (`/pm2`, `/multi-plan`, `/multi-execute`, `/multi-backend`, `/multi-frontend`, `/multi-workflow`) for managing complex multi-service workflows
- **Chinese (zh-CN) translations** — Complete translation of all agents, commands, skills, and rules (80+ files)
- **Full OpenCode integration** — 12 agents, 24 commands, 16 skills with hook support via OpenCode's plugin system (20+ event types)
# ./install.sh --target gemini --profile full
# .\install.ps1 --target gemini --profile full
**That's it!** You now have access to 47 agents, 181 skills, and 79 legacy command shims.
> - `~/.claude/bin/codeagent-wrapper`
```

## Source: https://raw.githubusercontent.com/firecrawl/firecrawl/main/README.md
```text
src="https://raw.githubusercontent.com/firecrawl/firecrawl/main/img/firecrawl_logo.png"
<a href="https://github.com/firecrawl/firecrawl/blob/main/LICENSE">
<img src="https://img.shields.io/github/license/firecrawl/firecrawl" alt="License">
<a href="https://pepy.tech/project/firecrawl-py">
<img src="https://static.pepy.tech/badge/firecrawl-py" alt="Downloads">
<a href="https://GitHub.com/firecrawl/firecrawl/graphs/contributors">
<img src="https://img.shields.io/github/contributors/firecrawl/firecrawl.svg" alt="GitHub Contributors">
<a href="https://firecrawl.dev">
<img src="https://img.shields.io/badge/Visit-firecrawl.dev-orange" alt="Visit firecrawl.dev">
<a href="https://twitter.com/firecrawl">
<a href="https://discord.gg/firecrawl">
# **🔥 Firecrawl**
**Power AI agents with clean web data.** The API to search, scrape, and interact with the web at scale. Open source and available as a [hosted service](https://firecrawl.dev/?ref=github).
<a href="https://github.com/firecrawl/firecrawl">
<img src="https://img.shields.io/github/stars/firecrawl/firecrawl.svg?style=social&label=Star&maxAge=2592000" alt="GitHub stars">
## Why Firecrawl?
- **Industry-leading reliability**: Covers 96% of the web, including JS-heavy pages — no proxy headaches, just clean data ([see benchmarks](https://www.firecrawl.dev/blog/the-worlds-best-web-data-api-v25))
- **Blazingly fast**: P95 latency of 3.4s across millions of pages, built for real-time agents and dynamic apps
- **Agent ready**: Connect Firecrawl to any AI agent or MCP client with a single command
- **Open source**: Developed transparently and collaboratively — [join our community](https://github.com/firecrawl/firecrawl)
| [**Agent**](#agent) | Automated data gathering, just describe what you need |
| [**Crawl**](#crawl) | Scrape all URLs of a website with a single request |
Sign up at [firecrawl.dev](https://firecrawl.dev) to get your API key. Try the [playground](https://firecrawl.dev/playground) to test it out.
from firecrawl import Firecrawl
```

## Source: https://raw.githubusercontent.com/googlecloudplatform/generative-ai/main/README.md
```text
> **[Gemini 3.1 Pro](https://cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/3-1-pro) has been released!**
> - [Intro to Gemini 3.1 Pro](gemini/getting-started/intro_gemini_3_1_pro.ipynb)
<img src="https://storage.googleapis.com/github-repo/img/gemini/Spark__Gradient_Alpha_100px.gif" width="45px" alt="Gemini">
<a href="gemini/"><code>gemini/</code></a>
Discover Gemini through starter notebooks, use cases, function calling, sample apps, and more.
- ✨ [Agent Development Kit (ADK) Samples](https://github.com/google/adk-samples): This repository provides ready-to-use agents built on top of the Agent Development Kit, designed to accelerate your development process. These agents cover a range of common use cases and complexities, from simple conversational bots to complex multi-agent workflows.
- [🚀 Agent Starter Pack](https://github.com/GoogleCloudPlatform/agent-starter-pack)
- A collection of production-ready Generative AI Agent templates built for Google Cloud.
- It accelerates development by providing a holistic, production-ready solution, addressing common challenges (Deployment & Operations, Evaluation, Customization, Observability) in building and deploying Gen AI agents.
- [Gemini Cookbook](https://github.com/google-gemini/cookbook/)
- [MCP Servers for GenMedia](https://goo.gle/vertex-genmedia-mcp) - Empower your agents with generative media tools.
- Gemini in Google Cloud
- [Gemini by Example](https://geminibyexample.com)
```

## Source: https://raw.githubusercontent.com/googlecloudplatform/generative-ai/main/vision/sample-apps/V-Start/README.md
```text
# V-Start: A Toolkit for Veo Prompting and Evaluation
V-Start is divided into two main categories: Prompting and Evaluation.
* **Prompt Enhancer**: Improve an existing prompt by leveraging Gemini to enhance its cinematic detail and effectiveness.
### Evaluation Tools
* **Alignment Eval**: An autorater that provides an objective score (0-100%) of how well a video matches its prompt. You can evaluate a single prompt-video pair or process multiple pairs in bulk by pasting data directly into the tool or uploading a CSV file from your local machine. The tool works by breaking the prompt into sub-questions, and Gemini uses its Visual Question Answering (VQA) capabilities to score the video's alignment. All results can be stored for further analysis.
* **Side-by-Side Comparison**: Compare videos side-by-side to gather human feedback. Participate in existing studies (like prompt format evaluation) or create your own for qualitative evaluation. Results can be stored for further analysis.
* **Core AI**: Google Gemini API (specifically gemini-2.5-pro)
│   └── veo-youtube-study.json # Data for the A/B evaluation study
├── api.js         # Handles the fetch call to the backend Gemini API
Open the `.env` file and add your Gemini API Key (if using Method 2):
API_KEY=your_gemini_api_key_here
Store your Gemini API key in Secret Manager.
gcloud secrets create gemini-api-key --replication-policy="automatic"
printf "your_gemini_api_key_here" | gcloud secrets versions add gemini-api-key --data-file=-
--set-env-vars="API_KEY=sm://${PROJECT_ID}/gemini-api-key/latest"
```
