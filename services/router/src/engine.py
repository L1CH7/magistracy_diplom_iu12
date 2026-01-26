from loguru import logger

class PgRoutingEngine:
    def __init__(self, config: dict):
        self.config = config
        self.pool = None

    async def initialize(self):
        logger.warning("PgRoutingEngine stub initialized. Implementation pending.")
        
    async def close(self):
        logger.info("PgRoutingEngine closed.")

    async def route(self, navigation_request):
        raise NotImplementedError("Routing is not implemented yet.")
