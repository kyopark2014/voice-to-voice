# nova_sonic_simple.py 코드 설명

## 개요

`nova_sonic_simple.py`는 AWS Bedrock의 Nova Sonic 모델을 사용하여 실시간 양방향 음성 대화를 구현한 Python 애플리케이션입니다. 마이크로부터 음성을 입력받아 AI 어시스턴트와 대화하고, 응답을 음성으로 출력합니다.

## 주요 구성 요소

### 1. 전역 상수 및 설정

```python
INPUT_SAMPLE_RATE = 16000    # 입력 오디오 샘플레이트 (16kHz)
OUTPUT_SAMPLE_RATE = 24000   # 출력 오디오 샘플레이트 (24kHz)
CHANNELS = 1                 # 모노 채널
FORMAT = pyaudio.paInt16     # 16비트 PCM 포맷
CHUNK_SIZE = 1024            # 오디오 청크 크기
```

- **INPUT_SAMPLE_RATE**: 마이크 입력 오디오의 샘플레이트 (16kHz)
- **OUTPUT_SAMPLE_RATE**: 스피커 출력 오디오의 샘플레이트 (24kHz)
- **CHANNELS**: 모노 채널 (1)
- **FORMAT**: 16비트 정수 PCM 포맷
- **CHUNK_SIZE**: 오디오 데이터를 처리하는 단위 크기 (1024 바이트)

### 2. 함수: `load_aws_credentials_from_config`

#### 목적
AWS 자격 증명을 `~/.aws/credentials`와 `~/.aws/config` 파일에서 로드하여 환경 변수로 설정합니다.

#### 동작 방식
1. **자격 증명 파일 읽기**: `~/.aws/credentials` 파일에서 지정된 프로필의 자격 증명을 읽습니다.
   - `aws_access_key_id`: AWS 액세스 키 ID
   - `aws_secret_access_key`: AWS 시크릿 액세스 키
   - `aws_session_token`: 세션 토큰 (있는 경우)

2. **설정 파일 읽기**: `~/.aws/config` 파일에서 리전 정보를 읽습니다.
   - 프로필이 'default'가 아닌 경우 `profile {profile}` 형식으로 검색
   - 'default'인 경우 그대로 검색

