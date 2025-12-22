import logging
import sys
import utils
import os
import boto3
import json

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("mcp-config")

script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, "config.json")

config = utils.load_config()
logger.info(f"config: {config}")

region = config["region"] if "region" in config else "us-west-2"
projectName = config["projectName"] if "projectName" in config else "mcp"
workingDir = os.path.dirname(os.path.abspath(__file__))
logger.info(f"workingDir: {workingDir}")

gateway_url = ""
bearer_token = ""

def initialize_config():
    global config

    # knowledge base name
    knowledge_base_name = config.get("knowledge_base_name", "")
    if not knowledge_base_name:
        knowledge_base_name = projectName
        config['knowledge_base_name'] = knowledge_base_name

    # knowledge base id
    knowledge_base_id = config.get("knowledge_base_id", "")
    if not knowledge_base_id:
        # search knowledge base id using knowledge base name
        bedrock_agent_client = boto3.client("bedrock-agent")
        response = bedrock_agent_client.list_knowledge_bases()
        for knowledge_base in response["knowledgeBaseSummaries"]:
            if knowledge_base["name"] == projectName:
                knowledge_base_id = knowledge_base["knowledgeBaseId"]
                break
        logger.info(f"knowledge_base_id: {knowledge_base_id}")
        config['knowledge_base_name'] = projectName
        config['knowledge_base_id'] = knowledge_base_id
    
    # secret name
    if not "secret_name" in config:
        secret_name = f"{projectName}/credentials"
        config['secret_name'] = secret_name
        logger.info(f"secret_name: {secret_name}")

    # save config
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

initialize_config()

def get_bearer_token_from_secret_manager(secret_name):
    try:
        session = boto3.Session()
        client = session.client('secretsmanager', region_name=region)
        response = client.get_secret_value(SecretId=secret_name)
        bearer_token_raw = response['SecretString']
        
        token_data = json.loads(bearer_token_raw)        
        if 'bearer_token' in token_data:
            bearer_token = token_data['bearer_token']
            return bearer_token
        else:
            logger.info("No bearer token found in secret manager")
            return None
    
    except Exception as e:
        logger.info(f"Error getting stored token: {e}")
        return None

def get_secret_value(secret_name):
    session = boto3.Session()
    client = session.client('secretsmanager', region_name=region)
    
    try:
        response = client.get_secret_value(SecretId=secret_name)
        return response['SecretString']
    except client.exceptions.ResourceNotFoundException:
        logger.info(f"Secret not found, creating new secret: {secret_name}")
        try:
            # Create secret value with bearer_key 
            secret_value = {
                "key": secret_name,
                "value": "need to update"
            }
            
            # Convert to JSON string
            secret_string = json.dumps(secret_value)

            client.create_secret(
                Name=secret_name,
                SecretString=secret_string,  
                Description=f"secret key and token for {secret_name}"
            )
            logger.info(f"Secret created: {secret_name}. Please update it with the actual value.")
            return None
        except Exception as create_error:
            logger.error(f"Failed to create secret: {create_error}")
            return None
    except Exception as e:
        logger.error(f"Error getting secret value: {e}")
        return None

def retrieve_bearer_token(secret_name):
    secret_name = config['secret_name']
    bearer_token = get_bearer_token_from_secret_manager(secret_name)
    logger.info(f"Bearer token from secret manager: {bearer_token[:100] if bearer_token else 'None'}...")

    # verify bearer token
    try:
        client = boto3.client('cognito-idp', region_name=region)
        response = client.get_user(
            AccessToken=bearer_token
        )
        logger.info(f"response: {response}")

        username = response['Username']
        logger.info(f"Username: {username}")

    except Exception as e:
        logger.info(f"Error verifying bearer token: {e}")

        # Try to get fresh bearer token from Cognito
        logger.info("Error verifying bearer token, getting fresh bearer token from Cognito...")
        bearer_token = create_cognito_bearer_token(config)
        logger.info(f"Bearer token from cognito: {bearer_token[:100] if bearer_token else 'None'}...")
        
        if bearer_token:
            secret_name = config['secret_name']
            save_bearer_token(secret_name, bearer_token)
        else:
            logger.info("Failed to get bearer token from Cognito. Exiting.")
            return {}
        
    return bearer_token

