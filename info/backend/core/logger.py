import logging


formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s"
)

# ------------------------
# AGENT LOGGER
# ------------------------

agent_logger = logging.getLogger(
    "agent"
)

agent_logger.setLevel(
    logging.INFO
)

agent_handler = logging.FileHandler(
    "logs/agent.log"
)

agent_handler.setFormatter(
    formatter
)

agent_logger.addHandler(
    agent_handler
)

# ------------------------
# TOOL LOGGER
# ------------------------

tool_logger = logging.getLogger(
    "tools"
)

tool_logger.setLevel(
    logging.INFO
)

tool_handler = logging.FileHandler(
    "logs/tools.log"
)

tool_handler.setFormatter(
    formatter
)

tool_logger.addHandler(
    tool_handler
)

# ------------------------
# ERROR LOGGER
# ------------------------

error_logger = logging.getLogger(
    "errors"
)

error_logger.setLevel(
    logging.ERROR
)

error_handler = logging.FileHandler(
    "logs/errors.log"
)

error_handler.setFormatter(
    formatter
)

error_logger.addHandler(
    error_handler
)