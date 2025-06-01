# SAI-Cam Security Guide

## 🔒 Credential Management

### ✅ **Secure Methods (Use These)**

#### 1. Environment Variables (.env file)
```bash
# Create .env file (automatically ignored by git)
cp .env.example .env
# Edit .env with your actual credentials
```

#### 2. System Environment Variables
```bash
export CAMERA_IP="192.168.1.100"
export CAMERA_USERNAME="admin"
export CAMERA_PASSWORD="your_secure_password"
```

#### 3. Interactive Setup Script
```bash
./scripts/deploy-setup.sh  # Prompts for credentials securely
```

### ❌ **Insecure Methods (Never Do This)**

- ❌ Hardcoding credentials in source code
- ❌ Committing real passwords to git
- ❌ Using default passwords in production
- ❌ Storing credentials in plain text config files that are committed

## 🛡️ **Security Features**

### Environment Variable Priority
The system uses secure fallback priorities:

1. **Environment variables** (highest priority)
2. **Config file values** (medium priority)
3. **Interactive prompts** (fallback)
4. **Default values** (lowest priority)

### Automatic Protection
- ✅ `.env` files are automatically ignored by git
- ✅ Config files with credentials are gitignored
- ✅ Password prompts are masked
- ✅ Environment variable substitution in config files
- ✅ Secure file permissions (600) for credential files

## 🔧 **Deployment Methods**

### Development/Testing
```bash
# Method 1: Use .env file
cp .env.example .env
# Edit .env with test credentials
python3 scripts/camera-test.py

# Method 2: Export variables
export CAMERA_IP="192.168.1.100"
export CAMERA_PASSWORD="test123"
python3 scripts/camera-test.py
```

### Production Deployment
```bash
# Method 1: Interactive setup
./scripts/deploy-setup.sh

# Method 2: Non-interactive with environment variables
export CAMERA_IP="10.0.1.50"
export CAMERA_PASSWORD="SecurePassword123!"
./scripts/deploy-setup.sh --non-interactive

# Method 3: Systemd environment files
sudo systemctl edit sai-cam
# Add environment variables to service
```

### CI/CD Deployment
```bash
# Use secrets management
export CAMERA_IP="$CI_CAMERA_IP"
export CAMERA_PASSWORD="$CI_CAMERA_PASSWORD"
./scripts/install.sh
```

## 📋 **Configuration Examples**

### Secure Config File
```yaml
# config.yaml - Safe to commit
cameras:
  - id: 'cam1'
    type: 'onvif'
    address: '${CAMERA_IP}'           # Environment variable
    username: '${CAMERA_USERNAME}'   # Environment variable  
    password: '${CAMERA_PASSWORD}'   # Environment variable
    port: 8000

  - id: 'cam2'
    type: 'rtsp'
    rtsp_url: '${RTSP_URL}'          # Full URL in environment
```

### Environment File (.env)
```bash
# .env - Never committed to git
CAMERA_IP=192.168.1.100
CAMERA_USERNAME=admin
CAMERA_PASSWORD=SecurePassword123!
RTSP_URL=rtsp://admin:SecurePassword123!@192.168.1.101:554/stream
```

## 🔍 **Security Checklist**

### Before Committing Code
- [ ] No hardcoded IP addresses from your network
- [ ] No real passwords in any files
- [ ] All examples use placeholder values
- [ ] .env files are in .gitignore
- [ ] Test with example values to ensure they don't work

### Before Deployment
- [ ] Set all required environment variables
- [ ] Use strong, unique passwords
- [ ] Secure file permissions on credential files
- [ ] Test credential loading from environment
- [ ] Verify no credentials in logs

### Production Security
- [ ] Change all default passwords
- [ ] Use HTTPS for server communications
- [ ] Implement certificate validation
- [ ] Regular credential rotation
- [ ] Monitor for credential exposure
- [ ] Use network isolation where possible

## ⚠️ **Common Security Mistakes**

### 1. Committing Real Credentials
```bash
# ❌ Wrong
CAMERA_PASSWORD="RealPassword123!"  # Real password in git

# ✅ Correct  
CAMERA_PASSWORD="${CAMERA_PASSWORD:-your_password_here}"  # Environment variable
```

### 2. Using Default Passwords
```bash
# ❌ Wrong
password: admin123  # Default password

# ✅ Correct
password: "${CAMERA_PASSWORD}"  # Secure environment variable
```

### 3. Logging Credentials
```python
# ❌ Wrong
logger.info(f"Connecting with password: {password}")

# ✅ Correct
logger.info("Connecting to camera (credentials configured)")
```

## 🚨 **If Credentials Are Exposed**

1. **Immediately change all exposed passwords**
2. **Review git history for credential commits**
3. **Rotate authentication tokens**
4. **Update all deployed systems**
5. **Consider credential management system**

## 📞 **Security Support**

For security issues or questions:
- Review this guide first
- Check environment variable configuration
- Test with placeholder values
- Verify .gitignore is working

Remember: **Security is everyone's responsibility!**