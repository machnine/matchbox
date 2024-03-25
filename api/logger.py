"""logging settings"""

import logging
from pathlib import Path


class LogManager:
    """Logging manager"""

    def __init__(self, log_dir_name="logs"):
        self.log_dir_name = log_dir_name
        self.log_dir = Path(self.log_dir_name)
        self.access_log_file = "access.log"
        self.error_log_file = "error.log"
        self.setup_directory()
        self.setup_log_files()

    def setup_directory(self):
        """Create log directory if it doesn't exist."""
        if not self.log_dir.exists():
            self.log_dir.mkdir(parents=True, exist_ok=True)

    def setup_log_files(self):
        """Create log files if they don't exist."""
        for log_file in [self.access_log_file, self.error_log_file]:
            file_path = self.log_dir / log_file
            if not file_path.exists():
                file_path.touch()

    def get_logger(self, file_name, log_source=None, log_level=logging.INFO):
        """Get logger configured with file handler and formatter."""
        log_file_path = self.log_dir / file_name
        logger = logging.getLogger(log_source) if log_source else logging.getLogger()
        logger.setLevel(log_level)
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

        file_handler = logging.FileHandler(log_file_path)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        return logger

    def setup_application_logging(self):
        """set up application wide logging"""
        self.get_logger(self.access_log_file, log_source="uvicorn.access")
        self.get_logger(self.error_log_file, log_level=logging.ERROR)


log_manager = LogManager()
