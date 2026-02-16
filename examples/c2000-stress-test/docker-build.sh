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

# Run build in Docker
echo -e "${GREEN}Building project in Docker...${NC}"
docker run --rm \
    --platform linux/amd64 \
    -v "$PROJECT_DIR":/ccs_projects/c2000-stress-test \
    -e PROJECT_NAME="$PROJECT_NAME" \
    "$DOCKER_IMAGE" \
    /bin/bash -c '
        set -e

        # Find CCS installation
        CCS_BASE=$(find /opt/ti -name "ccs_base" -type d | head -1)
        if [ -z "$CCS_BASE" ]; then
            echo "Error: CCS installation not found"
            exit 1
        fi

        echo "CCS Base: $CCS_BASE"

        # Find ccs-server-cli
        CCS_CLI=$(find "$CCS_BASE" -name "ccs-server-cli.sh" -type f | head -1)
        if [ -z "$CCS_CLI" ]; then
            echo "Error: ccs-server-cli.sh not found"
            exit 1
        fi

        echo "CCS CLI: $CCS_CLI"

        # Create workspace
        mkdir -p /workspaces

        # Import project
        echo "Importing project..."
        "$CCS_CLI" -noSplash -workspace /workspaces \
            -application com.ti.ccs.apps.importProject \
            -ccs.location /ccs_projects/c2000-stress-test

        # Build project
        echo "Building project..."
        "$CCS_CLI" -noSplash -workspace /workspaces \
            -application com.ti.ccs.apps.buildProject \
            -ccs.projects "$PROJECT_NAME"

        # Copy build artifacts back to project directory
        if [ -d "/workspaces/$PROJECT_NAME/Debug" ]; then
            echo "Copying build artifacts..."
            cp -r "/workspaces/$PROJECT_NAME/Debug" /ccs_projects/c2000-stress-test/
        fi

        echo "Build complete!"
    '

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
