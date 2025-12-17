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

class SimpleNovaSonic:
    def __init__(self, model_id='amazon.nova-2-sonic-v1:0', region='us-west-2'):
        self.model_id = model_id
        self.region = region
        self.client = None
        self.stream = None
        self.response = None
        self.is_active = False
        self.prompt_name = str(uuid.uuid4())
        self.content_name = str(uuid.uuid4())
        self.audio_content_name = str(uuid.uuid4())
        self.audio_queue = asyncio.Queue()
        self.role = None
        self.display_assistant_text = False
        
    def _initialize_client(self):
        """Initialize the Bedrock client."""
        config = Config(
            endpoint_uri=f"https://bedrock-runtime.{self.region}.amazonaws.com",
            region=self.region,
            aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
        )
        self.client = BedrockRuntimeClient(config=config)
    
    async def send_event(self, event_json):
        """Send an event to the stream."""
        event = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(bytes_=event_json.encode('utf-8'))
        )
        await self.stream.input_stream.send(event)
    
    async def start_session(self):
        """Start a new session with Nova Sonic."""
        if not self.client:
            self._initialize_client()
            
        # Initialize the stream
        self.stream = await self.client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=self.model_id)
        )
        self.is_active = True
        
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
        await self.send_event(session_start)
        
        # Send prompt start event
        #tiffany, amy, matthew ambre
        prompt_start = f'''
        {{
          "event": {{
            "promptStart": {{
              "promptName": "{self.prompt_name}",
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
        await self.send_event(prompt_start)
        
        # Send system prompt
        text_content_start = f'''
        {{
            "event": {{
                "contentStart": {{
                    "promptName": "{self.prompt_name}",
                    "contentName": "{self.content_name}",
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
        await self.send_event(text_content_start)
        
        # system_prompt = (
        #     "You are a warm, professional, and helpful male AI assistant. Give accurate answers that sound natural, direct, and human. Start by answering the user's question clearly in 1–2 sentences. Then, expand only enough to make the answer understandable, staying within 3–5 short sentences total. Avoid sounding like a lecture or essay."
        #     "When reading order numbers, please read each digit individually, separated by pauses. For example, order #1234 should be read as 'order number one-two-three-four' rather than 'order number one thousand two hundred thirty-four'."
        # )

        system_prompt = (
            "너는 여행 전문가이고 이름은 서연입니다. 편안한 대화를 하고자 합니다."
            "사용자의 질문에 대한 답변은 한문장으로 반드시 하세요."
            "사용자가 자세히 알려달라고 할때까지는 최대한 짭게 대답하세요."
            
        )

        # system_prompt = (
        #     "Tu es une experte en voyage et ton nom est Seoyeon. Tu veux avoir une conversation détendue."
        #     "Réponds toujours aux questions de l'utilisateur en une seule phrase."
        #     "Réponds de manière aussi brève que possible jusqu'à ce que l'utilisateur demande plus de détails."
        #     "Réponds toujours en français, même si la question est posée en coréen."
            
        # )


        text_input = f'''
        {{
            "event": {{
                "textInput": {{
                    "promptName": "{self.prompt_name}",
                    "contentName": "{self.content_name}",
                    "content": "{system_prompt}"
                }}
            }}
        }}
        '''
        await self.send_event(text_input)
        
        text_content_end = f'''
        {{
            "event": {{
                "contentEnd": {{
                    "promptName": "{self.prompt_name}",
                    "contentName": "{self.content_name}"
                }}
            }}
        }}
        '''
        await self.send_event(text_content_end)
        
        # Start processing responses
        self.response = asyncio.create_task(self._process_responses())
    
    async def start_audio_input(self):
        """Start audio input stream."""
        audio_content_start = f'''
        {{
            "event": {{
                "contentStart": {{
                    "promptName": "{self.prompt_name}",
                    "contentName": "{self.audio_content_name}",
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
        await self.send_event(audio_content_start)
    
    async def send_audio_chunk(self, audio_bytes):
        """Send an audio chunk to the stream."""
        if not self.is_active:
            return
            
        blob = base64.b64encode(audio_bytes)
        audio_event = f'''
        {{
            "event": {{
                "audioInput": {{
                    "promptName": "{self.prompt_name}",
                    "contentName": "{self.audio_content_name}",
                    "content": "{blob.decode('utf-8')}"
                }}
            }}
        }}
        '''
        await self.send_event(audio_event)
    
    async def end_audio_input(self):
        """End audio input stream."""
        audio_content_end = f'''
        {{
            "event": {{
                "contentEnd": {{
                    "promptName": "{self.prompt_name}",
                    "contentName": "{self.audio_content_name}"
                }}
            }}
        }}
        '''
        await self.send_event(audio_content_end)
    
    async def end_session(self):
        """End the session."""
        if not self.is_active:
            return
            
        prompt_end = f'''
        {{
            "event": {{
                "promptEnd": {{
                    "promptName": "{self.prompt_name}"
                }}
            }}
        }}
        '''
        await self.send_event(prompt_end)
        
        session_end = '''
        {
            "event": {
                "sessionEnd": {}
            }
        }
        '''
        await self.send_event(session_end)
        # close the stream
        await self.stream.input_stream.close()
    
    async def _process_responses(self):
        """Process responses from the stream."""
        try:
            while self.is_active:
                output = await self.stream.await_output()
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
                            self.role = content_start['role']
                            print(f"-> contentStart: role={content_start['role']}, type={content_start['type']}, completionId={content_start['completionId']}, contentId={content_start['contentId']}")
                            
                            # Check for speculative content
                            if 'additionalModelFields' in content_start:
                                additional_fields = json.loads(content_start['additionalModelFields'])
                                print(f" additionalModelFields: {additional_fields}")
                                if additional_fields.get('generationStage') == 'SPECULATIVE':
                                    self.display_assistant_text = True
                                else:
                                    self.display_assistant_text = False
                                
                        # Handle text output event
                        elif 'textOutput' in json_data['event']:
                            text = json_data['event']['textOutput']['content']    
                           
                            if (self.role == "ASSISTANT" and self.display_assistant_text):
                                print(f"Assistant: {text}")
                            elif self.role == "USER":
                                print(f"User: {text}")
                        
                        # Handle audio output
                        elif 'audioOutput' in json_data['event']:
                            print(f"audio...")
                            audio_content = json_data['event']['audioOutput']['content']
                            audio_bytes = base64.b64decode(audio_content)
                            await self.audio_queue.put(audio_bytes)

                        elif 'completionStart' in json_data['event']:
                            completionId = json_data['event']['completionStart']['completionId']
                            print(f"-> completionStart: {completionId}")                            
                        elif 'contentEnd' in json_data['event']:
                            print(f"-> contentEnd")
                        elif 'usageEvent' in json_data['event']:
                            print(f"usageEvent...")
                        else:
                            print(f"json_data: {json_data}")
        except Exception as e:
            print(f"Error processing responses: {e}")
    
    async def play_audio(self):
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
            while self.is_active:
                audio_data = await self.audio_queue.get()

                # Write the audio data in chunks to avoid blocking
                for i in range(0, len(audio_data), CHUNK_SIZE):
                    if not self.is_active:
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

    async def capture_audio(self):
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
        
        await self.start_audio_input()
        
        try:
            while self.is_active:
                audio_data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                print(f"-> audioInput: {audio_data[:10]}...")
                await self.send_audio_chunk(audio_data)
                await asyncio.sleep(0.01)
        except Exception as e:
            print(f"Error capturing audio: {e}")
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()
            print("Audio capture stopped.")
            await self.end_audio_input()

async def main():
    # Create Nova Sonic client
    nova_client = SimpleNovaSonic()
    
    # Start session
    await nova_client.start_session()
    
    # Start audio playback task
    playback_task = asyncio.create_task(nova_client.play_audio())
    
    # Start audio capture task
    capture_task = asyncio.create_task(nova_client.capture_audio())
    
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
    await nova_client.end_session()
    nova_client.is_active = False

    # cancel the response task
    if nova_client.response and not nova_client.response.done():
        nova_client.response.cancel()

    print("Session ended")

if __name__ == "__main__":
    # Load AWS credentials from ~/.aws/credentials and ~/.aws/config
    # This will only set environment variables if they are not already set
    load_aws_credentials_from_config()

    asyncio.run(main())