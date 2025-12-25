#!/bin/bash

set -e

# Configuration
REGION="us-west-2"
ECR_REPO="262976740991.dkr.ecr.us-west-2.amazonaws.com/speech-to-speech"
IMAGE_TAG="latest"
EKS_CLUSTER_NAME="streamlit-test-cluster"

echo "🚀 Starting deployment to EKS in $REGION..."

# 1. Get AWS credentials from local AWS CLI configuration
echo "🔑 Getting AWS credentials from local configuration..."
AWS_ACCESS_KEY_ID=$(aws configure get aws_access_key_id)
AWS_SECRET_ACCESS_KEY=$(aws configure get aws_secret_access_key)
AWS_DEFAULT_REGION=$(aws configure get region)
AWS_SESSION_TOKEN=$(aws configure get aws_session_token)

if [ -z "$AWS_ACCESS_KEY_ID" ] || [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
    echo "❌ Error: AWS credentials not found in local configuration"
    echo "   Please run 'aws configure' to set up your credentials"
    exit 1
fi

echo "✅ AWS credentials retrieved"

# 2. Login to ECR
echo "📦 Logging into ECR..."
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ECR_REPO

# 3. Build Docker image with AWS credentials
echo "🔨 Building Docker image with embedded AWS credentials..."
echo "⚠️  Note: AWS credentials will be embedded in the Docker image"
docker build \
    --platform linux/amd64 \
    --build-arg AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
    --build-arg AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
    --build-arg AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$REGION}" \
    --build-arg AWS_SESSION_TOKEN="$AWS_SESSION_TOKEN" \
    -t $ECR_REPO:$IMAGE_TAG .

# 4. Push to ECR
echo "⬆️ Pushing image to ECR..."
docker push $ECR_REPO:$IMAGE_TAG

# 5. Update kubeconfig for EKS
echo "⚙️ Updating kubeconfig for EKS cluster..."
aws eks update-kubeconfig --region $REGION --name $EKS_CLUSTER_NAME

# 6. Deploy to Kubernetes
echo "🚢 Deploying to Kubernetes..."
kubectl apply -f k8s-deployment.yaml
kubectl apply -f k8s-ingress.yaml

# 7. Wait for deployment
echo "⏳ Waiting for deployment to be ready..."
kubectl rollout status deployment/speech-to-speech --timeout=300s

# 8. Get service information
echo "📋 Getting service information..."
kubectl get services speech-to-speech-service
kubectl get ingress speech-to-speech-ingress

echo "✅ Deployment completed successfully!"
echo "🌐 Your application should be accessible via the LoadBalancer URL above."
