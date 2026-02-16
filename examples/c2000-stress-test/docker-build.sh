#!/bin/bash
# Docker-based headless build for C2000 stress test firmware
# Uses whuzfb/ccstudio Docker image

set -e

# Configuration
PROJECT_NAME="launchxl_ex1_f280039c_demo"
PROJECT_DIR="$(pwd)"
WORKSPACE_DIR="/tmp/ccs-workspace"
DOCKER_IMAGE="whuzfb/ccstudio:20.2-ubuntu24.04"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== C2000 Docker Build ===${NC}"
echo "Project: $PROJECT_NAME"
echo "Directory: $PROJECT_DIR"
echo "Docker Image: $DOCKER_IMAGE"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running${NC}"
    exit 1
fi

# Check if image exists
if ! docker image inspect "$DOCKER_IMAGE" > /dev/null 2>&1; then
    echo -e "${YELLOW}Docker image not found. Pulling...${NC}"
    docker pull "$DOCKER_IMAGE"
fi

# Clean previous build
echo -e "${GREEN}Cleaning previous build...${NC}"
rm -rf Debug/

# Run build in Docker (using image's built-in entrypoint)
echo -e "${GREEN}Building project in Docker...${NC}"
docker run --rm \
    --platform linux/amd64 \
    -v "$PROJECT_DIR":/ccs_projects/c2000-stress-test \
    -v /tmp/c2000ware-core-sdk:/tmp/c2000ware-core-sdk \
    -v "$WORKSPACE_DIR":/workspaces \
    "$DOCKER_IMAGE" \
    "c2000-stress-test/CCS/launchxl_ex1_f280039c_demo.projectspec" \
    "Debug"

# Copy build artifacts from workspace to project directory
if [ -d "$WORKSPACE_DIR/$PROJECT_NAME/Debug" ]; then
    echo -e "${GREEN}Copying build artifacts to project directory...${NC}"
    cp -r "$WORKSPACE_DIR/$PROJECT_NAME/Debug" "$PROJECT_DIR/"
fi

# Check if build succeeded
if [ -f "Debug/${PROJECT_NAME}.out" ]; then
    echo -e "${GREEN}=== Build Successful ===${NC}"
    echo "Output: Debug/${PROJECT_NAME}.out"
    ls -lh "Debug/${PROJECT_NAME}.out"
    echo ""
    echo -e "${GREEN}Ready to flash with: eabctl flash examples/c2000-stress-test${NC}"
else
    echo -e "${RED}=== Build Failed ===${NC}"
    echo "Output file not found: Debug/${PROJECT_NAME}.out"
    exit 1
fi
