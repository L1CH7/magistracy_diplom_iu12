# Grafana Setup for Log Visualization

## Quick Start

```bash
# 1. Start all services (if not running)
docker-compose up -d

# 2. Open Grafana in browser
# URL: http://localhost:3000
# Login: admin / admin
```

## Initial Setup

### 1. Add Loki Data Source

1. Open Grafana: http://localhost:3000
2. Login with `admin` / `admin` (change password if prompted)
3. Go to **Connections** → **Data Sources** (or **Configuration** → **Data Sources** in older versions)
4. Click **Add new data source**
5. Search and select **Loki**
6. Configure:
   - **Name**: `Loki`
   - **URL**: `http://loki:3100` ⚠️ **IMPORTANT**: Use `loki` (service name), NOT `localhost`
   - Leave other settings as default
   - Click **Save & Test**

You should see: ✅ "Data source successfully connected."

**Troubleshooting**:
- If connection fails, check containers: `docker ps | grep loki`
- Verify Loki is ready: `curl http://localhost:3100/ready`
- Check Grafana logs: `docker logs diplom-grafana`

### 2. Explore Logs

Go to **Explore** (compass icon in left menu) and try these queries:

#### All logs from server
```logql
{job="server_logs"}
```

#### All logs from client
```logql
{job="client_logs"}
```

#### All logs (both server and client)
```logql
{job=~".*_logs"}
```

#### Only errors
```logql
{job=~"server_errors|client_errors"}
```

**Important**: Use `{job=~".*_logs"}` not `{job="app_logs"}` - we have separate jobs for server and client.

#### Teleportation events
```logql
{job="client_logs"} |= "TELEPORTATION"
```

#### Logs for specific agent
```logql
{job="client_logs", agent_id="1"}
```

#### Logs for specific function
```logql
{job="server_logs", function="sim_agent_position"}
```

### 3. Create Dashboard

1. Go to **Dashboards** → **New Dashboard**
2. Click **Add visualization**
3. Select **Loki** as data source
4. Add queries:

**Panel 1: Log Rate by Level**
```logql
sum by(level) (rate({job=~".*_logs"}[1m]))
```

**Panel 2: Error Count**
```logql
sum(count_over_time({job=~".*_errors"}[5m]))
```

**Panel 3: Recent Errors**
```logql
{job=~".*_errors"} | json
```

**Panel 4: Agent Activity**
```logql
{job="client_logs", function=~".*agent.*"} | json
```

## Useful LogQL Patterns

### Filter by level (recommended)
```logql
{job=~".*_logs", level="ERROR"}
```

**Note**: `level` is already extracted as a label by Promtail, so you can filter directly without `| json`.

### Filter by message content
```logql
{job="server_logs"} |= "route" != "cache"
```

### Extract and filter fields
```logql
{job="client_logs"} | json | distance_m > 50
```

### Count errors per function
```logql
sum by(function) (count_over_time({level="ERROR"}[5m]))
```

### Agent movement tracking (TRACE enabled)
```logql
{job="server_logs", level="TRACE", function="get_current_position"}
```

## Troubleshooting

### No logs visible
1. Check Promtail is running: `docker ps | grep promtail`
2. Check Promtail logs: `docker logs diplom-promtail`
3. Verify log files exist:
   ```bash
   ls -lh logs/server/
   ls -lh logs/client/
   ```

### Data source connection fails
1. Check Loki is running: `docker ps | grep loki`
2. Test Loki directly: `curl http://localhost:3100/ready`
3. Check Loki logs: `docker logs diplom-loki`

### Old logs not showing
- Loki only ingests new log entries
- To see old logs, restart Promtail: `docker-compose restart promtail`

## Log Structure

Each log entry contains:

- **timestamp**: ISO 8601 format
- **level**: TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR, CRITICAL
- **logger**: Module name (e.g., `src.server.app`)
- **message**: Short structured message
- **function**: Function name
- **line**: Line number
- **module**: Module name
- **Extra fields** (depends on context):
  - `agent_id`: Agent identifier
  - `thread_id`: Thread identifier
  - `distance_m`: Distance in meters
  - `duration_ms`: Operation duration
  - etc.

## Example Queries for Debugging

### Find all teleportations
```logql
{job="client_logs"} |= "TELEPORTATION_DETECTED" | json
```

### Track agent #1 movement
```logql
{job="client_logs", agent_id="1", function="_update_agent_position"}
```

### Slow operations (>1s)
```logql
{job=~".*_logs"} | json | duration_ms > 1000
```

### Route building timeline
```logql
{job="server_logs"} |= "route" | json | __error__=""
```

### API call latency
```logql
{job="client_logs"} | json | api_duration_ms > 0
```

## Alert Examples

Create alerts in Grafana for:

1. **High error rate**
   ```logql
   rate({level="ERROR"}[1m]) > 0.1
   ```

2. **Teleportation detected**
   ```logql
   count_over_time({job="client_logs"} |= "TELEPORTATION"[5m]) > 0
   ```

3. **Slow operations**
   ```logql
   count_over_time({job=~".*_logs"} | json | duration_ms > 5000[5m]) > 5
   ```

## Advanced: TRACE Logging

TRACE level provides detailed movement tracking (high volume):

```bash
# Enable TRACE for server
python scripts/enable_trace.py enable server

# Restart containers to apply
docker-compose restart server

# View TRACE logs in Grafana
{job="server_logs", level="TRACE"}

# Disable when done
python scripts/enable_trace.py disable server
docker-compose restart server
```

## Tips

1. **Use time range selector** to limit query scope
2. **Add filters incrementally** to narrow results
3. **Use `| json`** to parse structured logs
4. **Combine with grep**: `{job="..."} |= "pattern" != "exclude"`
5. **Save useful queries** as dashboard panels
6. **Export dashboards** as JSON for version control

## Integration with Development Workflow

1. **Start development**: `make up`
2. **Run simulation** in client GUI
3. **Monitor logs live** in Grafana Explore
4. **Find issues** using filters (errors, agent_id, function)
5. **Enable TRACE** if needed for detailed debugging
6. **Export critical logs** via Grafana export feature

## References

- [Loki LogQL documentation](https://grafana.com/docs/loki/latest/logql/)
- [Grafana dashboards](https://grafana.com/docs/grafana/latest/dashboards/)
- [Promtail configuration](https://grafana.com/docs/loki/latest/clients/promtail/)
