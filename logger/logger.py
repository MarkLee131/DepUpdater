"""logger module to store the process of computation and update"""
import logging

from constants import get_log_path

logger = logging.getLogger("logger")
logger.setLevel(logging.DEBUG)

file_handler = None

def initialize_logger():
    global file_handler
    if file_handler is not None and file_handler.baseFilename != get_log_path():
        logger.removeHandler(file_handler)
        file_handler.close()
        file_handler = None
    if file_handler is None:
        # create file handler which logs debug messages
        file_handler = logging.FileHandler(get_log_path())
        file_handler.setLevel(logging.DEBUG)

        # just log debug messages in file_handler
        class DebugOnlyFilter(logging.Filter):
            def filter(self, record):
                return record.levelno == logging.DEBUG
        file_handler.addFilter(DebugOnlyFilter())

        # set formatter
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        file_handler.setFormatter(formatter)

        # add the handlers to the logger
        logger.addHandler(file_handler)

# log debug message
def log_debug(message):
    """log debug message and flush"""
    initialize_logger()
    logger.debug(message)
    file_handler.flush()
