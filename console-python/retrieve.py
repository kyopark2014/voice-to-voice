import json
import boto3
import traceback
import logging
import sys
import os

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("mcp-rag")

script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, "config.json")

def load_config():
    config = None
    try:
        with open("application/config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
            # logger.info(f"config: {config}")
    except Exception as e: 
        logger.error(f"Error loading config: {e}")
        config = {}
        config['projectName'] = "claude-agent"
        session = boto3.Session()
        bedrock_region = session.region_name

        sts = boto3.client("sts")
        response = sts.get_caller_identity()        
        config['region'] = bedrock_region
        accountId = response["Account"]
        config['accountId'] = accountId
        config['knowledge_base_id'] = "" # add knowledge_base_id manually
        
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    return config

config = load_config()

bedrock_region = config.get("region", "us-west-2")
projectName = config.get("projectName", "speech-to-speech")
accountId = config.get("accountId", None)
if accountId is None:
    raise Exception ("No accountId")
region = config.get("region", "us-west-2")
logger.info(f"region: {region}")
knowledge_base_id = config.get("knowledge_base_id", None)
if knowledge_base_id is None:
    raise Exception ("No knowledge_base_id")

numberOfDocs = 3
model_name = "Claude 3.5 Haiku"
knowledge_base_name = projectName

bedrock_agent_runtime_client = boto3.client(
    "bedrock-agent-runtime", 
    region_name=bedrock_region
)

def retrieve(query):
    response = bedrock_agent_runtime_client.retrieve(
        retrievalQuery={"text": query},
        knowledgeBaseId=knowledge_base_id,
            retrievalConfiguration={
                "vectorSearchConfiguration": {"numberOfResults": numberOfDocs},
            },
        )
    
    # logger.info(f"response: {response}")
    retrieval_results = response.get("retrievalResults", [])
    # logger.info(f"retrieval_results: {retrieval_results}")

    json_docs = []
    for result in retrieval_results:
        text = url = name = None
        if "content" in result:
            content = result["content"]
            if "text" in content:
                text = content["text"]

        if "location" in result:
            location = result["location"]
            if "s3Location" in location:
                uri = location["s3Location"]["uri"] if location["s3Location"]["uri"] is not None else ""
                
                name = uri.split("/")[-1]
                # encoded_name = parse.quote(name)                
                # url = f"{path}/{doc_prefix}{encoded_name}"
                url = uri # TODO: add path and doc_prefix
                
            elif "webLocation" in location:
                url = location["webLocation"]["url"] if location["webLocation"]["url"] is not None else ""
                name = "WEB"

        json_docs.append({
            "contents": text,              
            "reference": {
                "url": url,                   
                "title": name,
                "from": "RAG"
            }
        })
    logger.info(f"json_docs: {json_docs}")

    return json.dumps(json_docs, ensure_ascii=False)