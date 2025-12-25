import traceback
import boto3
import os
import json
import re
import time
import info 
import utils
import translator
import asyncio

from io import BytesIO
from PIL import Image
from langchain_aws import ChatBedrock
from botocore.config import Config
from langchain_core.prompts import MessagesPlaceholder, ChatPromptTemplate
from langchain_core.documents import Document

# Simple memory class to replace ConversationBufferWindowMemory
class SimpleMemory:
    def __init__(self, k=5):
        self.k = k
        self.chat_memory = SimpleChatMemory()
    
    def load_memory_variables(self, inputs):
        return {"chat_history": self.chat_memory.messages[-self.k:] if len(self.chat_memory.messages) > self.k else self.chat_memory.messages}

class SimpleChatMemory:
    def __init__(self):
        self.messages = []
    
    def add_user_message(self, message):
        self.messages.append(HumanMessage(content=message))
    
    def add_ai_message(self, message):
        self.messages.append(AIMessage(content=message))
    
    def clear(self):
        self.messages = []
        
from tavily import TavilyClient  
from urllib import parse
from pydantic.v1 import BaseModel, Field
from langchain_core.output_parsers import StrOutputParser
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, AIMessageChunk
from langchain_mcp_adapters.client import MultiServerMCPClient

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from multiprocessing import Process, Pipe

import logging
import sys

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)

logger = logging.getLogger("chat")

reasoning_mode = 'Disable'
debug_messages = []  # List to store debug messages

config = utils.load_config()
logger.info(f"config: {config}")

bedrock_region = config["region"] if "region" in config else "us-west-2"
projectName = config["projectName"] if "projectName" in config else "speech-to-speech"
accountId = config["accountId"] if "accountId" in config else None
region = config["region"] if "region" in config else "us-west-2"
logger.info(f"region: {region}")

MSG_LENGTH = 100    

model_name = "Claude 3.5 Sonnet"
model_type = "claude"
models = info.get_model_info(model_name)
number_of_models = len(models)
model_id = models[0]["model_id"]
debug_mode = "Enable"
multi_region = "Disable"

reasoning_mode = 'Disable'
grading_mode = 'Disable'
agent_type = 'langgraph'
enable_memory = 'Disable'
user_id = agent_type # for testing

def update(modelName, debugMode):    
    global model_name, model_id, model_type, debug_mode
    global models, user_id, agent_type

    # load mcp.env    
    # mcp_env = utils.load_mcp_env()
    
    if model_name != modelName:
        model_name = modelName
        logger.info(f"model_name: {model_name}")
        
        models = info.get_model_info(model_name)
        # model_id = models[0]["model_id"]
        # model_type = models[0]["model_type"]
                                
    if debug_mode != debugMode:
        debug_mode = debugMode        
        logger.info(f"debug_mode: {debug_mode}")

    # update mcp.env    
    # utils.save_mcp_env(mcp_env)
    # logger.info(f"mcp.env updated: {mcp_env}")

def update_mcp_env():
    mcp_env = utils.load_mcp_env()
    
    mcp_env['multi_region'] = multi_region
    mcp_env['grading_mode'] = grading_mode
    user_id = agent_type
    mcp_env['user_id'] = user_id

    utils.save_mcp_env(mcp_env)
    logger.info(f"mcp.env updated: {mcp_env}")

map_chain = dict() 
checkpointers = dict() 
memorystores = dict() 

checkpointer = MemorySaver()
memorystore = InMemoryStore()
memory_chain = None  # Initialize memory_chain as global variable

def initiate():
    global memory_chain, checkpointer, memorystore, checkpointers, memorystores

    if user_id in map_chain:  
        logger.info(f"memory exist. reuse it!")
        memory_chain = map_chain[user_id]

        checkpointer = checkpointers[user_id]
        memorystore = memorystores[user_id]
    else: 
        logger.info(f"memory not exist. create new memory!")
        memory_chain = SimpleMemory(k=5)
        map_chain[user_id] = memory_chain

        checkpointer = MemorySaver()
        memorystore = InMemoryStore()

        checkpointers[user_id] = checkpointer
        memorystores[user_id] = memorystore

def clear_chat_history():
    global memory_chain
    # Initialize memory_chain if it doesn't exist
    if memory_chain is None:
        initiate()
    
    if memory_chain and hasattr(memory_chain, 'chat_memory'):
        memory_chain.chat_memory.clear()
    else:
        memory_chain = SimpleMemory(k=5)
    map_chain[user_id] = memory_chain