3. **환경 변수 설정**: 해당 환경 변수가 이미 설정되어 있지 않은 경우에만 설정합니다.
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`
   - `AWS_SESSION_TOKEN`
   - `AWS_DEFAULT_REGION`

#### 매개변수
- `profile` (기본값: 'default'): 사용할 AWS 프로필 이름

### 3. 클래스: `SimpleNovaSonic`

Nova Sonic 모델과의 양방향 스트리밍 통신을 관리하는 메인 클래스입니다.

#### 초기화 (`__init__`)

```python
def __init__(self, model_id='amazon.nova-2-sonic-v1:0', region='us-west-2')
```

**인스턴스 변수:**
- `model_id`: 사용할 Bedrock 모델 ID (기본값: 'amazon.nova-2-sonic-v1:0')
- `region`: AWS 리전 (기본값: 'us-west-2')
- `client`: BedrockRuntimeClient 인스턴스
- `stream`: 양방향 스트림 객체
- `response`: 응답 처리 태스크
- `is_active`: 세션 활성 상태 플래그
- `prompt_name`: 프롬프트 식별자 (UUID)
- `content_name`: 텍스트 콘텐츠 식별자 (UUID)
- `audio_content_name`: 오디오 콘텐츠 식별자 (UUID)
- `audio_queue`: 오디오 출력 데이터를 저장하는 비동기 큐
- `role`: 현재 콘텐츠의 역할 (USER/ASSISTANT)
- `display_assistant_text`: 어시스턴트 텍스트 표시 여부

#### 메서드: `_initialize_client`

**목적**: Bedrock Runtime 클라이언트를 초기화합니다.

**동작 방식:**
1. `Config` 객체를 생성하여 엔드포인트 URI와 리전을 설정합니다.
2. `EnvironmentCredentialsResolver`를 사용하여 환경 변수에서 자격 증명을 읽습니다.
3. `BedrockRuntimeClient` 인스턴스를 생성하여 `self.client`에 저장합니다.

#### 메서드: `send_event`

**목적**: 스트림에 이벤트를 전송합니다.

**동작 방식:**
1. JSON 문자열을 UTF-8로 인코딩합니다.
2. `InvokeModelWithBidirectionalStreamInputChunk` 객체를 생성합니다.
3. 스트림의 `input_stream.send()`를 통해 이벤트를 전송합니다.

**매개변수:**
- `event_json`: 전송할 이벤트의 JSON 문자열

#### 메서드: `start_session`

**목적**: Nova Sonic과의 새 세션을 시작합니다.

**동작 방식:**
1. **클라이언트 초기화**: 클라이언트가 없으면 초기화합니다.
2. **스트림 생성**: `invoke_model_with_bidirectional_stream()`을 호출하여 양방향 스트림을 생성합니다.
3. **세션 시작 이벤트 전송**: 
   ```json
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
   ```
   - `maxTokens`: 최대 토큰 수 (1024)
   - `topP`: 샘플링 파라미터 (0.9)
   - `temperature`: 생성 온도 (0.1)

4. **프롬프트 시작 이벤트 전송**:
   - `promptName`: 고유한 프롬프트 이름
   - `textOutputConfiguration`: 텍스트 출력 설정 (text/plain)
   - `audioOutputConfiguration`: 오디오 출력 설정
     - `mediaType`: "audio/lpcm"
     - `sampleRateHertz`: 24000
     - `sampleSizeBits`: 16
     - `channelCount`: 1
     - `voiceId`: "ambre" (음성 ID)
     - `encoding`: "base64"
     - `audioType`: "SPEECH"

5. **시스템 프롬프트 전송**:
   - `contentStart` 이벤트: 텍스트 콘텐츠 시작, 역할은 "SYSTEM"
   - `textInput` 이벤트: 시스템 프롬프트 내용 전송
     - 현재 설정: "너는 여행 전문가이고 이름은 서연입니다. 편안한 대화를 하고자 합니다. 사용자의 질문에 대한 답변은 한문장으로 반드시 하세요. 사용자가 자세히 알려달라고 할때까지는 최대한 짧게 대답하세요."
   - `contentEnd` 이벤트: 텍스트 콘텐츠 종료

6. **응답 처리 태스크 시작**: `_process_responses()`를 비동기 태스크로 실행합니다.

#### 메서드: `start_audio_input`

**목적**: 오디오 입력 스트림을 시작합니다.

**동작 방식:**
1. `contentStart` 이벤트를 전송하여 오디오 입력을 시작합니다.
2. 설정:
   - `type`: "AUDIO"
   - `interactive`: true (대화형)
   - `role`: "USER"
   - `audioInputConfiguration`:
     - `mediaType`: "audio/lpcm"
     - `sampleRateHertz`: 16000
     - `sampleSizeBits`: 16
     - `channelCount`: 1
     - `audioType`: "SPEECH"
     - `encoding`: "base64"

#### 메서드: `send_audio_chunk`

**목적**: 오디오 청크를 스트림에 전송합니다.

**동작 방식:**
1. 세션이 활성화되어 있는지 확인합니다.
2. 오디오 바이트를 Base64로 인코딩합니다.
3. `audioInput` 이벤트를 생성하여 전송합니다.
   - `promptName`: 현재 프롬프트 이름
   - `contentName`: 오디오 콘텐츠 이름
   - `content`: Base64로 인코딩된 오디오 데이터

**매개변수:**
- `audio_bytes`: 전송할 오디오 바이트 데이터

#### 메서드: `end_audio_input`

**목적**: 오디오 입력 스트림을 종료합니다.

**동작 방식:**
1. `contentEnd` 이벤트를 전송하여 오디오 입력을 종료합니다.
   - `promptName`: 현재 프롬프트 이름
   - `contentName`: 오디오 콘텐츠 이름

#### 메서드: `end_session`

**목적**: 세션을 종료합니다.

**동작 방식:**
1. 세션이 활성화되어 있는지 확인합니다.
2. `promptEnd` 이벤트를 전송합니다.
3. `sessionEnd` 이벤트를 전송합니다.
4. 스트림의 입력 스트림을 닫습니다.

#### 메서드: `_process_responses`

**목적**: 스트림으로부터 받은 응답을 처리합니다.

**동작 방식:**
1. **무한 루프**: `is_active`가 True인 동안 계속 실행됩니다.
2. **응답 수신**: `stream.await_output()`으로 출력을 대기하고, `receive()`로 데이터를 받습니다.
3. **JSON 파싱**: 받은 바이트 데이터를 UTF-8로 디코딩하고 JSON으로 파싱합니다.
4. **이벤트 타입별 처리**:
   - **`contentStart`**: 콘텐츠 시작 이벤트
     - `role` (USER/ASSISTANT) 저장
     - `type` (TEXT/AUDIO) 확인
     - `completionId`, `contentId` 출력
     - `additionalModelFields`에서 `generationStage`가 "SPECULATIVE"인지 확인하여 `display_assistant_text` 플래그 설정
   
   - **`textOutput`**: 텍스트 출력 이벤트
     - `role`이 "ASSISTANT"이고 `display_assistant_text`가 True이면 "Assistant: {text}" 출력
     - `role`이 "USER"이면 "User: {text}" 출력
   
   - **`audioOutput`**: 오디오 출력 이벤트
     - Base64로 인코딩된 오디오 데이터를 디코딩
     - `audio_queue`에 추가하여 재생 대기
   
   - **`completionStart`**: 완료 시작 이벤트
     - `completionId` 출력
   
   - **`contentEnd`**: 콘텐츠 종료 이벤트
     - 종료 메시지 출력
   
   - **`usageEvent`**: 사용량 이벤트
     - 사용량 정보 출력
   
   - **기타 이벤트**: 알 수 없는 이벤트는 JSON 전체를 출력

5. **예외 처리**: 오류 발생 시 에러 메시지를 출력합니다.

#### 메서드: `play_audio`

**목적**: 오디오 응답을 재생합니다.

**동작 방식:**
1. **PyAudio 초기화**: PyAudio 인스턴스를 생성합니다.
2. **출력 스트림 열기**: 
   - 포맷: 16비트 정수
   - 채널: 모노 (1)
   - 샘플레이트: 24000 Hz
   - 출력 모드로 스트림 열기
3. **오디오 재생 루프**:
   - `audio_queue`에서 오디오 데이터를 가져옵니다.
   - 데이터를 `CHUNK_SIZE` 단위로 나누어 처리합니다.
   - 각 청크를 `run_in_executor`를 사용하여 비동기로 스트림에 작성합니다 (이벤트 루프 블로킹 방지).
   - 0.001초 대기하여 다른 태스크가 실행될 수 있도록 합니다.
4. **정리**: 
   - 스트림 중지 및 닫기
   - PyAudio 종료
   - 종료 메시지 출력

#### 메서드: `capture_audio`

**목적**: 마이크로부터 오디오를 캡처하여 Nova Sonic에 전송합니다.

**동작 방식:**
1. **PyAudio 초기화**: PyAudio 인스턴스를 생성합니다.
2. **입력 스트림 열기**:
   - 포맷: 16비트 정수
   - 채널: 모노 (1)
   - 샘플레이트: 16000 Hz
   - 입력 모드로 스트림 열기
3. **오디오 입력 시작**: `start_audio_input()` 호출
4. **캡처 루프**:
   - `CHUNK_SIZE`만큼 오디오 데이터를 읽습니다.
   - `send_audio_chunk()`로 전송합니다.
   - 0.01초 대기하여 CPU 사용률을 조절합니다.
5. **정리**:
   - 스트림 중지 및 닫기
   - PyAudio 종료
   - 종료 메시지 출력
   - `end_audio_input()` 호출

### 4. 함수: `main`

**목적**: 애플리케이션의 메인 진입점입니다.

**동작 방식:**
1. **Nova Sonic 클라이언트 생성**: `SimpleNovaSonic` 인스턴스를 생성합니다.
2. **세션 시작**: `start_session()`을 호출하여 세션을 시작합니다.
3. **오디오 재생 태스크 시작**: `play_audio()`를 비동기 태스크로 실행합니다.
4. **오디오 캡처 태스크 시작**: `capture_audio()`를 비동기 태스크로 실행합니다.
5. **사용자 입력 대기**: Enter 키 입력을 대기합니다 (`input()` 호출).
6. **태스크 취소**: 재생 및 캡처 태스크를 취소하고 완료를 대기합니다.
7. **세션 종료**: `end_session()`을 호출하고 `is_active`를 False로 설정합니다.
8. **응답 태스크 취소**: 응답 처리 태스크를 취소합니다.
9. **종료 메시지 출력**: "Session ended" 메시지를 출력합니다.

### 5. 실행 진입점

```python
if __name__ == "__main__":
    load_aws_credentials_from_config()
    asyncio.run(main())
