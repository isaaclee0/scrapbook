# Docker Image Optimization Guide

## 📊 Image Size Comparison

| Dockerfile | Size | Build Time | Use Case |
|------------|------|------------|----------|
| `Dockerfile` | **~1.5GB** | Fast | ❌ Development only (includes build tools) |
| `Dockerfile.optimized` | **~800MB** | Medium | ✅ Good for production |
| `Dockerfile.minimal` | **~500-700MB** | Slower | ✅ Best for production (smallest) |

## 🎯 Recommended: Use Dockerfile.minimal

The regular `Dockerfile` is 1.5GB because it includes:
- ❌ gcc compiler (100MB+)
- ❌ Node.js (50MB+)
- ❌ All -dev packages (200MB+)
- ❌ Build tools that are never used in production

### Quick Switch to Minimal Build

```bash
# Build with minimal Dockerfile
./build-and-push.sh --optimized

# This uses Dockerfile.minimal by default when --optimized is passed
```

Or specify explicitly:
```bash
docker build -f Dockerfile.minimal -t staugustine1/scrapbook:1.5.0 .
```

## 🔍 What's in Each Version?

### Dockerfile (1.5GB) - Development
```
✓ Python 3.11-slim (~150MB)
✓ gcc, g++, build tools (~150MB)
✓ Node.js + npm (~80MB)
✓ All -dev libraries (~200MB)
✓ FFmpeg (~100MB)
✓ Python packages (~200MB)
✓ Application code (~50MB)
✓ Runtime libraries (~100MB)
= ~1.5GB total
```

### Dockerfile.optimized (800MB) - Production
```
✓ Python 3.11-slim (~150MB)
✓ FFmpeg (~100MB)
✓ Python packages (~200MB)
✓ Runtime libraries (~100MB)
✓ Application code (~50MB)
✗ No build tools
✗ No Node.js (built in stage 1, then discarded)
= ~800MB total
```

### Dockerfile.minimal (500-700MB) - Production (Smallest)
```
✓ Python 3.11-slim (~150MB)
✓ FFmpeg (~100MB) - optional
✓ Python packages (~200MB)
✓ Runtime libraries (~80MB)
✓ Application code (~30MB) - only essential files
✗ No build tools
✗ No Node.js
✗ No scripts/ directory
= ~500-700MB total
```

## 💡 Further Optimization Options

### Remove FFmpeg if not needed (saves ~100MB)
If you don't need video frame extraction:

Edit `Dockerfile.minimal` and comment out line 64:
```dockerfile
# ffmpeg \
```

**New size: ~400-600MB**

### Use Alpine base (advanced, saves ~50MB)
Replace `python:3.11-slim` with `python:3.11-alpine`:
- Smaller base image
- Requires different package names
- More complex setup

**New size: ~350-550MB**

### Use distroless (advanced, saves ~100MB)
Use Google's distroless Python image:
- No shell or package manager
- Maximum security
- Harder to debug

**New size: ~400MB**

## 🚀 Migration Plan

### Step 1: Test the minimal build locally
```bash
# Build minimal version
docker build -f Dockerfile.minimal -t scrapbook:minimal-test .

# Check the size
docker images scrapbook:minimal-test

# Test it works
docker run -p 8000:8000 scrapbook:minimal-test
```

### Step 2: Update your build script
The build script already supports this:
```bash
./build-and-push.sh --optimized
```

### Step 3: Deploy
```bash
# Pull the new smaller image
docker pull staugustine1/scrapbook:1.5.0

# Restart services
docker-compose up -d
```

## 📝 Build Script Options

```bash
# Use regular Dockerfile (1.5GB)
./build-and-push.sh

# Use Dockerfile.optimized (800MB)
./build-and-push.sh --optimized

# To use minimal, update the script or:
docker build -f Dockerfile.minimal -t staugustine1/scrapbook:1.5.0 .
docker push staugustine1/scrapbook:1.5.0
```

## 🔍 Analyzing Your Current Image

To see what's taking up space in your current image:

```bash
# Install dive (Docker image analyzer)
# Mac: brew install dive
# Ubuntu: wget https://github.com/wagoodman/dive/releases/download/v0.10.0/dive_0.10.0_linux_amd64.deb && sudo dpkg -i dive_0.10.0_linux_amd64.deb

# Analyze the image
dive staugustine1/scrapbook:1.5.0
```

## ✅ Recommended Setup

For production, use `Dockerfile.minimal`:
- **67% smaller** than current (1.5GB → 500MB)
- Faster downloads and deployments
- Same functionality
- Better security (fewer packages = smaller attack surface)

The only downside is slightly longer build time due to multi-stage build, but this is a one-time cost during deployment.

