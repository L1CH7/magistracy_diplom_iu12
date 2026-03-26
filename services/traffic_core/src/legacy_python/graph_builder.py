from loguru import logger
from .db_manager import PostGISManager
from .state.task_manager import task_manager
import time
import concurrent.futures

class GraphBuilder:
    """
    Orchestrates the graph building process.
    Connects DBManager operations to build the routing topology.
    """
    def __init__(self, db_manager: PostGISManager):
        self.db = db_manager

    def _monitor_step(self, task_id, future, description, table_name, estimated_total, start_pct, end_pct):
        """Monitor a running DB task and update progress based on table counts."""
        while not future.done():
            time.sleep(5)  # Update every 5s (User asked for ~10s, 5 is better)
            try:
                current_count = self.db.get_table_count(table_name)
                # Estimate local percentage (cap at 99% until done)
                if estimated_total > 0:
                    local_pct = min(99, int((current_count / estimated_total) * 100))
                else:
                    local_pct = 0
                
                # Global percentage mapping
                global_range = end_pct - start_pct
                global_pct = start_pct + int((local_pct / 100.0) * global_range)
                
                msg = f"{description}: {current_count} processed ({local_pct}%)"
                if task_id:
                    task_manager.update_progress(task_id, global_pct, msg)
                    
            except Exception as e:
                logger.warning(f"Progress monitor error: {e}")
                
        # Task done
        if task_id:
            task_manager.update_progress(task_id, end_pct, f"{description}: Completed.")

    def build_graph_from_db(self, task_id: str = None):
        """
        Full recreation of the routing graph from OSM data.
        Steps:
        1. Prepare inputs (candidates)
        2. Clean/Node the network (pgr_nodeNetwork)
        3. Create Topology
        4. Fill operational tables
        5. Finalize/Cleanup
        """
        logger.info(f"[{task_id}] Starting graph build...")
        if task_id:
            task_manager.update_progress(task_id, 0, "Starting graph build...")
        
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        
        try:
            # Step 1: Prepare
            logger.info("Step 1: Preparing candidates (Extracting from OSM)...")
            if task_id:
                task_manager.update_progress(task_id, 1, "Step 1: Preparing candidates...")
            
            # Step 1.1: Init Structure
            future = executor.submit(self.db.init_candidate_table)
            while not future.done(): time.sleep(1)
            future.result()
            
            # Step 1.2: Batch Insert
            batch_size = 50000
            offset = 0
            total_extracted = 0
            
            while True:
                future = executor.submit(self.db.insert_candidates_batch, offset, batch_size)
                # Wait for batch
                while not future.done(): time.sleep(0.5)
                inserted = future.result()
                
                total_extracted += inserted
                offset += inserted
                
                msg = f"Step 1: Extracted {total_extracted} candidates..."
                logger.info(msg)
                if task_id:
                     # Map Step 1 (1-10%) based on rough count (e.g. 200k)
                    pct = min(9, 1 + int((total_extracted / 200000.0) * 9))
                    task_manager.update_progress(task_id, pct, msg)
                
                if inserted < batch_size:
                    break
            
            # Step 1.3: Finalize (Index)
            logger.info("Step 1: Indexing candidates...")
            future = executor.submit(self.db.finalize_candidate_table)
            while not future.done(): time.sleep(1)
            future.result()
            
            total_candidates = total_extracted
            # Noding usually increases edges by 1.2x - 2.0x depending on density. Let's assume 1.5x
            est_noded = max(int(total_candidates * 1.5), 1)
            
            logger.info(f"Step 1 Complete. Found {total_candidates} candidates.")
            
            # Step 2: Noding
            logger.info("Step 2: Smart Noding (Ground Only + Bridge Merge)...")
            future = executor.submit(self.db.run_pgr_nodeNetwork)
            # Monitor ground noding table. 
            self._monitor_step(task_id, future, "Step 2: Grid Noding", "edge_candidates_merged", est_noded, 10, 40)
            future.result()
            
            # Re-evaluate count after noding
            actual_noded = self.db.get_table_count('edge_candidates_merged')
            logger.info(f"Step 2 Complete. Merged edges: {actual_noded}")
            
            # Step 3: Topology
            logger.info("Step 3: Creating Topology (Merged Network)...")
            future = executor.submit(self.db.run_pgr_create_topology)
            est_nodes = max(int(actual_noded * 0.7), 1)
            self._monitor_step(task_id, future, "Step 3: Topology", "edge_candidates_merged_vertices_pgr", est_nodes, 40, 70)
            future.result()
            
            # Step 4: Populate
            logger.info("Step 4: Populating Graph Tables (Calculating costs)...")
            future = executor.submit(self.db.fill_graph_tables)
            self._monitor_step(task_id, future, "Step 4: Populating", "graphs.edges", actual_noded, 70, 95)
            future.result()
            
            # Step 5: Finalize
            logger.info("Step 5: Finalizing (Cleanup and Analyze)...")
            if task_id:
                task_manager.update_progress(task_id, 96, "Step 5: Finalizing...")
            self.db.finalize_graph()
            
            logger.success(f"[{task_id}] Graph build completed successfully.")
            if task_id:
                task_manager.update_progress(task_id, 100, "Graph build completed successfully.")
            
        except Exception as e:
            logger.exception(f"[{task_id}] Graph build failed: {e}")
            if task_id:
                task_manager.mark_failed(task_id, str(e))
            raise
        finally:
            executor.shutdown(wait=False)
