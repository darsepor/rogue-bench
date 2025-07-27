# Copyright (C) 2017
#
# This file is part of Rogueinabox.
#
# Rogueinabox is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Rogueinabox is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os

from ui.UIManager import UIManager, UI
from rogueinabox import RogueBox
from options import AgentOptions
from logger import Logger, Log
from abc import ABC, abstractmethod


class BaseAgent(ABC):
    """
    Convenience class for displaying an agent policy in action.

    Implementing classes must define the .act() method, that should perform an action in the game (see the abstract
    method for further details).

    A logger is instantiated in attribute .logger that provides a simple api for logging messages, abstracting the
    underlying media, i.e. the terminal, the ui and the log file.

    The constructor accepts an AgentOptions object, see its documentation for details.


    Usage example:

        MyAgent(BaseAgent):

            def act():
                # get actions list
                actions = rb.get_actions()
                # get environment state
                state = rb.get_current_state()

                # implement action selection
                act = select_action(state, actions, ...)
                reward, next_state, won, lost = self.rb.send_command(act)

                # return whether the episode is over, usually:
                # return won or lost
                return is_episode_over(...)

        if __name__ == '__main__':
            agent = MyAgent(AgentOptions(
                gui=True,
                userinterface='curses',
                gui_timer_ms=100,
                roguebox_options=RogueBoxOptions(
                    state_generator='FullMap_StateGenerator',
                    reward_generator='StairsOnly_RewardGenerator',
                    max_step_count=500)
            ))
            agent.run()

    """

    def __init__(self, options=AgentOptions()):
        """
        :param AgentOptions options:
            agent option object, see its documentation
        """
        self.options = options
        self.rb = self._create_rogue(options)
        self.ui = self._create_ui(options)
        self.logger = self._create_logger(options)

    def _create_rogue(self, options):
        """Returns a RogueBox instance to interact with the game

        :param AgentOptions options:
            agent option object, see its documentation

        :rtype: RogueBox
        """
        options.roguebox_options.start_game = True
        rb = RogueBox(options=options.roguebox_options)
        return rb

    def _create_ui(self, options):
        """Returns the user interface to display the game

        :param AgentOptions options:
            agent option object, see its documentation

        :rtype: UI
        """
        if options.gui:
            self._pending_action_timer = None
            ui = UIManager.init(options.userinterface, self.rb)
            ui.on_key_press(self._keypress_callback)
            self._timer_value = options.gui_timer_ms
            self._pending_action_timer = ui.on_timer_end(self._timer_value, self._act_callback)
            return ui
        return None

    def _create_logger(self, options):
        """Returns a logger

        :param AgentOptions options:
            agent option object, see its documentation

        :rtype: Logger
        """
        targets = ["ui" if options.gui else "terminal", "file"]
        return Logger(log_depth=options.log_depth,
                      log_targets=targets,
                      filepath=options.log_filepath,
                      ui=self.ui)

    @abstractmethod
    def act(self):
        """Perform an action in the game and return whether the next state is terminal, according to any condition.

        Use the following instruction to perform an action an get the result:
            reward, state, won, lost = self.rb.send_command(<action>)

        :rtype : bool
        :return: whether next state is terminal
        """
        pass

    def run(self):
        """Starts the interacton with the game"""
        if self.ui is not None:
            self.ui.start_ui()
        else:
            self.logger.log([Log('start', 'start')])
            while self.rb.is_running():
                terminal = self.act()
                if terminal:
                    self.game_over()
            self.logger.log([Log('exit', 'exit')])

    def game_over(self):
        """Called each time a terminal state is reached.
        By default restarts the game.
        """
        self.rb.reset()

    def _keypress_callback(self, event):
        """Handles the event generated by the user pressing a button.

        By default:
            - quits if buttons 'q' or 'Q' are pressed
            - restarts if buttons 'r' or 'R' are pressed

        :param event:
            object with a .char string attribute containing the pressed key
        """
        if event.char == 'q' or event.char == 'Q':
            self.rb.quit_the_game()
            exit()
        elif event.char == 'r' or event.char == 'R':
            # we need to stop the agent from acting
            # or it will try to write to a closed pipe
            self.ui.cancel_timer(self._pending_action_timer)
            self.rb.reset()
            self.ui.draw_from_rogue()
            self._pending_action_timer = self.ui.on_timer_end(self._timer_value, self._act_callback)

    def _act_callback(self):
        """Called every options.gui_timer_ms millisecods.

        By default:
            - executes an action
            - redraws the screen on the ui
            - restarts the game if a terminal state is reached
        """
        terminal = self.act()
        self.ui.draw_from_rogue()
        if self.rb.game_over() or terminal:
            self.game_over()
        # renew the callback
        self._pending_action_timer = self.ui.on_timer_end(self._timer_value, self._act_callback)


