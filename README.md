# Speech to Speech

여기서는 Speech to Speech의 구현에 대해 정리합니다.

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

