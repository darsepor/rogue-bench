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

from ui.UI import UI


class UIManager:
    @staticmethod
    def init(ui, rogue_box):
        """Launch an user interface and return it

        :rtype: UI
        """
        if ui == "tk":
            from ui.UITk import UITk
            return UITk(rogue_box)
        elif ui == "curses":
            from ui.UICurse import UICurse
            return UICurse(rogue_box)