def save_chat_history(text, msg):
    global memory_chain
    # Initialize memory_chain if it doesn't exist
    if memory_chain is None:
        initiate()
    
    if memory_chain and hasattr(memory_chain, 'chat_memory'):
        memory_chain.chat_memory.add_user_message(text)
        if len(msg) > MSG_LENGTH:
            memory_chain.chat_memory.add_ai_message(msg[:MSG_LENGTH])                          
        else:
            memory_chain.chat_memory.add_ai_message(msg) 


selected_chat = 0
def get_chat(extended_thinking):
    global selected_chat, model_type

    logger.info(f"models: {models}")
    logger.info(f"selected_chat: {selected_chat}")
    
    profile = models[selected_chat]
    # print('profile: ', profile)
        
    bedrock_region =  profile['bedrock_region']
    modelId = profile['model_id']
    model_type = profile['model_type']
    if model_type == 'claude':
        maxOutputTokens = 4096 # 4k
    else:
        maxOutputTokens = 5120 # 5k
    number_of_models = len(models)

    logger.info(f"LLM: {selected_chat}, bedrock_region: {bedrock_region}, modelId: {modelId}, model_type: {model_type}")

    if profile['model_type'] == 'nova':
        STOP_SEQUENCE = '"\n\n<thinking>", "\n<thinking>", " <thinking>"'
    elif profile['model_type'] == 'claude':
        STOP_SEQUENCE = "\n\nHuman:" 
    elif profile['model_type'] == 'openai':
        STOP_SEQUENCE = "" 
                          
    # bedrock   
    boto3_bedrock = boto3.client(
        service_name='bedrock-runtime',
        region_name=bedrock_region,
        config=Config(
            retries = {
                'max_attempts': 30
            }
        )
    )

    if profile['model_type'] != 'openai' and extended_thinking=='Enable':
        maxReasoningOutputTokens=64000
        logger.info(f"extended_thinking: {extended_thinking}")
        thinking_budget = min(maxOutputTokens, maxReasoningOutputTokens-1000)

        parameters = {
            "max_tokens":maxReasoningOutputTokens,
            "temperature":1,            
            "thinking": {
                "type": "enabled",
                "budget_tokens": thinking_budget
            },
            "stop_sequences": [STOP_SEQUENCE]
        }
    elif profile['model_type'] != 'openai' and extended_thinking=='Disable':
        parameters = {
            "max_tokens":maxOutputTokens,     
            "temperature":0.1,
            "top_k":250,
            "stop_sequences": [STOP_SEQUENCE]
        }
    elif profile['model_type'] == 'openai':
        parameters = {
            "max_tokens":maxOutputTokens,     
            "temperature":0.1
        }

    chat = ChatBedrock(   # new chat model
        model_id=modelId,
        client=boto3_bedrock, 
        model_kwargs=parameters,
        region_name=bedrock_region
    )
    
    # Disable streaming for OpenAI models
    if profile['model_type'] == 'openai':
        chat.streaming = False
    
    if multi_region=='Enable':
        selected_chat = selected_chat + 1
        if selected_chat == number_of_models:
            selected_chat = 0
    else:
        selected_chat = 0

    return chat

def print_doc(i, doc):
    if len(doc.page_content)>=100:
        text = doc.page_content[:100]
    else:
        text = doc.page_content
            
    logger.info(f"{i}: {text}, metadata:{doc.metadata}")

def translate_text(text):
    chat = get_chat(extended_thinking=reasoning_mode)

    system = (
        "You are a helpful assistant that translates {input_language} to {output_language} in <article> tags. Put it in <result> tags."
    )
    human = "<article>{text}</article>"
    
    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
    # print('prompt: ', prompt)
    
    if isKorean(text)==False :
        input_language = "English"
        output_language = "Korean"
    else:
        input_language = "Korean"
        output_language = "English"
                        
    chain = prompt | chat    
    try: 
        result = chain.invoke(
            {
                "input_language": input_language,
                "output_language": output_language,
                "text": text,
            }
        )
        msg = result.content
        logger.info(f"translated text: {msg}")
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")      
        raise Exception ("Not able to request to LLM")

    return msg[msg.find('<result>')+8:len(msg)-9] # remove <result> tag
    
reference_docs = []

# api key to get weather information in agent
secretsmanager = boto3.client(
    service_name='secretsmanager',
    region_name=bedrock_region,
)

