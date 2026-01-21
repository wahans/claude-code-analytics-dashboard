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
    except Exception:
        pass
    return entries


def calc_cost(tokens, pricing):
    """Calculate cost based on token usage."""
    input_price = pricing['input']
    output_price = pricing['output']

    regular_input = max(0, tokens.get('input', 0) - tokens.get('cache_read', 0))
    cost = (regular_input / 1_000_000) * input_price
    cost += (tokens.get('output', 0) / 1_000_000) * output_price
    cost += (tokens.get('cache_read', 0) / 1_000_000) * input_price * CACHE_READ_DISCOUNT
    cost += (tokens.get('cache_creation', 0) / 1_000_000) * input_price * CACHE_CREATE_PREMIUM
    return round(cost, 4)


def generate_cost_insight(session):
    """Generate a 1-2 line cost-saving insight based on session patterns."""
    tokens = session['tokens']
    tools = session['tool_calls']
    subagents = len(session['subagent_calls'])
    turns = session['turns']

    insights = []

    # Check output/input ratio - high output is expensive
    if tokens['output'] > 0 and tokens['input'] > 0:
        output_ratio = tokens['output'] / tokens['input']
        if output_ratio > 0.3:
            insights.append(('output', f"High output ratio ({output_ratio:.0%}). Consider asking for more concise responses."))

    # Check cache efficiency
    total_input = tokens['input'] + tokens['cache_read']
    if total_input > 0:
        cache_rate = tokens['cache_read'] / total_input
        if cache_rate < 0.5 and total_input > 100000:
            insights.append(('cache', f"Low cache rate ({cache_rate:.0%}). Breaking into smaller sessions could improve caching."))

    # Check for many subagent spawns
    if subagents > 5:
        insights.append(('subagents', f"{subagents} subagents spawned. Consolidating tasks could reduce overhead."))

    # Check for many turns (long conversation)
    if turns > 50:
        insights.append(('turns', f"{turns} turns in session. Clearer upfront requirements could reduce back-and-forth."))

    # Check for heavy file reading
    read_calls = tools.get('Read', 0) + tools.get('Glob', 0) + tools.get('Grep', 0)
    if read_calls > 100:
        insights.append(('reads', f"{read_calls} file operations. Providing more context upfront could reduce exploration."))

    # Check for Task tool overuse (spawning agents repeatedly)
    task_calls = tools.get('Task', 0)
    if task_calls > 10:
        insights.append(('tasks', f"{task_calls} Task calls. Consider batching related work to reduce agent spawning."))

    # Pick the most impactful insight (prioritize by potential savings)
    priority = ['output', 'cache', 'turns', 'subagents', 'tasks', 'reads']
    for p in priority:
        for (key, msg) in insights:
            if key == p:
                return msg

    # Default insight if nothing specific found
    if tokens['output'] > 500000:
        return "Large session. Consider /clear between distinct tasks to reset context."
    return "Review session for opportunities to provide clearer, more specific prompts."


def extract_session_data(entries, filepath, projects_path):
    """Extract comprehensive data from a single session's entries."""
    session_data = {
        'session_id': None,
        'file': str(filepath),
        'project': None,
        'tokens': {'input': 0, 'output': 0, 'cache_read': 0, 'cache_creation': 0},
        'turns': 0,
        'tool_calls': defaultdict(int),
        'mcp_calls': defaultdict(lambda: defaultdict(int)),  # server -> function -> count
        'subagent_calls': [],  # list of {type, description, prompt}
        'first_timestamp': None,
        'last_timestamp': None,
    }

    # Get project name from path
    try:
        rel_path = filepath.relative_to(projects_path)
        project_name = str(rel_path.parts[0]) if rel_path.parts else 'unknown'
        # Clean up project name
        if project_name.startswith('-Users-'):
            parts = project_name.replace('-Users-', '').split('-')
            if len(parts) > 1:
                session_data['project'] = parts[-1] or '~ (home)'
            else:
                session_data['project'] = '~ (home)'
        else:
            session_data['project'] = project_name
    except:
        session_data['project'] = 'unknown'

    last_tool = None
    sequences = []

    for entry in entries:
        # Track session ID
        sid = entry.get('sessionId')
        if sid and not session_data['session_id']:
            session_data['session_id'] = sid

        # Track timestamps
        ts = entry.get('timestamp')
        if ts:
            if not session_data['first_timestamp']:
                session_data['first_timestamp'] = ts
            session_data['last_timestamp'] = ts

        msg = entry.get('message', {})
        role = msg.get('role')

        # Count turns (assistant messages with content)
        if role == 'assistant':
            session_data['turns'] += 1

        # Extract token usage
        usage = msg.get('usage', {})
        if usage:
            session_data['tokens']['input'] += usage.get('input_tokens', 0)
            session_data['tokens']['output'] += usage.get('output_tokens', 0)
            session_data['tokens']['cache_read'] += usage.get('cache_read_input_tokens', 0)
            session_data['tokens']['cache_creation'] += usage.get('cache_creation_input_tokens', 0)

        # Extract tool calls
        content = msg.get('content', [])
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get('type') == 'tool_use':
                    tool_name = item.get('name', 'unknown')
                    session_data['tool_calls'][tool_name] += 1

                    # Track MCP calls with function names
                    if tool_name.startswith('mcp__'):
                        parts = tool_name.split('__')
                        if len(parts) >= 3:
                            server = parts[1]
                            function = parts[2]
                            session_data['mcp_calls'][server][function] += 1
                        elif len(parts) == 2:
                            server = parts[1]
                            session_data['mcp_calls'][server]['unknown'] += 1

                    # Track subagent calls with details
                    if tool_name == 'Task':
                        inp = item.get('input', {})
                        subagent_info = {
                            'type': inp.get('subagent_type', 'unknown'),
                            'description': inp.get('description', '')[:100],  # Truncate
                            'prompt': inp.get('prompt', '')[:200],  # Truncate for size
                        }
                        session_data['subagent_calls'].append(subagent_info)

                    # Track sequences
                    if last_tool:
                        simple_last = 'MCP' if last_tool.startswith('mcp__') else last_tool
                        simple_curr = 'MCP' if tool_name.startswith('mcp__') else tool_name
                        sequences.append(f"{simple_last} -> {simple_curr}")
                    last_tool = tool_name

    # Convert defaultdicts to regular dicts
    session_data['tool_calls'] = dict(session_data['tool_calls'])
    session_data['mcp_calls'] = {k: dict(v) for k, v in session_data['mcp_calls'].items()}

    return session_data, sequences


