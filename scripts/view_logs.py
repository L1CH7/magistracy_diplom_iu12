#!/usr/bin/env python3
"""
View application logs with filtering and formatting.

Usage:
    python scripts/view_logs.py                    # Show all recent logs
    python scripts/view_logs.py --errors           # Only errors
    python scripts/view_logs.py --teleportations   # Only teleportations
    python scripts/view_logs.py --agent 1          # Agent-specific logs
    python scripts/view_logs.py --trace            # Include TRACE level
    python scripts/view_logs.py --tail 100         # Last 100 lines
    python scripts/view_logs.py --follow           # Live tail -f mode
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime
import time


def parse_log_line(line: str) -> dict:
    """Parse JSON log line (loguru serialize=True format)."""
    try:
        data = json.loads(line)
        # Loguru serialize=True outputs: {"text": "...", "record": {...}}
        if isinstance(data, dict) and "record" in data:
            record = data["record"]
            # Flatten structure for compatibility
            return {
                "timestamp": record.get("time", {}).get("repr", ""),
                "level": record.get("level", {}).get("name", "INFO"),
                "message": record.get("message", ""),
                "function": record.get("function", ""),
                "line": record.get("line", ""),
                "module": record.get("module", ""),
                "logger": record.get("name", ""),
                **record.get("extra", {})
            }
        return data
    except json.JSONDecodeError:
        return None


def format_log_entry(entry: dict, show_full: bool = False) -> str:
    """Format log entry for human reading."""
    timestamp = entry.get('timestamp', '')
    if timestamp:
        # Parse ISO timestamp and format
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            time_str = dt.strftime('%H:%M:%S.%f')[:-3]
        except Exception:
            time_str = timestamp[:12]
    else:
        time_str = "??:??:??"
    
    level = entry.get('level', 'INFO')
    message = entry.get('message', '')
    function = entry.get('function', '')
    line_no = entry.get('line', '')
    
    # Color codes
    colors = {
        'TRACE': '\033[90m',    # Gray
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'SUCCESS': '\033[92m',  # Bright green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    reset = '\033[0m'
    
    color = colors.get(level, '')
    
    # Build header
    header = f"{time_str} | {color}{level:<8}{reset} | {function}:{line_no}"
    
    # Build message line
    msg_line = f"  {message}"
    
    # Add extra fields if show_full
    if show_full:
        extra_fields = []
        for key, value in entry.items():
            if key not in ['timestamp', 'level', 'message', 'function',
                          'line', 'module', 'process_id', 'thread_id',
                          'logger', 'exception']:
                extra_fields.append(f"    {key}={value}")
        
        if extra_fields:
            msg_line += "\n" + "\n".join(extra_fields)
    
    return f"{header}\n{msg_line}"


def filter_log_entry(entry: dict, args) -> bool:
    """Check if log entry matches filters."""
    # Level filter
    level = entry.get('level', 'INFO')
    if args.errors and level not in ['ERROR', 'CRITICAL']:
        return False
    
    if not args.trace and level == 'TRACE':
        return False
    
    # Teleportation filter
    if args.teleportations:
        message = entry.get('message', '')
        if 'TELEPORTATION' not in message and 'teleport' not in message.lower():
            return False
    
    # Agent filter
    if args.agent is not None:
        agent_id = entry.get('agent_id')
        if agent_id != args.agent:
            return False
    
    # Function filter
    if args.function:
        func = entry.get('function', '')
        if args.function not in func:
            return False
    
    return True


def view_logs(args):
    """View logs with filters."""
    log_dir = Path('logs')
    
    if not log_dir.exists():
        print(f"❌ Log directory not found: {log_dir}")
        print("Run the application first to generate logs.")
        return 1
    
    # Determine container (server by default, client if specified)
    container = 'client' if args.agent else 'server'
    container_dir = log_dir / container
    
    if not container_dir.exists():
        print(f"❌ Container log directory not found: {container_dir}")
        return 1
    
    # Determine which log file to read
    if args.errors:
        log_file = container_dir / 'errors.jsonl'
    elif args.slow:
        log_file = container_dir / 'slow_operations.jsonl'
    else:
        log_file = container_dir / 'app.jsonl'
    
    if not log_file.exists():
        print(f"❌ Log file not found: {log_file}")
        return 1
    
    print(f"📄 Reading: {log_file}")
    print(f"🔍 Filters: container={container}, errors={args.errors}, teleportations={args.teleportations}, "
          f"agent={args.agent}, trace={args.trace}")
    print("─" * 80)
    
    if args.follow:
        # Live tail mode
        return tail_follow(log_file, args)
    else:
        # Read from file
        return read_logs(log_file, args)


def read_logs(log_file: Path, args):
    """Read logs from file."""
    lines = []
    
    with open(log_file, 'r') as f:
        for line in f:
            entry = parse_log_line(line.strip())
            if entry and filter_log_entry(entry, args):
                lines.append(entry)
    
    # Apply tail limit
    if args.tail and args.tail > 0:
        lines = lines[-args.tail:]
    
    # Display
    for entry in lines:
        print(format_log_entry(entry, show_full=args.full))
        print()  # Blank line between entries
    
    print(f"─" * 80)
    print(f"📊 Showed {len(lines)} log entries")
    
    return 0


def tail_follow(log_file: Path, args):
    """Live tail -f mode."""
    print("🔴 Live mode (Ctrl+C to stop)\n")
    
    # Seek to end of file
    with open(log_file, 'r') as f:
        f.seek(0, 2)  # Seek to end
        
        try:
            while True:
                line = f.readline()
                if line:
                    entry = parse_log_line(line.strip())
                    if entry and filter_log_entry(entry, args):
                        print(format_log_entry(entry, show_full=args.full))
                        print()
                else:
                    time.sleep(0.1)  # Wait for new data
        except KeyboardInterrupt:
            print("\n\n🛑 Stopped")
            return 0


def main():
    parser = argparse.ArgumentParser(
        description='View application logs with filtering',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          Show recent logs
  %(prog)s --errors                 Show only errors
  %(prog)s --teleportations         Show teleportation events
  %(prog)s --agent 1                Show agent 1 logs
  %(prog)s --trace                  Include TRACE level
  %(prog)s --tail 50                Last 50 entries
  %(prog)s --follow                 Live tail mode
  %(prog)s --errors --follow        Live errors
  %(prog)s --function get_current_position  Filter by function
        """
    )
    
    parser.add_argument('--errors', action='store_true',
                       help='Show only ERROR and CRITICAL logs')
    parser.add_argument('--teleportations', action='store_true',
                       help='Show only teleportation-related logs')
    parser.add_argument('--agent', type=int, metavar='ID',
                       help='Filter by agent ID')
    parser.add_argument('--trace', action='store_true',
                       help='Include TRACE level logs')
    parser.add_argument('--slow', action='store_true',
                       help='Show slow operations only')
    parser.add_argument('--function', type=str, metavar='NAME',
                       help='Filter by function name')
    parser.add_argument('--tail', type=int, metavar='N',
                       help='Show last N entries')
    parser.add_argument('--follow', '-f', action='store_true',
                       help='Live tail mode (like tail -f)')
    parser.add_argument('--full', action='store_true',
                       help='Show all fields (verbose)')
    
    args = parser.parse_args()
    
    try:
        return view_logs(args)
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
