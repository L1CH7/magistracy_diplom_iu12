import socket
import random
import time
import subprocess
import os

def get_node_data():
    """Attempt to fetch both IDs and Coordinates from the database"""
    try:
        cmd = ["psql", "-t", "-A", "-c", "SELECT id, ST_X(geom), ST_Y(geom) FROM graphs.eb_nodes LIMIT 500", 
               "postgresql://postgres:postgres@localhost/nav_mas"]
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().splitlines()
        data = []
        for line in output:
            if '|' in line:
                parts = line.split('|')
                if len(parts) == 3:
                    data.append({
                        'id': int(parts[0]),
                        'x': float(parts[1]),
                        'y': float(parts[2])
                    })
        return data
    except Exception:
        # Fallback: dummy data
        return [{
            'id': 100 + i,
            'x': 37.6 + random.random()*0.1,
            'y': 55.7 + random.random()*0.1
        } for i in range(100)]

def run_test(host='localhost', port=5555, count=100):
    nodes = get_node_data()
    if not nodes:
        print("No nodes found!")
        return

    print(f"--- Smart Multi-point Load Test: {count} queries ---")
    print(f"{'#':<4} | {'Method':<6} | {'Pts':<3} | {'Path Time':>9} | {'Dist':>10} | {'Search Lat':>10} | {'Net Lat':>12}")
    print("-" * 125)
    
    # Storage for statistics: stats[method][num_pts] = {'search': [], 'net': []}
    methods = ['id', 'll', 'all']
    pts_range = [2, 3, 4, 5]
    
    stats = {m: {p: {'search': [], 'net': []} for p in pts_range} for m in methods}
    # Also add 'total' for each method
    for m in methods:
        stats[m]['total'] = {'search': [], 'net': []}
    
    for i in range(1, count + 1):
        num_pts = random.randint(2, 5)
        method = random.choice(['ll', 'id'])
        sampled = random.sample(nodes, num_pts)
        
        if method == 'll':
            coords_str = " ".join([f"{n['x']:.6f} {n['y']:.6f}" for n in sampled])
            query_str = f"ll {num_pts} {coords_str}"
        else:
            ids_str = " ".join([f"{n['id']} {random.random():.2f}" for n in sampled])
            query_str = f"id {num_pts} {ids_str}"
        
        start_t = time.perf_counter()
        response = "ERROR"
        success = False
        try:
            with socket.create_connection((host, port), timeout=5) as s:
                s.sendall((query_str + "\n").encode())
                response = s.recv(4096).decode().strip()
                success = "SUCCESS" in response
        except Exception as e:
            response = f"FAIL: {e}"
            
        dur_ms = (time.perf_counter() - start_t) * 1000
        
        path_time = "--"
        dist_str = "--"
        search_lat_ms = 0.0
        search_lat_display = "--"
        
        if success:
            try:
                # SUCCESS | Time: 90s | Distance: 1738.0m | Latency: 0.123ms | Segments: 13
                parts = response.split("|")
                path_time = parts[1].split(":")[1].strip()
                dist_str = parts[2].split(":")[1].strip()
                search_lat_raw = parts[3].split(":")[1].strip().replace("ms", "")
                search_lat_ms = float(search_lat_raw)
                search_lat_display = f"{search_lat_ms:.3f} ms"
                
                # Update stats
                for m_key in [method, 'all']:
                    stats[m_key][num_pts]['search'].append(search_lat_ms)
                    stats[m_key][num_pts]['net'].append(dur_ms)
                    stats[m_key]['total']['search'].append(search_lat_ms)
                    stats[m_key]['total']['net'].append(dur_ms)
            except Exception:
                pass
            
            print(f"{i:<4} | {method:<6} | {num_pts:<3} | {path_time:>9} | {dist_str:>10} | {search_lat_display:>10} | {dur_ms:9.2f} ms")
        else:
            print(f"{i:<4} | {method:<6} | {num_pts:<3} | {'--':>9} | {'--':>10} | {'--':>10} | {'--':>12}")

    # Final Statistics Printing
    def print_stat_table(title, method_stats):
        print(f"\n=== {title.upper()} STATISTICS ===")
        # 8 columns: S_AVG, S_P95, S_MIN, S_MAX, N_AVG, N_P95, N_MIN, N_MAX
        header = f"{'PTS':<4} | {'S-AVG':>9} | {'S-P95':>9} | {'S-MIN':>9} | {'S-MAX':>9} | {'N-AVG':>7} | {'N-P95':>7} | {'N-MIN':>7} | {'N-MAX':>7}"
        print(header)
        print("-" * len(header))

        def get_line(label, s_vals, n_vals):
            if not s_vals: return f"{label:<4} | {'--':>9} | {'--':>9} | {'--':>9} | {'--':>9} | {'--':>7} | {'--':>7} | {'--':>7} | {'--':>7}"
            
            def m(vals):
                sv = sorted(vals)
                return sum(vals)/len(vals), sv[int(0.95*len(sv))], min(vals), max(vals)
            
            sa, sp, smi, sma = m(s_vals)
            na, np95, nmi, nma = m(n_vals)
            return f"{label:<4} | {sa:9.4f} | {sp:9.4f} | {smi:9.4f} | {sma:9.4f} | {na:7.2f} | {np95:7.2f} | {nmi:7.2f} | {nma:7.2f}"

        for p in pts_range:
            print(get_line(str(p), method_stats[p]['search'], method_stats[p]['net']))
        
        print("-" * len(header))
        print(get_line("ALL", method_stats['total']['search'], method_stats['total']['net']))
        print("-" * len(header))

    print_stat_table("id (Direct ID Routing)", stats['id'])
    print_stat_table("ll (Coordinate Snap Routing)", stats['ll'])
    print_stat_table("OVERALL Performance", stats['all'])
    print("\n" + "="*95)

if __name__ == "__main__":
    run_test()
