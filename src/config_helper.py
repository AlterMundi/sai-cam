"""
Configuration Helper

Handles environment variables, config files, and interactive prompts
with secure fallback priorities for camera configurations.
"""

import os
import re
import getpass
import logging
from typing import Any, Optional, Dict
import yaml


class ConfigHelper:
    """Helper class for secure configuration management"""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.interactive_mode = True  # Can be disabled for automated deployments
        
    def get_secure_value(self, key: str, config_value: Any = None, 
                        default: Any = None, required: bool = False,
                        is_password: bool = False, description: str = None) -> Any:
        """
        Get configuration value with secure fallback priorities:
        1. Environment variable (highest priority)
        2. Config file value (medium priority)  
        3. Interactive prompt (fallback for missing values)
        4. Default value (lowest priority)
        
        Args:
            key: Environment variable name (e.g., 'CAMERA_PASSWORD')
            config_value: Value from config file
            default: Default value to use
            required: Whether this value is required
            is_password: Whether to mask input when prompting
            description: Human-readable description for prompts
            
        Returns:
            Configuration value from highest priority source
        """
        
        # 1. Environment variable (highest priority)
        env_value = os.getenv(key)
        if env_value:
            self.logger.debug(f"Using environment variable for {key}")
            return env_value
            
        # 2. Config file value (medium priority)
        if config_value is not None:
            # Support environment variable substitution in config files
            if isinstance(config_value, str) and config_value.startswith('${') and config_value.endswith('}'):
                env_key = config_value[2:-1]
                env_value = os.getenv(env_key)
                if env_value:
                    self.logger.debug(f"Using environment substitution {env_key} for {key}")
                    return env_value
                elif required:
                    self.logger.warning(f"Environment variable {env_key} not found for {key}")
                else:
                    self.logger.debug(f"Environment variable {env_key} not found, using config value")
                    return config_value
            else:
                self.logger.debug(f"Using config file value for {key}")
                return config_value
        
        # 3. Interactive prompt (fallback for missing values)
        if required and self.interactive_mode:
            prompt_desc = description or key.replace('_', ' ').lower()
            try:
                if is_password:
                    value = getpass.getpass(f"Enter {prompt_desc}: ")
                else:
                    value = input(f"Enter {prompt_desc}: ").strip()
                    
                if value:
                    self.logger.debug(f"Using interactive input for {key}")
                    return value
            except (KeyboardInterrupt, EOFError):
                self.logger.info("Interactive input cancelled")
                
        # 4. Default value (lowest priority)
        if default is not None:
            self.logger.debug(f"Using default value for {key}")
            return default
            
        # Required value not found
        if required:
            raise ValueError(f"Required configuration value '{key}' not found. "
                           f"Set environment variable {key} or provide in config file.")
        
        return None
    
    def expand_config_variables(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively expand environment variables in configuration
        Supports ${VAR_NAME} syntax
        """
        if isinstance(config, dict):
            return {k: self.expand_config_variables(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [self.expand_config_variables(item) for item in config]
        elif isinstance(config, str):
            # Expand environment variables
            pattern = r'\$\{([^}]+)\}'
            
            def replace_env_var(match):
                env_var = match.group(1)
                default_value = None
                
                # Support ${VAR_NAME:-default_value} syntax
                if ':-' in env_var:
                    env_var, default_value = env_var.split(':-', 1)
                
                value = os.getenv(env_var, default_value)
                if value is None:
                    self.logger.warning(f"Environment variable {env_var} not found")
                    return match.group(0)  # Return original if not found
                return value
            
            return re.sub(pattern, replace_env_var, config)
        else:
            return config
    
    def load_env_file(self, env_file_path: str = '.env') -> Dict[str, str]:
        """
        Load environment variables from .env file
        Returns dict of loaded variables
        """
        env_vars = {}
        
        if not os.path.exists(env_file_path):
            self.logger.debug(f"Environment file {env_file_path} not found")
            return env_vars
            
        try:
            with open(env_file_path, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    
                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue
                    
                    # Parse KEY=value format
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        
                        # Remove quotes if present
                        if (value.startswith('"') and value.endswith('"')) or \
                           (value.startswith("'") and value.endswith("'")):
                            value = value[1:-1]
                        
                        # Set environment variable
                        os.environ[key] = value
                        env_vars[key] = value
                        self.logger.debug(f"Loaded {key} from {env_file_path}")
                    else:
                        self.logger.warning(f"Invalid format in {env_file_path} line {line_num}: {line}")
                        
        except Exception as e:
            self.logger.error(f"Error loading {env_file_path}: {e}")
            
        self.logger.info(f"Loaded {len(env_vars)} environment variables from {env_file_path}")
        return env_vars
    
    def validate_required_vars(self, required_vars: Dict[str, str]) -> bool:
        """
        Validate that all required environment variables are set
        
        Args:
            required_vars: Dict of {var_name: description}
            
        Returns:
            True if all required vars are set, False otherwise
        """
        missing_vars = []
        
        for var_name, description in required_vars.items():
            if not os.getenv(var_name):
                missing_vars.append(f"  {var_name}: {description}")
        
        if missing_vars:
            self.logger.error("Missing required environment variables:")
            for var in missing_vars:
                self.logger.error(var)
            self.logger.error("Set these variables or provide values in config file")
            return False
            
        return True
    
    def get_camera_config_with_env(self, camera_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get camera configuration with environment variable support
        """
        camera_id = camera_config.get('id', 'unknown')
        camera_type = camera_config.get('type', 'rtsp')
        
        # Create a copy to avoid modifying original
        config = camera_config.copy()
        
        # Common camera settings
        if camera_type in ['rtsp', 'onvif']:
            # Network cameras may need credentials
            config['username'] = self.get_secure_value(
                'CAMERA_USERNAME',
                config.get('username'),
                'admin',
                description=f"username for camera {camera_id}"
            )
            
            config['password'] = self.get_secure_value(
                'CAMERA_PASSWORD', 
                config.get('password'),
                required=True,
                is_password=True,
                description=f"password for camera {camera_id}"
            )
        
        # Type-specific settings
        if camera_type == 'onvif':
            config['address'] = self.get_secure_value(
                'CAMERA_IP',
                config.get('address'),
                required=True,
                description=f"IP address for ONVIF camera {camera_id}"
            )
            
        elif camera_type == 'rtsp':
            # RTSP URL might contain credentials, handle carefully
            rtsp_url = config.get('rtsp_url')
            if rtsp_url and ('${' in rtsp_url):
                config['rtsp_url'] = self.expand_config_variables(rtsp_url)
        
        return config
    
    def set_interactive_mode(self, enabled: bool):
        """Enable or disable interactive prompts"""
        self.interactive_mode = enabled