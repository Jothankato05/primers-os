import logging
import os
from logging.handlers import RotatingFileHandler

class PrimersLogger:
    @staticmethod
    def get_logger(name: str):
        logger = logging.getLogger(name)
        if not logger.handlers:
            logger.setLevel(logging.DEBUG)
            
            # Console Handler
            c_handler = logging.StreamHandler()
            c_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            c_handler.setFormatter(c_format)
            c_handler.setLevel(logging.INFO)
            
            # File Handler
            log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
            f_handler = RotatingFileHandler(
                os.path.join(log_dir, "primers.log"), 
                maxBytes=10*1024*1024, 
                backupCount=5
            )
            f_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            f_handler.setFormatter(f_format)
            f_handler.setLevel(logging.DEBUG)
            
            logger.addHandler(c_handler)
            logger.addHandler(f_handler)
        
        return logger
