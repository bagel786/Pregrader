"""
Session management for multi-step grading workflow.
Handles front + back card image uploads with temporary storage.
"""
import uuid
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from pathlib import Path
import threading


class GradingSession:
    """Represents a single grading session for front + back photos."""
    
    def __init__(self, session_id: str = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.created_at = datetime.now()
        self.expires_at = self.created_at + timedelta(minutes=15)
        
        # Image paths
        self.front_image_path: Optional[str] = None
        self.back_image_path: Optional[str] = None
        
        # Analysis results
        self.front_analysis: Optional[Dict] = None
        self.back_analysis: Optional[Dict] = None
        self.combined_grade: Optional[Dict] = None
        
        # Status tracking
        self.status = "created"  # created, front_uploaded, back_uploaded, analyzing, complete, error
        self.error_message: Optional[str] = None
        
    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.now() > self.expires_at
    
    def to_dict(self) -> Dict:
        """Convert session to dictionary for API responses."""
        return {
            "session_id": self.session_id,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "has_front": self.front_image_path is not None,
            "has_back": self.back_image_path is not None,
            "has_grade": self.combined_grade is not None,
            "error": self.error_message
        }


class SessionManager:
    """
    Manages grading sessions with automatic cleanup.
    Thread-safe for concurrent API access.
    """
    
    def __init__(self, storage_dir: Path):
        self._sessions: Dict[str, GradingSession] = {}
        self._lock = threading.Lock()
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(exist_ok=True)
        
    def create_session(self) -> GradingSession:
        """Create a new grading session."""
        with self._lock:
            session = GradingSession()
            
            # Create session directory
            session_dir = self.storage_dir / session.session_id
            session_dir.mkdir(exist_ok=True)
            
            self._sessions[session.session_id] = session
            return session
    
    def get_session(self, session_id: str) -> Optional[GradingSession]:
        """Get session by ID, returns None if not found or expired."""
        with self._lock:
            session = self._sessions.get(session_id)
            
            if session is None:
                return None
            
            if session.is_expired():
                self._cleanup_session(session_id)
                return None
            
            return session
    
    def update_session(self, session_id: str, **kwargs) -> Optional[GradingSession]:
        """Update session attributes."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            
            for key, value in kwargs.items():
                if hasattr(session, key):
                    setattr(session, key, value)
            
            return session
    
    def delete_session(self, session_id: str) -> bool:
        """Delete a session and clean up files."""
        with self._lock:
            if session_id in self._sessions:
                self._cleanup_session(session_id)
                return True
            return False
    
    def _cleanup_session(self, session_id: str):
        """Clean up session files and remove from memory."""
        import shutil
        
        session_dir = self.storage_dir / session_id
        if session_dir.exists():
            shutil.rmtree(session_dir, ignore_errors=True)
        
        if session_id in self._sessions:
            del self._sessions[session_id]
    
    def cleanup_expired(self) -> int:
        """
        Clean up all expired sessions.
        Returns number of sessions cleaned up.
        """
        with self._lock:
            expired_ids = [
                sid for sid, session in self._sessions.items()
                if session.is_expired()
            ]
            
            for sid in expired_ids:
                self._cleanup_session(sid)
            
            return len(expired_ids)
    
    def get_session_dir(self, session_id: str) -> Path:
        """Get the storage directory for a session."""
        return self.storage_dir / session_id


# Singleton instance for the application
_session_manager: Optional[SessionManager] = None


def get_session_manager(storage_dir: Path = None) -> SessionManager:
    """Get the global session manager instance."""
    global _session_manager
    
    if _session_manager is None:
        if storage_dir is None:
            storage_dir = Path(__file__).parent.parent / "temp_uploads"
        _session_manager = SessionManager(storage_dir)
    
    return _session_manager
