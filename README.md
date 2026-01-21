# Claude Code Analytics Dashboard

A single-file HTML dashboard that visualizes your Claude Code usage by parsing the `~/.claude` folder logs.

![Dashboard Preview](https://img.shields.io/badge/Claude_Code-Analytics-blue)

## Features

- **Token & Cost Analytics** - Track input/output tokens, cache efficiency, estimated costs
- **Tool Usage** - See which tools Claude uses most (Bash, Read, Edit, etc.)
- **MCP Server Stats** - Monitor Model Context Protocol server usage
- **Subagent Analytics** - Track Task tool and subagent spawning patterns
- **Session Breakdown** - Usage by project and session
- **Config Health** - Recommendations based on your usage patterns

Supports both **Sonnet** ($3/$15 per MTok) and **Opus** ($15/$75 per MTok) pricing with a toggle.

## Quick Start

### Prerequisites

- Python 3.6+
- Claude Code installed (with usage data in `~/.claude`)

### Generate Your Dashboard

```bash
# Clone the repo
git clone https://github.com/wahans/claude-code-analytics-dashboard.git
cd claude-code-analytics-dashboard

# Generate your personalized dashboard
python generate_dashboard.py

# Open in browser
open my-dashboard.html  # macOS
# or: xdg-open my-dashboard.html  # Linux
# or: start my-dashboard.html  # Windows
```

That's it! A single HTML file is generated with all your data embedded - no server needed.

### Options

```bash
# Custom output filename
python generate_dashboard.py -o my-stats.html

# Specify custom .claude directory
python generate_dashboard.py --claude-dir /path/to/.claude

# Just extract data as JSON (no HTML)
python generate_dashboard.py --json-only
```

## What Data Is Analyzed?

The script parses JSONL conversation logs from `~/.claude/projects/` and extracts:

| Metric | Description |
|--------|-------------|
| **Sessions** | Distinct conversation sessions |
| **Tool Calls** | Invocations of Bash, Read, Edit, Write, Glob, Grep, etc. |
| **MCP Calls** | Calls to configured MCP servers (Gmail, Slack, etc.) |
| **Tokens** | Input, output, cache_read, cache_creation tokens |
| **Subagents** | Task tool usage with Explore, Plan, Bash agents |
| **Sequences** | Common consecutive tool patterns |

## Privacy

- **100% local** - All processing happens on your machine
- **No data sent anywhere** - The generated HTML is completely standalone
- **No external dependencies** - Works offline, no CDN calls

## File Structure

```
claude-code-analytics-dashboard/
├── generate_dashboard.py  # Main script - run this
├── template.html          # Dashboard template
├── README.md
└── my-dashboard.html      # Generated output (gitignored)
```

## Cost Calculation

Costs are estimated using Claude API pricing:

| Model | Input | Output | Cache Read | Cache Write |
|-------|-------|--------|------------|-------------|
| Sonnet 4 | $3/MTok | $15/MTok | $0.30/MTok (90% off) | $3.75/MTok (25% premium) |
| Opus 4.5 | $15/MTok | $75/MTok | $1.50/MTok (90% off) | $18.75/MTok (25% premium) |

## License

MIT
