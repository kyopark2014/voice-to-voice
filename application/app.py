import streamlit as st 
import chat
import json
import mcp_config 
import logging
import sys
import asyncio
import uuid
import translator

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("streamlit")

username = "sonic"

# title
st.set_page_config(page_title='S2S', page_icon=None, layout="centered", initial_sidebar_state="auto", menu_items=None)

mode_descriptions = {
    "일상적인 대화": [
        "대화이력을 바탕으로 챗봇과 일상의 대화를 편안히 즐길수 있습니다."
    ],
    "RAG": [
        "Bedrock Knowledge Base를 이용해 구현한 RAG로 필요한 정보를 검색합니다."
    ],
    "MCP agent": [
        "MCP를 활용한 agent를 이용합니다. 왼쪽 메뉴에서 필요한 MCP를 선택하세요."
    ],
    "Translator (Text2Speech)": [
        "Nova Sonic를 이용해 실시간 번역을 구현합니다."
    ],
    "Translator (Speech2Text)": [
        "Nova Sonic를 이용해 실시간 번역을 구현합니다."
    ]
}

def update_seed_image_url(url):
    with open("image_generator_config.json", "w", encoding="utf-8") as f:
        config = {"seed_image": url}
        json.dump(config, f, ensure_ascii=False, indent=4)

with st.sidebar:
    st.title("🔮 Menu")
    
    st.markdown(
        "Amazon Bedrock을 이용해 다양한 형태의 대화를 구현합니다." 
        "여기에서는 Sonic Model를 다양한 Agent를 이용할 수 있습니다." 
        "상세한 코드는 [Github](https://github.com/kyopark2014/speech-to-speech)을 참조하세요."
    )

    st.subheader("🐱 대화 형태")
    
    # radio selection
    mode = st.radio(
        label="원하는 대화 형태를 선택하세요. ",options=["일상적인 대화", "RAG", "MCP agent", "Translator (Text2Speech)", "Translator (Speech2Text)"], index=3
    )   
    st.info(mode_descriptions[mode][0])
    
    # mcp selection    
    if mode=='MCP agent':
        # MCP Config JSON input
        st.subheader("⚙️ MCP Config")

        # Change radio to checkbox
        mcp_options = [
            "basic", "short-term memory", "long-term memory", "outlook", "trade_info",
            "knowledge base", "kb-retriever (local)", "kb-retriever (runtime)", "agentcore gateway", 
            "use-aws (local)", "use-aws (runtime)", 
            "aws-knowledge", "aws-api", "aws document", "aws cost", "aws cli", "aws ccapi",
            "aws cloudwatch", "aws storage", "image generation", "aws diagram",
            "repl coder","agentcore coder", 
            "tavily-search", "tavily", "perplexity", "ArXiv", "wikipedia", "notion",
            "filesystem", "terminal", "text editor", "github",
            "context7", "puppeteer", "agentcore-browser", "playwright", "firecrawl", "obsidian", "airbnb", 
            "pubmed", "chembl", "clinicaltrial", "arxiv-manual", "사용자 설정"
        ]
        mcp_selections = {}
        default_selections = ["basic", "use-aws (local)", "tavily-search", "filesystem", "terminal"]
                
        with st.expander("MCP 옵션 선택", expanded=True):            
            for option in mcp_options:
                default_value = option in default_selections
                mcp_selections[option] = st.checkbox(option, key=f"mcp_{option}", value=default_value)
        
        if mcp_selections["사용자 설정"]:
            mcp = {}
            try:
                with open("user_defined_mcp.json", "r", encoding="utf-8") as f:
                    mcp = json.load(f)
                    logger.info(f"loaded user defined mcp: {mcp}")
            except FileNotFoundError:
                logger.info("user_defined_mcp.json not found")
                pass
            
            mcp_json_str = json.dumps(mcp, ensure_ascii=False, indent=2) if mcp else ""
            
            mcp_info = st.text_area(
                "MCP 설정을 JSON 형식으로 입력하세요",
                value=mcp_json_str,
                height=150
            )
            logger.info(f"mcp_info: {mcp_info}")

            if mcp_info:
                try:
                    mcp_config.mcp_user_config = json.loads(mcp_info)
                    logger.info(f"mcp_user_config: {mcp_config.mcp_user_config}")                    
                    st.success("JSON 설정이 성공적으로 로드되었습니다.")                    
                except json.JSONDecodeError as e:
                    st.error(f"JSON 파싱 오류: {str(e)}")
                    st.error("올바른 JSON 형식으로 입력해주세요.")
                    logger.error(f"JSON 파싱 오류: {str(e)}")
                    mcp_config.mcp_user_config = {}
            else:
                mcp_config.mcp_user_config = {}
                
            with open("user_defined_mcp.json", "w", encoding="utf-8") as f:
                json.dump(mcp_config.mcp_user_config, f, ensure_ascii=False, indent=4)
            logger.info("save to user_defined_mcp.json")
        
        mcp_servers = [server for server, is_selected in mcp_selections.items() if is_selected]
    else:
        mcp_servers = []

    if mode == 'Translator (Text2Speech)':
        translationMode = "text2speech"
    elif mode == 'Translator (Speech2Text)':
        translationMode = "speech2text"
    else:
        translationMode = ""

    if mode == 'Translator (Text2Speech)' or mode == 'Translator (Speech2Text)':
        # model selection box
        selectLanguage = st.selectbox(
            '🖊️ 번역할 언어를 선택하세요',
            (
                "Japanese",
                "French",
                "German",
                "Italian",
                "Spanish",
                "Portuguese",
                "Chinese",
                "English",
            ), index=0
        )
        language = selectLanguage if selectLanguage else "Japanese"
        logger.info(f"language: {language}")
        translator.is_active = False

    # model selection box
    modelName = st.selectbox(
        '🖊️ 사용 모델을 선택하세요',
        (
            "Claude 4.5 Haiku",
            'Claude 4.5 Sonnet',
            'Claude 4 Opus', 
            'Claude 4 Sonnet', 
            'Claude 3.7 Sonnet', 
            'Claude 3.5 Sonnet', 
            'Claude 3.0 Sonnet', 
            'Claude 3.5 Haiku', 
            'OpenAI OSS 120B',
            'OpenAI OSS 20B',
            "Nova 2 Sonic",            
            'Nova 2 Lite',
            "Nova Premier", 
            'Nova Pro', 
            'Nova Lite', 
            'Nova Micro',            
        ), index=0
    )

    # debug checkbox
    select_debugMode = st.checkbox('Debug Mode', value=True)
    debugMode = 'Enable' if select_debugMode else 'Disable'
    #logger.info('debugMode: ', debugMode)

    # Memory
    enable_memory = st.checkbox('Memory', value=True)
    memoryMode = 'Enable' if enable_memory else 'Disable'
    # logger.info(f"memory_mode: {memory_mode}")

    chat.update(modelName, debugMode, language, translationMode)    

    st.success(f"Connected to {modelName}", icon="💚")
    clear_button = st.button("대화 초기화", key="clear")
    # logger.info(f"clear_button: {clear_button}")

