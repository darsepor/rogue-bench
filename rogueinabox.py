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

import time
import os
import fcntl
import pty
import signal
import pyte
import shutil
import warnings

from .options import RogueBoxOptions
from .parser import RogueParser
from .evaluator import RogueEvaluator
from . import states
from . import rewards
from .exceptions import *

warnings.simplefilter("always", RogueLoopWarning)


class Terminal:
    def __init__(self, columns, lines):
        self.screen = pyte.DiffScreen(columns, lines)
        self.stream = pyte.ByteStream()
        self.stream.attach(self.screen)

    def feed(self, data):
        self.stream.feed(data)

    def read(self):
        return self.screen.display


def open_terminal(command, args, columns=80, lines=24):
    """Starts a child process executing the given command with args"""

    p_pid, master_fd = pty.fork()
    if p_pid == 0:  # Child.
        args = [command] + args
        env = dict(TERM="linux", LC_ALL="en_GB.UTF-8",
                   COLUMNS=str(columns), LINES=str(lines))
        os.execvpe(command, args, env)

    # set non blocking read
    flag = fcntl.fcntl(master_fd, fcntl.F_GETFD)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flag | os.O_NONBLOCK)
    # File-like object for I/O with the child process aka command.
    p_out = os.fdopen(master_fd, "w+b", 0)
    return Terminal(columns, lines), p_pid, p_out


