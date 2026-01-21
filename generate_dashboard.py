#!/usr/bin/env python3
"""
Claude Code Analytics Dashboard Generator

Parses ~/.claude folder logs and generates a standalone HTML dashboard.

Usage:
    python generate_dashboard.py              # Generate my-dashboard.html
    python generate_dashboard.py -o stats.html # Custom output filename
    python generate_dashboard.py --json-only   # Output JSON only
"""

import json
import os
import sys
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# Pricing per million tokens
PRICING = {
    'sonnet': {'input': 3, 'output': 15},
    'opus': {'input': 15, 'output': 75}
}
CACHE_READ_DISCOUNT = 0.1   # 90% discount
CACHE_CREATE_PREMIUM = 1.25  # 25% premium


def parse_jsonl_file(filepath):
    """Parse a single JSONL file and extract relevant data."""
    entries = []
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        pass
    return entries


def extract_tool_calls(entries):
    """Extract tool usage from entries."""
    tool_counts = defaultdict(int)
    mcp_counts = defaultdict(int)
    subagent_counts = defaultdict(int)
    sequences = []
    last_tool = None

    for entry in entries:
        msg = entry.get('message', {})
        content = msg.get('content', [])

        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get('type') == 'tool_use':
                    tool_name = item.get('name', 'unknown')
                    tool_counts[tool_name] += 1

                    # Track MCP calls
                    if tool_name.startswith('mcp__'):
                        parts = tool_name.split('__')
                        if len(parts) >= 2:
                            server = parts[1]
                            mcp_counts[server] += 1

                    # Track subagent usage
                    if tool_name == 'Task':
                        inp = item.get('input', {})
                        subagent_type = inp.get('subagent_type', 'unknown')
                        subagent_counts[subagent_type] += 1

                    # Track sequences
                    if last_tool:
                        sequences.append(f"{last_tool} -> {tool_name}")
                    last_tool = tool_name

    return tool_counts, mcp_counts, subagent_counts, sequences


def extract_tokens(entries):
    """Extract token usage from entries."""
    totals = {'input': 0, 'output': 0, 'cache_read': 0, 'cache_creation': 0}
    daily = defaultdict(lambda: {'input': 0, 'output': 0})

    for entry in entries:
        msg = entry.get('message', {})
        usage = msg.get('usage', {})

        if usage:
            totals['input'] += usage.get('input_tokens', 0)
            totals['output'] += usage.get('output_tokens', 0)
            totals['cache_read'] += usage.get('cache_read_input_tokens', 0)
            totals['cache_creation'] += usage.get('cache_creation_input_tokens', 0)

            # Try to get date from entry
            ts = entry.get('timestamp')
            if ts:
                try:
                    date = ts[:10]
                    daily[date]['input'] += usage.get('input_tokens', 0)
                    daily[date]['output'] += usage.get('output_tokens', 0)
                except:
                    pass

    return totals, dict(daily)


def calc_cost(tokens, pricing):
    """Calculate cost based on token usage."""
    input_price = pricing['input']
    output_price = pricing['output']

    regular_input = max(0, tokens['input'] - tokens['cache_read'])
    cost = (regular_input / 1_000_000) * input_price
    cost += (tokens['output'] / 1_000_000) * output_price
    cost += (tokens['cache_read'] / 1_000_000) * input_price * CACHE_READ_DISCOUNT
    cost += (tokens['cache_creation'] / 1_000_000) * input_price * CACHE_CREATE_PREMIUM
    return round(cost, 2)