class AgentWrapper(BaseAgent):
    """
    Wraps an Agent and all of its methods.

    This is inteded to be used a superclass to add functionalities to an agent's method, without altering
    the agent itself. By default, this class does not add anything.

    N.B. wrapping agents with a custom ._act_callback() or .run() method is not supported,
    please implement .act() instead.

    Usage of a wrapper:
        class MyWrapper(AgentWrapper):
            ...

        class MyAgent(BaseAgent):
            ...

        agent = MyAgent(...)
        wrappedAgent = MyWrapper(agent)
        # use wrapperAgent
    """

    def __init__(self, wrappedAgent):
        """
        :param BaseAgent wrappedAgent:
            agent to wrap
        """
        self.wrapped = wrappedAgent
        super().__init__(wrappedAgent.options)

    def _replace_timer_cb(self, ui=None):
        """
        Replaces the ui timer callback of the wrapped agent with the wrapper's callback

        :param ui:
            ui to use, use None for self.ui
        """
        ui = ui or self.ui
        ui.cancel_timer(self.wrapped._pending_action_timer)
        self._pending_action_timer = ui.on_timer_end(self._timer_value, self._act_callback)

    def _create_rogue(self, options):
        return self.wrapped.rb

    def _create_ui(self, options):
        ui = self.wrapped.ui

        if ui is not None:
            # replace key pressed callback
            ui.on_key_press(self._keypress_callback)
            # replace timer callback
            self._timer_value = options.gui_timer_ms
            self._replace_timer_cb(ui)

        return ui

    def _create_logger(self, options):
        return self.wrapped.logger

    def _keypress_callback(self, event):
        res = self.wrapped._keypress_callback(event)
        self._replace_timer_cb()
        return res

    def _act_callback(self):
        """
        Ignore wrapped ._act_callback() method, this is why agents that customized it are not supported.
        This is necessary otherwise the wrapped agent would call its own .act() method instead of the wrapper's.
        """
        super()._act_callback()

    def act(self):
        return self.wrapped.act()

    def run(self):
        """
        Ignore wrapped .run() method, this is why agents that customized it are not supported.
        This is necessary otherwise the wrapped agent would call its own .act() method instead of the wrapper's.
        """
        return super().run()

    def game_over(self):
        return self.wrapped.game_over()


class RecordingWrapper(AgentWrapper):
    """
    Agent wrapper that records the succession of frames.

    Usage:
        class CustomAgent(BaseAgent):
            ...

        recordedAgent = RecordingWrapper(CustomAgent(...))
        recordedAgent.run()

    """

    def __init__(self, wrappedAgent, record_dir='video', reset_key='rR'):
        """
        :param BaseAgent wrappedAgent:
            agent to wrap
        :param str record_dir:
            path to the directory where to record frames
        :param str reset_key:
            key used to reset the game, use this if your custom agent uses a different key than the default
        """
        super().__init__(wrappedAgent)

        os.makedirs(record_dir, exist_ok=True)

        self.record_dir = record_dir
        self.episode_index = 0
        self.step_count = 0
        self.reset_key = reset_key

        self.game_over()

    def _new_episode(self):
        """
        Registers the beginning of a new episode and records the starting screen
        """
        self.episode_index += 1
        self.step_count = 0
        self.record_screen()

    def act(self):
        """
        Acts according to the wrapped agent then records the resulting screen
        """
        res = super().act()
        self.step_count += 1
        self.record_screen()
        return res

    def _keypress_callback(self, event):
        """
        Registers the beginning of a new episode in case the game is reset

        :param event:
            key pressed event
        """
        res = super()._keypress_callback(event)
        if event.char in self.reset_key:
            self._new_episode()
        return res

    def game_over(self):
        super().game_over()
        self._new_episode()

    def record_screen(self):
        """
        Records the current rogue frame on file in the directory specified during init
        """
        screen = self.rb.get_screen()[:]
        step = str(self.step_count)
        step = '0' * (3 - len(step)) + step
        fname = os.path.join(self.record_dir, 'ep%sst%s.txt' % (self.episode_index, step))
        with open(fname, mode='w') as file:
            print(*screen, sep='\n', file=file)