class RogueBox:
    """Start a rogue game and expose interface to communicate with it.

    Usage example:

        rb = RogueBox(RogueBoxOptions(
            state_generator='FullMap_StateGenerator',
            reward_generator='StairsOnly_RewardGenerator',
            max_step_count=500)
        )

        # get actions list
        actions = rb.get_actions()
        # get initial state
        state = rb.get_current_state()

        terminal = False
        while not terminal:
            # implement action selection
            act = select_action(state, actions)
            reward, state, won, lost = rb.send_command(act)
            terminal = won or lost

    """

    @staticmethod
    def get_actions():
        """return the list of actions"""
        # h, j, k, l: ortogonal moves
        # y, u, b, n: diagonal moves
        # >: go downstairs
        # return ['h', 'j', 'k', 'l', '>', 'y', 'u', 'b', 'n']
        return ['h', 'j', 'k', 'l', '>']

    @staticmethod
    def default_game_exe_path():
        exe_name = 'rogue'
        this_file_dir = os.path.dirname(os.path.realpath(__file__))
        rogue_path = os.path.join(this_file_dir, 'rogue', exe_name)
        return rogue_path

    def __init__(self, options=RogueBoxOptions()):
        """
        :param RogueBoxOptions options:
             options object, see its documentation
        """
        if options.game_exe_path:
            self._default_exe = False
            self.rogue_path = options.game_exe_path
        else:
            self._default_exe = True
            self.rogue_path = self.default_game_exe_path()

        is_executable = shutil.which(self.rogue_path)
        if not is_executable:
            raise ValueError('game_exe_path "%s" is not executable' % self.rogue_path)

        self.rogue_options = options.rogue_options
        self.parser = RogueParser()

        if options.evaluator is None:
            self.evaluator = RogueEvaluator(max_step_count=options.max_step_count,
                                            episodes_for_evaluation=options.episodes_for_evaluation)
        else:
            self.evaluator = options.evaluator

        if options.reward_generator is None:
            raise ValueError('reward generator cannot be None, use "Dummy_RewardGenerator" instead')
        if isinstance(options.reward_generator, str):
            if not hasattr(rewards, options.reward_generator):
                raise ValueError('no reward generator named "%s" was found' % options.reward_generator)
            self.reward_generator = getattr(rewards, options.reward_generator)()
        else:
            self.reward_generator = options.reward_generator

        if options.state_generator is None:
            raise ValueError('state generator cannot be None, use "Dummy_StateGenerator" instead')
        if isinstance(options.state_generator, str):
            if not hasattr(states, options.state_generator):
                raise ValueError('no state generator named "%s" was found' % options.state_generator)
            self.state_generator = getattr(states, options.state_generator)()
        else:
            self.state_generator = options.state_generator

        self.transform_descent_action = options.transform_descent_action
        self.reached_amulet_level = False

        self.refresh_after_commands = options.refresh_after_commands
        self.refresh_command = '\x12'.encode()

        self.move_rogue = options.move_rogue

        self.busy_wait_seconds = options.busy_wait_seconds
        self.max_busy_wait_seconds = options.max_busy_wait_seconds

        # rogue process id
        self.pid = None
        self.has_cmd_count = False

        if options.start_game:
            self._start()

    def _start(self):
        """Start the game.
        If move_rogue was set to True in init, perform a legal move to see the tile below the player and the resulting
        state will be returned.

        :return:
            if move_rogue was set to True in init:
                (reward, state, won, lost)
            else:
                None
        """
        # reset internal variables
        self.step_count = 0
        self.state = None
        self.reward = None

        self.evaluator.on_run_begin()
        self.parser.reset()
        self.reward_generator.reset()
        self.state_generator.reset()
        self.reached_amulet_level = False

        # start game process
        rogue_args = self.rogue_options.generate_args() if self._default_exe else []
        self.terminal, self.pid, self.pipe = open_terminal(command=self.rogue_path, args=rogue_args)

        if not self.is_running():
            print("Could not find the executable in %s." % self.rogue_path)
            exit()

        # wait until the rogue spawns
        self.screen = self.get_empty_screen()
        self._update_screen()
        while not "Exp:" in self.screen[-1]:
            # TODO: can rogue enter an endless loop here too?
            time.sleep(self.busy_wait_seconds)
            self._update_screen()

        if not self.has_cmd_count:
            # if self.has_cmd_count was True then we found the cmd count previously so it will be still there
            # otherwise it may be the first time the game is started so we will check
            self.has_cmd_count = "Cmd" in self.screen[-1]

        self.frame_history = [self.parser.parse_screen(self.screen)]

        if self.move_rogue:
            # we move the rogue to be able to see the tile below it
            action = self.get_legal_actions()[0]
            return self.send_command(action)
        else:
            self.state = self.state_generator.compute_state(self.frame_history)

    def reset(self):
        """Kill and restart the rogue process.
        If move_rogue was set to True in init, an initial legal action is performed and the resulting state returned.

        :return:
            if move_rogue was set to True in init:
                (reward, state, won, lost)
            else:
                None
        """
        self.stop()
        return self._start()

    def stop(self):
        """kill the rogue process"""
        if self.is_running():
            self.pipe.close()
            os.kill(self.pid, signal.SIGTERM)
            # wait the process so it doesnt became a zombie
            os.waitpid(self.pid, 0)

    def get_current_state(self):
        """return the current state representation of the game.
        This is the same state returned by the last .send_command() call, or the initial state.
        """
        return self.state

    def _update_screen(self):
        """update the virtual screen and the class variable"""
        update = self.pipe.read(65536)
        if update:
            self.terminal.feed(update)
            self.screen = self.terminal.read()

    def get_empty_screen(self):
        screen = list()
        for row in range(24):
            value = ""
            for col in range(80):
                value += " "
            screen.append(value)
        return screen

    def print_screen(self):
        """print the current screen"""
        print(*self.screen, sep='\n')

    def get_screen(self):
        """return the screen as a list of strings.
        can be treated like a 24x80 matrix of characters (screen[17][42])"""
        return self.screen

    def get_screen_string(self):
        """return the screen as a single string with \n at EOL"""
        out = ""
        for line in self.screen:
            out += line
            out += '\n'
        return out

    @property
    def player_pos(self):
        """current player position"""
        return self.frame_history[-1].get_list_of_positions_by_tile("@")[0]

    @property
    def stairs_pos(self):
        """current stairs position or None if they are not visibile"""
        stairs = self.frame_history[-1].get_list_of_positions_by_tile("%")
        if stairs:
            return stairs[0]
        else:
            return None

    def get_legal_actions(self):
        """return the list of legal actions in the current screen"""
        actions = []
        row = self.player_pos[0]
        column = self.player_pos[1]
        if self.screen[row - 1][column] not in '-| ':
            actions += ['k']
        if self.screen[row + 1][column] not in '-| ':
            actions += ['j']
        if self.screen[row][column - 1] not in '-| ':
            actions += ['h']
        if self.screen[row][column + 1] not in '-| ':
            actions += ['l']
        if self.player_pos == self.stairs_pos:
            actions += ['>']
        return actions

    def game_over(self, screen=None):
        """check if we are at the game over screen (tombstone)"""
        if not screen:
            screen = self.screen
        # TODO: this returns True also for inventory screens
        return not ('Hp:' in screen[-1])

    def is_running(self):
        """check if the rogue process exited"""
        try:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
        except (OSError, TypeError):
            # TypeError in case self.pid is still None
            return False
        if pid == 0:
            return True
        else:
            return False

    def currently_in_corridor(self):
        """return whether the rogue is in a corridor"""
        info = self.frame_history[-1]
        return info.get_tile_below_player() == "#"

    def currently_in_door(self):
        """return whether the rogue is on a door"""
        info = self.frame_history[-1]
        return info.get_tile_below_player() == '+'

    def _dismiss_message(self):
        """dismiss a rogue status message (N.B. does not refresh the screen)"""
        messagebar = self.screen[0]
        if "ore--" in messagebar:
            # press space
            self.pipe.write(' '.encode())
        elif "all it" in messagebar:
            # press esc
            self.pipe.write('\e'.encode())

    def _need_to_dismiss(self):
        """check if there are status messages that need to be dismissed"""
        messagebar = self.screen[0]
        if "all it" in messagebar or "ore--" in messagebar:
            return True
        else:
            return False

    def _dismiss_all_messages(self):
        """dismiss all status messages and refresh the screen and returns the number of commands sent

        :rtype: int
        :return:
            number of commands sent

        :raises: RogueLoopError
            in case more than self.max_busy_wait_seconds are waited for
        """
        t0 = time.perf_counter()
        n_cmds = 0
        while self._need_to_dismiss():
            self._dismiss_message()
            time.sleep(self.busy_wait_seconds)
            self._update_screen()
            n_cmds += 1
            if (time.perf_counter() - t0) > self.max_busy_wait_seconds:
                raise RogueLoopError
        return n_cmds

    def quit_the_game(self):
        """Send the keystroke needed to quit the game."""
        self.pipe.write('Q'.encode())
        self.pipe.write('y'.encode())
        self.pipe.write('\n'.encode())

    def get_last_frame(self):
        return self.frame_history[-1]

    def _cmd_busy_wait(self, cmd_sent):
        """perform busy wait on the rogue custom build with command count

        :param int cmd_sent:
            number of commands that were sent since the last screen update
        """
        old_cmd_count = self.frame_history[-1].statusbar["command_count"]
        expected_cmd_count = old_cmd_count + cmd_sent
        new_cmd_count = old_cmd_count
        t0 = time.perf_counter()
        # busy wait until the cmd count is increased
        while new_cmd_count < expected_cmd_count:
            time.sleep(self.busy_wait_seconds)
            self._update_screen()
            dismiss_cmds = self._dismiss_all_messages()
            if self.game_over():
                break
            expected_cmd_count += dismiss_cmds
            try:
                # very rarely, the screen does not completely refresh
                # in particular the status bar (and cmd count) may not be totally drawn
                new_cmd_count = self.parser.get_cmd_count(self.screen)
            except RuntimeError:
                # screen was not fully refreshed and did not contain yet the cmd count
                pass
            if (time.perf_counter() - t0) > self.max_busy_wait_seconds:
                raise RogueLoopError

    def send_command(self, command, state_generator=None, reward_generator=None):
        """send a command to rogue and return (reward, state, won, lost).
        If passed generators are None, the ones supplied during init are used.
        """
        # if the caller passed a string longer than 1 character treat it as a sequence and
        # delegate to the helper that will stream the characters one by one.
        if isinstance(command, str) and len(command) > 1:
            return self.send_sequence(command, state_generator=state_generator,
                                       reward_generator=reward_generator)

        # turn descent command into ascent if this was requested in init
        if self.transform_descent_action and self.reached_amulet_level:
            if command == '>':
                command = '<'

        self.pipe.write(command.encode())
        # rogue may not properly print all tiles after elaborating a command
        # so, based on the init options, we send a refresh command
        if self.refresh_after_commands:
            self.pipe.write(self.refresh_command)

        try:
            entered_loop = False
            # wait until rogue elaborates the command
            if self.has_cmd_count:
                # this is a custom build of rogue that prints a cmd count in the status bar that is updated as soon as a
                # command is elaborated, so we can perform busy waiting
                self._cmd_busy_wait(cmd_sent=2 if self.refresh_after_commands else 1)
            else:
                # this build of rogue does not provide an easy and fast way to determine if the command elaboration is
                # done, so we must wait a fixed amount of time
                time.sleep(0.01)
                self._update_screen()
                self._dismiss_all_messages()
        except RogueLoopError:
            self.stop()
            entered_loop = True
            warnings.warn("rogue process entered an endless loop and was killed", RogueLoopWarning)

        self.step_count += 1

        new_screen = self.screen
        self.frame_history.append(self.parser.parse_screen(new_screen))

        if self.transform_descent_action and not self.reached_amulet_level:
            # check if the rogue reached the amulet level
            last_frame = self.frame_history[-1]
            if last_frame.has_statusbar():
                if last_frame.statusbar["dungeon_level"] == self.rogue_options.amulet_level:
                    self.reached_amulet_level = True

        state_generator = state_generator or self.state_generator
        reward_generator = reward_generator or self.reward_generator
        self.reward = reward_generator.compute_reward(self.frame_history)
        self.state = state_generator.compute_state(self.frame_history)

        is_rogue_dead = self.game_over(new_screen)
        won = (reward_generator and reward_generator.goal_achieved)
        stop = self.evaluator.on_step(self.frame_history, command, self.reward, self.step_count)
        lost = (stop or is_rogue_dead or entered_loop) and not won

        if won or lost:
            self.evaluator.on_run_end(self.frame_history, won, is_rogue_dead)

        return self.reward, self.state, won, lost

    def send_sequence(self, sequence, state_generator=None, reward_generator=None):
        """Stream several keystrokes to Rogue as one logical action.

        This is useful for commands that need an immediate follow-up key, e.g.
        "qa" (quaff item a) or count prefixes like "10h".

        The helper simply calls send_command for every byte in sequence so
        that all the usual bookkeeping (screen refresh, busy-wait, reward
        computation, logging, etc.) is reused.  The return value is the one
        coming from the last character sent.
        """
        last_result = None
        for ch in sequence:
            last_result = self.send_command(ch, state_generator=state_generator,
                                            reward_generator=reward_generator)
        return last_result