st.title('🔮 '+ mode)

if clear_button==True:    
    chat.map_chain = dict() 
    chat.checkpointers = dict() 
    chat.memorystores = dict() 
    chat.initiate()
    session_id = uuid.uuid4().hex

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.greetings = False

# Display chat messages from history on app rerun
def display_chat_messages() -> None:
    """logger.info message history
    @returns None
    """
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if "images" in message:                
                for url in message["images"]:
                    if url and url.strip():  # 빈 문자열이나 공백만 있는 경우 건너뛰기
                        logger.info(f"url: {url}")

                        file_name = url[url.rfind('/')+1:]
                        st.image(url, caption=file_name, use_container_width=True)
            
            # Display audio if available
            if "audio" in message and message["audio"]:
                audio_base64 = message["audio"]
                audio_data_url = f"data:audio/wav;base64,{audio_base64}"
                audio_html = f"""
                <audio controls style="width: 100%;">
                    <source src="{audio_data_url}" type="audio/wav">
                    Your browser does not support the audio element.
                </audio>
                """
                st.markdown(audio_html, unsafe_allow_html=True)
            
            # Display response (translated text) if available
            if "response" in message and message["response"]:
                st.markdown(f"**번역:** {message['response']}")
            
            st.markdown(message["content"])

display_chat_messages()

# Greet user
if not st.session_state.greetings:
    with st.chat_message("assistant"):
        intro = "아마존 베드락을 이용하여 주셔서 감사합니다. 편안한 대화를 즐기실 수 있습니다."
        st.markdown(intro)
        # Add assistant response to chat history
        st.session_state.messages.append({"role": "assistant", "content": intro})
        st.session_state.greetings = True

if clear_button or "messages" not in st.session_state:
    st.session_state.messages = []        
    uploaded_file = None
    
    st.session_state.greetings = False
    chat.clear_chat_history()
    st.rerun()    

