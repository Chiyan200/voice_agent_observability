#!/usr/bin/env python
"""
Quick test script to verify the voice agent setup is working correctly.
"""
import subprocess
import sys
import time
import requests
import json
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_dependencies():
    """Check if all required dependencies are installed."""
    print("\n📦 Checking dependencies...")
    
    required = {
        'fastapi': 'FastAPI',
        'websockets': 'WebSockets',
        'faster_whisper': 'Faster Whisper',
        'gtts': 'Google Text-to-Speech',
        'requests': 'Requests',
        'numpy': 'NumPy',
    }
    
    missing = []
    for module, name in required.items():
        try:
            __import__(module)
            print(f"  ✅ {name}")
        except ImportError:
            print(f"  ❌ {name}")
            missing.append(module)
    
    if missing:
        print(f"\n⚠️  Missing dependencies: {', '.join(missing)}")
        print("\nInstall them with:")
        print(f"  pip install {' '.join(missing)}")
        return False
    
    print("\n✅ All dependencies installed!")
    return True

def check_server_running():
    """Check if server is running on localhost:8000."""
    print("\n🔍 Checking if server is running...")
    
    try:
        response = requests.get("http://localhost:8000/health", timeout=2)
        if response.status_code == 200:
            print("  ✅ Server is running on http://localhost:8000")
            return True
    except requests.exceptions.ConnectionError:
        print("  ❌ Cannot connect to server on localhost:8000")
        print("\n     Start the server with:")
        print("     python server.py")
        return False
    except requests.exceptions.Timeout:
        print("  ⏱️  Server connection timeout")
        return False
    except Exception as e:
        print(f"  ⚠️  Error: {e}")
        return False

def test_tts():
    """Test if TTS is working."""
    print("\n🔊 Testing Text-to-Speech...")
    
    try:
        from gtts import gTTS
        import io
        
        test_text = "Hello, this is a test of the text to speech system."
        print(f"  Converting: '{test_text}'")
        
        tts = gTTS(text=test_text, lang='en')
        audio_buffer = io.BytesIO()
        tts.write_to_fp(audio_buffer)
        audio_size = len(audio_buffer.getvalue())
        
        print(f"  ✅ TTS working! Generated {audio_size} bytes of audio")
        return True
        
    except ImportError:
        print("  ❌ gTTS not installed")
        print("     Install with: pip install gtts")
        return False
    except Exception as e:
        print(f"  ❌ TTS error: {e}")
        print("     Make sure you have internet connection")
        return False

def test_whisper():
    """Test if Whisper is working."""
    print("\n🎤 Testing Speech Recognition (Whisper)...")
    
    try:
        from faster_whisper import WhisperModel
        
        # Try to load the model
        print("  Loading Whisper model (may take a moment)...")
        try:
            model = WhisperModel("tiny", device="cuda", compute_type="float16")
            print("  ✅ Whisper loaded with CUDA")
        except:
            print("  ℹ️  CUDA not available, using CPU")
            model = WhisperModel("tiny", device="cpu", compute_type="int8")
        
        print("  ✅ Whisper model loaded successfully")
        return True
        
    except ImportError:
        print("  ❌ faster_whisper not installed")
        print("     Install with: pip install faster-whisper")
        return False
    except Exception as e:
        print(f"  ⚠️  Whisper error: {e}")
        return False

def test_ollama():
    """Test if Ollama is running."""
    print("\n🦙 Testing Ollama LLM...")
    
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            models = data.get("models", [])
            if models:
                print(f"  ✅ Ollama running with {len(models)} model(s)")
                for model in models[:3]:  # Show first 3 models
                    print(f"     - {model.get('name', 'Unknown')}")
                return True
            else:
                print("  ⚠️  Ollama running but no models installed")
                return False
    except requests.exceptions.ConnectionError:
        print("  ❌ Cannot connect to Ollama on localhost:11434")
        print("\n     Start Ollama with: ollama serve")
        print("     Then pull a model: ollama pull qwen2.5:7b-instruct-q4_K_M")
        return False
    except Exception as e:
        print(f"  ⚠️  Ollama error: {e}")
        return False

def run_tests():
    """Run all tests."""
    print("=" * 60)
    print("🚀 Voice Agent Setup Verification")
    print("=" * 60)
    
    results = {
        'dependencies': check_dependencies(),
        'tts': test_tts(),
        'whisper': test_whisper(),
        'ollama': test_ollama(),
        'server': check_server_running(),
    }
    
    print("\n" + "=" * 60)
    print("📊 Summary")
    print("=" * 60)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {test_name.upper()}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n🎉 All tests passed! Your setup is ready to go.")
        print("\nTo start using the voice agent:")
        print("  1. Make sure Ollama is running: ollama serve")
        print("  2. Start the server: python server.py")
        print("  3. Open browser: http://localhost:8000")
        print("  4. Or run test: python test_websocket.py")
    else:
        print("\n⚠️  Some tests failed. Check the messages above.")
        
        if not results['dependencies']:
            print("\nStep 1: Install missing dependencies")
            print("  pip install -r requirements.txt")
        
        if not results['ollama']:
            print("\nStep 2: Start Ollama")
            print("  ollama serve")
        
        if not results['server']:
            print("\nStep 3: Start the server")
            print("  python server.py")
        
        return False
    
    return True

if __name__ == "__main__":
    try:
        success = run_tests()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
