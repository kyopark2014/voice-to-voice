import os
import asyncio
import base64
import json
import uuid
import pyaudio
from pathlib import Path
from configparser import ConfigParser
from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient, InvokeModelWithBidirectionalStreamOperationInput
from aws_sdk_bedrock_runtime.models import InvokeModelWithBidirectionalStreamInputChunk, BidirectionalInputPayloadPart
from aws_sdk_bedrock_runtime.config import Config
from smithy_aws_core.identity.environment import EnvironmentCredentialsResolver

# Audio configuration
INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000
CHANNELS = 1
FORMAT = pyaudio.paInt16
CHUNK_SIZE = 1024

def load_aws_credentials_from_config(profile='default'):
    """
    Load AWS credentials from ~/.aws/credentials and ~/.aws/config files.
    Sets environment variables if they are not already set.
    """
    aws_dir = Path.home() / '.aws'
    credentials_file = aws_dir / 'credentials'
    config_file = aws_dir / 'config'
    
    # Load credentials file
    if credentials_file.exists():
        credentials_parser = ConfigParser()
        credentials_parser.read(credentials_file)
        
        if profile in credentials_parser:
            profile_section = credentials_parser[profile]
            
            # Set access key if not already in environment
            if 'AWS_ACCESS_KEY_ID' not in os.environ:
                access_key = profile_section.get('aws_access_key_id')
                if access_key:
                    os.environ['AWS_ACCESS_KEY_ID'] = access_key
            
            # Set secret key if not already in environment
            if 'AWS_SECRET_ACCESS_KEY' not in os.environ:
                secret_key = profile_section.get('aws_secret_access_key')
                if secret_key:
                    os.environ['AWS_SECRET_ACCESS_KEY'] = secret_key
            
            # Set session token if present and not already in environment
            if 'AWS_SESSION_TOKEN' not in os.environ:
                session_token = profile_section.get('aws_session_token')
                if session_token:
                    os.environ['AWS_SESSION_TOKEN'] = session_token
    
    # Load config file for region
    if config_file.exists():
        config_parser = ConfigParser()
        config_parser.read(config_file)
        
        # Config file uses 'profile default' format, but also supports 'default'
        config_profile = f'profile {profile}' if profile != 'default' else profile
        if config_profile in config_parser:
            config_section = config_parser[config_profile]
        elif profile in config_parser:
            config_section = config_parser[profile]
        else:
            config_section = None
        
        if config_section:
            # Set region if not already in environment
            if 'AWS_DEFAULT_REGION' not in os.environ:
                region = config_section.get('region')
                if region:
                    os.environ['AWS_DEFAULT_REGION'] = region

model_id = 'amazon.nova-2-sonic-v1:0'
region = 'us-west-2'
client = None
stream = None
response = None
is_active = False
prompt_name = str(uuid.uuid4())
content_name = str(uuid.uuid4())
audio_content_name = str(uuid.uuid4())
text_content_name = str(uuid.uuid4())
audio_queue = asyncio.Queue()
input_queue = asyncio.Queue()  # 외부에서 텍스트 입력을 받기 위한 큐
role = None
display_assistant_text = False
is_active = False
sonic_client = None
run_task = None  # 백그라운드에서 실행되는 run() 태스크
playback_task = None  # 오디오 재생 태스크
silent_audio_task = None  # 무음 오디오 전송 태스크

def _initialize_client(region):
    """Initialize the Bedrock client."""
    config = Config(
        endpoint_uri=f"https://bedrock-runtime.{region}.amazonaws.com",
        region=region,
        aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
    )
    client = BedrockRuntimeClient(config=config)

    return client

async def send_event(event_json):
    """Send an event to the stream."""
    # Ensure event_json is a string
    if isinstance(event_json, bytes):
        event_json = event_json.decode('utf-8', errors='replace')
    elif not isinstance(event_json, str):
        event_json = str(event_json)
    
    # Ensure valid UTF-8 encoding before sending
    try:
        encoded_bytes = event_json.encode('utf-8')
    except UnicodeEncodeError:
        # Fallback: replace invalid characters
        encoded_bytes = event_json.encode('utf-8', errors='replace')
    
    event = InvokeModelWithBidirectionalStreamInputChunk(
        value=BidirectionalInputPayloadPart(bytes_=encoded_bytes)
    )
    await stream.input_stream.send(event)

