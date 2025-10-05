import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s]-[%(filename)s]: %(message)s",
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger("trading_app")