# api key for weather
def get_weather_api_key():
    weather_api_key = ""
    try:
        get_weather_api_secret = secretsmanager.get_secret_value(
            SecretId=f"openweathermap-{projectName}"
        )
        #print('get_weather_api_secret: ', get_weather_api_secret)
        secret = json.loads(get_weather_api_secret['SecretString'])
        #print('secret: ', secret)
        weather_api_key = secret['weather_api_key']

    except Exception as e:
        logger.info(f"weather api key is required: {e}")
        pass

    return weather_api_key

def get_langsmith_api_key():
    # api key to use LangSmith
    langsmith_api_key = langchain_project = ""
    try:
        get_langsmith_api_secret = secretsmanager.get_secret_value(
            SecretId=f"langsmithapikey-{projectName}"
        )
        #print('get_langsmith_api_secret: ', get_langsmith_api_secret)
        secret = json.loads(get_langsmith_api_secret['SecretString'])
        #print('secret: ', secret)
        langsmith_api_key = secret['langsmith_api_key']
        langchain_project = secret['langchain_project']
    except Exception as e:
        logger.info(f"langsmith api key is required: {e}")
        pass

    return langsmith_api_key, langchain_project

def tavily_search(query, k):
    docs = []    
    try:
        tavily_client = TavilyClient(api_key=utils.tavily_key)
        response = tavily_client.search(query, max_results=k)
        # print('tavily response: ', response)
            
        for r in response["results"]:
            name = r.get("title")
            if name is None:
                name = 'WWW'
            
            docs.append(
                Document(
                    page_content=r.get("content"),
                    metadata={
                        'name': name,
                        'url': r.get("url"),
                        'from': 'tavily'
                    },
                )
            )                   
    except Exception as e:
        logger.info(f"Exception: {e}")

    return docs

def isKorean(text):
    # check korean
    pattern_hangul = re.compile('[\u3131-\u3163\uac00-\ud7a3]+')
    word_kor = pattern_hangul.search(str(text))
    # print('word_kor: ', word_kor)

    if word_kor and word_kor != 'None':
        # logger.info(f"Korean: {word_kor}")
        return True
    else:
        # logger.info(f"Not Korean:: {word_kor}")
        return False
    
def traslation(chat, text, input_language, output_language):
    system = (
        "You are a helpful assistant that translates {input_language} to {output_language} in <article> tags." 
        "Put it in <result> tags."
    )
    human = "<article>{text}</article>"
    
    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
    # print('prompt: ', prompt)
    
    chain = prompt | chat    
    try: 
        result = chain.invoke(
            {
                "input_language": input_language,
                "output_language": output_language,
                "text": text,
            }
        )
        
        msg = result.content
        # print('translated text: ', msg)
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")     
        raise Exception ("Not able to request to LLM")

    return msg[msg.find('<result>')+8:len(msg)-9] # remove <result> tag

def print_doc(i, doc):
    if len(doc.page_content)>=100:
        text = doc.page_content[:100]
    else:
        text = doc.page_content
            
    logger.info(f"{i}: {text}, metadata:{doc.metadata}")

def show_extended_thinking(st, result):
    # logger.info(f"result: {result}")
    if "thinking" in result.response_metadata:
        if "text" in result.response_metadata["thinking"]:
            thinking = result.response_metadata["thinking"]["text"]
            st.info(thinking)

####################### LangChain #######################
# General Conversation
#########################################################
def general_conversation(query, st):
    global memory_chain
    initiate()  # Initialize memory_chain
    llm = get_chat(extended_thinking=reasoning_mode)

    system = (
        "당신의 이름은 서연이고, 질문에 대해 친절하게 답변하는 사려깊은 인공지능 도우미입니다."
        "상황에 맞는 구체적인 세부 정보를 충분히 제공합니다." 
        "모르는 질문을 받으면 솔직히 모른다고 말합니다."
    )
    
    human = "Question: {input}"
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system), 
        MessagesPlaceholder(variable_name="history"), 
        ("human", human)
    ])
                
    if memory_chain and hasattr(memory_chain, 'load_memory_variables'):
        history = memory_chain.load_memory_variables({})["chat_history"]
    else:
        history = []

    if model_type == 'openai':
        # For OpenAI models, use invoke instead of stream to avoid parsing issues
        chain = prompt | llm
        try: 
            result = chain.invoke(
                {
                    "history": history,
                    "input": query,
                }
            )  
            logger.info(f"result: {result}")
            
            content = result.content
            if '<reasoning>' in content and '</reasoning>' in content:
                # Extract reasoning content and show it in st.info
                reasoning_start = content.find('<reasoning>') + 11  # Length of '<reasoning>'
                reasoning_end = content.find('</reasoning>')
                reasoning_content = content[reasoning_start:reasoning_end]
                st.info(f"{reasoning_content}")
                
                # Extract main content after reasoning tag
                content = content.split('</reasoning>', 1)[1] if '</reasoning>' in content else content
            stream = iter([content])
            
        except Exception:
            err_msg = traceback.format_exc()
            logger.info(f"error message: {err_msg}")      
            raise Exception ("Not able to request to LLM: "+err_msg)
    else:
        # For other models, use streaming
        chain = prompt | llm | StrOutputParser()
        try: 
            stream = chain.stream(
                {
                    "history": history,
                    "input": query,
                }
            )  
            logger.info(f"stream: {stream}")
                
        except Exception:
            err_msg = traceback.format_exc()
            logger.info(f"error message: {err_msg}")      
            raise Exception ("Not able to request to LLM: "+err_msg)
        
    return stream

