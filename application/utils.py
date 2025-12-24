import logging
import sys
import json
import boto3
import os

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("utils")

script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, "config.json")
    
def load_config():
    config = None
    
    try:    
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        config = {}
        config['projectName'] = "speech-to-speech"
        session = boto3.Session()
        bedrock_region = session.region_name

        sts = boto3.client("sts")
        response = sts.get_caller_identity()        
        config['region'] = bedrock_region
        accountId = response["Account"]
        config['accountId'] = accountId

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)  

    return config

config = load_config()

bedrock_region = config['region']
accountId = config['accountId']
projectName = config['projectName']

def load_mcp_env():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mcp_env_path = os.path.join(script_dir, "mcp.env")
    
    with open(mcp_env_path, "r", encoding="utf-8") as f:
        mcp_env = json.load(f)
    return mcp_env

def save_mcp_env(mcp_env):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mcp_env_path = os.path.join(script_dir, "mcp.env")
    
    with open(mcp_env_path, "w", encoding="utf-8") as f:
        json.dump(mcp_env, f)