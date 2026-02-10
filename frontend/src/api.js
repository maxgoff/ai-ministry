/**
 * API client for the AI Ministry backend.
 */

const API_BASE = 'http://localhost:8001';
const TOKEN_KEY = 'ai_ministry_auth_token';

/**
 * Get the stored authentication token from localStorage.
 * @returns {string|null} The JWT token or null if not authenticated
 */
function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * Store the authentication token in localStorage.
 * @param {string} token - The JWT token to store
 */
function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

/**
 * Remove the authentication token from localStorage.
 */
function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

/**
 * Get the Authorization header for authenticated requests.
 * @returns {object} Headers object with Authorization if token exists
 */
export function getAuthHeader() {
  const token = getToken();
  if (token) {
    return { Authorization: `Bearer ${token}` };
  }
  return {};
}

export const api = {
  /**
   * Check if user is currently authenticated (has token).
   * @returns {boolean} True if token exists in localStorage
   */
  isAuthenticated() {
    return !!getToken();
  },

  /**
   * Register a new user account.
   * @param {string} email - User email address
   * @param {string} password - User password
   * @returns {Promise<{access_token: string, token_type: string}>}
   */
  async register(email, password) {
    const response = await fetch(`${API_BASE}/api/auth/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email, password }),
    });
    if (!response.ok) {
      if (response.status === 400) {
        const error = await response.json();
        throw new Error(error.detail || 'Email already registered');
      }
      if (response.status === 422) {
        throw new Error('Invalid email format');
      }
      throw new Error('Registration failed');
    }
    const data = await response.json();
    setToken(data.access_token);
    return data;
  },

  /**
   * Login with email and password.
   * @param {string} email - User email address
   * @param {string} password - User password
   * @returns {Promise<{access_token: string, token_type: string}>}
   */
  async login(email, password) {
    const response = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email, password }),
    });
    if (!response.ok) {
      if (response.status === 401) {
        throw new Error('Invalid email or password');
      }
      if (response.status === 422) {
        throw new Error('Invalid email format');
      }
      throw new Error('Login failed');
    }
    const data = await response.json();
    setToken(data.access_token);
    return data;
  },

  /**
   * Logout the current user by clearing the stored token.
   */
  logout() {
    clearToken();
  },

  /**
   * Get the current authenticated user's profile.
   * @returns {Promise<{id: string, email: string, created_at: string}>}
   */
  async getMe() {
    const response = await fetch(`${API_BASE}/api/auth/me`, {
      headers: {
        ...getAuthHeader(),
      },
    });
    if (!response.ok) {
      if (response.status === 401) {
        clearToken();
        throw new Error('Not authenticated');
      }
      throw new Error('Failed to get user profile');
    }
    return response.json();
  },

  /**
   * Get available models, personas, and default configuration.
   */
  async getConfig() {
    const response = await fetch(`${API_BASE}/api/config`);
    if (!response.ok) {
      throw new Error('Failed to get config');
    }
    return response.json();
  },

  /**
   * Check health status of all available models.
   * Requires authentication.
   */
  async checkModelsHealth() {
    const response = await fetch(`${API_BASE}/api/models/health`, {
      headers: {
        ...getAuthHeader(),
      },
    });
    if (!response.ok) {
      if (response.status === 401) {
        clearToken();
        throw new Error('Not authenticated');
      }
      throw new Error('Failed to check models health');
    }
    return response.json();
  },

  /**
   * List all conversations for the authenticated user.
   * Requires authentication.
   */
  async listConversations() {
    const response = await fetch(`${API_BASE}/api/conversations`, {
      headers: {
        ...getAuthHeader(),
      },
    });
    if (!response.ok) {
      if (response.status === 401) {
        clearToken();
        throw new Error('Not authenticated');
      }
      throw new Error('Failed to list conversations');
    }
    return response.json();
  },

  /**
   * Create a new conversation for the authenticated user.
   * Requires authentication.
   */
  async createConversation() {
    const response = await fetch(`${API_BASE}/api/conversations`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeader(),
      },
      body: JSON.stringify({}),
    });
    if (!response.ok) {
      if (response.status === 401) {
        clearToken();
        throw new Error('Not authenticated');
      }
      throw new Error('Failed to create conversation');
    }
    return response.json();
  },

  /**
   * Get a specific conversation owned by the authenticated user.
   * Requires authentication.
   */
  async getConversation(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}`,
      {
        headers: {
          ...getAuthHeader(),
        },
      }
    );
    if (!response.ok) {
      if (response.status === 401) {
        clearToken();
        throw new Error('Not authenticated');
      }
      if (response.status === 404) {
        throw new Error('Conversation not found');
      }
      throw new Error('Failed to get conversation');
    }
    return response.json();
  },

  /**
   * Send a message in a conversation.
   * Requires authentication and ownership of the conversation.
   */
  async sendMessage(conversationId, content) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/message`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeader(),
        },
        body: JSON.stringify({ content }),
      }
    );
    if (!response.ok) {
      if (response.status === 401) {
        clearToken();
        throw new Error('Not authenticated');
      }
      if (response.status === 404) {
        throw new Error('Conversation not found');
      }
      throw new Error('Failed to send message');
    }
    return response.json();
  },

  /**
   * Send a message and receive streaming updates.
   * Requires authentication and ownership of the conversation.
   * @param {string} conversationId - The conversation ID
   * @param {string} content - The message content
   * @param {function} onEvent - Callback function for each event: (eventType, data) => void
   * @param {object} ministryConfig - Optional ministry configuration
   * @returns {Promise<void>}
   */
  async sendMessageStream(conversationId, content, onEvent, ministryConfig = null) {
    const body = { content };
    if (ministryConfig) {
      body.ministry_config = ministryConfig;
    }

    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/message/stream`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeader(),
        },
        body: JSON.stringify(body),
      }
    );

    if (!response.ok) {
      if (response.status === 401) {
        clearToken();
        throw new Error('Not authenticated');
      }
      if (response.status === 404) {
        throw new Error('Conversation not found');
      }
      throw new Error('Failed to send message');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value);
      const lines = chunk.split('\n');

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          try {
            const event = JSON.parse(data);
            onEvent(event.type, event);
          } catch (e) {
            console.error('Failed to parse SSE event:', e);
          }
        }
      }
    }
  },

  /**
   * Export a conversation as Markdown.
   * Requires authentication and ownership of the conversation.
   * @param {string} conversationId - The conversation ID
   * @returns {Promise<void>} - Triggers file download
   */
  async exportMarkdown(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/export/markdown`,
      {
        headers: {
          ...getAuthHeader(),
        },
      }
    );
    if (!response.ok) {
      if (response.status === 401) {
        clearToken();
        throw new Error('Not authenticated');
      }
      if (response.status === 404) {
        throw new Error('Conversation not found');
      }
      throw new Error('Failed to export conversation');
    }

    // Get filename from Content-Disposition header
    const contentDisposition = response.headers.get('Content-Disposition');
    let filename = 'conversation.md';
    if (contentDisposition) {
      const match = contentDisposition.match(/filename="(.+)"/);
      if (match) filename = match[1];
    }

    // Download the file
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  /**
   * Export a conversation as PDF.
   * Requires authentication and ownership of the conversation.
   * @param {string} conversationId - The conversation ID
   * @returns {Promise<void>} - Triggers file download
   */
  async exportPDF(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/export/pdf`,
      {
        headers: {
          ...getAuthHeader(),
        },
      }
    );
    if (!response.ok) {
      if (response.status === 401) {
        clearToken();
        throw new Error('Not authenticated');
      }
      if (response.status === 404) {
        throw new Error('Conversation not found');
      }
      if (response.status === 501) {
        throw new Error('PDF export is not available. The server needs additional packages installed.');
      }
      throw new Error('Failed to export conversation');
    }

    // Get filename from Content-Disposition header
    const contentDisposition = response.headers.get('Content-Disposition');
    let filename = 'conversation.pdf';
    if (contentDisposition) {
      const match = contentDisposition.match(/filename="(.+)"/);
      if (match) filename = match[1];
    }

    // Download the file
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },
};
