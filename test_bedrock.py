#!/usr/bin/env python3

import boto3
import json

def test_bedrock_connection():
    try:
        # Create Bedrock Runtime client
        client = boto3.client('bedrock-runtime', region_name='us-west-2')
        
        # Test simple invoke with Nova Micro via inference profile
        response = client.invoke_model(
            modelId='us.amazon.nova-micro-v1:0',
            body=json.dumps({
                "messages": [{"role": "user", "content": [{"text": "Hello"}]}],
                "inferenceConfig": {
                    "max_new_tokens": 10,
                    "temperature": 0.1
                }
            })
        )
        
        print("✅ Bedrock connection successful!")
        print(f"Response: {response['body'].read().decode()}")
        
    except Exception as e:
        print(f"❌ Bedrock connection failed: {e}")
        return False
    
    return True

if __name__ == "__main__":
    test_bedrock_connection()
