from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, Optional, Any
import streamlit as st

@dataclass
class EditingSession:
    start_time: datetime
    pause_time: Optional[datetime] = None
    total_paused_time: float = 0.0
    is_paused: bool = False
    last_activity: datetime = datetime.now()
    active_time: float = 0.0  # Track actual active editing time
    idle_time: float = 0.0

    def to_dict(self) -> dict:
        return {
            'start_time': self.start_time,
            'pause_time': self.pause_time,
            'total_paused_time': self.total_paused_time,
            'is_paused': self.is_paused,
            'last_activity': self.last_activity,
            'active_time': self.active_time,
            'idle_time': self.idle_time
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'EditingSession':
        return cls(
            start_time=data['start_time'],
            pause_time=data['pause_time'],
            total_paused_time=data['total_paused_time'],
            is_paused=data['is_paused'],
            last_activity=data.get('last_activity', datetime.now()),
            active_time=data.get('active_time', 0.0),
            idle_time=data.get('idle_time', 0.0)
        )

class TimeTracker:
    IDLE_THRESHOLD = 30  # 30 seconds idle threshold

    def __init__(self):
        self.sessions: Dict[int, EditingSession] = {}
    
    def start_segment(self, segment_id: int) -> None:
        """Start tracking time for a segment"""
        current_time = datetime.now()
        if segment_id not in self.sessions:
            self.sessions[segment_id] = EditingSession(
                start_time=current_time,
                last_activity=current_time
            )
    
    def pause_segment(self, segment_id: int) -> None:
        """Pause time tracking for a segment"""
        if segment_id in self.sessions and not self.sessions[segment_id].is_paused:
            session = self.sessions[segment_id]
            current_time = datetime.now()
            
            # Calculate and add active time before pausing
            time_since_last = (current_time - session.last_activity).total_seconds()
            if time_since_last <= self.IDLE_THRESHOLD:
                session.active_time += time_since_last
            
            session.pause_time = current_time
            session.is_paused = True
            session.last_activity = current_time
    
    def resume_segment(self, segment_id: int) -> None:
        """Resume time tracking for a segment"""
        if segment_id in self.sessions and self.sessions[segment_id].is_paused:
            session = self.sessions[segment_id]
            current_time = datetime.now()
            
            if session.pause_time:
                pause_duration = (current_time - session.pause_time).total_seconds()
                session.total_paused_time += pause_duration
            
            session.is_paused = False
            session.pause_time = None
            session.last_activity = current_time
    
    def update_activity(self, segment_id: int) -> None:
        """Update activity tracking"""
        if segment_id in self.sessions:
            session = self.sessions[segment_id]
            current_time = datetime.now()
            
            if not session.is_paused:
                time_since_last = (current_time - session.last_activity).total_seconds()
                
                if time_since_last > self.IDLE_THRESHOLD:
                    # Add to idle time
                    session.idle_time += (time_since_last - self.IDLE_THRESHOLD)
                else:
                    # Add to active time
                    session.active_time += time_since_last
            
            session.last_activity = current_time

    def get_editing_time(self, segment_id: int) -> float:
        """Get actual editing time (excluding idle and paused time)"""
        if segment_id not in self.sessions:
            return 0.0
        
        session = self.sessions[segment_id]
        
        # If not paused, add time since last activity if it's within threshold
        if not session.is_paused:
            current_time = datetime.now()
            time_since_last = (current_time - session.last_activity).total_seconds()
            if time_since_last <= self.IDLE_THRESHOLD:
                return session.active_time + time_since_last
        
        return session.active_time

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

    def check_idle_time(self, segment_id: int) -> None:
        """Periodic idle time check"""
        if segment_id in self.sessions:
            session = self.sessions[segment_id]
            if not session.is_paused:
                current_time = datetime.now()
                time_since_last = (current_time - session.last_activity).total_seconds()
                
                if time_since_last > self.IDLE_THRESHOLD:
                    # Only count new idle time
                    new_idle = time_since_last - self.IDLE_THRESHOLD
                    if new_idle > session.idle_time:
                        additional_idle = new_idle - session.idle_time
                        session.idle_time = new_idle
                        
                        # Only show warning for significant idle time
                        if additional_idle >= 60:  # Show warning for 1+ minute
                            minutes = int(additional_idle // 60)
                            seconds = int(additional_idle % 60)
                            time_msg = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
                            st.warning(f"⚠️ Idle time detected: {time_msg}", icon="⚠️")