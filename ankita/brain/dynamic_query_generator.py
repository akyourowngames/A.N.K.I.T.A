"""
Dynamic Query Generator - Creates infinite query variations
"""
import random


class DynamicQueryGenerator:
    """Generates varied, natural queries dynamically."""
    
    def __init__(self, max_history=1000):
        self.templates = self._load_templates()
        self.synonyms = self._load_synonyms()
        
        # Track recently generated queries to avoid duplicates
        self.query_history = set()
        self.max_history = max_history
    
    def _load_templates(self):
        """Query templates with placeholders."""
        return {
            "hungry": [
                "I'm {intensity} {state}",
                "I {need} {food_type}",
                "{time_phrase} to eat",
                "What should I {action}",
                "I'm {craving} {specific_food}",
                "{question} where to {get_food}",
                "Can you {help_verb} me {find_action} food",
                "My stomach is {stomach_feeling}",
                "I haven't eaten {time_ago}",
                "I could {eat_verb} for {specific_food}",
                "{feeling} {hungry_adj} right now",
                "Need {food_type} {urgency}",
                "Looking for {meal_type}",
                "{food_action} sounds {good_adj}",
                "Where's the {nearest} {restaurant}",
                "I'm {thinking_about} {cuisine}",
                "{order} {delivery}",
                "Got any {food_suggestions}",
                "My {stomach} {wants} {food_type}",
                "{breakfast_lunch_dinner} {time_marker}"
            ],
            "sick": [
                "I'm {feeling} {sickness}",
                "I have {symptom}",
                "I {need_verb} {medicine_type}",
                "My {body_part} {hurts}",
                "I'm not feeling {well_synonym}",
                "I think I'm {illness}",
                "Can you help with my {symptom}",
                "I need to {action} my {symptom}",
                "{symptom} is {intensity} me",
                "I feel {sickness_adj}"
            ],
            "tired": [
                "I'm {so} {tired_state}",
                "I {need_verb} {sleep_type}",
                "I feel {exhausted_synonym}",
                "{time_phrase} for {sleep_action}",
                "I can't {keep_awake}",
                "My {body} {needs} rest",
                "I'm {running_out} of energy",
                "I could fall asleep {right_now}",
                "{help_me} get some sleep",
                "Feeling {drowsy_adj}",
                "Need to {rest_verb} {now}",
                "{body_part} feel {heavy}",
                "Can't {stay_verb} up",
                "{yawning} {constantly}",
                "Need {bed_noun} {soon}",
                "{energy_level} is {low_adj}",
                "Want to {lie_down}",
                "{sleep_quality} time",
                "My {brain} is {shutting_down}",
                "I'm {feeling} drowsy"
            ],
            "stressed": [
                "I'm {feeling} {stressed_state}",
                "I'm {so} {overwhelmed}",
                "{help_me} {calm_down}",
                "I {need_verb} to {relax_action}",
                "There's {too_much} {pressure}",
                "I can't {handle} this {stress}",
                "My {anxiety} is {intensity}",
                "{find_me} some {peace}",
                "I'm {having} a {panic_type}",
                "I {need_verb} {stress_relief}"
            ],
            "bored": [
                "I'm {so} {bored_state}",
                "I have {nothing} to do",
                "I {need_verb} {entertainment}",
                "What should I {do_action}",
                "{find_me} something {fun}",
                "I'm {looking_for} {activity}",
                "{time_phrase} to {kill} time",
                "Can you {suggest} something",
                "I want to {watch_or_play} {content}",
                "Give me {ideas_for} entertainment"
            ],
            "focus": [
                "I {need_verb} to {focus_action}",
                "{help_me} {concentrate}",
                "I {want_to} {work_verb}",
                "{enable} {focus_mode}",
                "I {need_verb} {concentration}",
                "Too many {distractions}",
                "{turn_on} {dnd_synonym}",
                "I have to {get_work_done}",
                "{block} the {noise}",
                "{start} my {work_session}"
            ],
            "music": [
                "{play_verb} {music_type}",
                "I {want_to} {listen} to music",
                "{turn_on} some {songs}",
                "{music_time}",
                "Can you {play_verb} {genre}",
                "I'm {in_mood_for} {music_style}",
                "{find_me} {good_music}",
                "{start} {spotify_or_youtube}",
                "I {need_verb} some {tunes}",
                "{queue_up} my {playlist}"
            ],
            "workout": [
                "I {want_to} {exercise_verb}",
                "{time_phrase} to {workout_action}",
                "Let's {gym_verb}",
                "I'm going to {exercise_type}",
                "{start} my {workout}",
                "I {need_verb} to {move}",
                "{help_me} with my {exercise_routine}",
                "{set} a {timer} for workout",
                "Gym {session_type}",
                "I'm {ready_to} {sweat}"
            ]
        }
    
    def _load_synonyms(self):
        """Synonym variations for placeholders."""
        return {
            # Hungry
            "intensity": ["", "really", "very", "super", "so", "extremely", "absolutely", "quite", "pretty"],
            "state": ["hungry", "starving", "famished", "ravenous", "peckish"],
            "need": ["need", "want", "could use", "looking for", "craving", "in need of"],
            "food_type": ["food", "something to eat", "a meal", "a snack", "a bite", "lunch", "dinner"],
            "time_phrase": ["Time", "It's time", "I should", "I need", "Gonna", "Should"],
            "action": ["eat", "have for lunch", "order", "get", "grab", "find"],
            "craving": ["craving", "dying for", "really want", "need", "desiring"],
            "specific_food": ["pizza", "burger", "chinese", "something", "pasta", "sushi", "tacos"],
            "question": ["Do you know", "Can you tell me", "Where can I find", "Know any"],
            "get_food": ["eat", "order food", "get a meal", "grab something", "find food"],
            "help_verb": ["help", "show", "tell", "guide", "assist"],
            "hungry_adj": ["starving", "hungry", "famished", "ravenous"],
            "urgency": ["ASAP", "now", "immediately", "soon", "quick"],
            "meal_type": ["breakfast", "lunch", "dinner", "brunch", "food"],
            "food_action": ["Eating", "Ordering", "Getting", "Having"],
            "good_adj": ["good", "great", "perfect", "amazing"],
            "nearest": ["nearest", "closest", "best"],
            "restaurant": ["restaurant", "place to eat", "food spot"],
            "thinking_about": ["thinking about", "in the mood for", "wanting"],
            "cuisine": ["italian", "mexican", "chinese", "indian", "food"],
            "order": ["Order", "Get", "Grab", "Find"],
            "delivery": ["delivery", "takeout", "food", "something"],
            "food_suggestions": ["suggestions", "ideas", "recommendations"],
            "stomach": ["stomach", "belly", "tummy"],
            "wants": ["wants", "needs", "is craving"],
            "breakfast_lunch_dinner": ["Breakfast", "Lunch", "Dinner"],
            "time_marker": ["time", "o'clock", "already"],
            "find_action": ["find", "order", "get", "locate"],
            "stomach_feeling": ["growling", "empty", "rumbling"],
            "time_ago": ["all day", "in hours", "since morning"],
            "eat_verb": ["go", "kill", "die"],
            
            # Sick
            "feeling": ["feeling", "getting", "becoming"],
            "sickness": ["sick", "ill", "unwell", "bad"],
            "symptom": ["a headache", "a cold", "fever", "nausea", "pain"],
            "need_verb": ["need", "want", "am looking for", "require"],
            "medicine_type": ["medicine", "medication", "pills", "relief"],
            "body_part": ["head", "stomach", "throat", "body"],
            "hurts": ["hurts", "aches", "is killing me", "is sore"],
            "well_synonym": ["well", "good", "okay", "fine", "right"],
            "illness": ["coming down with something", "getting sick", "ill"],
            "sickness_adj": ["terrible", "awful", "bad", "weak", "nauseous"],
            
            # Tired
            "so": ["so", "really", "very", "extremely", "super"],
            "tired_state": ["tired", "sleepy", "exhausted", "beat", "worn out"],
            "sleep_type": ["sleep", "rest", "a nap", "to lie down"],
            "exhausted_synonym": ["exhausted", "drained", "dead tired", "wiped out"],
            "sleep_action": ["sleep", "bed", "rest", "a nap"],
            "keep_awake": ["keep my eyes open", "stay awake", "focus"],
            "body": ["body", "eyes", "brain"],
            "needs": ["needs", "wants", "is craving"],
            "running_out": ["running out", "losing", "out"],
            "right_now": ["right now", "any second", "standing up"],
            "help_me": ["Help me", "I need to", "Can you help me"],
            
            # Stressed
            "stressed_state": ["stressed", "anxious", "overwhelmed", "tense"],
            "overwhelmed": ["overwhelmed", "under pressure", "stressed out"],
            "calm_down": ["calm down", "relax", "de-stress", "chill"],
            "relax_action": ["relax", "unwind", "calm down", "decompress"],
            "too_much": ["too much", "so much", "overwhelming"],
            "pressure": ["pressure", "stress", "weight on me"],
            "handle": ["handle", "deal with", "manage", "cope with"],
            "stress": ["stress", "pressure", "anxiety"],
            "anxiety": ["anxiety", "stress", "worry", "tension"],
            "peace": ["peace", "calm", "quiet", "relaxation"],
            "having": ["having", "experiencing", "feeling"],
            "panic_type": ["panic attack", "breakdown", "meltdown"],
            "stress_relief": ["stress relief", "to relax", "peace"],
            
            # Bored
            "bored_state": ["bored", "restless", "unstimulated"],
            "nothing": ["nothing", "absolutely nothing"],
            "entertainment": ["entertainment", "something fun", "to do"],
            "do_action": ["do", "watch", "play", "try"],
            "find_me": ["Find me", "Show me", "Give me", "Suggest"],
            "fun": ["fun", "interesting", "entertaining", "exciting"],
            "looking_for": ["looking for", "searching for", "want"],
            "activity": ["an activity", "something to do", "entertainment"],
            "kill": ["kill", "pass", "waste"],
            "suggest": ["suggest", "recommend", "show me"],
            "watch_or_play": ["watch", "play", "do", "try"],
            "content": ["something", "a video", "a game", "content"],
            "ideas_for": ["ideas for", "suggestions for", "options for"],
            
            # Focus
            "focus_action": ["focus", "concentrate", "get to work"],
            "concentrate": ["concentrate", "focus better", "think clearly"],
            "want_to": ["want to", "need to", "have to", "should"],
            "work_verb": ["work", "study", "focus", "get stuff done"],
            "enable": ["Enable", "Turn on", "Start", "Activate"],
            "focus_mode": ["focus mode", "work mode", "concentration mode"],
            "concentration": ["concentration", "focus", "clarity"],
            "distractions": ["distractions", "interruptions", "noise"],
            "turn_on": ["Turn on", "Enable", "Activate", "Start"],
            "dnd_synonym": ["do not disturb", "DND", "quiet mode"],
            "get_work_done": ["get work done", "be productive", "finish tasks"],
            "block": ["Block", "Stop", "Remove", "Eliminate"],
            "noise": ["noise", "distractions", "interruptions"],
            "start": ["Start", "Begin", "Initiate"],
            "work_session": ["work session", "focus time", "productivity"],
            
            # Music
            "play_verb": ["Play", "Put on", "Start"],
            "music_type": ["music", "some tunes", "songs"],
            "listen": ["listen", "hear", "enjoy"],
            "songs": ["songs", "music", "tunes", "tracks"],
            "music_time": ["Music time", "Time for music", "Let's play music"],
            "genre": ["rock", "jazz", "pop", "something", "chill music"],
            "in_mood_for": ["in the mood for", "want to hear", "feel like"],
            "music_style": ["calm music", "upbeat songs", "something chill"],
            "good_music": ["good music", "great songs", "nice tunes"],
            "spotify_or_youtube": ["Spotify", "YouTube", "music"],
            "tunes": ["tunes", "music", "songs", "beats"],
            "queue_up": ["Queue up", "Play", "Start"],
            "playlist": ["playlist", "favorite songs", "music"],
            
            # Workout
            "exercise_verb": ["workout", "exercise", "train", "get fit"],
            "workout_action": ["workout", "exercise", "train", "hit the gym"],
            "gym_verb": ["hit the gym", "workout", "exercise", "train"],
            "exercise_type": ["cardio", "lift weights", "exercise", "train"],
            "workout": ["workout", "exercise session", "training"],
            "move": ["move", "exercise", "be active", "get moving"],
            "exercise_routine": ["exercise routine", "workout", "training"],
            "set": ["Set", "Start", "Begin"],
            "timer": ["timer", "stopwatch", "countdown"],
            "session_type": ["session", "time", "day"],
            "ready_to": ["ready to", "going to", "about to"],
            "sweat": ["sweat", "work out", "exercise", "get fit"]
        }
    
    def generate(self, situation, avoid_duplicates=True):
        """
        Generate a random query for a situation.
        
        Args:
            situation: Situation name
            avoid_duplicates: Whether to check history
        
        Returns:
            str: Dynamically generated query
        """
        templates = self.templates.get(situation)
        if not templates:
            return f"I need help with {situation}"
        
        # Try up to 10 times to get unique query
        max_attempts = 10
        for attempt in range(max_attempts):
            # Pick random template
            template = random.choice(templates)
            
            # Replace placeholders with random synonyms
            query = template
            
            # Find all placeholders {word}
            import re
            placeholders = re.findall(r'\{(\w+)\}', template)
            
            for placeholder in placeholders:
                synonyms = self.synonyms.get(placeholder, [placeholder])
                replacement = random.choice(synonyms)
                query = query.replace(f'{{{placeholder}}}', replacement, 1)
            
            # Check if unique
            if not avoid_duplicates or query not in self.query_history:
                # Add to history
                if avoid_duplicates:
                    self.query_history.add(query)
                    
                    # Limit history size
                    if len(self.query_history) > self.max_history:
                        # Remove oldest half
                        history_list = list(self.query_history)
                        self.query_history = set(history_list[len(history_list)//2:])
                
                return query
        
        # If all attempts failed, return anyway (very rare)
        return query
    
    def generate_batch(self, situation, count=10):
        """Generate multiple unique queries."""
        queries = set()
        attempts = 0
        max_attempts = count * 3
        
        while len(queries) < count and attempts < max_attempts:
            query = self.generate(situation)
            queries.add(query)
            attempts += 1
        
        return list(queries)


# Test
if __name__ == '__main__':
    gen = DynamicQueryGenerator()
    
    print("=== Dynamic Query Generation ===\n")
    
    for situation in ["hungry", "sick", "tired", "stressed", "bored"]:
        print(f"\n{situation.upper()}:")
        queries = gen.generate_batch(situation, 5)
        for q in queries:
            print(f"  • {q}")
