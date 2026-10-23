import React, { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import ScreenQueue from './components/ScreenQueue';
import ScreenDetail from './components/ScreenDetail';

export default function App() {
  const [currentScreen, setCurrentScreen] = useState('queue'); // 'queue' | 'detail'
  const [selectedId, setSelectedId] = useState(null);
  const [stats, setStats] = useState(null);
  const [handoffs, setHandoffs] = useState([]);
  const [conversationDetail, setConversationDetail] = useState(null);
  const [loading, setLoading] = useState(true);

  // Fetch queue data
  const fetchQueue = async () => {
    try {
      const res = await fetch('/api/queue');
      if (res.ok) {
        const data = await res.json();
        setStats(data.stats);
        setHandoffs(data.handoffs || []);
      }
    } catch (err) {
      console.error('Failed to fetch queue:', err);
    } finally {
      setLoading(false);
    }
  };

  // Fetch conversation detail
  const fetchConversation = async (id) => {
    try {
      const res = await fetch(`/api/conversations/${id}`);
      if (res.ok) {
        const data = await res.json();
        setConversationDetail(data);
        setSelectedId(id);
        setCurrentScreen('detail');
        window.location.hash = id;
      }
    } catch (err) {
      console.error(`Failed to fetch conversation ${id}:`, err);
    }
  };

  // Handle resolve handoff
  const handleResolve = async (id) => {
    try {
      const res = await fetch(`/api/handoffs/${id}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ resolved_by: 'front_desk_staff' }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.stats) {
          setStats(data.stats);
        }
        // Update local handoff status
        setHandoffs((prev) =>
          prev.map((h) => (h.id === id ? { ...h, resolved: true } : h))
        );
      }
    } catch (err) {
      console.error(`Failed to resolve handoff ${id}:`, err);
    }
  };

  // Reset demo queue
  const handleResetQueue = async () => {
    try {
      const res = await fetch('/api/queue/reset', { method: 'POST' });
      if (res.ok) {
        await fetchQueue();
      }
    } catch (err) {
      console.error('Failed to reset queue:', err);
    }
  };

  useEffect(() => {
    fetchQueue();

    // Support deep link via hash e.g. #cv_4471
    const hash = window.location.hash.replace('#', '');
    if (hash) {
      fetchConversation(hash);
    }

    const onHashChange = () => {
      const h = window.location.hash.replace('#', '');
      if (h) {
        fetchConversation(h);
      } else {
        setCurrentScreen('queue');
        setSelectedId(null);
      }
    };

    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const handleBackToQueue = () => {
    setCurrentScreen('queue');
    setSelectedId(null);
    window.location.hash = '';
    fetchQueue();
  };

  return (
    <div className="app-container">
      {/* Sidebar with the 6 icons */}
      <Sidebar
        currentScreen={currentScreen}
        onSelectQueue={handleBackToQueue}
      />

      {/* Main Workspace */}
      <main className="main-content">
        {currentScreen === 'queue' ? (
          <ScreenQueue
            stats={stats}
            handoffs={handoffs}
            onSelectConversation={(id) => fetchConversation(id)}
            onResolveHandoff={handleResolve}
            onResetQueue={handleResetQueue}
          />
        ) : (
          <ScreenDetail
            conversation={conversationDetail}
            onBack={handleBackToQueue}
          />
        )}
      </main>
    </div>
  );
}
