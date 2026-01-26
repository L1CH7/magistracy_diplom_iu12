from loguru import logger
from src.db_manager import PostGISManager
from src.osm.osm_way_processor import OSMWayProcessor
from src.osm.turn_restrictions import TurnRestrictionManager

class GraphBuilder:
    def __init__(self, config_path: str, db_dsn: str):
        self.config_path = config_path
        self.db = PostGISManager() # Connects using env vars
        self.processor = OSMWayProcessor()
        self.restrictions_mgr = TurnRestrictionManager()

    async def initialize(self):
        logger.info("GraphBuilder initialized")

    def build_graph_from_db(self, task_id: str):
        """
        Build graph from existing DB tables using pgRouting topology.
        This blocks the thread it runs on, so should be run in executor.
        """
        try:
            from src.state.task_manager import task_manager
            import threading
            import time

            class StepLogger(threading.Thread):
                def __init__(self, task_id, message, progress, interval=10):
                    super().__init__()
                    self.task_id = task_id
                    self.message = message
                    self.progress = progress
                    self.interval = interval
                    self.stop_event = threading.Event()
                    self.daemon = True

                def run(self):
                    elapsed = 0
                    while not self.stop_event.is_set():
                        if elapsed > 0:
                            msg = f"{self.message} ({elapsed}s elapsed)"
                            logger.info(f"Task {self.task_id}: {msg}")
                            task_manager.update_progress(
                                self.task_id, self.progress, "processing", msg
                            )
                        time.sleep(self.interval)
                        elapsed += self.interval

                def stop(self):
                    self.stop_event.set()

            def run_with_logging(func, msg, start_progress):
                 logger = StepLogger(task_id, msg, start_progress)
                 task_manager.update_progress(task_id, start_progress, "processing", msg)
                 logger.start()
                 try:
                     func()
                 finally:
                     logger.stop()

            # Step 1
            run_with_logging(self.db.prepare_topology_inputs, "Step 1: Preparing edge candidates...", 10.0)
            
            # Step 2
            run_with_logging(self.db.run_pgr_create_topology, "Step 2: Running pgr_createTopology (heavy)...", 30.0)
            
            # Step 3
            run_with_logging(self.db.fill_graph_tables, "Step 3: Populating graph tables...", 70.0)
            
            # Step 4
            run_with_logging(self.db.finalize_graph, "Step 4: Finalizing...", 90.0)
            
            task_manager.mark_complete(task_id, "Graph built successfully from DB")
            logger.success("Graph build complete via SQL topology!")
            
        except Exception as e:
            logger.error(f"Graph verification/build failed: {e}")
            from src.state.task_manager import task_manager
            task_manager.mark_failed(task_id, str(e))
            raise

    # Legacy method kept for reference or removal
    async def build_graph_from_overpass(self, overpass_data: dict):
        raise NotImplementedError("Use build_graph_from_db")
