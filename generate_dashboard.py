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
from datetime import datetime, timedelta

# Pricing per million tokens
PRICING = {
    'sonnet': {'input': 3, 'output': 15},
    'opus': {'input': 15, 'output': 75},
    'haiku': {'input': 0.25, 'output': 1.25}
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
        'tool_errors': defaultdict(int),  # Track failed tool calls by tool name
        'tool_retries': defaultdict(int),  # Track consecutive same-tool calls
        'mcp_calls': defaultdict(lambda: defaultdict(int)),
        'subagent_calls': [],
        'first_timestamp': None,
        'last_timestamp': None,
        'hours_active': set(),
        'user_messages': 0,
    }

    # For tracking tool use IDs to match with errors
    pending_tool_uses = {}  # tool_use_id -> tool_name

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
            # Track hour of day
            try:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                session_data['hours_active'].add(dt.hour)
            except:
                pass

        msg = entry.get('message', {})
        role = msg.get('role')

        # Count turns (assistant messages with content)
        if role == 'assistant':
            session_data['turns'] += 1
        elif role == 'user':
            session_data['user_messages'] += 1

        # Extract token usage
        usage = msg.get('usage', {})
        if usage:
            session_data['tokens']['input'] += usage.get('input_tokens', 0)
            session_data['tokens']['output'] += usage.get('output_tokens', 0)
            session_data['tokens']['cache_read'] += usage.get('cache_read_input_tokens', 0)
            session_data['tokens']['cache_creation'] += usage.get('cache_creation_input_tokens', 0)

        # Extract tool calls and results
        content = msg.get('content', [])
        if isinstance(content, list):
            for item in content:
                # Track tool errors from results
                if isinstance(item, dict) and item.get('type') == 'tool_result':
                    tool_use_id = item.get('tool_use_id', '')
                    if item.get('is_error'):
                        session_data['tool_errors']['total'] += 1
                        # Track which tool failed
                        if tool_use_id in pending_tool_uses:
                            failed_tool = pending_tool_uses[tool_use_id]
                            session_data['tool_errors'][failed_tool] = session_data['tool_errors'].get(failed_tool, 0) + 1

                if isinstance(item, dict) and item.get('type') == 'tool_use':
                    tool_name = item.get('name', 'unknown')
                    tool_use_id = item.get('id', '')
                    session_data['tool_calls'][tool_name] += 1

                    # Track for error matching
                    if tool_use_id:
                        pending_tool_uses[tool_use_id] = tool_name

                    # Track retries (consecutive same-tool calls)
                    if last_tool == tool_name:
                        session_data['tool_retries'][tool_name] += 1

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

    # Convert defaultdicts to regular dicts and sets to lists
    session_data['tool_calls'] = dict(session_data['tool_calls'])
    session_data['tool_errors'] = dict(session_data['tool_errors'])
    session_data['tool_retries'] = dict(session_data['tool_retries'])
    session_data['mcp_calls'] = {k: dict(v) for k, v in session_data['mcp_calls'].items()}
    session_data['hours_active'] = list(session_data['hours_active'])

    # Calculate session duration in minutes
    if session_data['first_timestamp'] and session_data['last_timestamp']:
        try:
            start = datetime.fromisoformat(session_data['first_timestamp'].replace('Z', '+00:00'))
            end = datetime.fromisoformat(session_data['last_timestamp'].replace('Z', '+00:00'))
            session_data['duration_mins'] = max(1, int((end - start).total_seconds() / 60))
        except:
            session_data['duration_mins'] = 0
    else:
        session_data['duration_mins'] = 0

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
    all_mcp_data = defaultdict(lambda: defaultdict(int))
    all_subagent_data = defaultdict(list)
    all_daily = defaultdict(lambda: {'input': 0, 'output': 0, 'cost_sonnet': 0, 'sessions': 0})
    project_data = defaultdict(lambda: {'sessions': [], 'tokens': 0, 'cost_sonnet': 0})
    unique_sessions = set()

    # New aggregates for deeper analytics
    hourly_usage = defaultdict(lambda: {'tokens': 0, 'sessions': 0, 'cost': 0})
    weekday_usage = defaultdict(lambda: {'tokens': 0, 'sessions': 0, 'cost': 0})
    session_durations = []
    tool_chain_costs = defaultdict(lambda: {'count': 0, 'total_cost': 0})
    total_errors = 0
    sessions_with_errors = 0
    tool_error_counts = defaultdict(int)  # Which tools fail most
    tool_retry_counts = defaultdict(int)  # Which tools get retried most
    all_session_list = []  # For date filtering in UI

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
            all_daily[date]['sessions'] += 1

            # Hourly and weekday aggregation
            try:
                dt = datetime.fromisoformat(session_data['first_timestamp'].replace('Z', '+00:00'))
                hour = dt.hour
                weekday = dt.strftime('%A')
                session_tokens = session_data['tokens']['input'] + session_data['tokens']['output']

                hourly_usage[hour]['tokens'] += session_tokens
                hourly_usage[hour]['sessions'] += 1
                hourly_usage[hour]['cost'] += session_data['cost_sonnet']

                weekday_usage[weekday]['tokens'] += session_tokens
                weekday_usage[weekday]['sessions'] += 1
                weekday_usage[weekday]['cost'] += session_data['cost_sonnet']
            except:
                pass

        # Track session duration
        if session_data['duration_mins'] > 0:
            session_durations.append(session_data['duration_mins'])

        # Track errors
        errors_in_session = session_data['tool_errors'].get('total', 0)
        total_errors += errors_in_session
        if errors_in_session > 0:
            sessions_with_errors += 1

        # Aggregate tool-specific errors
        for tool, count in session_data['tool_errors'].items():
            if tool != 'total':
                tool_error_counts[tool] += count

        # Aggregate tool retries
        for tool, count in session_data['tool_retries'].items():
            tool_retry_counts[tool] += count

        # Build session list for date filtering
        all_session_list.append({
            'session_id': session_data['session_id'][:8] if session_data['session_id'] else 'unknown',
            'project': session_data['project'],
            'date': session_data['first_timestamp'][:10] if session_data['first_timestamp'] else 'unknown',
            'cost_sonnet': session_data['cost_sonnet'],
            'tokens': session_data['tokens']['input'] + session_data['tokens']['output'],
            'turns': session_data['turns'],
            'duration': session_data['duration_mins'],
            'errors': errors_in_session
        })

        # Aggregate project data (now with full session info)
        proj = session_data['project']
        project_data[proj]['sessions'].append({
            'session_id': session_data['session_id'][:8] if session_data['session_id'] else 'unknown',
            'date': session_data['first_timestamp'][:10] if session_data['first_timestamp'] else 'unknown',
            'cost_sonnet': session_data['cost_sonnet'],
            'tokens': session_data['tokens']['input'] + session_data['tokens']['output'],
            'turns': session_data['turns'],
            'duration': session_data['duration_mins'],
            'errors': errors_in_session
        })
        project_data[proj]['tokens'] += session_data['tokens']['input'] + session_data['tokens']['output']
        project_data[proj]['cost_sonnet'] += session_data['cost_sonnet']

    # Calculate totals
    sonnet_cost = calc_cost(total_tokens, PRICING['sonnet'])
    opus_cost = calc_cost(total_tokens, PRICING['opus'])

    # Process sequences with cost attribution
    seq_counts = defaultdict(int)
    for seq in all_sequences:
        seq_counts[seq] += 1

    # Calculate average cost per sequence (rough approximation)
    total_seq = len(all_sequences) if all_sequences else 1
    avg_cost_per_tool = sonnet_cost / total_seq if total_seq > 0 else 0

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

    # Format daily data (all days for trends)
    sorted_dates = sorted(all_daily.keys())
    daily_list = [{
        'date': d,
        'date_short': d[-5:],
        'input': all_daily[d]['input'],
        'output': all_daily[d]['output'],
        'cost': round(all_daily[d]['cost_sonnet'], 2),
        'sessions': all_daily[d]['sessions']
    } for d in sorted_dates]

    # Format hourly data
    hourly_list = []
    for hour in range(24):
        data = hourly_usage[hour]
        hourly_list.append({
            'hour': hour,
            'label': f"{hour:02d}:00",
            'tokens': data['tokens'],
            'sessions': data['sessions'],
            'cost': round(data['cost'], 2)
        })

    # Format weekday data
    day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    weekday_list = []
    for day in day_order:
        data = weekday_usage[day]
        weekday_list.append({
            'day': day,
            'day_short': day[:3],
            'tokens': data['tokens'],
            'sessions': data['sessions'],
            'cost': round(data['cost'], 2)
        })

    # Format session duration stats
    if session_durations:
        duration_stats = {
            'avg': round(sum(session_durations) / len(session_durations), 1),
            'max': max(session_durations),
            'min': min(session_durations),
            'median': sorted(session_durations)[len(session_durations) // 2],
            'distribution': {
                'under_5': len([d for d in session_durations if d < 5]),
                '5_to_15': len([d for d in session_durations if 5 <= d < 15]),
                '15_to_30': len([d for d in session_durations if 15 <= d < 30]),
                '30_to_60': len([d for d in session_durations if 30 <= d < 60]),
                'over_60': len([d for d in session_durations if d >= 60])
            }
        }
    else:
        duration_stats = {'avg': 0, 'max': 0, 'min': 0, 'median': 0, 'distribution': {}}

    # Format project data with full session lists
    proj_list = []
    for name, data in sorted(project_data.items(), key=lambda x: -x[1]['cost_sonnet']):
        sorted_sessions = sorted(data['sessions'], key=lambda x: -x['cost_sonnet'])
        proj_list.append({
            'name': name,
            'session_count': len(data['sessions']),
            'tokens': data['tokens'],
            'cost_sonnet': round(data['cost_sonnet'], 2),
            'sessions': sorted_sessions[:10],  # Top 10 sessions per project
            'total_errors': sum(s['errors'] for s in data['sessions'])
        })

    # Cost breakdown for pie chart
    input_cost = (total_tokens['input'] / 1_000_000) * PRICING['sonnet']['input']
    output_cost = (total_tokens['output'] / 1_000_000) * PRICING['sonnet']['output']
    cache_read_cost = (total_tokens['cache_read'] / 1_000_000) * PRICING['sonnet']['input'] * CACHE_READ_DISCOUNT
    cache_create_cost = (total_tokens['cache_creation'] / 1_000_000) * PRICING['sonnet']['input'] * CACHE_CREATE_PREMIUM
    cost_breakdown = {
        'input': round(input_cost, 2),
        'output': round(output_cost, 2),
        'cache_read': round(cache_read_cost, 2),
        'cache_creation': round(cache_create_cost, 2)
    }

    # Calculate Haiku what-if cost
    haiku_cost = calc_cost(total_tokens, PRICING['haiku'])

    # Calculate projected monthly cost (based on recent 7 days)
    recent_7_days = sorted_dates[-7:] if len(sorted_dates) >= 7 else sorted_dates
    if recent_7_days:
        recent_cost = sum(all_daily[d]['cost_sonnet'] for d in recent_7_days)
        daily_avg = recent_cost / len(recent_7_days)
        projected_monthly = round(daily_avg * 30, 2)
    else:
        projected_monthly = 0

    # Week-over-week comparison
    wow_comparison = {}
    if len(sorted_dates) >= 14:
        this_week = sorted_dates[-7:]
        last_week = sorted_dates[-14:-7]
        this_week_cost = sum(all_daily[d]['cost_sonnet'] for d in this_week)
        last_week_cost = sum(all_daily[d]['cost_sonnet'] for d in last_week)
        if last_week_cost > 0:
            wow_change = ((this_week_cost - last_week_cost) / last_week_cost) * 100
        else:
            wow_change = 0
        wow_comparison = {
            'this_week': round(this_week_cost, 2),
            'last_week': round(last_week_cost, 2),
            'change_pct': round(wow_change, 1),
            'change_direction': 'up' if wow_change > 0 else 'down' if wow_change < 0 else 'flat'
        }
    else:
        wow_comparison = {'this_week': 0, 'last_week': 0, 'change_pct': 0, 'change_direction': 'flat'}

    # Calculate average session cost for anomaly detection
    all_costs = [s['cost_sonnet'] for s in all_sessions if s['cost_sonnet'] > 0]
    avg_session_cost = sum(all_costs) / len(all_costs) if all_costs else 0
    anomaly_threshold = avg_session_cost * 2  # Sessions costing >2x average

    # Format tool error data
    tool_errors_list = sorted(tool_error_counts.items(), key=lambda x: -x[1])[:10]

    # Format tool retry data
    tool_retries_list = sorted(tool_retry_counts.items(), key=lambda x: -x[1])[:10]

    # Generate smart insights
    smart_insights = []

    # Weekday insight
    if weekday_list:
        max_day = max(weekday_list, key=lambda x: x['cost'])
        min_day = min(weekday_list, key=lambda x: x['cost'])
        if max_day['cost'] > 0 and min_day['cost'] > 0:
            ratio = max_day['cost'] / min_day['cost'] if min_day['cost'] > 0 else 1
            if ratio > 2:
                smart_insights.append({
                    'type': 'weekday',
                    'icon': '📅',
                    'title': f"{max_day['day']} costs {ratio:.1f}x more than {min_day['day']}",
                    'desc': 'Consider spreading work across days for more predictable costs.'
                })

    # Hourly insight
    if hourly_list:
        peak_hours = sorted(hourly_list, key=lambda x: -x['cost'])[:3]
        if peak_hours[0]['cost'] > 0:
            smart_insights.append({
                'type': 'hourly',
                'icon': '⏰',
                'title': f"Peak usage hours: {', '.join(h['label'] for h in peak_hours[:3])}",
                'desc': f"These hours account for significant cost."
            })

    # WoW insight
    if wow_comparison['change_pct'] > 20:
        smart_insights.append({
            'type': 'wow',
            'icon': '📈',
            'title': f"Spending up {wow_comparison['change_pct']}% vs last week",
            'desc': f"This week: ${wow_comparison['this_week']}, Last week: ${wow_comparison['last_week']}"
        })
    elif wow_comparison['change_pct'] < -20:
        smart_insights.append({
            'type': 'wow',
            'icon': '📉',
            'title': f"Spending down {abs(wow_comparison['change_pct'])}% vs last week",
            'desc': f"This week: ${wow_comparison['this_week']}, Last week: ${wow_comparison['last_week']}"
        })

    # Retry insight
    if tool_retries_list and tool_retries_list[0][1] > 10:
        smart_insights.append({
            'type': 'retry',
            'icon': '🔄',
            'title': f"{tool_retries_list[0][0]} retried {tool_retries_list[0][1]} times",
            'desc': 'Consecutive same-tool calls may indicate struggling. Review these sessions.'
        })

    # Error insight
    if tool_errors_list and tool_errors_list[0][1] > 5:
        smart_insights.append({
            'type': 'error',
            'icon': '⚠️',
            'title': f"{tool_errors_list[0][0]} failed {tool_errors_list[0][1]} times",
            'desc': 'This tool has the highest failure rate. Check permissions or usage patterns.'
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
            'cost_insight': insight,
            'is_anomaly': s['cost_sonnet'] > anomaly_threshold
        })

    return {
        'generated': datetime.now().strftime('%b %d, %Y'),
        'generated_ts': datetime.now().isoformat(),
        'summary': {
            'sessions': len(unique_sessions),
            'files': len(jsonl_files),
            'projects': len(project_data),
            'total_tool_calls': sum(all_tool_counts.values()),
            'unique_tools': len(all_tool_counts),
            'total_mcp_calls': sum(sum(f.values()) for f in all_mcp_data.values()),
            'active_mcp_servers': len(all_mcp_data),
            'total_subagent_calls': sum(len(v) for v in all_subagent_data.values()),
            'cache_rate': cache_rate,
            'total_errors': total_errors,
            'sessions_with_errors': sessions_with_errors,
            'error_rate': round(sessions_with_errors / len(unique_sessions) * 100, 1) if unique_sessions else 0,
            'total_retries': sum(tool_retry_counts.values()),
            'avg_session_cost': round(avg_session_cost, 2)
        },
        'tokens': total_tokens,
        'costs': {
            'sonnet': round(sonnet_cost, 2),
            'opus': round(opus_cost, 2),
            'haiku': round(haiku_cost, 2),
            'breakdown': cost_breakdown,
            'projected_monthly': projected_monthly
        },
        'wow': wow_comparison,
        'tools': [{'name': t[0], 'count': t[1]} for t in tools_list],
        'tool_errors': [{'name': t[0], 'count': t[1]} for t in tool_errors_list],
        'tool_retries': [{'name': t[0], 'count': t[1]} for t in tool_retries_list],
        'mcp': mcp_list,
        'subagents': subagent_list,
        'sequences': [{'sequence': s[0], 'count': s[1]} for s in seq_list],
        'daily': daily_list,
        'hourly': hourly_list,
        'weekday': weekday_list,
        'duration_stats': duration_stats,
        'projects': proj_list[:20],
        'expensive_sessions': session_insights,
        'all_sessions': sorted(all_session_list, key=lambda x: x['date'], reverse=True),
        'smart_insights': smart_insights
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
