"""
Logging wrapper for Azure Functions.
This module provides functions to redirect print statements to Azure Functions logger.
"""
import logging
import sys
import builtins

# Store the original print function
original_print = builtins.print

def init_logging_wrapper():
    """
    Initialize the logging wrapper by replacing the built-in print function.
    This should be called at the start of each Azure Function.
    """
    # Define a new print function that redirects to logging
    def azure_print(*args, **kwargs):
        # Convert args to string
        message = " ".join(str(arg) for arg in args)
        
        # Remove emoji characters that can cause encoding issues
        message = message.replace("[SUCCESS]", "[SUCCESS]").replace("[ERROR]", "[ERROR]")
        
        # Log the message
        logging.info(message)
        
        # Call the original print function
        original_print(*args, **kwargs)
    
    # Replace the built-in print function
    builtins.print = azure_print

def restore_original_print():
    """
    Restore the original print function.
    This should be called at the end of each Azure Function.
    """
    builtins.print = original_print
