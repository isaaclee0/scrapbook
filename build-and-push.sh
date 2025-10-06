#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Read version from VERSION file
if [ ! -f "VERSION" ]; then
    echo -e "${RED}Error: VERSION file not found${NC}"
    exit 1
fi

VERSION=$(cat VERSION | tr -d '\n')
echo -e "${BLUE}📦 Building Scrapbook v${VERSION}${NC}"
if [ "$USE_OPTIMIZED" != true ]; then
    echo -e "${YELLOW}💡 Tip: Use --optimized flag to reduce image size from 1.5GB to 500-700MB${NC}"
fi

# Docker Hub configuration (update these with your values)
DOCKER_HUB_USERNAME="${DOCKER_HUB_USERNAME:-staugustine1}"
IMAGE_NAME="scrapbook"
FULL_IMAGE_NAME="${DOCKER_HUB_USERNAME}/${IMAGE_NAME}"

# Parse command line arguments
BUILD_ONLY=false
SKIP_TESTS=false
USE_OPTIMIZED=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --build-only)
            BUILD_ONLY=true
            shift
            ;;
        --skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        --optimized)
            USE_OPTIMIZED=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --build-only    Build the image but don't push to Docker Hub"
            echo "  --skip-tests    Skip running tests before building"
            echo "  --optimized     Use Dockerfile.optimized instead of Dockerfile"
            echo "  --help          Show this help message"
            echo ""
            echo "Environment variables:"
            echo "  DOCKER_HUB_USERNAME    Your Docker Hub username (default: yourusername)"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Select Dockerfile
if [ "$USE_OPTIMIZED" = true ]; then
    DOCKERFILE="Dockerfile.minimal"
    echo -e "${YELLOW}✨ Using optimized ${DOCKERFILE} (500-700MB vs 1.5GB)${NC}"
else
    DOCKERFILE="Dockerfile"
fi

if [ ! -f "$DOCKERFILE" ]; then
    echo -e "${RED}Error: ${DOCKERFILE} not found${NC}"
    exit 1
fi

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running${NC}"
    exit 1
fi

# Ensure we're on a clean git state (optional warning)
if [ -n "$(git status --porcelain)" ]; then
    echo -e "${YELLOW}⚠️  Warning: You have uncommitted changes${NC}"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check if version tag exists in git
if git rev-parse "v${VERSION}" >/dev/null 2>&1; then
    echo -e "${GREEN}✓ Git tag v${VERSION} exists${NC}"
else
    echo -e "${YELLOW}⚠️  Warning: Git tag v${VERSION} does not exist${NC}"
    echo "   Run: git tag -a v${VERSION} -m \"Version ${VERSION}\""
fi

# Run tests (optional)
if [ "$SKIP_TESTS" = false ]; then
    echo -e "${BLUE}🧪 Running tests...${NC}"
    # Add your test command here, e.g.:
    # python -m pytest tests/ || { echo -e "${RED}Tests failed${NC}"; exit 1; }
    echo -e "${GREEN}✓ Tests passed (skipped - add tests here)${NC}"
fi

# Reminder about database migrations
echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}⚠️  IMPORTANT: Database Migration Required for v${VERSION}${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${BLUE}This version includes a new database schema for board default images.${NC}"
echo -e "${BLUE}After deploying, you MUST run the migration:${NC}"
echo ""
echo -e "   ${GREEN}docker-compose exec web python scripts/add_board_default_image.py${NC}"
echo ""
echo -e "${BLUE}Or use the database version manager:${NC}"
echo ""
echo -e "   ${GREEN}docker-compose exec web python scripts/db_version_manager.py --status${NC}"
echo -e "   ${GREEN}docker-compose exec web python scripts/db_version_manager.py --apply 1.5.4${NC}"
echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Build the Docker image
echo -e "${BLUE}🔨 Building Docker image...${NC}"
docker build -f "$DOCKERFILE" -t "${FULL_IMAGE_NAME}:${VERSION}" -t "${FULL_IMAGE_NAME}:latest" .

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Build successful${NC}"
else
    echo -e "${RED}Build failed${NC}"
    exit 1
fi

# Show image info
echo ""
echo -e "${BLUE}📋 Image Details:${NC}"
docker images "${FULL_IMAGE_NAME}" --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"

# Push to Docker Hub
if [ "$BUILD_ONLY" = false ]; then
    echo ""
    echo -e "${BLUE}🚀 Pushing to Docker Hub...${NC}"
    
    # Check if logged in to Docker Hub
    if ! docker info | grep -q "Username"; then
        echo -e "${YELLOW}⚠️  Not logged in to Docker Hub${NC}"
        echo "Logging in..."
        docker login
    fi
    
    echo -e "${BLUE}Pushing ${FULL_IMAGE_NAME}:${VERSION}${NC}"
    docker push "${FULL_IMAGE_NAME}:${VERSION}"
    
    echo -e "${BLUE}Pushing ${FULL_IMAGE_NAME}:latest${NC}"
    docker push "${FULL_IMAGE_NAME}:latest"
    
    echo -e "${GREEN}✓ Successfully pushed to Docker Hub${NC}"
    echo ""
    echo -e "${GREEN}🎉 Release complete!${NC}"
    echo ""
    echo -e "Pull this image with:"
    echo -e "  ${BLUE}docker pull ${FULL_IMAGE_NAME}:${VERSION}${NC}"
    echo -e "  ${BLUE}docker pull ${FULL_IMAGE_NAME}:latest${NC}"
else
    echo ""
    echo -e "${YELLOW}Build-only mode: Skipping Docker Hub push${NC}"
    echo ""
    echo -e "To push manually, run:"
    echo -e "  ${BLUE}docker push ${FULL_IMAGE_NAME}:${VERSION}${NC}"
    echo -e "  ${BLUE}docker push ${FULL_IMAGE_NAME}:latest${NC}"
fi

echo ""
echo -e "${GREEN}✓ Done!${NC}"

