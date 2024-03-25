"""logging settings"""

import logging
from pathlib import Path


def logging_setup():
    """setup logging"""
    log_dir_name = "logs"
    access_log_file = "access.log"
    error_log_file = "error.log"
    _, access_log, error_log = check_and_create_logs(log_dir_name, access_log_file, error_log_file)
    get_logger(access_log, log_source="uvicorn.access")
    get_logger(error_log, log_level=logging.ERROR)


def get_logger(
    log_filename: str,
    log_source: str = None,
    log_level: int = logging.INFO,
):
    """get logger"""
    logger = logging.getLogger(log_source) if log_source else logging.getLogger()
    logger.setLevel(log_level)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    file_handler = logging.FileHandler(log_filename)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def check_and_create_logs(log_dir_name: str, access_log_file: str, error_log_file: str):
    """check and create logs directory"""
    log_dir = Path(log_dir_name)
    access_log = log_dir / access_log_file
    error_log = log_dir / error_log_file

    if not log_dir.exists():
        log_dir.mkdir(parents=True, exist_ok=True)

    if not access_log.exists():
        access_log.touch()

    if not error_log.exists():
        error_log.touch()

    return log_dir, access_log, error_log