####################### Bedrock Agent #######################
# RAG using Lambda
############################################################# 
def get_rag_prompt(text):
    # print("###### get_rag_prompt ######")
    llm = get_chat(extended_thinking=reasoning_mode)
    # print('model_type: ', model_type)
    
    if model_type == "nova":
        if isKorean(text)==True:
            system = (
                "당신의 이름은 서연이고, 질문에 대해 친절하게 답변하는 사려깊은 인공지능 도우미입니다."
                "다음의 Reference texts을 이용하여 user의 질문에 답변합니다."
                "모르는 질문을 받으면 솔직히 모른다고 말합니다."
                "답변의 이유를 풀어서 명확하게 설명합니다."
            )
        else: 
            system = (
                "You will be acting as a thoughtful advisor."
                "Provide a concise answer to the question at the end using reference texts." 
                "If you don't know the answer, just say that you don't know, don't try to make up an answer."
                "You will only answer in text format, using markdown format is not allowed."
            )    
    
        human = (
            "Question: {question}"

            "Reference texts: "
            "{context}"
        ) 
        
    # elif model_type == "claude":
    else: 
        if isKorean(text)==True:
            system = (
                "당신의 이름은 서연이고, 질문에 대해 친절하게 답변하는 사려깊은 인공지능 도우미입니다."
                "다음의 <context> tag안의 참고자료를 이용하여 상황에 맞는 구체적인 세부 정보를 충분히 제공합니다." 
                "모르는 질문을 받으면 솔직히 모른다고 말합니다."
                "답변의 이유를 풀어서 명확하게 설명합니다."
                "결과는 <result> tag를 붙여주세요."
            )
        else: 
            system = (
                "You will be acting as a thoughtful advisor."
                "Here is pieces of context, contained in <context> tags." 
                "If you don't know the answer, just say that you don't know, don't try to make up an answer."
                "You will only answer in text format, using markdown format is not allowed."
                "Put it in <result> tags."
            )    

        human = (
            "<question>"
            "{question}"
            "</question>"

            "<context>"
            "{context}"
            "</context>"
        )

    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
    # print('prompt: ', prompt)
    
    rag_chain = prompt | llm

    return rag_chain
 
def retrieve_knowledge_base(query):
    lambda_client = boto3.client(
        service_name='lambda',
        region_name=bedrock_region,
    )

    functionName = f"knowledge-base-for-{projectName}"
    logger.info(f"functionName: {functionName}")

    try:
        payload = {
            'function': 'search_rag',
            'knowledge_base_name': knowledge_base_name,
            'keyword': query,
            'top_k': numberOfDocs,
            'grading': grading_mode,
            'model_name': model_name,
            'multi_region': multi_region
        }
        logger.info(f"payload: {payload}")

        output = lambda_client.invoke(
            FunctionName=functionName,
            Payload=json.dumps(payload),
        )
        payload = json.load(output['Payload'])
        logger.info(f"response: {payload['response']}")
        
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")       

    return payload['response']

def get_reference_docs(docs):    
    reference_docs = []
    for doc in docs:
        reference = doc.get("reference")
        reference_docs.append(
            Document(
                page_content=doc.get("contents"),
                metadata={
                    'name': reference.get("title"),
                    'url': reference.get("url"),
                    'from': reference.get("from")
                },
            )
        )     
    return reference_docs

