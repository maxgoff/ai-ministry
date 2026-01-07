"""Configuration for the AI Ministry.

Configuration is loaded from ministry_config.yaml if present,
otherwise falls back to hardcoded defaults.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv

load_dotenv()


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""

    pass


def _require_env_var(
    var_name: str,
    description: Optional[str] = None
) -> str:
    """
    Validate that a required environment variable is set.

    Args:
        var_name: The name of the environment variable to check
        description: Optional description of what this variable is for,
                     used in error messaging

    Returns:
        The value of the environment variable

    Raises:
        ConfigurationError: If the environment variable is not set or is empty
    """
    value = os.getenv(var_name)

    if value is None or value.strip() == "":
        desc_text = f" ({description})" if description else ""
        raise ConfigurationError(
            f"Required environment variable '{var_name}'{desc_text} is not set.\n\n"
            f"To fix this:\n"
            f"  1. Create a .env file in the project root (copy from .env.example)\n"
            f"  2. Set {var_name}=your_value in the .env file\n"
            f"  3. Or set it as an environment variable: export {var_name}=your_value"
        )

    return value

# Find config file (check project root)
CONFIG_PATH = Path(__file__).parent.parent / "ministry_config.yaml"


def _load_yaml_config() -> Dict[str, Any]:
    """Load configuration from YAML file if it exists."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


# Load YAML config once at module import
_yaml_config = _load_yaml_config()

# LLM API Configuration
# Supports both LiteLLM (local) and OpenRouter (cloud)
_api_config = _yaml_config.get("api", {})
LLM_API_URL = os.getenv(
    "LLM_API_URL",
    _api_config.get("url", "http://localhost:4000/chat/completions")
)
LLM_API_KEY = _require_env_var("LLM_API_KEY", "API key for LLM service")

# Legacy OpenRouter support (fallback if LLM_API_KEY not set)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") or LLM_API_KEY
OPENROUTER_API_URL = LLM_API_URL

# Hardcoded defaults (used if YAML not present)
_DEFAULT_AVAILABLE_MODELS = [
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

_DEFAULT_MINISTRY_MODELS = [
    "openai/gpt-4.1",
    "google/gemini-3-pro",
    "anthropic/claude-opus-4.5",
    "moonshot/kimi-k2-thinking",
    "x-ai/grok-4.1",
]

_DEFAULT_PERSONAS = {
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

_DEFAULT_MODEL_PERSONA_MAP = {
    "openai/gpt-4.1": "analytical_strategist",
    "google/gemini-3-pro": "systems_thinker",
    "anthropic/claude-opus-4.5": "principled_reasoner",
    "moonshot/kimi-k2-thinking": "deep_analyst",
    "x-ai/grok-4.1": "unconventional_thinker",
}

# Load from YAML or use defaults
AVAILABLE_MODELS: List[str] = _yaml_config.get("available_models", _DEFAULT_AVAILABLE_MODELS)
AVAILABLE_PERSONAS: Dict[str, Dict[str, str]] = _yaml_config.get("personas", _DEFAULT_PERSONAS)


# Parse ministry members from YAML format
def _parse_ministry_members() -> tuple[List[str], Dict[str, str]]:
    """Parse ministry_members from YAML into model list and persona mapping."""
    yaml_members = _yaml_config.get("ministry_members", [])
    if not yaml_members:
        return _DEFAULT_MINISTRY_MODELS, _DEFAULT_MODEL_PERSONA_MAP

    models = []
    persona_map = {}
    for member in yaml_members:
        model_id = member.get("id") if isinstance(member, dict) else member
        models.append(model_id)
        if isinstance(member, dict) and "persona" in member:
            persona_map[model_id] = member["persona"]

    return models, persona_map


DEFAULT_MINISTRY_MODELS, DEFAULT_MODEL_PERSONAS = _parse_ministry_members()

# Legacy alias for backward compatibility
COUNCIL_MODELS = DEFAULT_MINISTRY_MODELS

# Prime Minister model - synthesizes final response
DEFAULT_PRIME_MINISTER = _yaml_config.get("prime_minister", "google/gemini-3-pro")

# Legacy alias for backward compatibility
CHAIRMAN_MODEL = DEFAULT_PRIME_MINISTER

# Data directory for conversation storage
DATA_DIR = "data/conversations"

# Legacy MODEL_PERSONAS format for backward compatibility
MODEL_PERSONAS = {
    model: AVAILABLE_PERSONAS.get(persona_id, _DEFAULT_PERSONAS.get(persona_id, {}))
    for model, persona_id in DEFAULT_MODEL_PERSONAS.items()
}

# Log config source on import
if CONFIG_PATH.exists():
    print(f"[Config] Loaded from {CONFIG_PATH}")
else:
    print("[Config] Using hardcoded defaults (no ministry_config.yaml found)")
