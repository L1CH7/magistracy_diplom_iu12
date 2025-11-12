#!/bin/bash
# Teleportation Log Collection Script
# Usage: ./collect_teleport_logs.sh [output_file]

OUTPUT_FILE="${1:-teleport_report.txt}"

echo "Collecting teleportation logs..."
echo "Output: $OUTPUT_FILE"
echo ""

{
    echo "========================================"
    echo "TELEPORTATION DEBUGGING REPORT"
    echo "Generated: $(date)"
    echo "========================================"
    echo ""
    
    echo "=== 1. CLIENT TELEPORTATION DETECTIONS (last 30) ==="
    docker compose logs client 2>&1 | grep "TELEPORTATION_DETECTED" | tail -30
    echo ""
    
    echo "=== 2. AGENT-SIDE TELEPORTATIONS (last 20) ==="
    docker compose logs server 2>&1 | grep "AGENT_TELEPORT_IN_get_current_position" | tail -20
    echo ""
    
    echo "=== 3. SERVER-SIDE TELEPORTATIONS (last 20) ==="
    docker compose logs server 2>&1 | grep "SERVER_DETECTED_TELEPORT" | tail -20
    echo ""
    
    echo "=== 4. ROUTE SWITCH REQUESTS (last 15) ==="
    docker compose logs server 2>&1 | grep "route_switch_requested" | tail -15
    echo ""
    
    echo "=== 5. AGENT RESTARTS (last 10) ==="
    docker compose logs server 2>&1 | grep "agent_RESTARTED_on_new_route" | tail -10
    echo ""
    
    echo "=== 6. MERGE OPERATIONS (last 10) ==="
    docker compose logs server 2>&1 | grep "merge_updated_position" | tail -10
    echo ""
    
    echo "=== 7. FATAL MERGE FAILURES ==="
    docker compose logs server 2>&1 | grep "FATAL_merge_failed"
    echo ""
    
    echo "=== 8. ROUTE SWITCHES TO MERGED (last 10) ==="
    docker compose logs server 2>&1 | grep "route_switched_to_merged" | tail -10
    echo ""
    
    echo "========================================"
    echo "SUMMARY"
    echo "========================================"
    
    CLIENT_TELEPORTS=$(docker compose logs client 2>&1 | grep "TELEPORTATION_DETECTED" | wc -l)
    AGENT_TELEPORTS=$(docker compose logs server 2>&1 | grep "AGENT_TELEPORT_IN_get_current_position" | wc -l)
    SERVER_TELEPORTS=$(docker compose logs server 2>&1 | grep "SERVER_DETECTED_TELEPORT" | wc -l)
    RESTARTS=$(docker compose logs server 2>&1 | grep "agent_RESTARTED_on_new_route" | wc -l)
    MERGES=$(docker compose logs server 2>&1 | grep "merge_updated_position" | wc -l)
    FATALS=$(docker compose logs server 2>&1 | grep "FATAL_merge_failed" | wc -l)
    
    echo "Client-detected teleportations: $CLIENT_TELEPORTS"
    echo "Agent-detected teleportations: $AGENT_TELEPORTS"
    echo "Server-detected teleportations: $SERVER_TELEPORTS"
    echo "Agent restarts: $RESTARTS"
    echo "Successful merges: $MERGES"
    echo "Fatal merge failures: $FATALS"
    echo ""
    
    if [ "$MERGES" -eq 0 ] && [ "$RESTARTS" -gt 0 ]; then
        echo "⚠️  WARNING: Only restarts, no merges! Check merge logic."
    fi
    
    if [ "$FATALS" -gt 0 ]; then
        echo "🔴 FATAL: Merge failures detected! Check edge matching logic."
    fi
    
    if [ "$CLIENT_TELEPORTS" -gt 0 ]; then
        RATIO=$((CLIENT_TELEPORTS / (RESTARTS + 1)))
        if [ "$RATIO" -gt 2 ]; then
            echo "⚠️  WARNING: Many teleportations per restart! Check start_time adjustment."
        fi
    fi
    
    echo ""
    echo "Report saved to: $OUTPUT_FILE"
    
} > "$OUTPUT_FILE"

echo "Done! View report:"
echo "  cat $OUTPUT_FILE"
echo "  less $OUTPUT_FILE"