def analyze_claude_folder(claude_dir):
    """Analyze the .claude folder and return comprehensive analytics data."""
    claude_path = Path(claude_dir).expanduser()
    projects_path = claude_path / 'projects'

    if not projects_path.exists():
        print(f"Error: {projects_path} not found")
        sys.exit(1)

    # Find all JSONL files
    jsonl_files = list(projects_path.rglob('*.jsonl'))
    print(f"Found {len(jsonl_files)} JSONL files")

    # Collect all session data
    all_sessions = []
    all_sequences = []

    # Aggregates
    total_tokens = {'input': 0, 'output': 0, 'cache_read': 0, 'cache_creation': 0}
    all_tool_counts = defaultdict(int)
    all_mcp_data = defaultdict(lambda: defaultdict(int))  # server -> function -> count
    all_subagent_data = defaultdict(list)  # type -> list of {description, prompt}
    all_daily = defaultdict(lambda: {'input': 0, 'output': 0, 'cost_sonnet': 0})
    project_data = defaultdict(lambda: {'sessions': 0, 'tokens': 0, 'cost_sonnet': 0})
    unique_sessions = set()

    for filepath in jsonl_files:
        entries = parse_jsonl_file(filepath)
        if not entries:
            continue

        session_data, sequences = extract_session_data(entries, filepath, projects_path)
        all_sequences.extend(sequences)

        # Skip empty sessions
        if session_data['tokens']['input'] == 0 and session_data['tokens']['output'] == 0:
            continue

        # Calculate session cost
        session_data['cost_sonnet'] = calc_cost(session_data['tokens'], PRICING['sonnet'])
        session_data['cost_opus'] = calc_cost(session_data['tokens'], PRICING['opus'])

        all_sessions.append(session_data)

        # Track unique sessions
        if session_data['session_id']:
            unique_sessions.add(session_data['session_id'])

        # Aggregate tokens
        for key in total_tokens:
            total_tokens[key] += session_data['tokens'][key]

        # Aggregate tool counts
        for tool, count in session_data['tool_calls'].items():
            all_tool_counts[tool] += count

        # Aggregate MCP data
        for server, functions in session_data['mcp_calls'].items():
            for func, count in functions.items():
                all_mcp_data[server][func] += count

        # Aggregate subagent data
        for sub in session_data['subagent_calls']:
            all_subagent_data[sub['type']].append({
                'description': sub['description'],
                'prompt': sub['prompt'],
                'session': session_data['session_id']
            })

        # Aggregate daily data
        if session_data['first_timestamp']:
            date = session_data['first_timestamp'][:10]
            all_daily[date]['input'] += session_data['tokens']['input']
            all_daily[date]['output'] += session_data['tokens']['output']
            all_daily[date]['cost_sonnet'] += session_data['cost_sonnet']

        # Aggregate project data
        proj = session_data['project']
        project_data[proj]['sessions'] += 1
        project_data[proj]['tokens'] += session_data['tokens']['input'] + session_data['tokens']['output']
        project_data[proj]['cost_sonnet'] += session_data['cost_sonnet']

    # Process sequences
    seq_counts = defaultdict(int)
    for seq in all_sequences:
        seq_counts[seq] += 1

    # Calculate totals
    sonnet_cost = calc_cost(total_tokens, PRICING['sonnet'])
    opus_cost = calc_cost(total_tokens, PRICING['opus'])

    # Cache efficiency
    total_input = total_tokens['input'] + total_tokens['cache_read']
    cache_rate = round((total_tokens['cache_read'] / total_input * 100), 1) if total_input > 0 else 0

    # Format tool data
    tools_list = sorted(all_tool_counts.items(), key=lambda x: -x[1])[:20]

    # Format MCP data with function breakdown
    mcp_list = []
    for server, functions in sorted(all_mcp_data.items(), key=lambda x: -sum(x[1].values())):
        server_total = sum(functions.values())
        func_list = sorted(functions.items(), key=lambda x: -x[1])[:10]
        mcp_list.append({
            'server': server,
            'count': server_total,
            'functions': [{'name': f[0], 'count': f[1]} for f in func_list]
        })

    # Format subagent data with details
    subagent_list = []
    for agent_type, calls in sorted(all_subagent_data.items(), key=lambda x: -len(x[1])):
        # Get unique descriptions (sample up to 10)
        seen_descriptions = set()
        sample_calls = []
        for call in calls:
            desc = call['description'] or call['prompt'][:50]
            if desc and desc not in seen_descriptions and len(sample_calls) < 10:
                seen_descriptions.add(desc)
                sample_calls.append({
                    'description': call['description'],
                    'prompt': call['prompt']
                })
        subagent_list.append({
            'type': agent_type,
            'count': len(calls),
            'samples': sample_calls
        })

    # Format sequence data
    seq_list = sorted(seq_counts.items(), key=lambda x: -x[1])[:15]

    # Format daily data (last 14 days)
    sorted_dates = sorted(all_daily.keys())[-14:]
    daily_list = [{
        'date': d[-5:],
        'input': all_daily[d]['input'],
        'output': all_daily[d]['output'],
        'cost': round(all_daily[d]['cost_sonnet'], 2)
    } for d in sorted_dates]

    # Format project data
    proj_list = []
    for name, data in sorted(project_data.items(), key=lambda x: -x[1]['cost_sonnet']):
        proj_list.append({
            'name': name,
            'sessions': data['sessions'],
            'tokens': data['tokens'],
            'cost_sonnet': round(data['cost_sonnet'], 2)
        })

    # Get most expensive sessions
    expensive_sessions = sorted(all_sessions, key=lambda x: -x['cost_sonnet'])[:20]
    session_insights = []
    for s in expensive_sessions:
        # Get top tools for this session
        top_tools = sorted(s['tool_calls'].items(), key=lambda x: -x[1])[:5]

        # Generate cost-saving insight
        insight = generate_cost_insight(s)

        session_insights.append({
            'session_id': s['session_id'][:8] if s['session_id'] else 'unknown',
            'project': s['project'],
            'cost_sonnet': s['cost_sonnet'],
            'cost_opus': s['cost_opus'],
            'tokens_in': s['tokens']['input'],
            'tokens_out': s['tokens']['output'],
            'cache_read': s['tokens']['cache_read'],
            'turns': s['turns'],
            'date': s['first_timestamp'][:10] if s['first_timestamp'] else 'unknown',
            'top_tools': [{'name': t[0], 'count': t[1]} for t in top_tools],
            'subagents_used': len(s['subagent_calls']),
            'mcp_servers_used': list(s['mcp_calls'].keys()),
            'cost_insight': insight
        })

    return {
        'generated': datetime.now().strftime('%b %d, %Y'),
        'summary': {
            'sessions': len(unique_sessions),
            'files': len(jsonl_files),
            'projects': len(project_data),
            'total_tool_calls': sum(all_tool_counts.values()),
            'unique_tools': len(all_tool_counts),
            'total_mcp_calls': sum(sum(f.values()) for f in all_mcp_data.values()),
            'active_mcp_servers': len(all_mcp_data),
            'total_subagent_calls': sum(len(v) for v in all_subagent_data.values()),
            'cache_rate': cache_rate
        },
        'tokens': total_tokens,
        'costs': {'sonnet': round(sonnet_cost, 2), 'opus': round(opus_cost, 2)},
        'tools': [{'name': t[0], 'count': t[1]} for t in tools_list],
        'mcp': mcp_list,
        'subagents': subagent_list,
        'sequences': [{'sequence': s[0], 'count': s[1]} for s in seq_list],
        'daily': daily_list,
        'projects': proj_list[:15],
        'expensive_sessions': session_insights
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
    print(f"  Subagent calls: {data['summary']['total_subagent_calls']}")
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
