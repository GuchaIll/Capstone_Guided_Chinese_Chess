
## **Kibo Animation Flow**

This defines how **Kibo reacts with animations** based on in-game events and player performance.

---

### **1. Game Outcome Events**

* **Player Wins**

  * Trigger: Victory condition achieved
  * Animation: *Celebration (default win animation)*

* **Knocked Out / Defeat**

  * Trigger: Player loses or is eliminated
  * Animation: *Knockout / defeat reaction*

---

### **2. Major Game Advantage**

* **Large Material Gain (e.g., strong capture)**

  * Trigger: Player captures high-value piece or swings evaluation significantly
  * Animation: *Excited reaction*

---

### **3. Positive Performance Reactions**

* **High Accuracy Move**

  * Trigger: Move aligns closely with engine-best
  * Animation: *Cheering*

* **Avoids a Blunder**

  * Trigger: Player selects a safe move instead of a losing one
  * Animation (randomized):

    * Standing clap
    * Fist pump

* **Finds Optimal Move**

  * Trigger: Best possible move in position
  * Animation (randomized):

    * Booty hip hop dance
    * Dancing
    * Northern soul spin

---

### **4. Negative Performance Reactions**

* **Misses a Strong Move**

  * Trigger: Player overlooks a clearly better option
  * Animation (randomized):

    * Sitting disbelief
    * Crying

* **Illegal Move Attempt**

  * Trigger: Player attempts invalid move
  * Animation: *Angry reaction*

---

### **5. Animation Selection Rules**

* When multiple animations are listed:

  * Select **randomly** or based on **personality weighting**
* Prioritize triggers in this order:

  1. Game outcome (win/loss)
  2. Major advantage (material swing)
  3. Move quality (optimal / mistake / blunder)
  4. Rule violations (illegal move)