```

**동작 방식:**
1. AWS 자격 증명을 로드합니다.
2. `asyncio.run()`을 사용하여 `main()` 함수를 실행합니다.

## 전체 동작 흐름

1. **초기화 단계**:
   - AWS 자격 증명 로드
   - `SimpleNovaSonic` 인스턴스 생성

2. **세션 시작**:
   - Bedrock 클라이언트 초기화
   - 양방향 스트림 생성
   - 세션 시작 이벤트 전송
   - 프롬프트 시작 이벤트 전송
   - 시스템 프롬프트 전송
   - 응답 처리 태스크 시작

3. **실시간 대화**:
   - **오디오 캡처 태스크**: 마이크로부터 오디오를 지속적으로 읽어 스트림에 전송
   - **응답 처리 태스크**: 스트림으로부터 응답을 받아 텍스트/오디오 처리
   - **오디오 재생 태스크**: 응답 오디오를 큐에서 가져와 스피커로 재생

4. **세션 종료**:
   - Enter 키 입력 대기
   - 모든 태스크 취소
   - 세션 종료 이벤트 전송
   - 스트림 닫기

## 주요 특징

1. **비동기 처리**: `asyncio`를 사용하여 오디오 캡처, 재생, 응답 처리를 동시에 수행합니다.
2. **양방향 스트리밍**: 실시간으로 오디오를 주고받으며 대화합니다.
3. **이벤트 기반 아키텍처**: JSON 이벤트를 통해 세션, 프롬프트, 콘텐츠를 관리합니다.
4. **큐 기반 오디오 재생**: 오디오 출력을 큐에 저장하여 순차적으로 재생합니다.
5. **예외 처리**: 각 주요 함수에서 예외를 처리하여 안정성을 확보합니다.

## 사용 방법

1. AWS 자격 증명 설정 (`~/.aws/credentials`, `~/.aws/config`)
2. 필요한 패키지 설치 (pyaudio, aws-sdk-bedrock-runtime 등)
3. 스크립트 실행: `python nova_sonic_simple.py`
4. 마이크에 대고 말하기
5. Enter 키를 눌러 종료

## 주의사항

- 마이크와 스피커가 정상적으로 작동해야 합니다.
- AWS Bedrock 서비스에 대한 접근 권한이 필요합니다.
- 인터넷 연결이 필요합니다 (AWS 서비스 접근용).
- 오디오 포맷은 LPCM (Linear Pulse Code Modulation)을 사용합니다.
