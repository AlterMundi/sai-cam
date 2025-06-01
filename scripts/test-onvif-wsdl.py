#!/usr/bin/env python3
"""
Test ONVIF WSDL Path Detection

Quick test to verify WSDL path detection works correctly.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def test_wsdl_path_detection():
    """Test WSDL path detection logic"""
    import sys
    import os
    import glob
    
    print("🔍 Testing ONVIF WSDL Path Detection")
    print("=" * 40)
    
    # Test the same logic as in the ONVIF camera
    potential_paths = [
        f'/opt/sai-cam/venv/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages/wsdl/',
        '/opt/sai-cam/venv/lib/python3.4/site-packages/wsdl/',  # Legacy path from working script
        f'/opt/sai-cam/venv/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages/onvif/wsdl/',
        # Additional common paths
        '/usr/local/lib/python3*/site-packages/wsdl/',
        './venv/lib/python3*/site-packages/wsdl/',
    ]
    
    print(f"Python version: {sys.version_info.major}.{sys.version_info.minor}")
    print(f"Checking {len(potential_paths)} potential WSDL paths...\n")
    
    found_paths = []
    
    for i, path in enumerate(potential_paths, 1):
        print(f"{i}. {path}")
        
        # Handle glob patterns
        paths_to_check = [path]
        if '*' in path:
            matches = glob.glob(path)
            if matches:
                paths_to_check = matches
                print(f"   Glob expansion: {matches}")
        
        for check_path in paths_to_check:
            if os.path.exists(check_path):
                print(f"   ✅ EXISTS: {check_path}")
                found_paths.append(check_path)
                
                # Check if it contains WSDL files
                try:
                    wsdl_files = [f for f in os.listdir(check_path) if f.endswith('.wsdl')]
                    print(f"   📄 WSDL files: {len(wsdl_files)} found")
                    if wsdl_files:
                        print(f"      • {', '.join(wsdl_files[:3])}{'...' if len(wsdl_files) > 3 else ''}")
                except Exception as e:
                    print(f"   ⚠️  Error reading directory: {e}")
                break
            else:
                print(f"   ❌ Not found: {check_path}")
    
    print(f"\n📊 Summary:")
    print(f"   • {len(found_paths)} valid WSDL paths found")
    
    if found_paths:
        print(f"   • Recommended path: {found_paths[0]}")
        return found_paths[0]
    else:
        print("   ⚠️  No WSDL paths found - ONVIF may not work correctly")
        return None

def test_environment_variable():
    """Test environment variable loading"""
    print("\n🔧 Testing Environment Variable Loading")
    print("=" * 40)
    
    # Load .env file if it exists
    env_file = '../.env'
    if os.path.exists(env_file):
        print(f"📄 Loading {env_file}...")
        with open(env_file, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    if key == 'ONVIF_WSDL_PATH':
                        print(f"   • {key}={value}")
                        os.environ[key] = value
    
    # Check environment variable
    wsdl_path = os.getenv('ONVIF_WSDL_PATH')
    if wsdl_path:
        print(f"✅ ONVIF_WSDL_PATH set to: {wsdl_path}")
        if os.path.exists(wsdl_path):
            print(f"✅ Path exists and is accessible")
            return wsdl_path
        else:
            print(f"❌ Path does not exist: {wsdl_path}")
    else:
        print("ℹ️  ONVIF_WSDL_PATH not set in environment")
    
    return None

if __name__ == '__main__':
    print("🧪 ONVIF WSDL Path Testing Tool")
    print("================================\n")
    
    # Test environment variable first
    env_path = test_environment_variable()
    
    # Test auto-detection
    detected_path = test_wsdl_path_detection()
    
    print(f"\n🎯 Final Result:")
    final_path = env_path or detected_path
    if final_path:
        print(f"   ✅ WSDL path resolved to: {final_path}")
        print(f"   🚀 ONVIF cameras should work correctly")
    else:
        print(f"   ❌ No valid WSDL path found")
        print(f"   ⚠️  ONVIF cameras may fail to initialize")
        print(f"\n💡 Suggestions:")
        print(f"   1. Install onvif-zeep: pip install onvif-zeep")
        print(f"   2. Set ONVIF_WSDL_PATH environment variable manually")
        print(f"   3. Check if WSDL files exist in your Python environment")