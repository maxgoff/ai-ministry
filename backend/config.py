"""Configuration for the AI Ministry."""

import os
from dotenv import load_dotenv

load_dotenv()

# LLM API Configuration
# Supports both LiteLLM (local) and OpenRouter (cloud)
# Set LLM_API_URL to switch between them:
#   - LiteLLM (local):  http://localhost:4000/chat/completions
#   - OpenRouter:       https://openrouter.ai/api/v1/chat/completions
LLM_API_URL = os.getenv("LLM_API_URL", "http://localhost:4000/chat/completions")
LLM_API_KEY = os.getenv("LLM_API_KEY", "sk-litellm-master-key")

# Legacy OpenRouter support (fallback if LLM_API_KEY not set)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") or LLM_API_KEY
OPENROUTER_API_URL = LLM_API_URL

# All available models (for health checking and selection)
AVAILABLE_MODELS = [
    "openai/gpt-4.1",
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "google/gemini-3-pro",
    "google/gemini-2.5-pro",
    "google/gemini-2.5-flash",
    "anthropic/claude-opus-4.5",
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-sonnet-4",
    "anthropic/claude-3.5-sonnet",
    "anthropic/claude-opus-4",
    "moonshot/kimi-k2-thinking",
    "x-ai/grok-4.1",
    "x-ai/grok-2",
]

# Default ministry members - list of model identifiers (provider/model format)
DEFAULT_MINISTRY_MODELS = [
    "openai/gpt-4.1",
    "google/gemini-3-pro",
    "anthropic/claude-opus-4.5",
    "moonshot/kimi-k2-thinking",
    "x-ai/grok-4.1",
]

# Legacy alias for backward compatibility
COUNCIL_MODELS = DEFAULT_MINISTRY_MODELS

# Default Prime Minister model - synthesizes final response
DEFAULT_PRIME_MINISTER = "google/gemini-3-pro"

# Legacy alias for backward compatibility
CHAIRMAN_MODEL = DEFAULT_PRIME_MINISTER

# Data directory for conversation storage
DATA_DIR = "data/conversations"

# Available personas for role cycling technique
# Each persona provides a unique analytical lens to maximize perspective diversity
AVAILABLE_PERSONAS = {
    "analytical_strategist": {
        "name": "Analytical Strategist",
        "instruction": "You approach problems with structured analysis, identifying trade-offs, practical implementation paths, and clear decision frameworks."
    },
    "systems_thinker": {
        "name": "Systems Thinker",
        "instruction": "You focus on interconnections, edge cases, scalability considerations, and how solutions behave across different contexts and scales."
    },
    "principled_reasoner": {
        "name": "Principled Reasoner",
        "instruction": "You reason from first principles, considering ethical implications, nuanced consequences, and the deeper 'why' behind recommendations."
    },
    "deep_analyst": {
        "name": "Deep Analyst",
        "instruction": "You apply extended reasoning and thorough exploration, especially for complex or technical topics requiring careful step-by-step analysis."
    },
    "unconventional_thinker": {
        "name": "Unconventional Thinker",
        "instruction": "You bring fresh perspectives and challenge conventional wisdom, identifying overlooked angles and providing candid, direct assessments."
    },
    "devil_advocate": {
        "name": "Devil's Advocate",
        "instruction": "You challenge assumptions and highlight potential flaws, risks, and counterarguments to strengthen the overall analysis."
    },
    "pragmatic_implementer": {
        "name": "Pragmatic Implementer",
        "instruction": "You focus on practical execution, feasibility, resource requirements, and real-world constraints that affect implementation."
    },
}

# Default model-to-persona mapping
DEFAULT_MODEL_PERSONAS = {
    "openai/gpt-4.1": "analytical_strategist",
    "google/gemini-3-pro": "systems_thinker",
    "anthropic/claude-opus-4.5": "principled_reasoner",
    "moonshot/kimi-k2-thinking": "deep_analyst",
    "x-ai/grok-4.1": "unconventional_thinker",
}

# Legacy MODEL_PERSONAS format for backward compatibility
MODEL_PERSONAS = {
    model: AVAILABLE_PERSONAS[persona_id]
    for model, persona_id in DEFAULT_MODEL_PERSONAS.items()
}
