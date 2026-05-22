"""
Utility functions for voice agent
"""
import os
import requests
import json
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class OllamaClient:
    """Helper class to interact with Ollama API"""
    
    def __init__(self, api_url: str = None):
        self.api_url = api_url or os.getenv("OLLAMA_API_URL", "http://localhost:11434")
    
    def is_running(self) -> bool:
        """Check if Ollama is running"""
        try:
            response = requests.get(f"{self.api_url}/api/tags", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def get_models(self) -> list:
        """Get list of available models"""
        try:
            response = requests.get(f"{self.api_url}/api/tags", timeout=5)
            models = response.json().get("models", [])
            return [m.get("name") for m in models]
        except Exception as e:
            logger.error(f"Error fetching models: {e}")
            return []
    
    def model_exists(self, model_name: str) -> bool:
        """Check if model is available"""
        models = self.get_models()
        return any(model_name in m for m in models)
    
    def generate(self, prompt: str, model: str, system: str = "", **kwargs) -> str:
        """Generate text response from model"""
        try:
            payload = {
                "model": model,
                "prompt": prompt,
                "system": system,
                "stream": False,
                "temperature": kwargs.get("temperature", 0.7),
                "top_p": kwargs.get("top_p", 0.9),
                "top_k": kwargs.get("top_k", 40),
            }
            
            response = requests.post(
                f"{self.api_url}/api/generate",
                json=payload,
                timeout=60
            )
            
            if response.status_code == 200:
                return response.json().get("response", "").strip()
            else:
                logger.error(f"Ollama error: {response.status_code}")
                return ""
        except Exception as e:
            logger.error(f"Generation error: {e}")
            return ""

class AudioHelper:
    """Helper functions for audio processing"""
    
    @staticmethod
    def normalize_audio(audio_bytes: bytes) -> bytes:
        """Normalize audio levels"""
        import numpy as np
        audio_data = np.frombuffer(audio_bytes, dtype=np.int16)
        # Simple normalization
        max_val = np.max(np.abs(audio_data))
        if max_val > 0:
            audio_data = (audio_data / max_val * 32767).astype(np.int16)
        return audio_data.tobytes()
    
    @staticmethod
    def get_audio_duration(audio_bytes: bytes, sample_rate: int = 16000) -> float:
        """Calculate audio duration in seconds"""
        num_samples = len(audio_bytes) // 2  # 16-bit = 2 bytes
        return num_samples / sample_rate
