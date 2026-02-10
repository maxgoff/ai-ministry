import { useState, useEffect, useRef } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import AuthForm from './components/AuthForm';
import { api } from './api';
import './App.css';

function App() {
  // Authentication state
  const [user, setUser] = useState(null);
  const [authChecking, setAuthChecking] = useState(true);

  // App state
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const ministryConfigRef = useRef(null);

  const handleMinistryConfigChange = (config) => {
    ministryConfigRef.current = config;
  };

  // Check for existing token on app load
  useEffect(() => {
    checkAuth();
  }, []);

  // Load conversations when authenticated
  useEffect(() => {
    if (user) {
      loadConversations();
    }
  }, [user]);

  // Load conversation details when selected
  useEffect(() => {
    if (currentConversationId) {
      loadConversation(currentConversationId);
    }
  }, [currentConversationId]);

  const loadConversations = async () => {
    try {
      const convs = await api.listConversations();
      setConversations(convs);
    } catch (error) {
      // Handle token expiration gracefully
      if (error.message === 'Not authenticated') {
        handleLogout();
        return;
      }
    }
  };

  const loadConversation = async (id) => {
    try {
      const conv = await api.getConversation(id);
      setCurrentConversation(conv);
    } catch (error) {
      // Handle token expiration gracefully
      if (error.message === 'Not authenticated') {
        handleLogout();
        return;
      }
    }
  };

  const checkAuth = async () => {
    if (!api.isAuthenticated()) {
      setAuthChecking(false);
      return;
    }

    try {
      const userData = await api.getMe();
      setUser(userData);
    } catch {
      // Token expired or invalid - clear it
      api.logout();
    } finally {
      setAuthChecking(false);
    }
  };

  const handleAuthSuccess = async () => {
    try {
      const userData = await api.getMe();
      setUser(userData);
    } catch {
      // This shouldn't happen right after login, but handle it gracefully
      api.logout();
    }
  };

  const handleLogout = () => {
    api.logout();
    setUser(null);
    setConversations([]);
    setCurrentConversationId(null);
    setCurrentConversation(null);
  };

  const handleNewConversation = async () => {
    try {
      const newConv = await api.createConversation();
      setConversations([
        { id: newConv.id, created_at: newConv.created_at, message_count: 0 },
        ...conversations,
      ]);
      setCurrentConversationId(newConv.id);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = (id) => {
    setCurrentConversationId(id);
  };

  const handleSendMessage = async (content) => {
    if (!currentConversationId) return;

    setIsLoading(true);
    try {
      // Optimistically add user message to UI
      const userMessage = { role: 'user', content };
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, userMessage],
      }));

      // Create a partial assistant message that will be updated progressively
      const assistantMessage = {
        role: 'assistant',
        stage0: null,
        stage1: null,
        stage2: null,
        stage3: null,
        metadata: null,
        loading: {
          stage0: false,
          stage1: false,
          stage2: false,
          stage3: false,
        },
      };

      // Add the partial assistant message
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, assistantMessage],
      }));

      // Send message with streaming
      await api.sendMessageStream(currentConversationId, content, (eventType, event) => {
        switch (eventType) {
          case 'stage0_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage0 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage0_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage0 = event.data;
              lastMsg.loading.stage0 = false;
              return { ...prev, messages };
            });
            break;

          case 'stage1_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage1 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage1_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage1 = event.data;
              lastMsg.loading.stage1 = false;
              return { ...prev, messages };
            });
            break;

          case 'stage2_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage2 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage2_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage2 = event.data;
              lastMsg.metadata = event.metadata;
              lastMsg.loading.stage2 = false;
              return { ...prev, messages };
            });
            break;

          case 'stage3_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage3 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage3_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage3 = event.data;
              lastMsg.loading.stage3 = false;
              return { ...prev, messages };
            });
            break;

          case 'title_complete':
            // Reload conversations to get updated title
            loadConversations();
            break;

          case 'complete':
            // Stream complete, reload conversations list
            loadConversations();
            setIsLoading(false);
            break;

          case 'error':
            console.error('Stream error:', event.message);
            setIsLoading(false);
            break;

          default:
            console.log('Unknown event type:', eventType);
        }
      }, ministryConfigRef.current);
    } catch (error) {
      console.error('Failed to send message:', error);
      // Remove optimistic messages on error
      setCurrentConversation((prev) => ({
        ...prev,
        messages: prev.messages.slice(0, -2),
      }));
      setIsLoading(false);
    }
  };

  // Show loading state while checking authentication
  if (authChecking) {
    return (
      <div className="app app-loading">
        <div className="loading-spinner">Loading...</div>
      </div>
    );
  }

  // Show auth form when not authenticated
  if (!user) {
    return <AuthForm onAuthSuccess={handleAuthSuccess} />;
  }

  // Show main app when authenticated
  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        onMinistryConfigChange={handleMinistryConfigChange}
        user={user}
        onLogout={handleLogout}
      />
      <ChatInterface
        conversation={currentConversation}
        onSendMessage={handleSendMessage}
        isLoading={isLoading}
      />
    </div>
  );
}

export default App;
