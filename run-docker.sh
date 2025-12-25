#!/bin/bash

# Docker Run Script (for ARG-built images)
echo "🚀 Docker Run Script"
echo "=================================="

if [ -f "application/config.json" ]; then
    PROJECT_NAME=$(python3 -c "import json; print(json.load(open('application/config.json'))['projectName'])")

    CURRENT_FOLDER_NAME=$(basename $(pwd))
    echo "CURRENT_FOLDER_NAME: ${CURRENT_FOLDER_NAME}"

    DOCKER_NAME="${PROJECT_NAME}_${CURRENT_FOLDER_NAME}"
    echo "DOCKER_NAME: ${DOCKER_NAME}"
else
    # Fallback to default name if config.json not found
    CURRENT_FOLDER_NAME=$(basename $(pwd))
    DOCKER_NAME="speech-to-speech_${CURRENT_FOLDER_NAME}"
    echo "⚠️  config.json not found, using default DOCKER_NAME: ${DOCKER_NAME}"
fi

# Check if image exists
echo "🔍 Checking for Docker image '${DOCKER_NAME}:latest'..."
IMAGE_EXISTS=$(sudo docker images --format "{{.Repository}}:{{.Tag}}" | grep -q "^${DOCKER_NAME}:latest$" && echo "yes" || echo "no")
if [ "$IMAGE_EXISTS" != "yes" ]; then
    echo "❌ Docker image '${DOCKER_NAME}:latest' not found."
    echo "   Please build the image first using:"
    echo "   ./build-docker.sh"
    exit 1
else
    echo "✅ Docker image found: ${DOCKER_NAME}:latest"
    # Verify image actually exists by inspecting it
    if ! sudo docker inspect ${DOCKER_NAME}:latest >/dev/null 2>&1; then
        echo "❌ Docker image '${DOCKER_NAME}:latest' exists but cannot be inspected."
        echo "   The image may be corrupted. Please rebuild using:"
        echo "   ./build-docker.sh"
        exit 1
    fi
fi

# Stop and remove existing container if it exists
echo "🧹 Cleaning up existing container..."
sudo docker stop ${DOCKER_NAME}-container 2>/dev/null || true
sudo docker rm ${DOCKER_NAME}-container 2>/dev/null || true

# Disable OpenTelemetry for local development
echo "🔍 OpenTelemetry disabled for local development"

# Run Docker container with x86_64 architecture (EKS node compatibility)
echo ""
echo "🚀 Starting Docker container for x86_64 architecture..."
sudo docker run -d \
    --platform linux/amd64 \
    --name ${DOCKER_NAME}-container \
    -p 8501:8501 \
    ${DOCKER_NAME}:latest
   
if [ $? -eq 0 ]; then
    echo "✅ Container started successfully!"
    echo ""
    echo "🌐 Access your application at: http://localhost:8501"
    echo ""
    echo "📊 Container status:"
    sudo docker ps | grep ${DOCKER_NAME}-container
    echo ""
    echo "📝 To view logs: sudo docker logs ${DOCKER_NAME}-container"
    echo "🛑 To stop: sudo docker stop ${DOCKER_NAME}-container"
    echo "🗑️  To remove: sudo docker rm ${DOCKER_NAME}-container"
    echo ""
    echo "🔍 To test AWS credentials in container:"
    echo "   sudo docker exec -it ${DOCKER_NAME}-container aws sts get-caller-identity"
else
    echo "❌ Failed to start container"
    exit 1
fi 