# 출력 스트림 처리

스트림은 [아래](https://docs.aws.amazon.com/ko_kr/nova/latest/userguide/images/output-events.png)와 같이 처리 됩니다.

<img width="850" alt="image" src="https://github.com/user-attachments/assets/672aaae3-2ea5-4442-87c2-105ca28b36f3" />

## 스트림 처리

응답에는 자동 음성 인식(ASR) 트랜스크립션(사용자가 말한 내용), 선택적 도구 사용(외부 정보가 필요한 경우), 텍스트 응답(모델이 말하려는 내용), 오디오 응답(음성 출력) 등 여러 콘텐츠 블록이 순차적으로 포함됩니다.

ASR 트랜스크립션이 먼저 표시되어 contentStart에 role: "USER" 및 "additionalModelFields": "{\"generationStage\":\"FINAL\"}"을 사용하여 모델이 사용자 음성을 이해한 내용을 전달합니다.



시작시 completionStart를 받습니다. contentStart는 콘텐츠 유형 및 형식, 실제 콘텐츠 이벤트를 정의합니다.

Client에서 contentStart는 콘텐츠 유형 및 형식, 실제 콘텐츠 이벤트를 정의합니다. 이후 스트림으로 contentStart의 결과를 받습니다. 

```java
{
   "event":{
      "completionStart":{
         "completionId":"a16f0ca2-bb29-41a4-b9bb-728632770965",
         "promptName":"b5e93ca7-23b1-4e91-9963-af1b5b8e640c",
         "sessionId":"d7f50ba1-077d-469b-adac-944cb0374b9c"
      }
   }
}
```



contentStart로 role 정보를 확인합니다. additionalModelFields의 generationStage가 SPECULATIVE로 계획된 음성의 미리 보기를 제공합니다. 이때, display_assistant_text를 true로 설정합니다.


```java
{
   "event":{
      "contentStart":{
         "additionalModelFields":"{\"generationStage\":\"SPECULATIVE\"}",
         "completionId":"a16f0ca2-bb29-41a4-b9bb-728632770965",
         "contentId":"0243d58d-9134-4970-9e89-896ddeb67fb7",
         "promptName":"b5e93ca7-23b1-4e91-9963-af1b5b8e640c",
         "role":"ASSISTANT",
         "sessionId":"d7f50ba1-077d-469b-adac-944cb0374b9c",
         "textOutputConfiguration":{
            "mediaType":"text/plain"
         },
         "type":"TEXT"
      }
   }
}
```

이때의 text는 textOutput의 content로 확인합니다.

```java
{
   "event":{
      "textOutput":{
         "completionId":"a16f0ca2-bb29-41a4-b9bb-728632770965",
         "content":"안녕하세요! 여행 전문가 서연입니다. 여행에 대해 어떤 도움이 필요하신가요?",
         "contentId":"0243d58d-9134-4970-9e89-896ddeb67fb7",
         "promptName":"b5e93ca7-23b1-4e91-9963-af1b5b8e640c",
         "role":"ASSISTANT",
         "sessionId":"d7f50ba1-077d-469b-adac-944cb0374b9c"
      }
   }
}
```

음성 대화는 completionId를 공유하고 text, audio등은 다른 contentId를 가지고 있습니다.

현재의 세그맨트가 종료가 될때 contentEnd를 받습니다. 이때, completionId이 종료된것을 알 수 있습니다. 

```java
{
   "event":{
      "contentEnd":{
         "completionId":"a16f0ca2-bb29-41a4-b9bb-728632770965",
         "contentId":"0243d58d-9134-4970-9e89-896ddeb67fb7",
         "promptName":"b5e93ca7-23b1-4e91-9963-af1b5b8e640c",
         "sessionId":"d7f50ba1-077d-469b-adac-944cb0374b9c",
         "stopReason":"PARTIAL_TURN",
         "type":"TEXT"
      }
   }
}
```

오디오 응답은 스트림 전체에서 동일한 contentId를 공유하는 base64로 인코딩된 음성 청크를 전달합니다.

```java
{
   "event":{
      "audioOutput":{
         "completionId":"d69397cc-a12e-4958-bb5f-2831423991f2",
         "content":"uAAGAyP+KwESAo/+HAJHAS/+kgIi/8oAVQBf/hwAdADxAMf9/QLi/5H7xgJkAov8sQHs/tj++P5KALgBW/5cAVP/zP7tARb+gPAwEDNwF9/8L+a/3N+w36fvfU807xR/Hf8Wrz+fMz8QPu0uvQ6iHpPOqC7PvqrOvV6yTq8Otp7Yfu4u8x8MHwsPEG9Sn5ofw9/94AXAGCAv0EXQhEDIUPaxKIEyAUihWtFm4XZRmdGfoYtBjLF2kYWBlKGR4XLhXKEtsP+g4fDqsN9wtRCm0HxAOXAp4ACACH/wr+Ivyl+g76HPo8+lP6+vmY+HD4V/g8+aT6/vvx/BT9c/0Q/m3+2v9KAZEBzgLIAoECQgMZA+gChAIwAQUAYf7//E78mPqn93P16fL88IPyj/Oz8wjymO+a7a3qq+pc67/q8Os37ETrTuvj68Psse0D79bv1e9f8U30zPbv+qX9If9KAHEBFAQlBkAKtQ3aD2USfhOvFNEV5BZMGIoYBBkAGRIYARk9GpEZWhjaFmsU6xH8EKwPjg4oDvkL0AlAB7cErwJCAScAr/5P/Ub8JPsR+1X74flE+fP42ffi98L4yPmO+l77evwz/Lf8/f0l/r3+IgCCAE0BZQLPAusCSgJmAuoAD/+f/wf+1/yI/Iz5qvfd9L/yFvOC8z314PPv8NvvDu1x7LzrHuwN7aPrN+z06tDrmeyN7NjuWO6y7tjvRvFA9Kr3BftO/Kb9v/4CAZgDmQacCokMnA4MEUESDRTeFXMWbxewF0oYlxjTGGoabBqmGXIY3xWDFGsTGRNUEooQOA+vDDEKpQdMBu4EUANtAk8Akv68/bf8Rvy8+7H68fmm+KL4KflQ+XT6ffqE+qH62vqp+4P8df2D/t3+FP/e/zAA6ADYAPMA6gD4/zr/rv6G/Q391PtK+bf4XPQL83f07/Iu9tv0JfLQ8GDuhe2f61XuO+3E62Tuxes27Gvt+uzt7VXuP+9I76rwlvM096D5VfsN/fX96f4lAhcFewd9C84M4w4dEW4SCRR9FAMW2BYhF8cXixezGQYa7RkBGcEVbBXHE1YTRxOnEV8QBg5jDOkJ7wcJB6MEwQNcAn0Af/8F/hj+",
         "contentId":"b3fc4d0d-0f03-4576-86d5-e50a2e815217",
         "promptName":"fe8dff38-d942-43bf-bd9b-82544b950faf",
         "role":"ASSISTANT",
         "sessionId":"528592c5-259a-4101-9b2d-94bf6d8f9478"
      }
   }
}
```

Amazon Nova Sonic이 말하는 동안 사용자가 Nova Sonic을 중단하면 Nova Sonic은 즉시 음성 생성을 중지하고 듣기 모드로 전환한 다음, 중단 발생을 알리는 콘텐츠 알림을 전송합니다. 

Nova Sonic은 실시간보다 빠르게 작동하기 때문에 일부 오디오는 이미 전송되었지만 아직 재생되지 않았을 수 있습니다. 중단 알림을 통해 클라이언트 애플리케이션은 오디오 대기열을 지우고 즉시 재생을 중지하여 응답성이 뛰어난 대화 경험을 제공할 수 있습니다.

응답 처리 과정에서 토큰 소비를 추적하기 위해 usageEvent 이벤트가 전송됩니다. 이러한 이벤트에는 입력 토큰과 출력 토큰(음성 및 텍스트 모두)에 대한 자세한 지표와 그 누적 합계가 포함되어 있습니다. 각 usageEvent는 대화 흐름의 다른 이벤트와 동일한 sessionId, promptName, completionId를 유지합니다. 세부 정보 섹션에서는 토큰 사용량의 증분 변경 사항(델타)과 총합을 모두 제공하여 대화 중 사용량을 정확하게 모니터링할 수 있습니다.

```java
{
   "event":{
      "usageEvent":{
         "completionId":"d69397cc-a12e-4958-bb5f-2831423991f2",
         "details":{
            "delta":{
               "input":{
                  "speechTokens":0,
                  "textTokens":0
               },
               "output":{
                  "speechTokens":20,
                  "textTokens":0
               }
            },
            "total":{
               "input":{
                  "speechTokens":280,
                  "textTokens":458
               },
               "output":{
                  "speechTokens":34,
                  "textTokens":35
               }
            }
         },
         "promptName":"fe8dff38-d942-43bf-bd9b-82544b950faf",
         "sessionId":"528592c5-259a-4101-9b2d-94bf6d8f9478",
         "totalInputTokens":738,
         "totalOutputTokens":69,
         "totalTokens":807
      }
   }
}
```
