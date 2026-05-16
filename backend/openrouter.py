"""OpenRouter API client for making LLM requests."""

import asyncio
import httpx
from typing import List, Dict, Any, Optional
from .config import OPENROUTER_API_KEY, OPENROUTER_API_URL, XAI_API_KEY, XAI_API_URL

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY = 1.0  # seconds
MAX_DELAY = 30.0  # seconds

# HTTP status codes that warrant a retry
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def _is_retryable_error(error: Exception) -> bool:
    """Check if an error is transient and worth retrying."""
    if isinstance(error, httpx.TimeoutException):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in RETRYABLE_STATUS_CODES
    if isinstance(error, (httpx.ConnectError, httpx.ReadError)):
        return True
    return False


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 600.0,
    max_retries: int = MAX_RETRIES
) -> Optional[Dict[str, Any]]:
    """
    Query a single model via OpenRouter API with exponential backoff.

    Args:
        model: OpenRouter model identifier (e.g., "openai/gpt-4o")
        messages: List of message dicts with 'role' and 'content'
        timeout: Request timeout in seconds
        max_retries: Maximum number of retry attempts

    Returns:
        Response dict with 'content' and optional 'reasoning_details', or None if failed
    """
    # Route xai/ prefixed models directly to x.ai API
    if model.startswith("xai/"):
        api_url = XAI_API_URL
        api_key = XAI_API_KEY
        api_model = model[len("xai/"):]  # Strip prefix for native model name
    else:
        api_url = OPENROUTER_API_URL
        api_key = OPENROUTER_API_KEY
        api_model = model

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": api_model,
        "messages": messages,
    }

    last_error = None

    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    api_url,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()

                data = response.json()
                message = data['choices'][0]['message']

                # Handle reasoning models (like Kimi K2 Thinking) that return content
                # in reasoning_content instead of content
                content = message.get('content') or ''
                reasoning_content = message.get('reasoning_content') or ''

                # Also check provider_specific_fields for reasoning_content
                provider_fields = message.get('provider_specific_fields', {})
                if not reasoning_content and provider_fields:
                    reasoning_content = provider_fields.get('reasoning_content') or ''

                # For reasoning models, use reasoning_content as the main content if content is empty
                if not content and reasoning_content:
                    content = reasoning_content

                return {
                    'content': content,
                    'reasoning_content': reasoning_content,
                    'reasoning_details': message.get('reasoning_details')
                }

        except Exception as e:
            last_error = e

            if attempt < max_retries and _is_retryable_error(e):
                delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                print(f"[Retry] {model} attempt {attempt + 1}/{max_retries + 1} failed: {e}. Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
            else:
                break

    print(f"[Error] {model} failed after {max_retries + 1} attempts: {last_error}")
    return None


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]]
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Query multiple models in parallel.

    Args:
        models: List of OpenRouter model identifiers
        messages: List of message dicts to send to each model

    Returns:
        Dict mapping model identifier to response dict (or None if failed)
    """
    # Create tasks for all models
    tasks = [query_model(model, messages) for model in models]

    # Wait for all to complete, capturing exceptions instead of raising
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    # Map models to their responses, converting exceptions to None
    result = {}
    for model, response in zip(models, responses):
        if isinstance(response, Exception):
            print(f"[Error] Unexpected exception for {model}: {response}")
            result[model] = None
        else:
            result[model] = response

    return result