def run_rag_with_knowledge_base(query, st):
    global reference_docs, contentList
    reference_docs = []
    contentList = []

    # retrieve
    if debug_mode == "Enable":
        st.info(f"RAG 검색을 수행합니다. 검색어: {query}")  

    relevant_context = retrieve_knowledge_base(query)    
    logger.info(f"relevant_context: {relevant_context}")
    
    # change format to document
    reference_docs = get_reference_docs(json.loads(relevant_context))
    st.info(f"{len(reference_docs)}개의 관련된 문서를 얻었습니다.")

    rag_chain = get_rag_prompt(query)
                       
    msg = ""    
    try: 
        result = rag_chain.invoke(
            {
                "question": query,
                "context": relevant_context                
            }
        )
        logger.info(f"result: {result}")

        msg = result.content        
        if msg.find('<result>')!=-1:
            msg = msg[msg.find('<result>')+8:msg.find('</result>')]        
               
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")                    
        raise Exception ("Not able to request to LLM")
    
    if reference_docs:
        logger.info(f"reference_docs: {reference_docs}")
        ref = "\n\n### Reference\n"
        for i, reference in enumerate(reference_docs):
            ref += f"{i+1}. [{reference.metadata['name']}]({reference.metadata['url']}), {reference.page_content[:100]}...\n"    
        logger.info(f"ref: {ref}")
        msg += ref
    
    return msg, reference_docs
   
def extract_thinking_tag(response, st):
    if response.find('<thinking>') != -1:
        status = response[response.find('<thinking>')+10:response.find('</thinking>')]
        logger.info(f"gent_thinking: {status}")
        
        if debug_mode=="Enable":
            st.info(status)

        if response.find('<thinking>') == 0:
            msg = response[response.find('</thinking>')+12:]
        else:
            msg = response[:response.find('<thinking>')]
        logger.info(f"msg: {msg}")
    else:
        msg = response

    return msg

streaming_index = None
index = 0
def add_notification(containers, message):
    global index

    if index == streaming_index:
        index += 1

    if containers is not None:
        containers['notification'][index].info(message)
    index += 1

def update_streaming_result(containers, message, type):
    global streaming_index
    streaming_index = index

    if containers is not None:
        if type == "markdown":
            containers['notification'][streaming_index].markdown(message)
        elif type == "info":
            containers['notification'][streaming_index].info(message)

tool_info_list = dict()
tool_input_list = dict()
tool_name_list = dict()

sharing_url = config["sharing_url"] if "sharing_url" in config else None
s3_prefix = "docs"
capture_prefix = "captures"

