# Semantic Control - Comprehensive Test Suite
# Test all 82 situations to verify they detect correctly and execute

## EMOTIONS & MOODS

### Happy & Positive
- "i'm happy" → happy (should play happy music)
- "feeling great" → happy
- "khush hu" → happy

### Sad & Down
- "i'm sad" → sad (should play uplifting music)
- "feeling down" → sad
- "udaas hu" → sad

### Angry & Frustrated
- "i'm angry" → angry (should play calming music)
- "really mad" → angry
- "i'm frustrated" → frustrated (should play funny videos)
- "annoying" → frustrated

### Anxious & Confused
- "i'm anxious" → anxious (should play meditation music)
- "nervous" → anxious
- "i'm confused" → confused (should play relaxing music)

### Lonely & Tired
- "i'm lonely" → lonely (should play podcasts)
- "feeling alone" → lonely
- "i'm tired" → tired (should dim screen + calm music)
- "exhausted" → tired
- "thak gaya" → tired

### Energy & Motivation
- "i need energy" → energize (should play energetic music)
- "pump up" → energize
- "i need motivation" → motivated (should play motivational speech)
- "inspire me" → motivated

### Sleepy
- "i'm sleepy" → sleepy (should dim screen + lower volume)
- "neend aa rahi hai" → sleepy
- "can't sleep" → sleep_trouble (should play sleep sounds)

## HEALTH & WELLNESS

### Sick & Pain
- "i am sick" → sick (should dim screen + search remedies)
- "not feeling well" → sick
- "bimar hu" → sick
- "i have headache" → headache (should dim + relaxing sounds)
- "sar dard ho raha" → headache
- "i have fever" → fever (should search fever remedies)
- "i have cold" → cold (should search cold remedies)
- "stomach ache" → stomachache

### Fitness
- "i want to workout" → workout (should play workout music)
- "exercise karna hai" → workout
- "i want to do yoga" → yoga (should play yoga music)
- "i want to meditate" → meditation (should play meditation sounds)
- "going for a run" → running (should play running music)

## WORK & PRODUCTIVITY

### Focus & Study
- "i want focus" → focus (should close chrome)
- "need to concentrate" → focus
- "padhai karni hai" → focus
- "i need to work" → work (should open notepad)
- "kaam karna hai" → work

### Coding & Creative
- "i want to code" → coding (should open vscode + lofi)
- "coding time" → coding
- "i want to create" → creative (should play creative music)
- "art banana hai" → creative
- "need ideas" → brainstorm (should play ambient music)

### Meetings & Presentations
- "i have a meeting" → meeting (should adjust brightness + volume)
- "meeting hai" → meeting
- "i have presentation" → presentation (should close distractions)

### Breaks
- "i need a break" → break (should lock screen)
- "break chahiye" → break
- "study break" → study_break (should play relax music)
- "padhai ka break" → study_break

### Overwhelmed & Procrastinating
- "i'm overwhelmed" → overwhelmed (should play stress relief)
- "bahut kuch hai" → overwhelmed
- "i'm procrastinating" → procrastinating (should close chrome + focus music)
- "kaam nahi ho raha" → procrastinating

### Exams & Interviews
- "i have exam" → exam (should close chrome + study music)
- "test tomorrow" → exam
- "i have interview" → interview (should search interview tips)

## ENTERTAINMENT

### Music & Relax
- "play music" → music (should play music on youtube)
- "gaana chalao" → music
- "i want to relax" → relax (should play lofi music)
- "chill" → relax

### Party & Dance
- "party mood" → party (should play party songs)
- "let's party" → party
- "i want to dance" → dance (should play dance music)

### Movies & Shows
- "i want to watch movie" → movie (should find movies)
- "movie dekhni hai" → movie
- "binge watch" → binge_watch (should find web series)

### Comedy & Fun
- "make me laugh" → comedy (should play comedy videos)
- "funny videos" → comedy
- "i am bored" → bored (should open trending youtube)
- "nothing to do" → bored

### Podcasts & Learning
- "play podcast" → podcast (should play podcasts)
- "i want to learn" → learn (should play educational content)
- "teach me" → learn

## SYSTEM & NETWORK