async def start_session():
    """Start a new session with Nova Sonic."""
    global is_active, sonic_client, stream, response

    if not sonic_client:
        sonic_client = _initialize_client(region)
        
    # Initialize the stream
    stream = await sonic_client.invoke_model_with_bidirectional_stream(
        InvokeModelWithBidirectionalStreamOperationInput(model_id=model_id)
    )
    is_active = True
    
    # Send session start event
    session_start = '''
    {
        "event": {
        "sessionStart": {
            "inferenceConfiguration": {
            "maxTokens": 1024,
            "topP": 0.9,
            "temperature": 0.1
            }
        }
        }
    }
    '''
    await send_event(session_start)
    
    # Send prompt start event
    #tiffany, amy, matthew ambre
    prompt_start = f'''
    {{
        "event": {{
        "promptStart": {{
            "promptName": "{prompt_name}",
            "textOutputConfiguration": {{
            "mediaType": "text/plain"
            }},
            "audioOutputConfiguration": {{
            "mediaType": "audio/lpcm",
            "sampleRateHertz": 24000,
            "sampleSizeBits": 16,
            "channelCount": 1,
            "voiceId": "matthew",
            "encoding": "base64",
            "audioType": "SPEECH"
            }}
        }}
        }}
    }}
    '''
    await send_event(prompt_start)
    
    # Send system prompt
    text_content_start = f'''
    {{
        "event": {{
            "contentStart": {{
                "promptName": "{prompt_name}",
                "contentName": "{content_name}",
                "type": "TEXT",
                "interactive": false,
                "role": "SYSTEM",
                "textInputConfiguration": {{
                    "mediaType": "text/plain"
                }}
            }}
        }}
    }}
    '''
    await send_event(text_content_start)
    
    system_prompt = (
        "당신은 실시간 번역기입니다." 
        "사용자가 한국어로 입력하면, 원문 그대로를 일본어로 번역하여 답변하세요."
        "번역한 내용만 답변합니다."        
        "이전의 대화는 무시하고 현재 대화만 번역합니다."
    )

    text_input = f'''
    {{
        "event": {{
            "textInput": {{
                "promptName": "{prompt_name}",
                "contentName": "{content_name}",
                "content": "{system_prompt}"
            }}
        }}
    }}
    '''
    await send_event(text_input)
    
    text_content_end = f'''
    {{
        "event": {{
            "contentEnd": {{
                "promptName": "{prompt_name}",
                "contentName": "{content_name}"
            }}
        }}
    }}
    '''
    await send_event(text_content_end)
    
    # Start processing responses
    response = asyncio.create_task(_process_responses())

async def start_audio_input():
    """Start audio input stream."""
    audio_content_start = f'''
    {{
        "event": {{
            "contentStart": {{
                "promptName": "{prompt_name}",
                "contentName": "{audio_content_name}",
                "type": "AUDIO",
                "interactive": true,
                "role": "USER",
                "audioInputConfiguration": {{
                    "mediaType": "audio/lpcm",
                    "sampleRateHertz": 16000,
                    "sampleSizeBits": 16,
                    "channelCount": 1,
                    "audioType": "SPEECH",
                    "encoding": "base64"
                }}
            }}
        }}
    }}
    '''
    await send_event(audio_content_start)

async def send_audio_chunk(audio_bytes):
    """Send an audio chunk to the stream."""
    if not is_active:
        return
        
    blob = base64.b64encode(audio_bytes)
    audio_event = f'''
    {{
        "event": {{
            "audioInput": {{
                "promptName": "{prompt_name}",
                "contentName": "{audio_content_name}",
                "content": "{blob.decode('utf-8')}"
            }}
        }}
    }}
    '''
    await send_event(audio_event)

async def end_audio_input():
    """End audio input stream."""
    audio_content_end = f'''
    {{
        "event": {{
            "contentEnd": {{
                "promptName": "{prompt_name}",
                "contentName": "{audio_content_name}"
            }}
        }}
    }}
    '''
    await send_event(audio_content_end)

async def start_text_input():
    """Start text input stream."""
    global text_content_name
    text_content_name = str(uuid.uuid4())  # Generate new content name for each text input
    text_content_start = f'''
    {{
        "event": {{
            "contentStart": {{
                "promptName": "{prompt_name}",
                "contentName": "{text_content_name}",
                "role": "USER",
                "type": "TEXT",
                "interactive": true,
                "textInputConfiguration": {{
                    "mediaType": "text/plain"
                }}
            }}
        }}
    }}
    '''
    await send_event(text_content_start)

async def send_text(text):
    """Send text input to the stream."""
    if not is_active:
        return
    
    # Ensure text is a proper UTF-8 string
    if isinstance(text, bytes):
        text = text.decode('utf-8', errors='replace')
    elif not isinstance(text, str):
        text = str(text)
    
    # Create text input event with proper JSON encoding
    text_input_event = {
        "event": {
            "textInput": {
                "promptName": prompt_name,
                "contentName": text_content_name,
                "content": text
            }
        }
    }
    text_event = json.dumps(text_input_event, ensure_ascii=False)
    await send_event(text_event)

