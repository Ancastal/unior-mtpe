from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, Optional, Any

@dataclass
class EditingSession:
    start_time: datetime
    pause_time: Optional[datetime] = None
    total_paused_time: float = 0.0  # in seconds
    is_paused: bool = False

    def to_dict(self) -> dict:
        """Convert session to dictionary for MongoDB storage"""
        return {
            'start_time': self.start_time,
            'pause_time': self.pause_time,
            'total_paused_time': self.total_paused_time,
            'is_paused': self.is_paused
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'EditingSession':
        """Create session from dictionary (for MongoDB retrieval)"""
        return cls(
            start_time=data['start_time'],
            pause_time=data['pause_time'],
            total_paused_time=data['total_paused_time'],
            is_paused=data['is_paused']
        )

class TimeTracker:
    def __init__(self):
        self.sessions: Dict[int, EditingSession] = {}
    
    def start_segment(self, segment_id: int) -> None:
        """Start tracking time for a segment"""
        if segment_id not in self.sessions:
            self.sessions[segment_id] = EditingSession(start_time=datetime.now())
    
    def pause_segment(self, segment_id: int) -> None:
        """Pause time tracking for a segment"""
        if segment_id in self.sessions and not self.sessions[segment_id].is_paused:
            session = self.sessions[segment_id]
            session.pause_time = datetime.now()
            session.is_paused = True
    
    def resume_segment(self, segment_id: int) -> None:
        """Resume time tracking for a segment"""
        if segment_id in self.sessions and self.sessions[segment_id].is_paused:
            session = self.sessions[segment_id]
            pause_duration = (datetime.now() - session.pause_time).total_seconds()
            session.total_paused_time += pause_duration
            session.is_paused = False
            session.pause_time = None
    
    def get_editing_time(self, segment_id: int) -> float:
        """Get total editing time for a segment in seconds"""
        if segment_id not in self.sessions:
            return 0.0
        
        session = self.sessions[segment_id]
        total_time = (datetime.now() - session.start_time).total_seconds()
        
        # If currently paused, add time until pause
        if session.is_paused:
            active_time = (session.pause_time - session.start_time).total_seconds()
            return active_time - session.total_paused_time
        
        # Otherwise, return total time minus paused time
        return total_time - session.total_paused_time 

    def to_dict(self) -> dict:
        """Convert TimeTracker to dictionary for MongoDB storage"""
        return {
            'sessions': {
                str(k): v.to_dict() for k, v in self.sessions.items()
            }
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'TimeTracker':
        """Create TimeTracker from dictionary (for MongoDB retrieval)"""
        tracker = cls()
        if data and 'sessions' in data:
            tracker.sessions = {
                int(k): EditingSession.from_dict(v) 
                for k, v in data['sessions'].items()
            }
        return tracker