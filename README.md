# Speech to Speech

여기서는 Speech to Speech의 구현에 대해 정리합니다.

## Architecture

[기본적인 구조](https://catalog.us-east-1.prod.workshops.aws/workshops/5238419f-1337-4e0f-8cd7-02239486c40d/en-US/01-core-functions/00-setup-code)는 아래와 같습니다.

<img width="680" height="338" alt="image" src="https://github.com/user-attachments/assets/d6944f50-8b7c-464a-b143-a59a3214502e" />






## 대화

성공적인 대화형 애플리케이션을 구현하고 상호 작용 전반에 걸쳐 적절한 대화 상태를 유지하려면 올바른 이벤트 순서가 중요합니다. [양방향 API를 사용하여 입력 이벤트 처리](https://docs.aws.amazon.com/ko_kr/nova/latest/userguide/input-events.html)와 같은 형태로 동작합니다.

<img width="971" height="521" alt="image" src="https://github.com/user-attachments/assets/9c1b653e-23ad-4612-9a0a-58465461afdd" />

### 입력

오디오 스트리밍은 연속 마이크 샘플링으로 작동합니다. 초기 contentStart를 전송한 후, 오디오 프레임(각각 약 32ms)이 마이크에서 직접 캡처되어 동일한 contentName을 사용하여 즉시 audioInput 이벤트로 전송됩니다. 

이러한 오디오 샘플은 캡처되는 대로 실시간으로 스트리밍되어 대화 전체에서 자연스러운 마이크 샘플링 케이던스를 유지해야 합니다. 모든 오디오 프레임은 대화가 끝나고 명시적으로 닫힐 때까지 하나의 콘텐츠 컨테이너를 공유합니다.

### 스트림 출력

### 대화의 종료

대화가 끝나거나 종료되어야 하는 경우 열려 있는 모든 스트림을 올바르게 닫고 올바른 순서로 세션을 끝내는 것이 중요합니다. 세션을 올바르게 끝내고 리소스 누수를 방지하려면 다음과 같은 특정 닫기 순서를 따라야 합니다.

contentEnd 이벤트를 사용하여 열려 있는 모든 오디오 스트림을 닫습니다.

원래 promptName을 참조하는 promptEnd 이벤트를 전송합니다.

sessionEnd 이벤트를 전송합니다.

이러한 닫기 이벤트를 건너뛰면 대화가 불완전하거나 리소스가 분리될 수 있습니다.


## 설치 방법

```text
pip install aws_sdk_bedrock_runtime portaudio
```

Mac에서는 아래와 같이 portaudio을 설치합니다.

```python
brew install portaudio
```

```text
source .venv/bin/activate && python nova_sonic_simple.py
```

[Introducing gpt-realtime in the API](https://www.youtube.com/watch?v=nfBbmtMJhX0)

[Building voice agents with OpenAI — Dominik Kundel, OpenAI](https://www.youtube.com/watch?v=iXhba366fQc)

chained voice agent: tone, longer delay, context 문제 

speech-to-speech voice agent: 


## Reference 

[Amazon Nova Sonic Python Streaming Implementation](https://github.com/aws-samples/amazon-nova-samples/tree/main/speech-to-speech/sample-codes/console-python)

[Amazon Bedrock Runtime Client](https://pypi.org/project/aws_sdk_bedrock_runtime/)

[Unlocking Voice Interaction with LangGraph Agents](https://www.youtube.com/watch?v=xM67AJy1aL8): voice를 text로 변환하여 LangGraph agent를 활용

[Task mAIstro](https://github.com/langchain-ai/task_mAIstro): LangGraph 프로젝트, ElevenLabs로 text-to-speech 처리

[Amazon-Nova 양방향 API를 사용하여 출력 이벤트 처리](https://docs.aws.amazon.com/ko_kr/nova/latest/userguide/output-events.html)