# Always show the chat input
if prompt := st.chat_input("메시지를 입력하세요."):
    with st.chat_message("user"):  # display user message in chat message container
        st.markdown(prompt)

    st.session_state.messages.append({"role": "user", "content": prompt})  # add user message to chat history
    prompt = prompt.replace('"', "").replace("'", "")
    logger.info(f"prompt: {prompt}")

    with st.chat_message("assistant"):
        if mode == '일상적인 대화':
            stream = chat.general_conversation(prompt, st)            
            response = st.write_stream(stream)
            logger.info(f"response: {response}")
            st.session_state.messages.append({"role": "assistant", "content": response})

            chat.save_chat_history(prompt, response)

        elif mode == 'RAG':
            with st.status("running...", expanded=True, state="running") as status:
                response, reference_docs = chat.run_rag_with_knowledge_base(prompt, st)                           
                st.write(response)
                logger.info(f"response: {response}")

                st.session_state.messages.append({"role": "assistant", "content": response})

                chat.save_chat_history(prompt, response)
                    
        elif mode == 'MCP agent':            
            sessionState = ""

            with st.status("thinking...", expanded=True, state="running") as status:
                containers = {
                    "tools": st.empty(),
                    "status": st.empty(),
                    "notification": [st.empty() for _ in range(1000)]
                }

                response, image_url = asyncio.run(chat.run_langgraph_agent(
                    query=prompt, 
                    mcp_servers=mcp_servers, 
                    history_mode=history_mode, 
                    containers=containers))

                if debugMode == "Disable":
                    st.markdown(response)
        
            st.session_state.messages.append({
                "role": "assistant", 
                "content": response,
                "images": image_url if image_url else []
            })

            if image_url:
                for url in image_url:
                    if url and url.strip():  # 빈 문자열이나 공백만 있는 경우 건너뛰기
                        logger.info(f"url: {url}")
                        file_name = url[url.rfind('/')+1:]
                        st.image(url, caption=file_name, use_container_width=True)

            if memoryMode == "Enable":
                chat.save_to_memory(prompt, response)            

        elif mode == 'Translator (Text2Speech)':
            audio_container = st.empty()
            response = chat.run_text2speech(prompt)
            logger.info(f"response: {response}")

            # Get and display audio if available
            audio_wav_bytes = translator.get_audio_wav_bytes()
            audio_base64 = None
            if audio_wav_bytes:
                logger.info(f"Displaying audio in Streamlit: {len(audio_wav_bytes)} bytes")
                
                # Encode audio to base64 for HTML embedding
                import base64
                audio_base64 = base64.b64encode(audio_wav_bytes).decode('utf-8')
                audio_data_url = f"data:audio/wav;base64,{audio_base64}"
                
                # Create HTML audio element
                audio_html = f"""
                <audio controls style="width: 100%;">
                    <source src="{audio_data_url}" type="audio/wav">
                    Your browser does not support the audio element.
                </audio>
                """
                audio_container.markdown(audio_html, unsafe_allow_html=True)
                
                # Clear audio chunks after displaying
                translator.clear_audio_chunks()

            # translate
            pronunciate_to_korean = chat.pronunciate_to_korean(response, language)
            logger.info(f"pronunciate_to_korean: {pronunciate_to_korean}")
            st.info(pronunciate_to_korean)

            # Add message with audio and response
            message_data = {
                "role": "assistant", 
                "content": pronunciate_to_korean
            }
            if audio_base64:
                message_data["audio"] = audio_base64
            if response:
                message_data["response"] = response
            
            st.session_state.messages.append(message_data)

        elif mode == 'Translator (Speech2Text)':
            audio_container = st.empty()
            response = chat.run_speech2text(prompt)
            logger.info(f"response: {response}")

            # Get and display audio if available
            audio_wav_bytes = translator.get_audio_wav_bytes()
            audio_base64 = None
            if audio_wav_bytes:
                logger.info(f"Displaying audio in Streamlit: {len(audio_wav_bytes)} bytes")
                
                # Encode audio to base64 for HTML embedding
                import base64
                audio_base64 = base64.b64encode(audio_wav_bytes).decode('utf-8')
                audio_data_url = f"data:audio/wav;base64,{audio_base64}"
                
                # Create HTML audio element
                audio_html = f"""
                <audio controls style="width: 100%;">
                    <source src="{audio_data_url}" type="audio/wav">
                    Your browser does not support the audio element.
                </audio>
                """
                audio_container.markdown(audio_html, unsafe_allow_html=True)
                
                # Clear audio chunks after displaying
                translator.clear_audio_chunks()

            # translate
            pronunciate_to_korean = chat.pronunciate_to_korean(response, language)
            logger.info(f"pronunciate_to_korean: {pronunciate_to_korean}")
            st.info(pronunciate_to_korean)

            # Add message with audio and response
            message_data = {
                "role": "assistant", 
                "content": pronunciate_to_korean
            }
            if audio_base64:
                message_data["audio"] = audio_base64
            if response:
                message_data["response"] = response
            
            st.session_state.messages.append(message_data)

        else:
            stream = chat.general_conversation(prompt)

            response = st.write_stream(stream)
            logger.info(f"response: {response}")

            st.session_state.messages.append({"role": "assistant", "content": response})
        

def main():
    """Entry point for the application."""
    # This function is used as an entry point when running as a package
    # The code above is already running the Streamlit app
    pass


if __name__ == "__main__":
    # This is already handled by Streamlit
    pass