async def end_text_input():
    """End text input stream."""
    text_content_end = f'''
    {{
        "event": {{
            "contentEnd": {{
                "promptName": "{prompt_name}",
                "contentName": "{text_content_name}"
            }}
        }}
    }}
    '''
    await send_event(text_content_end)

async def end_session():
    """End the session."""
    if not is_active:
        return
        
    prompt_end = f'''
    {{
        "event": {{
            "promptEnd": {{
                "promptName": "{prompt_name}"
            }}
        }}
    }}
    '''
    await send_event(prompt_end)
    
    session_end = '''
    {
        "event": {
            "sessionEnd": {}
        }
    }
    '''
    await send_event(session_end)
    # close the stream
    await stream.input_stream.close()

async def _process_responses():
    """Process responses from the stream."""
    global is_active, role, display_assistant_text
    try:
        while is_active:
            try:
                output = await stream.await_output()
                result = await output[1].receive()
                
                if result.value and result.value.bytes_:
                    response_data = result.value.bytes_.decode('utf-8')
                    json_data = json.loads(response_data)                    
                    
                    if 'event' in json_data:
                        # Handle content start event
                        if 'contentStart' in json_data['event']:
                            # print(f"json_data: {json_data}")
                            content_start = json_data['event']['contentStart'] 
                            # set role
                            role = content_start['role']
                            # print(f"-> contentStart: role={content_start['role']}, type={content_start['type']}, completionId={content_start['completionId']}, contentId={content_start['contentId']}")
                            
                            # Check for speculative content
                            if 'additionalModelFields' in content_start:
                                additional_fields = json.loads(content_start['additionalModelFields'])
                                #print(f" additionalModelFields: {additional_fields}")
                                if additional_fields.get('generationStage') == 'SPECULATIVE':
                                    display_assistant_text = True
                                else:
                                    display_assistant_text = False
                                
                        # Handle text output event
                        elif 'textOutput' in json_data['event']:
                            text = json_data['event']['textOutput']['content']    
                            
                            if (role == "ASSISTANT" and display_assistant_text):
                                print(f"Assistant: {text}")
                            elif role == "USER":
                                print(f"User: {text}")
                        
                        # Handle audio output
                        elif 'audioOutput' in json_data['event']:
                            # print(f"audio...")
                            audio_content = json_data['event']['audioOutput']['content']
                            audio_bytes = base64.b64decode(audio_content)
                            await audio_queue.put(audio_bytes)

                        # elif 'completionStart' in json_data['event']:
                        #     completionId = json_data['event']['completionStart']['completionId']
                        #     print(f"-> completionStart: {completionId}")                            
                        # elif 'contentEnd' in json_data['event']:
                        #     print(f"-> contentEnd")
                        #elif 'usageEvent' in json_data['event']:
                        #    print(f"usageEvent...")
                        # else:
                        #     print(f"json_data: {json_data}")
            except asyncio.CancelledError:
                print("Response processing cancelled.")
                break
            except Exception as e:
                print(f"Error processing response chunk: {e}")
                # Continue processing other chunks
                continue
    except Exception as e:
        print(f"Error processing responses: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("Response processing stopped.")

async def play_audio():
    """Play audio responses."""
    p = pyaudio.PyAudio()
    stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=OUTPUT_SAMPLE_RATE,
        output=True,
        frames_per_buffer=CHUNK_SIZE
    )

    try:
        while is_active:
            try:
                audio_data = await audio_queue.get()

                # Write the audio data in chunks to avoid blocking
                for i in range(0, len(audio_data), CHUNK_SIZE):
                    if not is_active:
                        break

                    end = min(i + CHUNK_SIZE, len(audio_data))
                    chunk = audio_data[i:end]

                    # Write chunk in executor to avoid blocking the event loop
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        stream.write,
                        chunk
                    )

                    # Brief yield to allow other tasks to run
                    await asyncio.sleep(0.001)
            except asyncio.CancelledError:
                print("Audio playback cancelled.")
                break
            except Exception as e:
                print(f"Error playing audio chunk: {e}")
                import traceback
                traceback.print_exc()
                # Continue playing other chunks
                continue

    except Exception as e:
        print(f"Error playing audio: {e}")
        import traceback
        traceback.print_exc()
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()
        print("Audio playing stopped.")

async def capture_audio():
    """Capture audio from microphone and send to Nova Sonic."""
    p = pyaudio.PyAudio()
    stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=INPUT_SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK_SIZE
    )
    
    print("Starting audio capture. Speak into your microphone...")
    print("Press Enter to stop...")
    
    await start_audio_input()
    
    try:
        while is_active:
            audio_data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            # print(f"-> audioInput: {audio_data[:10]}...")
            await send_audio_chunk(audio_data)
            await asyncio.sleep(0.01)
    except Exception as e:
        print(f"Error capturing audio: {e}")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()
        print("Audio capture stopped.")
        await end_audio_input()