def save_bearer_token(secret_name, bearer_token):
    try:        
        session = boto3.Session()
        client = session.client('secretsmanager', region_name=region)
        
        # Create secret value with bearer_key 
        secret_value = {
            "bearer_key": "mcp_server_bearer_token",
            "bearer_token": bearer_token
        }
        
        # Convert to JSON string
        secret_string = json.dumps(secret_value)
        
        # Check if secret already exists
        try:
            client.describe_secret(SecretId=secret_name)
            # Secret exists, update it
            client.put_secret_value(
                SecretId=secret_name,
                SecretString=secret_string
            )
            logger.info(f"Bearer token updated in secret manager with key: {secret_value['bearer_key']}")
        except client.exceptions.ResourceNotFoundException:
            # Secret doesn't exist, create it
            client.create_secret(
                Name=secret_name,
                SecretString=secret_string,
                Description="MCP Server Cognito credentials with bearer key and token"
            )
            logger.info(f"Bearer token created in secret manager with key: {secret_value['bearer_key']}")
            
    except Exception as e:
        logger.info(f"Error saving bearer token: {e}")
        # Continue execution even if saving fails

mcp_user_config = {}    

def load_config(mcp_type):
    if mcp_type == "image generation":
        mcp_type = 'image_generation'
    elif mcp_type == "aws diagram":
        mcp_type = 'aws_diagram'
    elif mcp_type == "aws document":
        mcp_type = 'aws_documentation'
    elif mcp_type == "aws cost":
        mcp_type = 'aws_cost'
    elif mcp_type == "ArXiv":
        mcp_type = 'arxiv'
    elif mcp_type == "aws cloudwatch":
        mcp_type = 'aws_cloudwatch'
    elif mcp_type == "aws storage":
        mcp_type = 'aws_storage'
    elif mcp_type == "knowledge base":
        mcp_type = 'knowledge_base_lambda'
    elif mcp_type == "repl coder":
        mcp_type = 'repl_coder'
    elif mcp_type == "agentcore coder":
        mcp_type = 'agentcore_coder'
    elif mcp_type == "aws cli":
        mcp_type = 'aws_cli'
    elif mcp_type == "text editor":
        mcp_type = 'text_editor'
    elif mcp_type == "aws-api":
        mcp_type = 'aws-api-mcp-server'
    elif mcp_type == "aws-knowledge":
        mcp_type = 'aws-knowledge-mcp-server'
    elif mcp_type == "aws ccapi":
        mcp_type = 'ccapi'
    elif mcp_type == "use-aws (runtime)":
        mcp_type = "use-aws"
    elif mcp_type == "kb-retriever (runtime)":        
        mcp_type = "kb-retriever"

    if mcp_type == "basic":
        return {
            "mcpServers": {
                "search": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_basic.py"
                    ]
                }
            }
        }
    
    elif mcp_type == "use-aws (local)":
        return {
            "mcpServers": {
                "use-aws": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_use_aws.py"
                    ]
                }
            }
        }
        
    elif mcp_type == "kb-retriever (local)":
        return {
            "mcpServers": {
                "kb_retriever": {
                    "command": "python",
                    "args": [f"{workingDir}/mcp_server_retrieve.py"]
                }
            }
        }
    
    elif mcp_type == "kb-retriever":
        agent_arn = get_agent_runtime_arn(mcp_type)
        logger.info(f"mcp_type: {mcp_type}, agent_arn: {agent_arn}")
        encoded_arn = agent_arn.replace(':', '%3A').replace('/', '%2F')

        if not bearer_token:
            bearer_token = retrieve_bearer_token(config['secret_name'])
            logger.info(f"Bearer token from secret manager: {bearer_token[:100] if bearer_token else 'None'}...")

        return {
            "mcpServers": {
                "kb-retriever": {
                    "type": "streamable_http",
                    "url": f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT",
                    "headers": {
                        "Authorization": f"Bearer {bearer_token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream"
                    }
                }
            }
        }

    elif mcp_type == "image_generation":
        return {
            "mcpServers": {
                "imageGeneration": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_image_generation.py"
                    ]
                }
            }
        }    
    
    elif mcp_type == "airbnb":
        return {
            "mcpServers": {
                "airbnb": {
                    "command": "npx",
                    "args": [
                        "-y",
                        "@openbnb/mcp-server-airbnb",
                        "--ignore-robots-txt"
                    ]
                }
            }
        }
    
    elif mcp_type == "playwright":
        return {
            "mcpServers": {
                "playwright": {
                    "command": "npx",
                    "args": [
                        "@playwright/mcp@latest"
                    ]
                }
            }
        }
    
    elif mcp_type == "obsidian":
        return {
            "mcpServers": {
                "mcp-obsidian": {
                "command": "npx",
                "args": [
                    "-y",
                    "@smithery/cli@latest",
                    "run",
                    "mcp-obsidian",
                    "--config",
                    "{\"vaultPath\":\"/\"}"
                ]
                }
            }
        }
    
    elif mcp_type == "aws_diagram":
        return {
            "mcpServers": {
                "awslabs.aws-diagram-mcp-server": {
                    "command": "uvx",
                    "args": ["awslabs.aws-diagram-mcp-server"],
                    "env": {
                        "FASTMCP_LOG_LEVEL": "ERROR"
                    },
                }
            }
        }
    
    elif mcp_type == "aws_documentation":
        return {
            "mcpServers": {
                "awslabs.aws-documentation-mcp-server": {
                    "command": "uvx",
                    "args": ["awslabs.aws-documentation-mcp-server@latest"],
                    "env": {
                        "FASTMCP_LOG_LEVEL": "ERROR"
                    }
                }
            }
        }
    
    elif mcp_type == "aws_cost":
        return {
            "mcpServers": {
                "aws_cost": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_aws_cost.py"
                    ]
                }
            }
        }    
    
    elif mcp_type == "aws_cloudwatch":
        return {
            "mcpServers": {
                "aws_cloudwatch_log": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_aws_log.py"
                    ],
                    "env": {
                        "region": region,
                        "FASTMCP_LOG_LEVEL": "ERROR"
                    }
                }
            }
        }  
    
    elif mcp_type == "aws_storage":
        return {
            "mcpServers": {
                "aws_storage": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_aws_storage.py"
                    ]
                }
            }
        }    
        
    elif mcp_type == "arxiv":
        return {
            "mcpServers": {
                "arxiv-mcp-server": {
                    "command": "npx",
                    "args": [
                        "-y",
                        "@smithery/cli@latest",
                        "run",
                        "arxiv-mcp-server",
                        "--config",
                        "{\"storagePath\":\"/Users/ksdyb/Downloads/ArXiv\"}"
                    ]
                }
            }
        }
    
    elif mcp_type == "firecrawl":
        return {
            "mcpServers": {
                "firecrawl-mcp": {
                    "command": "npx",
                    "args": ["-y", "firecrawl-mcp"],
                    "env": {
                        "FIRECRAWL_API_KEY": utils.firecrawl_key
                    }
                }
            }
        }
        
    elif mcp_type == "knowledge_base_lambda":
        return {
            "mcpServers": {
                "knowledge_base_lambda": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_lambda_knowledge_base.py"
                    ]
                }
            }
        }    
    
    elif mcp_type == "repl_coder":
        return {
            "mcpServers": {
                "repl_coder": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_repl_coder.py"
                    ]
                }
            }
        }    
    
    elif mcp_type == "agentcore_coder":
        return {
            "mcpServers": {
                "agentcore_coder": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_agentcore_coder.py"
                    ]
                }
            }
        }
    
    elif mcp_type == "aws_cli":
        return {
            "mcpServers": {
                "aw-cli": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_aws_cli.py"
                    ]
                }
            }
        }    
    
    elif mcp_type == "tavily":
        return {
            "mcpServers": {
                "tavily-mcp": {
                    "command": "npx",
                    "args": ["-y", "tavily-mcp@0.1.4"],
                    "env": {
                        "TAVILY_API_KEY": utils.tavily_key
                    },
                }
            }
        }
    
    elif mcp_type == "wikipedia":
        return {
            "mcpServers": {
                "wikipedia": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_wikipedia.py"
                    ]
                }
            }
        }      
    
    elif mcp_type == "terminal":
        return {
            "mcpServers": {
                "iterm-mcp": {
                    "command": "npx",
                    "args": [
                        "-y",
                        "iterm-mcp"
                    ]
                }
            }
        }
    
    elif mcp_type == "filesystem":
        parent_dir = os.path.dirname(workingDir)
        return {
            "mcpServers": {
                "filesystem": {
                    "command": "npx",
                    "args": [
                        "@modelcontextprotocol/server-filesystem",
                        parent_dir  
                    ]
                }
            }
        }
    
    elif mcp_type == "puppeteer":
        return {
            "mcpServers": {
                "puppeteer": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-puppeteer"]
                }
            }
        }
    
    elif mcp_type == "perplexity":
        return {
            "mcpServers": {
                "perplexity-mcp": {                    
                    "command": "uvx",
                    "args": [
                        "perplexity-mcp"
                    ],
                    "env": {
                        "PERPLEXITY_API_KEY": utils.perplexity_key,
                        "PERPLEXITY_MODEL": "sonar"
                    }
                }
            }
        }

    elif mcp_type == "text_editor":
        return {
            "mcpServers": {
                "textEditor": {
                    "command": "npx",
                    "args": ["-y", "mcp-server-text-editor"]
                }
            }
        }
    
    elif mcp_type == "context7":
        return {
            "mcpServers": {
                "context7": {
                    "command": "npx",
                    "args": ["-y", "@upstash/context7-mcp@latest"]
                }
            }
        }
    
    elif mcp_type == "pubmed":
        return {
            "mcpServers": {
                "pubmed": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_pubmed.py"  
                    ]
                }
            }
        }
    
    elif mcp_type == "chembl":
        return {
            "mcpServers": {
                "chembl": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_chembl.py"
                    ]
                }
            }
        }
    
    elif mcp_type == "clinicaltrial":
        return {
            "mcpServers": {
                "clinicaltrial": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_clinicaltrial.py"
                    ]
                }
            }
        }
    
    elif mcp_type == "arxiv-manual":
        return {
            "mcpServers": {
                "arxiv-manual": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_arxiv.py"
                    ]
                }
            }
        }
    
    elif mcp_type == "tavily-search":
        return {
            "mcpServers": {
                "tavily-search": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_tavily.py"
                    ]
                }
            }
        }
        
    elif mcp_type == "aws_knowledge_base":  # AWS Labs cloudwatch-logs MCP Server
        return {
            "mcpServers": {
                "aws_knowledge_base": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_kb.py"
                    ],
                    "env": {
                        "KB_INCLUSION_TAG_KEY": projectName
                    }
                }
            }
        }
    
    elif mcp_type == "aws-api-mcp-server": 
        return {
            "mcpServers": {
                "awslabs.aws-api-mcp-server": {
                    "command": "uvx",
                    "args": [
                        "awslabs.aws-api-mcp-server@latest"
                    ],
                    "env": {
                        "region": region,
                        "AWS_API_MCP_WORKING_DIR": workingDir
                    }
                }
            }
        }
    
    elif mcp_type == "aws-knowledge-mcp-server":
        return {
            "mcpServers": {
                "aws-knowledge-mcp-server": {
                    "command": "npx",
                    "args": [
                        "mcp-remote",
                        "https://knowledge-mcp.global.api.aws"
                    ]
                }
            }
        }
    
    elif mcp_type == "agentcore-browser":
        return {
            "mcpServers": {
                "agentcore-browser": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_browser.py"
                    ]
                }
            }
        }
    
    elif mcp_type == "long-term memory":
        return {
            "mcpServers": {
                "long-term memory": {
                    "command": "python",
                    "args": [f"{workingDir}/mcp_server_long_term_memory.py"]
                }
            }
        }
    
    elif mcp_type == "ccapi":
        return {
            "mcpServers": {
                "awslabs.ccapi-mcp-server": {
                    "command": "uvx",
                    "args": [
                        "awslabs.ccapi-mcp-server@latest"
                    ],
                    "env": {
                        "AWS_PROFILE": "default",
                        "DEFAULT_TAGS": "enabled",
                        "SECURITY_SCANNING": "enabled",
                        "FASTMCP_LOG_LEVEL": "ERROR"
                    },
                    "disabled": "false",
                    "autoApprove": "[]"
                }
            }
        }
        
    elif mcp_type == "short-term memory":
        return {
            "mcpServers": {
                "short-term memory": {
                    "command": "python",
                    "args": [f"{workingDir}/mcp_server_short_term_memory.py"]
                }
            }
        }    
    
    elif mcp_type == "notion":
        token = utils.get_notion_key()
        return {
            "mcpServers": {
                "notionApi": {
                    "command": "npx",
                    "args": ["-y", "@notionhq/notion-mcp-server"],
                    "env": {
                        "NOTION_TOKEN": token
                    }
                }
            }
        }    

    elif mcp_type == "github":
        secret_name = f"github-personal-access-token"
        secret_value = json.loads(get_secret_value(secret_name))
        GITHUB_PERSONAL_ACCESS_TOKEN = secret_value['value']

        if not GITHUB_PERSONAL_ACCESS_TOKEN:
            logger.info(f"No github personal access token found in secret manager")
            return {}
        else:
            return {
                "mcpServers": {
                    "github": {
                    "command": "docker",
                    "args": [
                        "run",
                        "-i",
                        "--rm",
                        "-e",
                        f"GITHUB_PERSONAL_ACCESS_TOKEN={GITHUB_PERSONAL_ACCESS_TOKEN}",
                        "ghcr.io/github/github-mcp-server"
                    ]
                    }
                }
            }
            
    elif mcp_type == "outlook":
        secret_name = f"outlook-mcp-user-email"
        secret_value = json.loads(get_secret_value(secret_name))
        OUTLOOK_MCP_USER_EMAIL = secret_value['value']
        if not OUTLOOK_MCP_USER_EMAIL:
            logger.info(f"No outlook user email found in secret manager")
            return {}
        else:
            logger.info(f"outlook user email: {OUTLOOK_MCP_USER_EMAIL}")
            return {
                "mcpServers": {
                    "outlook": {
                        "command": f"{workingDir}/outlook-mac/outlook_mcp.py",
                        "env":{
                            "USER_EMAIL":OUTLOOK_MCP_USER_EMAIL,
                            "OUTLOOK_MCP_LOG_LEVEL":"INFO"
                        }
                    }
                }
            }
    
    elif mcp_type == "trade_info":
        return {
            "mcpServers": {
                "trade_info": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_trade_info.py"
                    ]
                }
            }
        }
        
    elif mcp_type == "사용자 설정":
        return mcp_user_config

def load_selected_config(mcp_servers: dict):
    logger.info(f"mcp_servers: {mcp_servers}")
    
    loaded_config = {}
    for server in mcp_servers:
        config = load_config(server)        
        if config:
            loaded_config.update(config["mcpServers"])
    return {
        "mcpServers": loaded_config
    }
