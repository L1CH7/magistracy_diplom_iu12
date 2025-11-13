#!/usr/bin/env python3
"""CLI wrapper for common LogQL queries to Loki."""

import argparse
import json
from datetime import datetime, timedelta
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from typing import Optional


LOKI_URL = "http://localhost:3100"


def query_loki(
    query: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 100
) -> dict:
    """Query Loki API."""
    params = {
        'query': query,
        'limit': limit,
    }
    
    if start:
        params['start'] = start
    if end:
        params['end'] = end
    
    url = f"{LOKI_URL}/loki/api/v1/query_range?{urlencode(params)}"
    
    try:
        req = Request(url)
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Loki query failed: {e}")
        return {}


def format_log_entry(entry: dict) -> str:
    """Format single log entry for display."""
    values = entry.get('values', [[]])
    if not values:
        return ""
    
    timestamp_ns, message = values[0][0], values[0][1]
    timestamp = datetime.fromtimestamp(int(timestamp_ns) / 1e9)
    
    try:
        log = json.loads(message)
        level = log.get('record', {}).get('level', {}).get('name', '?')
        msg = log.get('record', {}).get('message', message)
        func = log.get('record', {}).get('function', '?')
        return f"[{timestamp:%H:%M:%S}] {level:7} {func:20} {msg}"
    except json.JSONDecodeError:
        return f"[{timestamp:%H:%M:%S}] {message}"


def main():
    """Parse args and execute query."""
    parser = argparse.ArgumentParser(
        description='Query Loki logs with LogQL',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show last 20 errors
  query_logs.py --errors --limit 20
  
  # Show logs from last hour
  query_logs.py --last 1h
  
  # Show logs from specific agent
  query_logs.py --agent 1 --limit 50
  
  # Show logs from function
  query_logs.py --function calculate_route
  
  # Custom LogQL query
  query_logs.py --query '{job="server_logs"} |= "HTTP"'
        """
    )
    
    parser.add_argument('--errors', action='store_true',
                        help='Show only ERROR level logs')
    parser.add_argument('--agent', type=int, metavar='N',
                        help='Filter by agent number')
    parser.add_argument('--function', type=str, metavar='NAME',
                        help='Filter by function name')
    parser.add_argument('--last', type=str, metavar='DURATION',
                        help='Time range (e.g., 5m, 1h, 2d)')
    parser.add_argument('--limit', type=int, default=100,
                        help='Max results (default: 100)')
    parser.add_argument('--query', type=str,
                        help='Custom LogQL query')
    
    args = parser.parse_args()
    
    # Build LogQL query
    if args.query:
        logql = args.query
    else:
        # Start with base selector
        if args.agent is not None:
            logql = '{job="client_logs"}'
        else:
            logql = '{job="server_logs"}'
        
        # Add level filter
        if args.errors:
            logql += ' | json | level="ERROR"'
        
        # Add function filter
        if args.function:
            logql += f' | json | function="{args.function}"'
    
    # Calculate time range
    start_time = None
    if args.last:
        duration_map = {'m': 60, 'h': 3600, 'd': 86400}
        unit = args.last[-1]
        value = int(args.last[:-1])
        
        if unit in duration_map:
            delta = timedelta(seconds=value * duration_map[unit])
            # Loki expects nanosecond Unix timestamp
            start_dt = datetime.now() - delta
            start_time = str(int(start_dt.timestamp() * 1e9))
    
    print(f"📊 LogQL: {logql}")
    print(f"🔍 Limit: {args.limit}")
    if start_time:
        print(f"⏰ Since: {start_time}")
    print()
    
    # Execute query
    result = query_loki(logql, start=start_time, limit=args.limit)
    
    if not result or result.get('status') != 'success':
        print("❌ Query failed")
        return 1
    
    # Display results
    data = result.get('data', {}).get('result', [])
    
    if not data:
        print("📭 No logs found")
        return 0
    
    print(f"📄 Found {len(data)} streams:")
    print()
    
    total_entries = 0
    for stream in data:
        labels = stream.get('stream', {})
        values = stream.get('values', [])
        
        print(f"  Stream: {labels}")
        for timestamp_ns, message in values:
            timestamp = datetime.fromtimestamp(int(timestamp_ns) / 1e9)
            try:
                log = json.loads(message)
                level = log.get('record', {}).get('level',
                                                  {}).get('name', '?')
                msg = log.get('record', {}).get('message', message)
                func = log.get('record', {}).get('function', '?')
                print(f"    [{timestamp:%H:%M:%S}] {level:7} "
                      f"{func:20} {msg}")
            except json.JSONDecodeError:
                print(f"    [{timestamp:%H:%M:%S}] {message}")
            
            total_entries += 1
    
    print()
    print(f"✅ Показано {total_entries} записей")
    return 0


if __name__ == "__main__":
    exit(main())