async def send_silent_audio():
    """Send continuous silent audio chunks to maintain audio stream."""
    # Create silent audio chunk (16-bit PCM, 16kHz, mono)
    silent_chunk_size = CHUNK_SIZE * 2  # 2 bytes per sample for 16-bit
    silent_chunk = b'\x00' * silent_chunk_size
    
    while is_active:
        try:
            # Send silent audio chunk
            await send_audio_chunk(silent_chunk)
            # Wait for next chunk (maintain ~16kHz sample rate)
            await asyncio.sleep(0.01)  # 10ms delay
        except Exception as e:
            if is_active:
                print(f"Error sending silent audio: {e}")
            break

async def process_text_input(user_input):
    """Process text input and send to Nova Sonic."""
    # Ensure proper UTF-8 encoding handling
    if isinstance(user_input, bytes):
        # If somehow bytes, decode with error handling
        user_input = user_input.decode('utf-8', errors='replace')
    elif not isinstance(user_input, str):
        user_input = str(user_input)
    
    # Normalize the string to ensure valid UTF-8
    # Encode and decode to catch any encoding issues early
    try:
        user_input = user_input.encode('utf-8', errors='replace').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError) as e:
        print(f"Warning: Encoding issue detected, using error replacement: {e}")
        user_input = user_input.encode('utf-8', errors='replace').decode('utf-8')
    
    # Send text input to Nova Sonic
    await start_text_input()
    await send_text(user_input)
    await end_text_input()
    
    print(f"📝 Text sent: {user_input}\n")

async def send_text_input(text):
    """
    외부에서 텍스트 입력을 주입하는 함수.
    
    Args:
        text: 전송할 텍스트 문자열
    
    Example:
        await send_text_input("안녕하세요")
    """
    if not is_active:
        raise RuntimeError("Session is not active. Call start_session() first.")
    await input_queue.put(text)

async def run(use_stdin=True, skip_init=False):
    """
    번역기를 실행합니다.
    
    Args:
        use_stdin: True이면 표준 입력(stdin)에서 입력을 받고, False이면 큐에서 입력을 받습니다.
                   기본값은 True입니다.
        skip_init: True이면 초기화를 건너뛰고 입력 루프만 실행합니다. 기본값은 False입니다.
    """
    global is_active, playback_task, silent_audio_task
    
    if not skip_init:
        # Start session
        await start_session()
        
        # Start audio playback task
        print("Starting audio playback task...")
        playback_task = asyncio.create_task(play_audio())
        
        # Start audio input stream (required for audio output)
        await start_audio_input()
        
        # Start silent audio task to maintain audio stream
        silent_audio_task = asyncio.create_task(send_silent_audio())
    
    if use_stdin:
        print("Starting text input mode. Type your message and press Enter...")
        print("Type 'quit' or press Enter (empty line) to stop...")
    else:
        print("Starting text input mode. Waiting for external input via send_text_input()...")
        print("Use send_text_input(text) function to send text.")
    
    try:
        while is_active:
            if use_stdin:
                print("Waiting for user input...")
                # Get user input from stdin
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: input("You: ")
                )
                
                # Check if user wants to stop
                if user_input.strip().lower() == 'quit':
                    print("Quitting...")
                    break
                if user_input.strip() == '':
                    print("Stopping text input...")
                    break
            else:
                # Get user input from queue (external input)
                print("Waiting for external input...")
                user_input = await input_queue.get()
                
                # Check for special stop signal
                if user_input is None or user_input.strip().lower() == '__stop__':
                    print("Stopping text input...")
                    break
            
            # Process text input
            await process_text_input(user_input)
            
    except Exception as e:
        print(f"Error reading text: {e}")
    finally:
        if not skip_init:
            # Stop silent audio task
            if silent_audio_task and not silent_audio_task.done():
                silent_audio_task.cancel()
                try:
                    await silent_audio_task
                except asyncio.CancelledError:
                    pass
            
            # End audio input
            await end_audio_input()
            print("Text input stopped.")
            
            # First cancel the tasks
            tasks = []
            if playback_task and not playback_task.done():
                print("Cancelling audio playback task...")
                tasks.append(playback_task)
            for task in tasks:
                print(f"Cancelling task: {task}")
                task.cancel()
            if tasks:
                print("Gathering tasks...")
                await asyncio.gather(*tasks, return_exceptions=True)
            
            # End session
            await end_session()
            is_active = False

            # cancel the response task
            if response and not response.done():
                response.cancel()

            print("Session ended")

# if __name__ == "__main__":
#     # Load AWS credentials from ~/.aws/credentials and ~/.aws/config
#     # This will only set environment variables if they are not already set
#     load_aws_credentials_from_config()

#     asyncio.run(run_translator())