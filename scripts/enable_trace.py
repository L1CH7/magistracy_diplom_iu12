#!/usr/bin/env python3
"""
Enable TRACE logging in running Docker containers.

Usage:
    python scripts/enable_trace.py client   # Enable TRACE in client
    python scripts/enable_trace.py server   # Enable TRACE in server
    python scripts/enable_trace.py both     # Enable in both

This creates a flag file that containers check on startup.
"""

import sys
import subprocess
from pathlib import Path


def enable_trace_for_container(container_name: str):
    """Enable TRACE logging for container."""
    # Create flag file in logs directory
    log_dir = Path('logs')
    log_dir.mkdir(parents=True, exist_ok=True)
    
    flag_file = log_dir / f'TRACE_ENABLED_{container_name}'
    flag_file.touch()
    
    print(f"✅ TRACE enabled for {container_name}")
    print(f"   Flag file: {flag_file}")
    print(f"   Restart container to apply: docker-compose restart {container_name}")
    
    return flag_file


def disable_trace_for_container(container_name: str):
    """Disable TRACE logging for container."""
    log_dir = Path('logs')
    flag_file = log_dir / f'TRACE_ENABLED_{container_name}'
    
    if flag_file.exists():
        flag_file.unlink()
        print(f"✅ TRACE disabled for {container_name}")
        print(f"   Restart container to apply: docker-compose restart {container_name}")
    else:
        print(f"ℹ️  TRACE was not enabled for {container_name}")


def check_trace_status():
    """Check TRACE status for all containers."""
    log_dir = Path('logs')
    
    if not log_dir.exists():
        print("ℹ️  No logs directory yet")
        return
    
    containers = ['client', 'server']
    
    print("📊 TRACE Status:")
    print("─" * 40)
    
    for container in containers:
        flag_file = log_dir / f'TRACE_ENABLED_{container}'
        status = "🟢 ENABLED" if flag_file.exists() else "⚫ DISABLED"
        print(f"{container:10s}: {status}")
    
    print("─" * 40)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nCurrent status:")
        check_trace_status()
        return 1
    
    command = sys.argv[1].lower()
    
    if command == 'status':
        check_trace_status()
        return 0
    
    elif command == 'enable':
        if len(sys.argv) < 3:
            print("Usage: enable_trace.py enable <client|server|both>")
            return 1
        
        target = sys.argv[2].lower()
        
        if target == 'both':
            enable_trace_for_container('client')
            enable_trace_for_container('server')
        elif target in ['client', 'server']:
            enable_trace_for_container(target)
        else:
            print(f"❌ Unknown target: {target}")
            return 1
        
        print("\n💡 Restart containers:")
        print(f"   docker-compose restart {target if target != 'both' else 'client server'}")
        
    elif command == 'disable':
        if len(sys.argv) < 3:
            print("Usage: enable_trace.py disable <client|server|both>")
            return 1
        
        target = sys.argv[2].lower()
        
        if target == 'both':
            disable_trace_for_container('client')
            disable_trace_for_container('server')
        elif target in ['client', 'server']:
            disable_trace_for_container(target)
        else:
            print(f"❌ Unknown target: {target}")
            return 1
    
    elif command in ['client', 'server', 'both']:
        # Shorthand: enable_trace.py client == enable_trace.py enable client
        target = command
        
        if target == 'both':
            enable_trace_for_container('client')
            enable_trace_for_container('server')
        else:
            enable_trace_for_container(target)
        
        print("\n💡 Restart containers:")
        print(f"   docker-compose restart {target if target != 'both' else 'client server'}")
    
    else:
        print(f"❌ Unknown command: {command}")
        print(__doc__)
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
