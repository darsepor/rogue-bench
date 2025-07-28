
import os
import random
import re
import xml.etree.ElementTree as ET
from openai import OpenAI
from dotenv import load_dotenv
import threading
import queue

from baseagent import BaseAgent
from logger import Log
from options import AgentOptions, RogueBoxOptions
from evaluator import AmuletLevelsRogueEvaluator

load_dotenv()

class OpenRouterIntegration:
    def __init__(self, api_key):
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )

    def query(self, prompt):
        completion = self.client.chat.completions.create(
            model="deepseek/deepseek-r1-0528:free",
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )
        return completion.choices[0].message.content


class LLMAgent(BaseAgent):
    """
    An agent that uses a Large Language Model to decide which action to take.
    """

    def __init__(self, options=AgentOptions(), llm_integration=None):
        super().__init__(options)
        self.llm_integration = llm_integration
        self.history = []
        
        with open("rogue_guide.txt", "r", encoding="utf-8", errors="ignore") as f:
            self.rogue_guide = f.read()

        self.action_queue = queue.Queue(maxsize=1)
        self.llm_thread = None

    def game_over(self):
        """
        Called when the game ends. Resets the game and the agent's state.
        """
        # Call the parent implementation to reset the game environment
        super().game_over()

        # The old thread will eventually die. Let's make sure we start a new one.
        self.llm_thread = None
        
        # Clear the action queue to prevent acting on stale data from a past life
        with self.action_queue.mutex:
            self.action_queue.queue.clear()

        # Clear the agent's history
        self.history = []

    def _llm_worker(self):
        """
        Worker function to be run in a separate thread.
        Queries the LLM and puts the chosen action in the queue.
        """
        screen = self.rb.get_screen_string()
        prompt = self.construct_prompt(screen, self.history)
        action, note = self.get_llm_action(prompt)

        # Update history here so it's in sync with the action taken
        self.history.append((action, note))
        if len(self.history) > 50: # Keep history to the last 50 turns
            self.history.pop(0)

        self.action_queue.put(action)

    def act(self):
        """
        The main loop for the agent's decision-making process.
        Checks for a pending action from the LLM, or starts a new query.
        """
        # If the LLM is not already thinking, start a new worker thread
        if self.llm_thread is None or not self.llm_thread.is_alive():
            self.llm_thread = threading.Thread(target=self._llm_worker)
            self.llm_thread.daemon = True
            self.llm_thread.start()

        try:
            # Check for an action from the queue without blocking
            chosen_action = self.action_queue.get_nowait()
        except queue.Empty:
            # No action ready yet, do nothing this tick.
            return False 

        if not chosen_action.strip():
            return False         # do nothing this tick

        if isinstance(chosen_action, str) and len(chosen_action) > 1:
            reward, next_state, won, lost = self.rb.send_sequence(chosen_action)
        else:
            reward, next_state, won, lost = self.rb.send_command(chosen_action)

        note = self.history[-1][1] if self.history else "N/A"
        self.logger.log([
            Log("action", f"Chosen action: {chosen_action}"),
            Log("note", f"Note: {note}"),
            Log("result", f"Reward: {reward}, Won: {won}, Lost: {lost}")
        ])
        return won or lost

    def construct_prompt(self, screen, history):
        """
        Constructs the prompt to be sent to the LLM.
        The variable parts (history, screen) are placed at the end to improve KV cache hits.
        """
        history_str = "\n".join([f"<move><action>{a}</action><note>{n}</note></move>" for a, n in history])

        prompt = f"""You are an expert player of the game Rogue. Your goal is to find the Amulet of Yendor.
You will be given the game's instruction manual for reference. Based on the history of your last 50 moves and the current screen, decide on the best next action.

Your response MUST be in a simple XML format inside a <move> tag. Do not add any other text, greetings, or markdown formatting.
Example:
<move>
    <action>h</action>
    <note>Exploring the corridor to the west.</note>
</move>

--- GAME GUIDE ---
{self.rogue_guide}
--- END GAME GUIDE ---

Now, here is the information for your current turn.

--- HISTORY (last 50 moves) ---
{history_str}
--- END HISTORY ---

--- CURRENT SCREEN ---
{screen}
--- END CURRENT SCREEN ---

What is your next move?
"""
        return prompt

    def get_llm_action(self, prompt):
        """
        Gets the action from the LLM by parsing its XML response.
        This method is now called by the worker thread.
        """
        response = self.llm_integration.query(prompt).strip()
        print("LLM RAW-RESPONSE:\n", repr(response))
        
        action = ''
        note = "No explanation provided."

        try:
            root = ET.fromstring(response)
            action_element = root.find('action')
            note_element = root.find('note')

            if action_element is not None and action_element.text:
                action = action_element.text.strip()
            
            if note_element is not None and note_element.text:
                note = note_element.text.strip()

        except ET.ParseError:
            note = "Fallback: LLM provided malformed XML."

        # Safety check: if action is empty for any reason, fall back to a random move.
        if not action:
            action = random.choice(['h', 'j', 'k', 'l', '>'])
            # If the note was also empty, update it.
            if note == "No explanation provided.":
                note = "Fallback: LLM provided an empty or invalid action."
            
        return action, note


if __name__ == '__main__':
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not found in .env file")

    llm_integration = OpenRouterIntegration(api_key)

    agent = LLMAgent(
        AgentOptions(
            gui=True,
            userinterface='tk',
            gui_timer_ms=100,
            roguebox_options=RogueBoxOptions(
                state_generator='Dummy_StateGenerator',
                reward_generator='StairsOnly_RewardGenerator',
                evaluator=AmuletLevelsRogueEvaluator(),
                max_step_count=500,
                move_rogue=True,
                # Increase the busy wait time slightly to give Rogue more
                # time to process the '--More--' dismissal command.
                busy_wait_seconds=0.01
            )
        ),
        llm_integration=llm_integration
    )
    agent.run() 