def get_tool_info(tool_name, tool_content):
    tool_references = []    
    urls = []
    content = ""

    # tavily
    if isinstance(tool_content, str) and "Title:" in tool_content and "URL:" in tool_content and "Content:" in tool_content:
        logger.info("Tavily parsing...")
        items = tool_content.split("\n\n")
        for i, item in enumerate(items):
            # logger.info(f"item[{i}]: {item}")
            if "Title:" in item and "URL:" in item and "Content:" in item:
                try:
                    title_part = item.split("Title:")[1].split("URL:")[0].strip()
                    url_part = item.split("URL:")[1].split("Content:")[0].strip()
                    content_part = item.split("Content:")[1].strip().replace("\n", "")
                    
                    logger.info(f"title_part: {title_part}")
                    logger.info(f"url_part: {url_part}")
                    logger.info(f"content_part: {content_part}")

                    content += f"{content_part}\n\n"
                    
                    tool_references.append({
                        "url": url_part,
                        "title": title_part,
                        "content": content_part[:100] + "..." if len(content_part) > 100 else content_part
                    })
                except Exception as e:
                    logger.info(f"Parsing error: {str(e)}")
                    continue                

    # OpenSearch
    elif tool_name == "SearchIndexTool": 
        if ":" in tool_content:
            extracted_json_data = tool_content.split(":", 1)[1].strip()
            try:
                json_data = json.loads(extracted_json_data)
                # logger.info(f"extracted_json_data: {extracted_json_data[:200]}")
            except json.JSONDecodeError:
                logger.info("JSON parsing error")
                json_data = {}
        else:
            json_data = {}
        
        if "hits" in json_data:
            hits = json_data["hits"]["hits"]
            if hits:
                logger.info(f"hits[0]: {hits[0]}")

            for hit in hits:
                text = hit["_source"]["text"]
                metadata = hit["_source"]["metadata"]
                
                content += f"{text}\n\n"

                filename = metadata["name"].split("/")[-1]
                # logger.info(f"filename: {filename}")
                
                content_part = text.replace("\n", "")
                tool_references.append({
                    "url": metadata["url"], 
                    "title": filename,
                    "content": content_part[:100] + "..." if len(content_part) > 100 else content_part
                })
                
        logger.info(f"content: {content}")
        
    # Knowledge Base
    elif tool_name == "QueryKnowledgeBases": 
        try:
            # Handle case where tool_content contains multiple JSON objects
            if tool_content.strip().startswith('{'):
                # Parse each JSON object individually
                json_objects = []
                current_pos = 0
                brace_count = 0
                start_pos = -1
                
                for i, char in enumerate(tool_content):
                    if char == '{':
                        if brace_count == 0:
                            start_pos = i
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0 and start_pos != -1:
                            try:
                                json_obj = json.loads(tool_content[start_pos:i+1])
                                # logger.info(f"json_obj: {json_obj}")
                                json_objects.append(json_obj)
                            except json.JSONDecodeError:
                                logger.info(f"JSON parsing error: {tool_content[start_pos:i+1][:100]}")
                            start_pos = -1
                
                json_data = json_objects
            else:
                # Try original method
                json_data = json.loads(tool_content)                
            # logger.info(f"json_data: {json_data}")

            # Build content
            if isinstance(json_data, list):
                for item in json_data:
                    if isinstance(item, dict) and "content" in item:
                        content_text = item["content"].get("text", "")
                        content += content_text + "\n\n"

                        uri = "" 
                        if "location" in item:
                            if "s3Location" in item["location"]:
                                uri = item["location"]["s3Location"]["uri"]
                                # logger.info(f"uri (list): {uri}")
                                ext = uri.split(".")[-1]

                                # if ext is an image 
                                url = sharing_url + "/" + s3_prefix + "/" + uri.split("/")[-1]
                                if ext in ["jpg", "jpeg", "png", "gif", "bmp", "tiff", "ico", "webp"]:
                                    url = sharing_url + "/" + capture_prefix + "/" + uri.split("/")[-1]
                                logger.info(f"url: {url}")
                                
                                tool_references.append({
                                    "url": url, 
                                    "title": uri.split("/")[-1],
                                    "content": content_text[:100] + "..." if len(content_text) > 100 else content_text
                                })          
                
        except json.JSONDecodeError as e:
            logger.info(f"JSON parsing error: {e}")
            json_data = {}
            content = tool_content  # Use original content if parsing fails

        logger.info(f"content: {content}")
        logger.info(f"tool_references: {tool_references}")

    # aws document
    elif tool_name == "search_documentation":
        try:
            json_data = json.loads(tool_content)
            for item in json_data:
                logger.info(f"item: {item}")
                
                if isinstance(item, str):
                    try:
                        item = json.loads(item)
                    except json.JSONDecodeError:
                        logger.info(f"Failed to parse item as JSON: {item}")
                        continue
                
                if isinstance(item, dict) and 'url' in item and 'title' in item:
                    url = item['url']
                    title = item['title']
                    content_text = item['context'][:100] + "..." if len(item['context']) > 100 else item['context']
                    tool_references.append({
                        "url": url,
                        "title": title,
                        "content": content_text
                    })
                else:
                    logger.info(f"Invalid item format: {item}")
                    
        except json.JSONDecodeError:
            logger.info(f"JSON parsing error: {tool_content}")
            pass

        logger.info(f"content: {content}")
        logger.info(f"tool_references: {tool_references}")
            
    # ArXiv
    elif tool_name == "search_papers" and "papers" in tool_content:
        try:
            json_data = json.loads(tool_content)

            papers = json_data['papers']
            for paper in papers:
                url = paper['url']
                title = paper['title']
                abstract = paper['abstract'].replace("\n", "")
                content_text = abstract[:100] + "..." if len(abstract) > 100 else abstract
                content += f"{content_text}\n\n"
                logger.info(f"url: {url}, title: {title}, content: {content_text}")

                tool_references.append({
                    "url": url,
                    "title": title,
                    "content": content_text
                })
        except json.JSONDecodeError:
            logger.info(f"JSON parsing error: {tool_content}")
            pass

        logger.info(f"content: {content}")
        logger.info(f"tool_references: {tool_references}")

    # aws-knowledge
    elif tool_name == "aws___read_documentation":
        logger.info(f"#### {tool_name} ####")
        if isinstance(tool_content, dict):
            json_data = tool_content
        elif isinstance(tool_content, list):
            json_data = tool_content
        else:
            json_data = json.loads(tool_content)
        
        logger.info(f"json_data: {json_data}")

        if "content" in json_data:
            content = json_data["content"]
            logger.info(f"content: {content}")
            if "result" in content:
                result = content["result"]
                logger.info(f"result: {result}")
                
        payload = {}
        if "response" in json_data:
            payload = json_data["response"]["payload"]
        elif "content" in json_data:
            payload = json_data

        if "content" in payload:
            payload_content = payload["content"]
            if "result" in payload_content:
                result = payload_content["result"]
                logger.info(f"result: {result}")
                if isinstance(result, str) and "AWS Documentation from" in result:
                    logger.info(f"Processing AWS Documentation format: {result}")
                    try:
                        # Extract URL from "AWS Documentation from https://..."
                        url_start = result.find("https://")
                        if url_start != -1:
                            # Find the colon after the URL (not inside the URL)
                            url_end = result.find(":", url_start)
                            if url_end != -1:
                                # Check if the colon is part of the URL or the separator
                                url_part = result[url_start:url_end]
                                # If the colon is immediately after the URL, use it as separator
                                if result[url_end:url_end+2] == ":\n":
                                    url = url_part
                                    content_start = url_end + 2  # Skip the colon and newline
                                else:
                                    # Try to find the actual URL end by looking for space or newline
                                    space_pos = result.find(" ", url_start)
                                    newline_pos = result.find("\n", url_start)
                                    if space_pos != -1 and newline_pos != -1:
                                        url_end = min(space_pos, newline_pos)
                                    elif space_pos != -1:
                                        url_end = space_pos
                                    elif newline_pos != -1:
                                        url_end = newline_pos
                                    else:
                                        url_end = len(result)
                                    
                                    url = result[url_start:url_end]
                                    content_start = url_end + 1
                                
                                # Remove trailing colon from URL if present
                                if url.endswith(":"):
                                    url = url[:-1]
                                
                                # Extract content after the URL
                                if content_start < len(result):
                                    content_text = result[content_start:].strip()
                                    # Truncate content for display
                                    display_content = content_text[:100] + "..." if len(content_text) > 100 else content_text
                                    display_content = display_content.replace("\n", "")
                                    
                                    tool_references.append({
                                        "url": url,
                                        "title": "AWS Documentation",
                                        "content": display_content
                                    })
                                    content += content_text + "\n\n"
                                    logger.info(f"Extracted URL: {url}")
                                    logger.info(f"Extracted content length: {len(content_text)}")
                    except Exception as e:
                        logger.error(f"Error parsing AWS Documentation format: {e}")
        logger.info(f"content: {content}")
        logger.info(f"tool_references: {tool_references}")

    else:        
        try:
            if isinstance(tool_content, dict):
                json_data = tool_content
            elif isinstance(tool_content, list):
                json_data = tool_content
            else:
                json_data = json.loads(tool_content)
            
            logger.info(f"json_data: {json_data}")
            if isinstance(json_data, dict) and "path" in json_data:  # path
                path = json_data["path"]
                if isinstance(path, list):
                    for url in path:
                        urls.append(url)
                else:
                    urls.append(path)            

            if isinstance(json_data, dict):
                for item in json_data:
                    logger.info(f"item: {item}")
                    if "reference" in item and "contents" in item:
                        url = item["reference"]["url"]
                        title = item["reference"]["title"]
                        content_text = item["contents"][:100] + "..." if len(item["contents"]) > 100 else item["contents"]
                        tool_references.append({
                            "url": url,
                            "title": title,
                            "content": content_text
                        })
            else:
                logger.info(f"json_data is not a dict: {json_data}")

                for item in json_data:
                    if "reference" in item and "contents" in item:
                        url = item["reference"]["url"]
                        title = item["reference"]["title"]
                        content_text = item["contents"][:100] + "..." if len(item["contents"]) > 100 else item["contents"]
                        tool_references.append({
                            "url": url,
                            "title": title,
                            "content": content_text
                        })
                
            logger.info(f"tool_references: {tool_references}")

        except json.JSONDecodeError:
            pass

    return content, urls, tool_references


