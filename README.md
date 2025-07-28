# Initial Results 2025/07/28:

The LLMs fail miserably, they understand what is going on but navigating tiles seems to be an issue. It is lucky if the agent leaves the initial room or goes through a corridors. It is most likely a tokenization rather than performance issue, as tokens most certainly do not correspond to, say, game tiles marked by '.', etc. The next step is to encode Rogue's ASCII GUI in a tokenizer-friendly way and/or use a parser already present in this environment.

# Rogueinabox: a Rogue environment for AI learning

  Rogueinabox is a higly modular and configurable learning environment built around the videogame Rogue,
  the father of the roguelike genre.
  
  It offers easy ways to interact with the game, especially for the reinforcement learning setting,
  providing several built-in state and reward generators and utilities for creating custom ones. 

## Build Notes for this repository:
The original rogue submodule (rogueinabox/rogue) fails to compile with modern ncurses libraries on Cygwin/Windows, so we replace it with a more modern submodule in this repository.


## Cloning and building

  Clone the repository with the default git command:
  ```console
  git clone <URL>
  ```
  
  Before executing the next step, you may want to create/activate your python
  [virtual environment](https://docs.python.org/3/library/venv.html).
  In order to create it:
  ```console
  python3 -m venv /path/to/venv
  ```

  And to activate it:
  ```console
  . /path/to/venv/bin/activate
  ```
  Make sure to do this before the next step, because it will update pip
  and install python dependencies.

  Finally execute:
  ```console
  make install
  ```
  
  This will install python dependencies, pull our Rogue custom build (in a submodule) and build its executable.
  
#### Manual cloning and building

  If you have trouble with the previous procedure,
  here we describe an alternative more complete manual process.
  This library comes with its own custom Rogue build,
  which has its own git repository and is included as a submodule.
  In order for it to be correctly initialized and used, you can either clone this repo
  with the following command:
  ```console
  git clone --recurse-submodules <URL>
  ```

  Or you can clone it in the standard way and then run the following
  from within your local repo directory:
  ```console
  git submodule update --init --recursive
  ```
  
  Install python requirements:
  ```console
  pip install -r requirements.txt
  ```
  
  After that, you need to enter in our custom Rogue build directory and make it:
  ```console
  cd rogue
  make
  ```
