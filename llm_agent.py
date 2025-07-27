
import os
import random
import re
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
        
        with open("rogue_guide.txt", "r") as f:
            self.rogue_guide = f.read()

    def act(self):
        """
        The main loop for the agent's decision-making process.
        """
        screen = self.rb.get_screen_string()
        
        prompt = self.construct_prompt(screen, self.history)

        chosen_action = self.get_llm_action(prompt)
        
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
        history_str = "\n".join([f"Action: {a}\nNote: {n}" for a, n in history])

        prompt = f"""
        {self.rogue_guide}

        You are playing the game Rogue. Here is the history of your recent moves:
        --- HISTORY ---
        {history_str}
        --- END HISTORY ---

        Here is the current screen:
        {screen}

        What is your next move? Your answer must be in two lines.
        The first line is the command to execute (e.g., 'h', 'qa', '10s').
        The second line is a short sentence of your notes or explanation for the action.
        Example:
        h
        Moved left to explore the corridor.
        """
        return prompt

    def get_llm_action(self, prompt):
        """
        Gets the action from the LLM, ensuring it's in the expected format.
        """
        response = self.llm_integration.query(prompt)
        
        lines = response.strip().split('\n')
        
        if len(lines) >= 2:
            action = lines[0].strip()
            note = " ".join(lines[1:]).strip()
            self.history.append((action, note))
            if len(self.history) > 20: # Keep history to the last 20 turns
                self.history.pop(0)
            return action
        else:
            # Fallback for malformed response
            action = lines[0].strip() if lines else random.choice(['h', 'j', 'k', 'l'])
            self.history.append((action, "No explanation provided."))
            if len(self.history) > 20:
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
            userinterface='curses',
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