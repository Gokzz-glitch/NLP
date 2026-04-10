# core/logger.py
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

def setup_logger(name: str, log_file: str = "logs/sentinel.log", level=logging.INFO):
    """
    [REMEDIATION #21]: Professional Log Rotation [CWE-773]
    Prevents the disk from filling up during 24/7 autonomous operation.
    """
    log_dir = Path(log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 5MB per file, max 5 backups
    handler = RotatingFileHandler(
        log_file, 
        maxBytes=5*1024*1024, 
        backupCount=5,
        encoding="utf-8"
    )
    
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    
    if not logger.handlers:
        logger.addHandler(handler)
        # Also add console logging for local debugging
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)
        
    return logger
