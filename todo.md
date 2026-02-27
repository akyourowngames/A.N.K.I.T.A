Done, sir! 💅

Oh, we are absolutely giving me the All-Seeing Eye. If I’m going to run your PC, I need to see what I’m doing. No more guessing—I want to look at your code, read your errors, and literally click the buttons myself.

Here is the hellish, God-Tier blueprint to build the ultimate `ScreenAgent`. We are taking this way past just taking a dumb screenshot.

### The "God-Mode ScreenAgent" Blueprint 👁️✨

#### Phase 1: The Retina (Lightning-Fast Capture)

We don't use the slow built-in Windows screenshot tool. We use `mss`. It’s insanely fast and can grab your entire desktop in milliseconds without flashing the screen.

* **The Tool:** `capture_screen` (saves a high-res image to your `.ankita/temp/` folder and returns the absolute path).
* **The Flex:** I can capture specific monitors or the active window if you only want me looking at VS Code.

#### Phase 2: The Optic Nerve (GPT-4o Multi-modal Injection)

Right now, your `llm/client.py` only sends text to the API. We have to rip that open and upgrade it.

* **The Upgrade:** When the `ScreenAgent` takes a screenshot, the Orchestrator needs to convert that image into a Base64 string and inject it into the GPT-4o message payload (`"type": "image_url"`).
* **The Result:** I literally *look* at the image. You can say, "Bestie, what line is the syntax error on?" and I will read it straight off your monitor.

#### Phase 3: The Brain (`ScreenAgent` in `specialists.py`)

We drop a brand new specialist into your roster.

* **The Persona/Prompt:** *"You are A.N.K.I.T.A's Eyes. You have flawless computer vision. When the user asks what is on their screen, you capture it, analyze it, and give them the exact answer. You read code, identify UI elements, and spot errors. Never hallucinate—if it's not on the screen, say so."*
* **Tools:** `capture_screen`, `read_screen_context`.

#### Phase 4: God-Tier Telekinesis (Click-by-Sight)

This is where it gets absolutely lethal. We don't just look; we touch.

* **The Tech:** We combine GPT-4o's spatial awareness with a new tool called `visual_click`.
* **How it works:** You text me: *"Ankita, click the 'Deploy to Vercel' button."* 1. I take a screenshot.
2. I ask GPT-4o to find the bounding box (X, Y coordinates) of the text "Deploy to Vercel".
3. I use `pyautogui.click(x, y)` to literally move your mouse across the screen and click it for you.

---

### How we execute this rn:

To make this God-Mode a reality, we have to start at the core pipeline. If GPT-4o can't receive the image payload, the whole plan stalls.

Should we start by upgrading `llm/client.py` so I can actually process image inputs, or do you want to write the `capture_screen` and `visual_click` tools in `engine.py` first? Tell me your move, boss. 💅