### Network Issues
- "net is slow" → network_slow (should reconnect wifi)
- "wifi is slow" → network_slow
- "internet sucks" → network_slow

### System Performance
- "system is slow" → system_slow (should close heavy apps)
- "laptop is lagging" → system_slow
- "laptop is hot" → system_hot (should lower brightness + volume)
- "fan is loud" → system_hot
- "overheating" → system_hot

## DAILY LIFE

### Food & Drinks
- "i'm hungry" → hungry (should search food delivery)
- "bhookh lagi" → hungry
- "i want to cook" → cooking (should find recipes)
- "recipe chahiye" → cooking
- "i'm thirsty" → thirsty

### Shopping & Travel
- "i want to shop" → shopping (should search online shopping)
- "shopping karna hai" → shopping
- "i want to travel" → travel (should show travel vlogs)
- "ghoomna hai" → travel
- "book ticket" → booking

### Fashion & Health Tips
- "fashion ideas" → fashion (should show fashion trends)
- "health tips" → health (should find health tips)

### Time of Day
- "good morning" → morning (should increase brightness + morning music)
- "subah ho gayi" → morning
- "good night" → night (should dim screen + lower volume)
- "raat ho gayi" → night
- "late night" → late_night (should dim + late night music)

### Weather & Traffic
- "how's the weather" → weather_check (should check weather)
- "mausam kaisa hai" → weather_check
- "how's the traffic" → traffic (should check traffic update)
- "stuck in traffic" → stuck_traffic (should play calm music)

### Celebrations
- "let's celebrate" → celebration (should play celebration music)
- "it's my birthday" → birthday (should play birthday songs)
- "anniversary hai" → anniversary (should play romantic songs)

### Spiritual & Prayer
- "feeling spiritual" → spiritual (should play spiritual music)
- "i want to pray" → prayer (should play devotional songs)

### Social
- "i have a date" → date (should play romantic music)
- "family time" → family_time (should close chrome)

### Chores
- "i need to clean" → cleaning (should play cleaning music)
- "safai karna hai" → cleaning
- "laundry time" → laundry (should play podcast)

### Activities
- "i want to game" → gaming (should close chrome for performance)
- "game khelna hai" → gaming
- "i want to read" → reading (should adjust brightness)
- "book padhna hai" → reading

### Commute
- "going to work" → commute (should play podcast)
- "office ja raha" → commute

## INFO & NEWS

### News & Updates
- "show me news" → news (should play news today)
- "kya ho raha hai" → news
- "sports dekhni hai" → sports (should find sports highlights)
- "tech news" → tech (should find tech news)

## SPECIAL MOODS

### Nostalgic & Romantic
- "feeling nostalgic" → nostalgic (should play 90s music)
- "purani yaadein" → nostalgic
- "feeling romantic" → romantic (should play romantic songs)
- "love songs" → romantic

## TEST PROCEDURE

1. **Run each test phrase** in Ankita
2. **Verify detection:** Check that correct situation is detected with high confidence (>0.7)
3. **Verify actions:** Ensure all actions in the situation execute
4. **Verify results:** Check that tool results are displayed to user (for web search, etc.)
5. **Verify learning:** Weights should adjust based on success/failure

## EXPECTED BEHAVIOR

### Successful Test:
```
You: i am sick
[Semantic] Detected: sick (confidence: 1.00)
[Ankita] Finding home remedies for you. Please rest.
DEBUG: executing brightness.down
DEBUG: executing web.search
1. Home Remedies for Common Illnesses
   Here are some effective home remedies...
2. Natural Healing Methods
   Try these natural approaches...
[SemanticLearner] Adjusted sick:system.brightness.down weight to 1.10
[SemanticLearner] Adjusted sick:web.search weight to 1.10
```

### Failed Test (Low Confidence):
```
You: some random text
[Semantic] No situation detected (best: 0.42)
[Falling back to traditional intent classification]
```

### Failed Test (Wrong Detection):
```
You: i want to code
[Semantic] Detected: work (confidence: 0.71)  ← WRONG! Should be "coding"
[Need to add more phrases to "coding" situation]
```

## NOTES
- Hindi/Hinglish phrases should work equally well
- Confidence should be >0.7 for good matches
- Some phrases may match multiple situations (expected)
- Learning weights will adjust over time based on user acceptance