def analyze_claude_folder(claude_dir):
    """Analyze the .claude folder and return analytics data."""
    claude_path = Path(claude_dir).expanduser()
    projects_path = claude_path / 'projects'

    if not projects_path.exists():
        print(f"Error: {projects_path} not found")
        sys.exit(1)

    # Find all JSONL files
    jsonl_files = list(projects_path.rglob('*.jsonl'))
    print(f"Found {len(jsonl_files)} JSONL files")

    # Aggregate data
    all_tool_counts = defaultdict(int)
    all_mcp_counts = defaultdict(int)
    all_subagent_counts = defaultdict(int)
    all_sequences = []
    total_tokens = {'input': 0, 'output': 0, 'cache_read': 0, 'cache_creation': 0}
    all_daily = defaultdict(lambda: {'input': 0, 'output': 0})
    sessions = set()
    projects = set()
    project_tokens = defaultdict(lambda: {'sessions': 0, 'tokens': 0})

    for filepath in jsonl_files:
        entries = parse_jsonl_file(filepath)
        if not entries:
            continue

        # Extract session and project info
        for entry in entries:
            sid = entry.get('sessionId')
            if sid:
                sessions.add(sid)

        # Get project name from path
        rel_path = filepath.relative_to(projects_path)
        project_name = str(rel_path.parts[0]) if rel_path.parts else 'unknown'
        projects.add(project_name)

        # Extract tool calls
        tool_counts, mcp_counts, subagent_counts, sequences = extract_tool_calls(entries)
        for tool, count in tool_counts.items():
            all_tool_counts[tool] += count
        for server, count in mcp_counts.items():
            all_mcp_counts[server] += count
        for agent, count in subagent_counts.items():
            all_subagent_counts[agent] += count
        all_sequences.extend(sequences)

        # Extract tokens
        tokens, daily = extract_tokens(entries)
        for key in total_tokens:
            total_tokens[key] += tokens[key]
        for date, vals in daily.items():
            all_daily[date]['input'] += vals['input']
            all_daily[date]['output'] += vals['output']

        # Project stats
        project_tokens[project_name]['sessions'] += 1
        project_tokens[project_name]['tokens'] += tokens['input'] + tokens['output']

    # Process sequences
    seq_counts = defaultdict(int)
    for seq in all_sequences:
        # Simplify tool names for sequences
        parts = seq.split(' -> ')
        simple_parts = []
        for p in parts:
            if p.startswith('mcp__'):
                simple_parts.append('MCP')
            else:
                simple_parts.append(p)
        simple_seq = ' -> '.join(simple_parts)
        seq_counts[simple_seq] += 1

    # Calculate costs
    sonnet_cost = calc_cost(total_tokens, PRICING['sonnet'])
    opus_cost = calc_cost(total_tokens, PRICING['opus'])

    # Cache efficiency
    total_input = total_tokens['input'] + total_tokens['cache_read']
    cache_rate = round((total_tokens['cache_read'] / total_input * 100), 1) if total_input > 0 else 0

    # Format data for dashboard
    tools_list = sorted(all_tool_counts.items(), key=lambda x: -x[1])[:15]
    mcp_list = sorted(all_mcp_counts.items(), key=lambda x: -x[1])
    subagent_list = sorted(all_subagent_counts.items(), key=lambda x: -x[1])
    seq_list = sorted(seq_counts.items(), key=lambda x: -x[1])[:10]

    # Daily data (last 14 days)
    sorted_dates = sorted(all_daily.keys())[-14:]
    daily_list = [{'date': d[-5:], 'input': all_daily[d]['input'], 'output': all_daily[d]['output']}
                  for d in sorted_dates]

    # Project data
    proj_list = []
    for name, data in sorted(project_tokens.items(), key=lambda x: -x[1]['tokens']):
        display_name = name
        if name.startswith('-Users-'):
            parts = name.replace('-Users-', '').split('-')
            if len(parts) > 1:
                display_name = parts[-1] or '~ (home)'
            else:
                display_name = '~ (home)'
        proj_list.append({'name': display_name, 'sessions': data['sessions'], 'tokens': data['tokens']})

    return {
        'generated': datetime.now().strftime('%b %d, %Y'),
        'summary': {
            'sessions': len(sessions),
            'files': len(jsonl_files),
            'projects': len(projects),
            'total_tool_calls': sum(all_tool_counts.values()),
            'unique_tools': len(all_tool_counts),
            'total_mcp_calls': sum(all_mcp_counts.values()),
            'active_mcp_servers': len(all_mcp_counts),
            'cache_rate': cache_rate
        },
        'tokens': total_tokens,
        'costs': {'sonnet': sonnet_cost, 'opus': opus_cost},
        'tools': [{'name': t[0], 'count': t[1]} for t in tools_list],
        'mcp': [{'server': m[0], 'count': m[1]} for m in mcp_list],
        'subagents': [{'type': s[0], 'count': s[1]} for s in subagent_list],
        'sequences': [{'sequence': s[0], 'count': s[1]} for s in seq_list],
        'daily': daily_list,
        'projects': proj_list[:10]
    }


def generate_html(data):
    """Generate the complete HTML dashboard with embedded data."""
    template_path = Path(__file__).parent / 'template.html'

    if not template_path.exists():
        print(f"Error: template.html not found at {template_path}")
        sys.exit(1)

    with open(template_path, 'r') as f:
        html = f.read()

    # Inject data
    html = html.replace('__DATA_PLACEHOLDER__', json.dumps(data, indent=2))
    return html


def main():
    parser = argparse.ArgumentParser(description='Generate Claude Code Analytics Dashboard')
    parser.add_argument('-o', '--output', default='my-dashboard.html', help='Output HTML filename')
    parser.add_argument('--claude-dir', default='~/.claude', help='Path to .claude directory')
    parser.add_argument('--json-only', action='store_true', help='Output JSON data only')
    args = parser.parse_args()

    print(f"Analyzing {args.claude_dir}...")
    data = analyze_claude_folder(args.claude_dir)

    print(f"\nAnalysis complete:")
    print(f"  Sessions: {data['summary']['sessions']}")
    print(f"  Tool calls: {data['summary']['total_tool_calls']}")
    print(f"  MCP calls: {data['summary']['total_mcp_calls']}")
    print(f"  Cache rate: {data['summary']['cache_rate']}%")
    print(f"  Est. cost (Sonnet): ${data['costs']['sonnet']}")
    print(f"  Est. cost (Opus): ${data['costs']['opus']}")

    if args.json_only:
        output_path = args.output.replace('.html', '.json')
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"\nJSON saved to: {output_path}")
    else:
        html = generate_html(data)
        with open(args.output, 'w') as f:
            f.write(html)
        print(f"\nDashboard saved to: {args.output}")
        print(f"Open in browser: open {args.output}")


if __name__ == '__main__':
    main()
