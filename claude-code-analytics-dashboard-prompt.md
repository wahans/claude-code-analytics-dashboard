# Claude Code Analytics Dashboard - Expert Prompt

Use this prompt with Claude Code to build a comprehensive, dynamic analytics dashboard for your Claude Code usage.

---

## The Prompt

```
Build a comprehensive, interactive Claude Code Analytics Dashboard that parses my local ~/.claude folder data and provides actionable insights to help me optimize my configuration and usage patterns.

## Core Requirements

### Data Sources to Parse
1. **Session Logs**: Parse all JSONL files in `~/.claude/projects/*/` containing session transcripts
2. **MCP Configuration**: Read `.mcp.json` (project-scoped) and `~/.claude/settings.json` / `~/.claude/settings.local.json` for MCP server configs
3. **Subagents**: Scan `~/.claude/agents/` (user-level) and `.claude/agents/` (project-level) for custom subagent definitions
4. **Rules Files**: Locate and track references to `CLAUDE.md` files at all scopes (project root, ~/.claude/CLAUDE.md, nested directories)
5. **Skills**: Identify any skills defined in `.claude/skills/` or referenced in session logs
6. **Hooks**: Parse hook configurations from settings files

### JSONL Log Structure Reference
Each log entry follows this schema:
```json
{
  "parentUuid": "string",
  "sessionId": "string",
  "version": "string",
  "gitBranch": "string",
  "cwd": "string",
  "message": {
    "role": "user|assistant",
    "content": [
      {
        "type": "text|tool_use|tool_result",
        "text": "string",
        "name": "string",  // Tool name when type is tool_use
        "input": {},
        "tool_use_id": "string"
      }
    ],
    "usage": {
      "input_tokens": 0,
      "output_tokens": 0,
      "cache_creation_input_tokens": 0,
      "cache_read_input_tokens": 0
    }
  },
  "uuid": "string",
  "timestamp": "ISO-8601",
  "toolUseResult": {}
}
```

### Analytics Modules to Implement

#### 1. MCP Server Analytics
- List all configured MCP servers (user vs project scope)
- Track which MCP tools are actually being invoked (parse tool_use entries where name matches MCP tool patterns)
- Calculate usage frequency per MCP server and tool
- Identify "dead" MCP servers (configured but never used)
- Show MCP tool success/failure rates

#### 2. Subagent Analytics
- Detect Task tool invocations with `subagent_type` parameter
- Track which subagent types are triggered (explore, plan, general-purpose, custom agents)
- Measure subagent invocation frequency and patterns
- Calculate average subagent execution duration (using timestamp deltas)
- Identify most/least used custom subagents

#### 3. Tool Usage Analytics
- Aggregate all tool invocations by tool name (Read, Write, Edit, Bash, Grep, Glob, WebFetch, etc.)
- Calculate tool frequency rankings
- Track tool chains (common sequences of tool calls)
- Identify tools with high failure rates from tool_result analysis
- Show tool usage trends over time (daily/weekly)

#### 4. Rules File Analytics
- Detect when CLAUDE.md files are referenced in session context
- Track which project-specific vs user-global rules are active
- Identify if rules are being followed (correlate with session outcomes)
- List all CLAUDE.md locations and their content summaries

#### 5. Skills Analytics
- Track skill invocations from session logs
- Measure skill usage frequency
- Identify skills that are defined but never used

#### 6. Token & Cost Analytics
- Calculate daily/weekly/monthly token usage
- Break down by input vs output vs cache tokens
- Show cache efficiency (cache_read vs cache_creation ratios)
- Estimate costs using current Claude pricing
- Track token usage trends and anomalies
- Show per-project and per-session breakdowns

#### 7. Session Analytics
- Session count over time
- Average session duration and token consumption
- Sessions per project/directory
- Git branch distribution across sessions
- Identify high-cost sessions

### Dashboard Interface Requirements

Create an interactive React dashboard (save as .jsx file) with:

1. **Navigation sidebar** with sections for each analytics module
2. **Overview page** with key metrics summary cards:
   - Total sessions analyzed
   - Total tokens consumed
   - Estimated cost
   - Most-used tools/MCP servers/subagents
3. **Filterable date range selector** (last 7 days, 30 days, all time, custom)
4. **Project filter** to scope analysis to specific projects
5. **Interactive charts using Recharts**:
   - Line charts for usage trends over time
   - Bar charts for tool/MCP/subagent rankings
   - Pie charts for distribution breakdowns
   - Heatmaps for usage patterns by day/hour
6. **Sortable data tables** for detailed drill-down
7. **Export functionality** to JSON for raw data

### Implementation Notes

1. **Start by exploring my actual ~/.claude folder** to understand the real data structure
2. Use bash to find all JSONL files: `find ~/.claude/projects -name "*.jsonl" -type f`
3. Parse JSONL files efficiently - they can be large
4. Handle parsing errors gracefully (some entries may be malformed)
5. Store parsed data in React state for interactive filtering
6. Make the dashboard fully client-side (no backend needed)
7. Include clear section headers and tooltips explaining each metric
8. Add a "Configuration Health" section that provides actionable recommendations:
   - Unused MCP servers to remove
   - Underutilized subagents
   - High-cost patterns to optimize
   - Cache efficiency improvements

### Output
1. A single comprehensive React (.jsx) file that can render in Claude's artifact viewer
2. Include sample/demo data fallback if ~/.claude folder is not accessible
3. Make it visually polished with a dark theme suitable for developers
4. Save any helper Python scripts used for data extraction separately

### Stretch Goals (if time permits)
- Real-time monitoring mode that watches for new log entries
- Comparison view between time periods
- Anomaly detection for unusual usage spikes
- Integration suggestions based on observed tool usage patterns
- Export to HTML for sharing/archiving
```

---

## Usage Instructions

1. Copy the prompt above (everything between the triple backticks)
2. Paste it into Claude Code
3. Claude will:
   - Explore your `~/.claude` folder structure
   - Parse your session logs and configuration files
   - Build an interactive React dashboard
   - Save it as a `.jsx` file you can view

## What This Prompt Addresses

Based on the original X thread request, this prompt specifically targets:

| Need from Thread | How This Prompt Addresses It |
|------------------|------------------------------|
| "What percent of time using MCP servers" | MCP Server Analytics module with usage frequency tracking |
| "Which skills are being used when and how often" | Skills Analytics module with invocation tracking |
| "Which subagents are triggered" | Subagent Analytics with Task tool parsing |
| "Which rules files are referenced" | Rules File Analytics tracking CLAUDE.md usage |
| "Important insights to help developers improve setups" | Configuration Health section with actionable recommendations |
| "Something more dynamic and powerful" | Full interactive React dashboard with filters, charts, and drill-downs |

## References

This prompt was designed based on analysis of:
- [Claude Code Data Usage Docs](https://code.claude.com/docs/en/data-usage)
- [ccusage CLI tool](https://github.com/ryoppippi/ccusage) - Token usage analytics
- [clog viewer](https://github.com/HillviewCap/clog) - JSONL log viewer
- [claude_telemetry](https://github.com/TechNickAI/claude_telemetry) - OpenTelemetry wrapper
- [Claude Code Settings Docs](https://code.claude.com/docs/en/settings)
- [Understanding Claude Code's Full Stack](https://alexop.dev/posts/understanding-claude-code-full-stack/)
