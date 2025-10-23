"""
Azure Blob Storage Logging Module for PGIM Dealio Azure Functions.

This module provides logging functionality that saves logs to Azure Blob Storage.
"""

import os
import logging
import datetime
import io
from typing import Optional

from azure.storage.blob import BlobServiceClient
from .auth import get_blob_service_client

class BlobStorageLogHandler(logging.Handler):
    """
    A custom logging handler that writes logs to Azure Blob Storage.
    """
    
    def __init__(self, function_name: str, level=logging.INFO):
        """
        Initialize the BlobStorageLogHandler.
        
        Args:
            function_name: Name of the function generating the logs
            level: Logging level
        """
        super().__init__(level)
        self.function_name = function_name
        self.log_buffer = io.StringIO()
        self.container_name = "logs"
        
        # Set up formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.setFormatter(formatter)
    
    def emit(self, record):
        """
        Emit a log record to the buffer.
        
        Args:
            record: Log record to emit
        """
        try:
            msg = self.format(record)
            self.log_buffer.write(msg + '\n')
        except Exception:
            self.handleError(record)
    
    def flush(self):
        """
        Flush the log buffer to Azure Blob Storage.
        """
        try:
            # Get blob service client
            blob_service_client = get_blob_service_client()
            
            # Get container client
            container_client = blob_service_client.get_container_client(self.container_name)
            
            # Create container if it doesn't exist
            try:
                container_client.get_container_properties()
            except Exception:
                container_client.create_container()
            
            # Generate blob name with timestamp
            now = datetime.datetime.now()
            date_folder = now.strftime("%Y-%m-%d")
            timestamp = now.strftime("%Y%m%d_%H%M%S")
            blob_name = f"{self.function_name}/{date_folder}/{timestamp}.log"
            
            # Get blob client
            blob_client = container_client.get_blob_client(blob_name)
            
            # Upload log buffer
            log_content = self.log_buffer.getvalue()
            if log_content:
                blob_client.upload_blob(log_content, overwrite=True)
                
                # Clear buffer after successful upload
                self.log_buffer = io.StringIO()
        except Exception as e:
            # If we can't upload to blob storage, log to console
            print(f"Error uploading logs to blob storage: {e}")
    
    def close(self):
        """
        Close the handler and flush any remaining logs.
        """
        self.flush()
        self.log_buffer.close()
        super().close()

def setup_blob_logging(function_name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Set up logging to Azure Blob Storage.
    
    Args:
        function_name: Name of the function
        level: Logging level
        
    Returns:
        Logger configured to log to Azure Blob Storage
    """
    # Create logger
    logger = logging.getLogger(function_name)
    logger.setLevel(level)
    
    # Add blob storage handler
    blob_handler = BlobStorageLogHandler(function_name, level)
    logger.addHandler(blob_handler)
    
    # Add console handler for local development
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger
