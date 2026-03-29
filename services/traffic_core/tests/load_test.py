import socket
import random
import time
import subprocess
import os

def get_node_data():
    """Attempt to fetch both IDs and Coordinates from the database"""
    try:
        # Используем ST_StartPoint, чтобы получить начальную точку линии (LineString) перед извлечением X и Y.
        # Добавляем TABLESAMPLE SYSTEM(5) для частого получения случайной, но равномерной выборки узлов по всему графу.
        cmd = ["psql", "-t", "-A", "-c", 
               "SELECT id, ST_X(ST_StartPoint(geom)), ST_Y(ST_StartPoint(geom)) FROM graphs.eb_nodes TABLESAMPLE SYSTEM(5) LIMIT 2000", 
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
    except Exception as e:
        print(f"[ERROR] Database query failed: {e}")
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

    # 1. Pre-processing: Get real internal EdgeIDs for nodes
    print(f"Preprocessing {len(nodes)} nodes to get internal dense IDs...")
    processed_nodes = []
    
    # Use a single connection or persistent for speed, but here we just do simple ones
    for idx, n in enumerate(nodes):
        if idx % 100 == 0:
            print(f"  Mapped {idx}/{len(nodes)} nodes...")
        
        query_str = f"ll 2 {n['x']:.6f} {n['y']:.6f} {n['x']:.6f} {n['y']:.6f}"
        try:
            with socket.create_connection((host, port), timeout=2) as s:
                s.sendall((query_str + "\n").encode())
                resp = s.recv(4096).decode().strip()
                if "SUCCESS" in resp:
                    # SUCCESS | Time: 0s | Distance: 0.0m | Latency: 0.123ms | Iterations: 1 | FirstID: 12345 | Segments: 1
                    parts = resp.split("|")
                    for p in parts:
                        if "FirstID" in p:
                            fid = int(p.split(":")[1].strip())
                            n['dense_id'] = fid
                            processed_nodes.append(n)
                            break
        except Exception:
            pass
            
    if not processed_nodes:
        print("[FATAL] Could not map any nodes to internal IDs. Check if server is running.")
        return
    
    nodes = processed_nodes
    print(f"Preprocessing complete. {len(nodes)} nodes ready for fair comparison.")

    # 2. Prepare shuffled test queue
    test_queue = []
    # We want 'count' total tests, roughly half 'id' and half 'll' for the same points
    # to make the comparison absolutely fair.
    actual_count = count // 2
    for _ in range(actual_count):
        num_pts = random.randint(2, 5)
        sampled = random.sample(nodes, num_pts)
        # Add both variants to the queue
        test_queue.append(('ll', num_pts, sampled))
        test_queue.append(('id', num_pts, sampled))
    
    random.shuffle(test_queue)

    print(f"\n--- Fair Shuffled Load Test: {len(test_queue)} queries ---")
    print(f"{'#':<4} | {'Method':<6} | {'Pts':<3} | {'Path Time':>9} | {'Dist':>10} | {'Search Lat':>10} | {'Net Lat':>12}")
    print("-" * 125)
    
    # Storage for statistics
    methods = ['id', 'll', 'all']
    pts_range = [2, 3, 4, 5]
    stats = {m: {p: {'search': [], 'net': [], 'iterations': [], 'time': [], 'dist': []} for p in pts_range} for m in methods}
    for m in methods:
        stats[m]['total'] = {'search': [], 'net': [], 'iterations': [], 'time': [], 'dist': []}
    
    for i, (method, num_pts, sampled) in enumerate(test_queue, 1):
        if method == 'll':
            coords_str = " ".join([f"{n['x']:.6f} {n['y']:.6f}" for n in sampled])
            query_str = f"ll {num_pts} {coords_str}"
        else:
            # Fair ID routing: use the actual internal IDs found during preprocessing
            ids_str = " ".join([f"{n['dense_id']} 0.0" for n in sampled])
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
                # SUCCESS | Time: 90s | Distance: 1738.0m | Latency: 0.123ms | Iterations: 13 | FirstID: 456 | Segments: 13
                parts = response.split("|")
                path_time = parts[1].split(":")[1].strip()
                dist_str = parts[2].split(":")[1].strip()
                search_lat_raw = parts[3].split(":")[1].strip().replace("ms", "")
                search_lat_ms = float(search_lat_raw)
                search_lat_display = f"{search_lat_ms:.3f} ms"
                iterations = int(parts[4].split(":")[1].strip())
                
                path_time_val = float(path_time.replace("s", ""))
                dist_val = float(dist_str.replace("m", ""))
                
                # Update stats
                for m_key in [method, 'all']:
                    stats[m_key][num_pts]['search'].append(search_lat_ms)
                    stats[m_key][num_pts]['net'].append(dur_ms)
                    stats[m_key][num_pts]['iterations'].append(iterations)
                    stats[m_key][num_pts]['time'].append(path_time_val)
                    stats[m_key][num_pts]['dist'].append(dist_val)
                    
                    stats[m_key]['total']['search'].append(search_lat_ms)
                    stats[m_key]['total']['net'].append(dur_ms)
                    stats[m_key]['total']['iterations'].append(iterations)
                    stats[m_key]['total']['time'].append(path_time_val)
                    stats[m_key]['total']['dist'].append(dist_val)
            except Exception:
                pass
            
            print(f"{i:<4} | {method:<6} | {num_pts:<3} | {path_time:>9} | {dist_str:>10} | {search_lat_display:>10} | {dur_ms:9.2f} ms")
        else:
            print(f"{i:<4} | {method:<6} | {num_pts:<3} | {'--':>9} | {'--':>10} | {'--':>10} | {'--':>12}")

    # Final Statistics Printing
    def print_stat_table(title, method_stats):
        print(f"\n=== {title.upper()} STATISTICS ===")
        # 13 columns: S_AVG, S_P95, S_MAX, N_AVG, N_P95, I-AVG, T-AVG, T-MAX, D-AVG, D-MAX
        header = f"{'PTS':<4} | {'S-AVG':>7} | {'S-P95':>7} | {'S-MAX':>7} | {'N-AVG':>7} | {'N-P95':>7} | {'I-AVG':>8} | {'T-AVG':>7} | {'T-MAX':>7} | {'D-AVG':>9} | {'D-MAX':>9}"
        print(header)
        print("-" * len(header))

        def get_line(label, s_vals, n_vals, i_vals, t_vals, d_vals):
            if not s_vals: return f"{label:<4} | {'--':>7} | {'--':>7} | {'--':>7} | {'--':>7} | {'--':>7} | {'--':>8} | {'--':>7} | {'--':>7} | {'--':>9} | {'--':>9}"
            
            def m(vals):
                sv = sorted(vals)
                return sum(vals)/len(vals), sv[int(0.95*len(sv))], min(vals), max(vals)
            
            sa, sp, smi, sma = m(s_vals)
            na, np95, nmi, nma = m(n_vals)
            ia = sum(i_vals)/len(i_vals) if i_vals else 0
            ta = sum(t_vals)/len(t_vals) if t_vals else 0
            tm = max(t_vals) if t_vals else 0
            da = sum(d_vals)/len(d_vals) if d_vals else 0
            dm = max(d_vals) if d_vals else 0
            
            return f"{label:<4} | {sa:7.3f} | {sp:7.3f} | {sma:7.3f} | {na:7.2f} | {np95:7.2f} | {ia:8.1f} | {ta:7.1f}s | {tm:7.1f}s | {da:7.1f}m | {dm:7.1f}m"

        for p in pts_range:
            print(get_line(str(p), method_stats[p]['search'], method_stats[p]['net'], method_stats[p]['iterations'], method_stats[p]['time'], method_stats[p]['dist']))
        
        print("-" * len(header))
        print(get_line("ALL", method_stats['total']['search'], method_stats['total']['net'], method_stats['total']['iterations'], method_stats['total']['time'], method_stats['total']['dist']))
        print("-" * len(header))

    print_stat_table("id (Direct ID Routing)", stats['id'])
    print_stat_table("ll (Coordinate Snap Routing)", stats['ll'])
    print_stat_table("OVERALL Performance", stats['all'])
    print("\n" + "="*95)

if __name__ == "__main__":
    run_test(count=1000)
