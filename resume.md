# Resume Prompt

Use this prompt to continue development on the Claude Code Analytics Dashboard.

---

## Prompt

```
I'm continuing work on the Claude Code Analytics Dashboard project.

**Project:** `/Users/wallyhansen/Desktop/sandbox/claude-code-analytics-dashboard`

**What it does:** Parses `~/.claude` JSONL logs and generates a standalone HTML dashboard with usage analytics, cost tracking, and insights.

**Key files:**
- `generate_dashboard.py` - Python extractor that parses logs and injects data into template
- `template.html` - Vanilla HTML/CSS/JS dashboard UI
- `CLAUDE.md` - Project conventions and architecture
- `backlog.md` - Feature backlog

**Current state:**
- Dashboard fully functional with 10+ pages (Overview, Tokens, Time Patterns, Tools, MCP, Subagents, Projects, Cost Calculator, Cost Insights, Error Analysis, Health)
- Features: WoW comparison, smart insights, anomaly detection, tool error/retry tracking, export JSON, clickable charts, project search
- No external dependencies - pure Python stdlib + vanilla JS

**What I want to work on next:**
[Pick from backlog.md or describe new feature]

Please read CLAUDE.md first for project conventions, then check backlog.md for the feature list.
```

---

## Quick Start

```bash
cd /Users/wallyhansen/Desktop/sandbox/claude-code-analytics-dashboard
# Regenerate dashboard after changes
python3 generate_dashboard.py && open my-dashboard.html
```
