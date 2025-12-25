#!/bin/bash

set -e

REGION="us-west-2"
CLUSTER_NAME="streamlit-test-cluster"
NAMESPACE="default"
SERVICE_ACCOUNT_NAME="speech-to-speech-sa"
ROLE_NAME="speech-to-speech-bedrock-role"

echo "🔐 Setting up IAM role for Bedrock access..."

# Get OIDC issuer URL
OIDC_ISSUER=$(aws eks describe-cluster --name $CLUSTER_NAME --region $REGION --query "cluster.identity.oidc.issuer" --output text)
echo "OIDC Issuer: $OIDC_ISSUER"

# Create trust policy
cat > trust-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::262976740991:oidc-provider/${OIDC_ISSUER#https://}"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "${OIDC_ISSUER#https://}:sub": "system:serviceaccount:${NAMESPACE}:${SERVICE_ACCOUNT_NAME}",
          "${OIDC_ISSUER#https://}:aud": "sts.amazonaws.com"
        }
      }
    }
  ]
}
EOF

# Create IAM role
aws iam create-role \
  --role-name $ROLE_NAME \
  --assume-role-policy-document file://trust-policy.json \
  --region $REGION || echo "Role already exists"

# Attach Bedrock policy
aws iam attach-role-policy \
  --role-name $ROLE_NAME \
  --policy-arn arn:aws:iam::aws:policy/AmazonBedrockFullAccess \
  --region $REGION

# Get role ARN
ROLE_ARN=$(aws iam get-role --role-name $ROLE_NAME --query 'Role.Arn' --output text)
echo "Role ARN: $ROLE_ARN"

# Create service account with annotation
kubectl create serviceaccount $SERVICE_ACCOUNT_NAME --namespace $NAMESPACE || echo "ServiceAccount already exists"
kubectl annotate serviceaccount $SERVICE_ACCOUNT_NAME \
  --namespace $NAMESPACE \
  eks.amazonaws.com/role-arn=$ROLE_ARN \
  --overwrite

echo "✅ IAM role and service account configured"
echo "Role ARN: $ROLE_ARN"

# Clean up
rm -f trust-policy.json
