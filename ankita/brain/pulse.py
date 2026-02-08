"""
Pulse Engine - The proactive heartbeat of A.N.K.I.T.A.
Monitors system, context, and time to trigger autonomous actions or suggestions.
"""
import time
import os
import psutil
from datetime import datetime
try:
    from brain.context_collector import get_current_context
    from brain.learning_db import get_db
    from brain.hybrid_intelligence import get_hybrid_ai
    from executor.executor import execute
except ImportError:
    # Fallback for direct execution
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from brain.context_collector import get_current_context
    from brain.learning_db import get_db
    from brain.hybrid_intelligence import get_hybrid_ai
    from executor.executor import execute

class PulseEngine:
    """
    Background engine that evaluates system health and user context 
    to provide 'Aggressive' proactive support.
    """
    
    def __init__(self, interval_sec=30):
        self.interval = interval_sec
        self.db = get_db()
        self.hybrid_ai = get_hybrid_ai()
        self.last_window = None
        
        # Thresholds for 'Aggressive' actions
        self.thresholds = {
            'cpu_critical': 85.0,
            'ram_critical': 90.0,
            'battery_low': 20.0,
            'idle_time_min': 15
        }
        
        self.last_action_time = {}
        self.running = False

    def start(self):
        """Start the heartbeat loop."""
        print(f"[Pulse] Heartbeat initialized. Interval: {self.interval}s")
        self.running = True
        try:
            while self.running:
                self.beat()
                time.sleep(self.interval)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.running = False
        print("[Pulse] Heartbeat stopped.")

    def beat(self):
        """A single evaluation cycle."""
        context = get_current_context()
        now = datetime.now()
        
        current_window = context.get('active_window_title', 'Unknown')
        # Remove unicode chars that cause encoding issues
        current_window = current_window.encode('ascii', errors='ignore').decode('ascii')
        if current_window != self.last_window:
            print(f"[Pulse] Beat at {now.strftime('%H:%M:%S')} | App: {current_window}")
            self.last_window = current_window
        
        # 0. Check for WhatsApp calls
        self._check_whatsapp_calls()

        # 1. Evaluate System Health (Tier 1: Auto-Optimization)
        self._check_system_health(context)
        
        # 2. Evaluate User Context (Tier 2: Predictive Suggestions)
        self._check_user_context(context)
        
        # 3. Evaluate Temporal Pulse (Tier 3: Habit/Health Nudges)
        self._check_temporal_pulse(now)
        
        # 4. Git Ghost Check (Unique Feature: Auto-Social)
        self._check_git_commits()

    def _check_whatsapp_calls(self):
        """Monitor for incoming WhatsApp calls and notify Krish."""
        if not self._can_perform("wa_call_check", 5): # Check every 5s
            return
            
        try:
            from tools.social import whatsapp
            # Use _ensure_page to get handle to WhatsApp Web
            page = whatsapp._ensure_page(headless=False)
            caller = whatsapp.check_incoming_call(page)
            
            if caller:
                msg = f"Sir, you have an incoming WhatsApp call from {caller}. Should I engage and discuss with them?"
                print(f"[Pulse] 📲 Incoming Call: {caller}")
                
                # Send notification
                self._run_tool("system.notification.send", {
                    "title": "Incoming WhatsApp Call",
                    "message": msg
                })
                
                # Speak notification
                try:
                    from ankita_core import speak_with_bargein
                    speak_with_bargein(msg)
                except:
                    pass
        except:
            pass

    def _check_system_health(self, context):
        """Aggressively maintain performance."""
        cpu = context.get('cpu_percent', 0)
        ram = context.get('memory_percent', 0)
        
        # Safe-proactive: if CPU is pegged, suggest an action (do NOT auto-kill)
        if cpu > self.thresholds['cpu_critical']:
            heavy_procs = self._get_heavy_processes()
            if heavy_procs and self._can_perform("cpu_warning", 300):  # 5 min cooldown
                target = heavy_procs[0]  # Top offender
                msg = (
                    f"High CPU detected ({cpu}%). Top offender: {target['name']} ({target.get('cpu_percent', 0)}%). "
                    "Want me to open Task Manager or kill it?"
                )
                print(f"[Pulse] Proactive Warning: {msg}")
                self._run_tool("system.notification.send", {
                    "title": "High CPU",
                    "message": msg,
                })
                # Offer Task Manager (non-destructive)
                self._run_tool("system.processes.manager", {"action": "manager"})
                self._log_pulse_event("nudge", f"Warned high CPU; suggested managing {target['name']}")

    def _check_user_context(self, context):
        """Anticipate needs based on active app."""
        active_app = context.get('active_window_process', '').lower()
        
        # Scenario: Coding detected
        if active_app in ('code', 'pycharm', 'terminal', 'wt'):
            # If we haven't suggested focus mode in 1 hour
            if self._can_perform("suggest_focus", 3600):
                print("[Pulse] Nudge: User is coding. Suggesting Deep Work mode.")
                self._run_tool("system.notification.send", {
                    "title": "Deep Work Detected",
                    "message": "Sir, you're locked in. Should I enable Focus Mode?"
                })
                self._log_pulse_event("nudge", "Offered Focus Mode for coding session")

    def _check_temporal_pulse(self, now):
        """Time-based logic (e.g. Ghaziabad late night)."""
        # Late Night Ghaziabad logic (1 AM - 5 AM)
        if now.hour >= 1 and now.hour < 5:
            if self._can_perform("late_night_care", 7200):
                print("[Pulse] Aggressive Care: It's late. Enabling Night Light and dimming screen.")
                self._run_tool("system.nightlight.on", {})
                self._run_tool("system.brightness.down", {})
                self._run_tool("system.notification.send", {
                    "title": "Night Owl Mode",
                    "message": "It's late in Ghaziabad. Dimming screen for your eyes, Sir."
                })
                self._log_pulse_event("auto_optimize", "Late night optimization applied")

    def _check_git_commits(self):
        """Unique: Watch for code commits and auto-socialize."""
        if not self._can_perform("git_ghost_check", 60): # Every 60s
            return
            
        try:
            from tools.social.git_ghost import run as ghost_run
            result = ghost_run(action="check")
            
            if result.get("status") == "success" and "New commit detected" in result.get("message", ""):
                caption = result.get("draft_caption", "")
                print(f"[Pulse] Ghost Committer: Posting new commit to Instagram...")
                
                # Auto-Socialize!
                # We'll take a screenshot of the commit as the image
                self._run_tool("system.screenshot.full", {"path": "commit_proof.png"})
                
                # Post to Instagram
                # Note: This is aggressive - it just DOES it.
                self._run_tool("instagram.post", {
                    "file_path": "commit_proof.png",
                    "caption": caption
                })
                
                # Report back to boss
                self._run_tool("system.notification.send", {
                    "title": "A.N.K.I.T.A: Ghost Committer",
                    "message": f"Successfully posted your latest commit to followers: '{result['commit']['message']}'"
                })
                
                self._log_pulse_event("auto_social", f"Posted commit: {result['commit']['hash'][:8]}")
        except Exception as e:
            print(f"[Pulse] Git Ghost Error: {e}")

    def _run_tool(self, tool_name, args):
        """Helper to run executor from within Pulse."""
        try:
            plan = {"steps": [{"tool": tool_name, "args": args}]}
            execute(plan)
        except Exception as e:
            print(f"[Pulse] Tool Error {tool_name}: {e}")

    def _get_heavy_processes(self):
        """Find non-system processes eating resources."""
        procs = []
        for proc in psutil.process_iter(['name', 'cpu_percent']):
            try:
                if proc.info['cpu_percent'] > 30:
                    procs.append(proc.info)
            except: pass
        return sorted(procs, key=lambda x: x['cpu_percent'], reverse=True)

    def _can_perform(self, action_key, cooldown_sec):
        """Check if enough time has passed since last action."""
        last = self.last_action_time.get(action_key, 0)
        if time.time() - last > cooldown_sec:
            self.last_action_time[action_key] = time.time()
            return True
        return False

    def _log_pulse_event(self, type, description):
        """Log event to database for learning."""
        try:
            context = get_current_context()
            context['situation_detected'] = f"pulse_{type}"
            self.db.log_action(
                context=context,
                action=description,
                success=1
            )
        except Exception as e:
            print(f"[Pulse] Failed to log event: {e}")


if __name__ == "__main__":
    # Test run
    engine = PulseEngine(interval_sec=10)
    engine.start()
