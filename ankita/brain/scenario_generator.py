"""
Scenario Generator - Creates realistic training scenarios for Ankita
"""
import random
from datetime import datetime
try:
    from brain.dynamic_query_generator import DynamicQueryGenerator
    HAS_DYNAMIC = True
except:
    HAS_DYNAMIC = False


class ScenarioGenerator:
    """Generates realistic user interactions across all situations."""
    
    def __init__(self, use_dynamic_queries=True):
        self.scenarios = self._load_scenarios()
        self.use_dynamic = use_dynamic_queries and HAS_DYNAMIC
        
        if self.use_dynamic:
            self.dynamic_gen = DynamicQueryGenerator()
            print("[ScenarioGen] Dynamic query generation enabled! [Rocket]")
    
    def _load_scenarios(self):
        """Define all situation templates with variations."""
        return {
            "hungry": {
                "queries": [
                    "I'm hungry",
                    "I need food",
                    "What should I eat",
                    "I'm starving",
                    "Food delivery near me",
                    "Where can I eat",
                    "I want something to eat",
                    "Feeling hungry",
                    "Order food",
                    "I want pizza"
                ],
                "contexts": {
                    "morning": {"hour": [7, 8, 9, 10], "expected": "breakfast"},
                    "afternoon": {"hour": [12, 13, 14], "expected": "lunch"},
                    "evening": {"hour": [19, 20, 21], "expected": "dinner"}
                },
                "expected_actions": [
                    "food.delivery",       # NEW! Actually order food
                    "web.search",          # Search restaurants
                    "files.downloads",     # Recipe PDFs
                    "notepad.open"         # Shopping list
                ]
            },
            "workout": {
                "queries": [
                    "I want to workout",
                    "Time to exercise",
                    "Start my workout",
                    "Gym time",
                    "Let's workout",
                    "Exercise session"
                ],
                "contexts": {
                    "morning": {"hour": [6, 7, 8], "timer": 20},
                    "evening": {"hour": [17, 18, 19], "timer": 30}
                },
                "expected_actions": ["timer.set", "music.play"]
            },
            "music": {
                "queries": [
                    "Play music",
                    "I want to listen to music",
                    "Play some songs",
                    "Music time",
                    "Turn on music",
                    "Play Spotify",
                    "I want to hear music"
                ],
                "contexts": {
                    "any": {"hour": list(range(6, 23))}
                },
                "expected_actions": [
                    "spotify.play",        # NEW! Spotify
                    "youtube.play",        # YouTube music
                    "youtube.trending"     # Trending music
                ]
            },
            "weather": {
                "queries": [
                    "What's the weather",
                    "Weather today",
                    "Check weather",
                    "How's the weather",
                    "Weather forecast"
                ],
                "contexts": {
                    "morning": {"hour": [6, 7, 8, 9]}
                },
                "expected_actions": ["weather.current"]
            },
            "focus": {
                "queries": [
                    "I need to focus",
                    "Focus mode",
                    "Start focus mode",
                    "I need concentration",
                    "Help me focus",
                    "I need to work",
                    "Enable focus"
                ],
                "contexts": {
                    "work_hours": {"hour": [9, 10, 11, 14, 15, 16]}
                },
                "expected_actions": [
                    "focus.mode",          # NEW! Complete focus
                    "dnd.on",              # Do not disturb
                    "system.app.close",    # Close distractions
                    "timer.set"            # Pomodoro timer
                ]
            },
            "morning": {
                "queries": [
                    "Good morning",
                    "Morning routine",
                    "Start my day",
                    "Morning"
                ],
                "contexts": {
                    "morning": {"hour": [6, 7, 8, 9]}
                },
                "expected_actions": ["weather.current", "calendar.today"]
            },
            "chill": {
                "queries": [
                    "I want to chill",
                    "Relax mode",
                    "Time to relax",
                    "Chill time"
                ],
                "contexts": {
                    "evening": {"hour": [19, 20, 21, 22]}
                },
                "expected_actions": ["youtube.play", "spotify.play"]
            },
            "sick": {
                "queries": [
                    "I'm sick",
                    "I don't feel well",
                    "I have a headache",
                    "I'm not feeling good",
                    "I feel ill",
                    "I need medicine",
                    "Health issue",
                    "I'm feeling unwell"
                ],
                "contexts": {
                    "any_time": {"hour": list(range(0, 24))}
                },
                "expected_actions": [
                    "medicine.reminder",    # NEW! Medicine reminders
                    "web.search",           # Symptoms search
                    "notepad.open",         # Log symptoms
                    "system.brightness.down", # Comfort
                    "system.volume.down"    # Quiet
                ]
            },
            "tired": {
                "queries": [
                    "I'm tired",
                    "I'm sleepy",
                    "Need sleep",
                    "Feeling exhausted",
                    "Want to rest",
                    "Time for bed",
                    "I need rest"
                ],
                "contexts": {
                    "night": {"hour": [21, 22, 23, 0, 1, 2]},
                    "afternoon": {"hour": [14, 15, 16]}
                },
                "expected_actions": [
                    "dnd.on",               # Do not disturb
                    "system.brightness.down", # Dim screen
                    "timer.set",            # Nap alarm
                    "spotify.play",         # Sleep music
                    "system.wifi.off"       # Disconnect
                ]
            },
            "stressed": {
                "queries": [
                    "I'm stressed",
                    "I feel anxious",
                    "I'm overwhelmed",
                    "Too much pressure",
                    "I need to calm down",
                    "Help me relax",
                    "Stress relief",
                    "I'm panicking"
                ],
                "contexts": {
                    "work_hours": {"hour": [9, 10, 11, 14, 15, 16, 17]},
                    "evening": {"hour": [19, 20, 21]}
                },
                "expected_actions": [
                    "spotify.play",         # Calm music
                    "dnd.on",               # Peace
                    "system.app.close",     # Remove stress
                    "timer.set",            # Breathing timer
                    "system.brightness.down", # Softer
                    "web.search"            # Stress tips
                ]
            },
            "bored": {
                "queries": [
                    "I'm bored",
                    "Nothing to do",
                    "I need entertainment",
                    "What should I do",
                    "Kill time",
                    "Boredom",
                    "Entertain me"
                ],
                "contexts": {
                    "any_time": {"hour": list(range(6, 24))}
                },
                "expected_actions": [
                    "youtube.trending",     # Trending videos
                    "spotify.play",         # Music
                    "instagram.feed",       # Social browsing
                    "instagram.reels",      # Reels
                    "web.search"            # Discover
                ]
            },
            "personality": {
                "queries": [
                    "Be cool",
                    "Show some style",
                    "What's good Ankita",
                    "You're fire",
                    "Keep it lit"
                ],
                "contexts": {
                    "any_time": {"hour": list(range(0, 24))}
                },
                "expected_actions": [
                    "personality.cool",     # NEW! Stay cool
                    "personality.swagger",  # NEW! Swagger mode
                    "youtube.play",         # Play cool music
                    "spotify.play"          # Vibe music
                ]
            },
            "system_guardian": {
                "queries": [
                    "Check system health",
                    "Is my PC lagging?",
                    "Scan for heavy processes",
                    "How's my memory looking?",
                    "Guardian mode"
                ],
                "contexts": {
                    "any_time": {"hour": list(range(0, 24))}
                },
                "expected_actions": [
                    "system.sentinel.health",
                    "system.sentinel.guardian"
                ]
            },
            "vision_ocr": {
                "queries": [
                    "Read my screen",
                    "What's on the display?",
                    "Find the Login button",
                    "Click on the text Next",
                    "Scan the screen"
                ],
                "contexts": {
                    "any_time": {"hour": list(range(0, 24))}
                },
                "expected_actions": [
                    "vision.ocr.read",
                    "vision.ocr.click"
                ]
            },
            "messaging": {
                "queries": [
                    "Open WhatsApp",
                    "Send a message to Arjun",
                    "Any new WhatsApp messages?",
                    "Message Rahul on WhatsApp",
                    "WhatsApp notifications"
                ],
                "contexts": {
                    "any_time": {"hour": list(range(0, 24))}
                },
                "expected_actions": [
                    "whatsapp.open",
                    "whatsapp.send",
                    "whatsapp.notifications"
                ]
            },
            "email": {
                "queries": [
                    "Open Gmail",
                    "Check my emails",
                    "Send an email to boss",
                    "Any new mail?",
                    "Gmail inbox"
                ],
                "contexts": {
                    "any_time": {"hour": list(range(0, 24))}
                },
                "expected_actions": [
                    "gmail.open",
                    "gmail.send",
                    "gmail.inbox"
                ]
            }
        }
    
    def generate_scenario(self, situation=None, time_context=None):
        """
        Generate a random scenario.
        
        Args:
            situation: Specific situation or None for random
            time_context: dict with 'hour' or None for random
        
        Returns:
            dict: {
                'query': str,
                'situation': str,
                'hour': int,
                'expected_action': str,
                'context': dict
            }
        """
        # Pick random situation if not specified
        # Pick situation
        situation_name = situation or random.choice(list(self.scenarios.keys()))
        situation_def = self.scenarios[situation_name]
        
        # Generate query - use dynamic 80% of time for variety
        if self.use_dynamic and random.random() < 0.8:
            # Dynamic generation
            query = self.dynamic_gen.generate(situation_name)
        else:
            # Fallback to fixed templates
            query = random.choice(situation_def['queries'])
        
        # Determine time context
        if time_context and 'hour' in time_context:
            hour = time_context['hour']
        else:
            # Pick appropriate time based on situation contexts
            ctx_type = random.choice(list(situation_def['contexts'].keys()))
            context_def = situation_def['contexts'][ctx_type]
            hour = random.choice(context_def['hour'])
        
        # Build full context
        now = datetime.now()
        
        context = {
            'timestamp': now.isoformat(),
            'hour': hour,
            'minute': random.randint(0, 59),
            'day_of_week': now.strftime("%A").lower(),
            'is_weekend': now.weekday() >= 5,
            'time_of_day': self._get_time_of_day(hour),
            'battery_percent': random.randint(20, 100),
            'is_charging': random.choice([True, False]),
            'situation_detected': situation_name
        }
        
        # Pick expected action
        expected_action = random.choice(situation_def['expected_actions'])
        
        return {
            'query': query,
            'situation': situation_name,
            'hour': hour,
            'expected_action': expected_action,
            'context': context
        }
    
    def _get_time_of_day(self, hour):
        """Convert hour to time_of_day."""
        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 21:
            return "evening"
        else:
            return "night"
    
    def generate_batch(self, count=100, distribution=None):
        """
        Generate batch of scenarios.
        
        Args:
            count: Number of scenarios
            distribution: Dict of situation -> weight, or None for uniform
        
        Returns:
            list: Scenario dicts
        """
        scenarios = []
        
        if distribution is None:
            # Uniform distribution
            situations = list(self.scenarios.keys())
            for _ in range(count):
                situation = random.choice(situations)
                scenario = self.generate_scenario(situation)
                if scenario:
                    scenarios.append(scenario)
        else:
            # Weighted distribution
            situations = list(distribution.keys())
            weights = [distribution[s] for s in situations]
            
            for _ in range(count):
                situation = random.choices(situations, weights=weights, k=1)[0]
                scenario = self.generate_scenario(situation)
                if scenario:
                    scenarios.append(scenario)
        
        return scenarios