# Global variables to track event loop and background task
_translator_loop = None
_background_task = None

def get_or_create_loop():
    """Get existing event loop or create a new one."""
    global _translator_loop
    
    if _translator_loop is None or _translator_loop.is_closed():
        # Create new event loop
        _translator_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_translator_loop)
        logger.info(f"Created new event loop: {_translator_loop}")
        # Start loop in background thread
        import threading
        def run_loop():
            _translator_loop.run_forever()
        thread = threading.Thread(target=run_loop, daemon=True)
        thread.start()
        logger.info("Started event loop in background thread")
    else:
        logger.info(f"Using existing event loop: {_translator_loop}")
    
    return _translator_loop

async def _run_translator_async(text, language):
    """Async implementation of run_translator."""
    global _background_task
    
    # Enable Streamlit audio mode for Docker/Streamlit environment
    translator.use_streamlit_audio = True
    
    logger.info(f"is_active: {translator.is_active}")    
    if not translator.is_active:        
        logger.info(f"Starting translator as background task...")
        # Use the persistent loop created by run_translator
        loop = get_or_create_loop()
        _background_task = loop.create_task(translator.translate(language))
        logger.info(f"Created translate task: {_background_task}")
        await asyncio.sleep(0.5)
    
    if _background_task and not _background_task.done():
        await asyncio.sleep(0.1)

    # Send text using send_text_input with provided text
    logger.info(f"Sending text: {text}")
    await translator.send_text_input(text=text)

    # Wait for response from output_queue
    logger.info(f"Waiting for response from output_queue")
    translated_text = ""
    try:
        # Wait for response with timeout (30 seconds)
        response_chunks = []
        timeout = 30.0  # seconds
        start_time = time.time()
        
        consecutive_timeouts = 0
        max_consecutive_timeouts = 3  # Wait for 3 consecutive timeouts before giving up
        
        while True:
            try:
                # Wait for chunk with timeout
                remaining_time = timeout - (time.time() - start_time)
                if remaining_time <= 0:
                    logger.info("Timeout waiting for translation response")
                    break
                    
                chunk = await asyncio.wait_for(
                    translator.output_queue.get(),
                    timeout=min(remaining_time, 1.5)  # Check every 1.5 seconds
                )
                
                # Reset timeout counter when we receive a chunk
                consecutive_timeouts = 0
                
                response_chunks.append(chunk)
                logger.info(f"Received translation chunk: {chunk}")
                        
            except asyncio.TimeoutError:
                consecutive_timeouts += 1
                logger.debug(f"Timeout waiting for chunk (consecutive: {consecutive_timeouts})")
                
                # Check if there are any chunks in the queue that arrived during the timeout
                while not translator.output_queue.empty():
                    try:
                        chunk = translator.output_queue.get_nowait()
                        consecutive_timeouts = 0  # Reset counter if we get a chunk
                        response_chunks.append(chunk)
                        logger.info(f"Received translation chunk after timeout check: {chunk}")
                    except asyncio.QueueEmpty:
                        break
                
                # If we have chunks and had multiple consecutive timeouts, assume response is complete
                if response_chunks and consecutive_timeouts >= max_consecutive_timeouts:
                    logger.info(f"Received {consecutive_timeouts} consecutive timeouts, assuming translation complete")
                    break
                
                # If no chunks yet, continue waiting
                if not response_chunks:
                    remaining_time = timeout - (time.time() - start_time)
                    if remaining_time <= 0:
                        logger.info("Overall timeout waiting for translation response")
                        break
                    continue
        
        translated_text = "".join(response_chunks) if response_chunks else text
        logger.info(f"Final translated text: {translated_text}")
        
        # Wait a bit more for audio to be collected
        await asyncio.sleep(1.0)
        
    except Exception as e:
        error_msg = str(e) if e else "Unknown error"
        logger.info(f"Error reading from output_queue: {error_msg}")
        if hasattr(e, '__traceback__'):
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
    
    return translated_text

