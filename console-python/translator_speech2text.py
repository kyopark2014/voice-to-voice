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
audio_queue = asyncio.Queue()
role = None
display_assistant_text = False
is_active = False
sonic_client = None

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
    event = InvokeModelWithBidirectionalStreamInputChunk(
        value=BidirectionalInputPayloadPart(bytes_=event_json.encode('utf-8'))
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
    # turn detection sensitivity: HIGH, MEDIUM, LOW
    session_start = '''
    {
        "event": {
        "sessionStart": {
            "inferenceConfiguration": {
                "maxTokens": 1024,
                "topP": 0.9,
                "temperature": 0.1
            }
        },
            "turnDetectionConfiguration": {
                "endpointingSensitivity": "MEDIUM" 
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
            "voiceId": "ambre",
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
        "사용자가 일본어로 입력하면, 원문 그대로를 한국어로 번역하여 답변하세요."
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
    try:
        while is_active:
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
                        print(f"-> contentStart: role={content_start['role']}, type={content_start['type']}, completionId={content_start['completionId']}, contentId={content_start['contentId']}")
                        
                        # Check for speculative content
                        if 'additionalModelFields' in content_start:
                            additional_fields = json.loads(content_start['additionalModelFields'])
                            print(f" additionalModelFields: {additional_fields}")
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

                    elif 'completionStart' in json_data['event']:
                        completionId = json_data['event']['completionStart']['completionId']
                        print(f"-> completionStart: {completionId}")                            
                    elif 'contentEnd' in json_data['event']:
                        print(f"-> contentEnd")
                    # elif 'usageEvent' in json_data['event']:
                    #     print(f"usageEvent...")
                    # else:
                    #     print(f"json_data: {json_data}")
    except Exception as e:
        print(f"Error processing responses: {e}")

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

    except Exception as e:
        print(f"Error playing audio: {e}")
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

async def main():
    global is_active
    # Start session
    await start_session()
    
    # Start audio playback task
    playback_task = asyncio.create_task(play_audio())
    
    # Start audio capture task
    capture_task = asyncio.create_task(capture_audio())
    
    # Wait for user to press Enter to stop
    await asyncio.get_event_loop().run_in_executor(None, input)
        
    # First cancel the tasks
    tasks = []
    if not playback_task.done():
        tasks.append(playback_task)
    if not capture_task.done():
        tasks.append(capture_task)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    
    # End session
    await end_session()
    is_active = False

    # cancel the response task
    if response and not response.done():
        response.cancel()

    print("Session ended")

if __name__ == "__main__":
    # Load AWS credentials from ~/.aws/credentials and ~/.aws/config
    # This will only set environment variables if they are not already set
    load_aws_credentials_from_config()

    asyncio.run(main())