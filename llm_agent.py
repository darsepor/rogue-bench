
import os
import random
import re
import xml.etree.ElementTree as ET
from openai import OpenAI
from dotenv import load_dotenv

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
            model="deepseek/deepseek-chat-v3-0324:free",
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

    def act(self):
        """
        The main loop for the agent's decision-making process.
        """
        screen = self.rb.get_screen_string()
        
        prompt = self.construct_prompt(screen, self.history)

        chosen_action = self.get_llm_action(prompt)
        
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
        """
        history_str = "\n".join([f"<move><action>{a}</action><note>{n}</note></move>" for a, n in history])

        prompt = f"""
        {self.rogue_guide}

        You are playing the game Rogue. Here is the history of your recent moves:
        --- HISTORY ---
        {history_str}
        --- END HISTORY ---

        Here is the current screen:
        {screen}

        What is your next move? Your response MUST be in a simple XML format.

        Example:
        <move>
            <action>h</action>
            <note>Exploring the corridor to the west.</note>
        </move>

        Do not add any other text, greetings, or markdown formatting outside of the main <move> tag.
        """
        return prompt

    def get_llm_action(self, prompt):
        """
        Gets the action from the LLM by parsing its XML response.
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

        self.history.append((action, note))
        if len(self.history) > 20: # Keep history to the last 20 turns
            self.history.pop(0)
            
        return action


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
                max_step_count=500
            )
        ),
        llm_integration=llm_integration
    )
    agent.run() 