def run_translator(text, language):
    """Synchronous wrapper for run_translator that uses persistent event loop."""
    # Get or create persistent event loop
    loop = get_or_create_loop()
    
    # Run the async function in the persistent loop
    if loop.is_running():
        # If loop is already running, schedule the coroutine
        future = asyncio.run_coroutine_threadsafe(_run_translator_async(text, language), loop)
        return future.result(timeout=35.0)  # Wait up to 35 seconds
    else:
        # If loop is not running, run it
        return loop.run_until_complete(_run_translator_async(text, language))

def pronunciate_to_korean(context, language):
    system = (
        f"당신은 여행자입니다. 현지인과 얘기하기 위하여 <context> tag안의 {language}를 읽고 싶습니다. <example>의 예시를 참고하세요."
        f"<context> tag안의 문장을 원문 그대로 읽을때에 한글로 발음기호를 표시하세요."
        "<example> 私は駅を探しています。 => 와타시 와 에키 오 사가시테 이마스.</example>"
        "발음 결과는 <result> tag를 붙여주세요."
    )
    human = "<context>{context}</context>"
    
    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
    # print('prompt: ', prompt)
    
    chat = get_chat(extended_thinking=reasoning_mode)
    chain = prompt | chat    
    try: 
        result = chain.invoke(
            {
                "context": context,
            }
        )
        
        msg = result.content
        # print('translated text: ', msg)
    except Exception:
        err_msg = traceback.format_exc()
        logger.info(f"error message: {err_msg}")     
        raise Exception ("Not able to request to LLM")

    return msg[msg.find('<result>')+8:len(msg)-9] # remove <result> tag
