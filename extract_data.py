#!/usr/bin/env python3
"""
Claude Code Analytics Data Extractor
Parses ~/.claude JSONL logs and outputs aggregated analytics data.
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import re

def parse_jsonl_file(filepath):
    """Parse a single JSONL file, yielding valid entries."""
    entries = []
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"Error reading {filepath}: {e}", file=sys.stderr)
    return entries

def extract_tool_uses(content):
    """Extract tool use info from message content."""
    tools = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get('type') == 'tool_use':
                tool_info = {
                    'name': item.get('name', 'unknown'),
                    'id': item.get('id', ''),
                    'input': item.get('input', {})
                }
                tools.append(tool_info)
    return tools

def extract_tool_results(content):
    """Extract tool results from message content."""
    results = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get('type') == 'tool_result':
                result_info = {
                    'tool_use_id': item.get('tool_use_id', ''),
                    'is_error': item.get('is_error', False),
                    'content': str(item.get('content', ''))[:200]  # Truncate
                }
                results.append(result_info)
    return results

def is_mcp_tool(tool_name):
    """Check if tool is an MCP tool."""
    return tool_name.startswith('mcp__') or '__' in tool_name

def extract_mcp_server(tool_name):
    """Extract MCP server name from tool name."""
    if tool_name.startswith('mcp__'):
        parts = tool_name.split('__')
        if len(parts) >= 2:
            return parts[1]
    return None

def main():
    claude_dir = Path.home() / '.claude'
    projects_dir = claude_dir / 'projects'

    if not projects_dir.exists():
        print(json.dumps({"error": "~/.claude/projects not found"}))
        sys.exit(1)

    # Find all JSONL files
    jsonl_files = list(projects_dir.rglob('*.jsonl'))
    print(f"Found {len(jsonl_files)} JSONL files", file=sys.stderr)

    # Analytics containers
    sessions = {}
    tool_usage = defaultdict(lambda: {'count': 0, 'errors': 0})
    mcp_usage = defaultdict(lambda: {'count': 0, 'errors': 0, 'tools': defaultdict(int)})
    subagent_usage = defaultdict(lambda: {'count': 0, 'total_duration_ms': 0})
    daily_tokens = defaultdict(lambda: {'input': 0, 'output': 0, 'cache_read': 0, 'cache_creation': 0})
    projects = defaultdict(lambda: {'sessions': 0, 'tokens': 0})
    hourly_usage = defaultdict(int)
    tool_sequences = defaultdict(int)

    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_read = 0
    total_cache_creation = 0

    for jsonl_file in jsonl_files:
        entries = parse_jsonl_file(jsonl_file)

        # Determine project from path
        rel_path = str(jsonl_file.relative_to(projects_dir))
        project_name = rel_path.split('/')[0] if '/' in rel_path else 'default'

        # Check if this is a subagent file
        is_subagent = 'subagents' in str(jsonl_file)

        last_tools = []  # For tool sequences

        for entry in entries:
            # Skip non-message entries
            if entry.get('type') not in ['user', 'assistant']:
                continue

            session_id = entry.get('sessionId', 'unknown')
            timestamp_str = entry.get('timestamp', '')
            cwd = entry.get('cwd', '')
            git_branch = entry.get('gitBranch', '')

            # Parse timestamp
            try:
                if timestamp_str:
                    ts = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    date_key = ts.strftime('%Y-%m-%d')
                    hour = ts.hour
                else:
                    ts = None
                    date_key = 'unknown'
                    hour = 0
            except:
                ts = None
                date_key = 'unknown'
                hour = 0

            # Track session
            if session_id not in sessions:
                sessions[session_id] = {
                    'id': session_id,
                    'project': project_name,
                    'cwd': cwd,
                    'git_branch': git_branch,
                    'first_timestamp': timestamp_str,
                    'last_timestamp': timestamp_str,
                    'message_count': 0,
                    'input_tokens': 0,
                    'output_tokens': 0,
                    'cache_read': 0,
                    'cache_creation': 0,
                    'tool_calls': 0
                }
            else:
                sessions[session_id]['last_timestamp'] = timestamp_str

            sessions[session_id]['message_count'] += 1

            # Track project
            projects[project_name]['sessions'] = len(set(
                s['id'] for s in sessions.values() if s['project'] == project_name
            ))

            # Process message
            message = entry.get('message', {})
            role = message.get('role', '')
            content = message.get('content', [])
            usage = message.get('usage', {})

            # Token tracking
            input_tok = usage.get('input_tokens', 0)
            output_tok = usage.get('output_tokens', 0)
            cache_read = usage.get('cache_read_input_tokens', 0)
            cache_create = usage.get('cache_creation_input_tokens', 0)

            # Also check nested cache_creation structure
            cache_creation_nested = usage.get('cache_creation', {})
            if isinstance(cache_creation_nested, dict):
                cache_create += cache_creation_nested.get('ephemeral_5m_input_tokens', 0)
                cache_create += cache_creation_nested.get('ephemeral_1h_input_tokens', 0)

            total_input_tokens += input_tok
            total_output_tokens += output_tok
            total_cache_read += cache_read
            total_cache_creation += cache_create

            daily_tokens[date_key]['input'] += input_tok
            daily_tokens[date_key]['output'] += output_tok
            daily_tokens[date_key]['cache_read'] += cache_read
            daily_tokens[date_key]['cache_creation'] += cache_create

            sessions[session_id]['input_tokens'] += input_tok
            sessions[session_id]['output_tokens'] += output_tok
            sessions[session_id]['cache_read'] += cache_read
            sessions[session_id]['cache_creation'] += cache_create

            projects[project_name]['tokens'] += input_tok + output_tok

            hourly_usage[hour] += 1

            # Tool usage tracking
            if role == 'assistant':
                tools_used = extract_tool_uses(content)
                current_tools = []

                for tool in tools_used:
                    tool_name = tool['name']
                    tool_usage[tool_name]['count'] += 1
                    sessions[session_id]['tool_calls'] += 1
                    current_tools.append(tool_name)

                    # MCP tracking
                    if is_mcp_tool(tool_name):
                        server = extract_mcp_server(tool_name)
                        if server:
                            mcp_usage[server]['count'] += 1
                            mcp_usage[server]['tools'][tool_name] += 1

                    # Subagent tracking (Task tool with subagent_type)
                    if tool_name == 'Task':
                        subagent_type = tool.get('input', {}).get('subagent_type', 'unknown')
                        subagent_usage[subagent_type]['count'] += 1

                # Track tool sequences (pairs)
                if last_tools and current_tools:
                    for prev in last_tools[-3:]:  # Last 3 tools
                        for curr in current_tools[:3]:  # First 3 current
                            seq = f"{prev} -> {curr}"
                            tool_sequences[seq] += 1

                last_tools = current_tools if current_tools else last_tools

            # Tool results (errors)
            if role == 'user':
                results = extract_tool_results(content)
                for result in results:
                    if result.get('is_error'):
                        # Find matching tool by ID - simplified: just increment general errors
                        for tool_name in tool_usage:
                            pass  # Would need to track tool_use_id mapping

    # Calculate derived metrics
    session_list = list(sessions.values())

    # Sort and limit data
    tool_ranking = sorted(
        [{'name': k, 'count': v['count'], 'errors': v['errors']}
         for k, v in tool_usage.items()],
        key=lambda x: x['count'],
        reverse=True
    )[:50]

    mcp_ranking = sorted(
        [{'server': k, 'count': v['count'], 'tools': dict(v['tools'])}
         for k, v in mcp_usage.items()],
        key=lambda x: x['count'],
        reverse=True
    )

    subagent_ranking = sorted(
        [{'type': k, 'count': v['count']}
         for k, v in subagent_usage.items()],
        key=lambda x: x['count'],
        reverse=True
    )[:30]

    daily_data = sorted(
        [{'date': k, **v} for k, v in daily_tokens.items() if k != 'unknown'],
        key=lambda x: x['date']
    )[-90:]  # Last 90 days

    project_ranking = sorted(
        [{'name': k, **v} for k, v in projects.items()],
        key=lambda x: x['tokens'],
        reverse=True
    )[:30]

    top_sequences = sorted(
        [{'sequence': k, 'count': v} for k, v in tool_sequences.items()],
        key=lambda x: x['count'],
        reverse=True
    )[:30]

    # Top sessions by tokens
    top_sessions = sorted(
        session_list,
        key=lambda x: x['input_tokens'] + x['output_tokens'],
        reverse=True
    )[:50]

    # Hourly distribution
    hourly_dist = [{'hour': h, 'count': hourly_usage.get(h, 0)} for h in range(24)]

    # Pricing (per million tokens)
    SONNET_INPUT = 3.0
    SONNET_OUTPUT = 15.0
    OPUS_INPUT = 15.0
    OPUS_OUTPUT = 75.0
    CACHE_READ_DISCOUNT = 0.1  # 90% discount
    CACHE_CREATE_MULTIPLIER = 1.25  # 25% more

    # Calculate costs
    def calc_cost(input_tok, output_tok, cache_read, cache_create, input_price, output_price):
        # Regular input (excluding cached)
        regular_input = max(0, input_tok - cache_read)
        cost = (regular_input / 1_000_000) * input_price
        cost += (output_tok / 1_000_000) * output_price
        cost += (cache_read / 1_000_000) * input_price * CACHE_READ_DISCOUNT
        cost += (cache_create / 1_000_000) * input_price * CACHE_CREATE_MULTIPLIER
        return round(cost, 2)

    sonnet_cost = calc_cost(total_input_tokens, total_output_tokens, total_cache_read, total_cache_creation, SONNET_INPUT, SONNET_OUTPUT)
    opus_cost = calc_cost(total_input_tokens, total_output_tokens, total_cache_read, total_cache_creation, OPUS_INPUT, OPUS_OUTPUT)

    # Cache efficiency
    total_input_with_cache = total_input_tokens + total_cache_read + total_cache_creation
    cache_hit_rate = (total_cache_read / total_input_with_cache * 100) if total_input_with_cache > 0 else 0

    # Output final data
    output = {
        'generated_at': datetime.now().isoformat(),
        'summary': {
            'total_sessions': len(sessions),
            'total_jsonl_files': len(jsonl_files),
            'total_input_tokens': total_input_tokens,
            'total_output_tokens': total_output_tokens,
            'total_cache_read': total_cache_read,
            'total_cache_creation': total_cache_creation,
            'cache_hit_rate': round(cache_hit_rate, 1),
            'estimated_cost_sonnet': sonnet_cost,
            'estimated_cost_opus': opus_cost,
            'total_tool_calls': sum(t['count'] for t in tool_ranking),
            'total_mcp_calls': sum(m['count'] for m in mcp_ranking),
            'unique_tools': len(tool_usage),
            'unique_mcp_servers': len(mcp_usage),
            'unique_subagents': len(subagent_usage),
            'unique_projects': len(projects)
        },
        'tools': tool_ranking,
        'mcp_servers': mcp_ranking,
        'subagents': subagent_ranking,
        'daily_usage': daily_data,
        'hourly_distribution': hourly_dist,
        'projects': project_ranking,
        'top_sessions': top_sessions,
        'tool_sequences': top_sequences
    }

    print(json.dumps(output, indent=2))

if __name__ == '__main__':
    main()
