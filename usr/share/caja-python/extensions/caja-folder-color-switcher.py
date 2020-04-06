# -*- coding: utf-8 -*-
# Folder Color 0.0.11
# Copyright (C) 2012-2014 Marcos Alvarez Costales https://launchpad.net/~costales
#
# Folder Color is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# Folder Color is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Folder Color; if not, see http://www.gnu.org/licenses
# for more information.

import os, urllib, gettext, locale, collections
import subprocess
from gi.repository import Caja, GObject, Gio, GLib
_ = gettext.gettext

# LOGGING setup:
# By default, we are only logging messages of level WARNING or higher.
# For debugging purposes it is useful to run Nemo/Caja with
# LOG_FOLDER_COLOR_SWITCHER=10 (DEBUG).
import logging
log_level = os.getenv('LOG_FOLDER_COLOR_SWITCHER', None)
if not log_level:
    log_level = logging.WARNING
else:
    log_level = int(log_level)
logging.basicConfig(level=log_level)
logger = logging.getLogger(__name__)

# Note: we don't actually use the second column programmatically
# It's there so color names are picked up when the pot file is generated
# Further down the code we use gettext on the first column...
# The reason we don't pick up the second column is because the gettext domain
# needs to be the one of the file browser right now.. and then switch to our own domain
# when the time comes to generate the menu.
# We need this list prior to that moment though.
COLORS = collections.OrderedDict ([
            ('Sand', _('Sand')),
            ('Beige', _('Beige')),
            ('Yellow', _('Yellow')),
            ('Orange', _('Orange')),
            ('Brown', _('Brown')),
            ('Red', _('Red')),
            ('Purple', _('Purple')),
            ('Pink', _('Pink')),
            ('Blue', _('Blue')),
            ('Cyan', _('Cyan')),
            ('Aqua', _('Aqua')),
            ('Teal', _('Teal')),
            ('Green', _('Green')),
            ('White', _('White')),
            ('Grey', _('Grey')),
            ('Black', _('Black'))
           ])

class Theme(object):
    KNOWN_THEMES = {
        'Mint-X': 'Green',
        'Mint-Y': 'Green',
        'Mint-X-Dark': 'Green',
        'Rave-X-CX': 'Beige',
        'Faience': 'Beige',
        'gnome': 'Beige',
        'Matrinileare': 'Beige',
        'menta': 'Green',
        'mate': 'Beige',
        'oxygen': 'Blue'
    }
    logger.debug("Known themes are: %s" % KNOWN_THEMES)

    def __init__(self, base_name, color_variant):
        self.base_name = base_name
        self.color_variant = color_variant

        self.base_path = str("/usr/share/icons/%s/" % self)

        self.variants = {}
        self.default_folder_file = None
        self.inherited_themes_cache = None
        self.supported_theme_colors = None

        self.KNOWN_DIRECTORIES = {
            GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP): 'user-desktop',
            GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS): 'folder-documents',
            GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD): 'folder-download',
            GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_MUSIC): 'folder-music',
            GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES): 'folder-pictures',
            GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PUBLIC_SHARE): 'folder-publicshare',
            GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_TEMPLATES): 'folder-templates',
            GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_VIDEOS): 'folder-videos',
            GLib.get_home_dir(): 'folder-home',
        }

        self.discover_image_support()

    def __str__(self):
        if self.color_variant:
            return "%s-%s" % (self.base_name, self.color_variant)
        else:
            return "%s" % self.base_name

    @staticmethod
    def parse(theme_str):
        base_name = theme_str
        color_variant = None
        for color in COLORS:
            if theme_str.endswith("-%s" % color):
                base_name = theme_str[:-len("-%s" % color)]
                color_variant = color
        return base_name, color_variant

    @staticmethod
    def from_theme_name(theme_str):
        base_name, color_variant = Theme.parse(theme_str)
        return Theme(base_name, color_variant)

    def get_variant(self, base_name, color):
        if color is not None:
            key = "%s-%s" % (base_name, color)
        else:
            key = "%s" % base_name

        if key in self.variants.keys():
            return self.variants[key]
        else:
            variant = Theme(base_name, color)
            self.variants[key] = variant
            return variant

    def discover_image_support(self):
        logger.debug("Discovering image support for theme %s" % self)

        for key in self.KNOWN_DIRECTORIES.keys():
            found = False

            for ext in (".png", ".svg"):
                path = os.path.join(self.base_path, "places", "48", self.KNOWN_DIRECTORIES[key] + ext)

                if os.path.isfile(path):
                    logger.debug("Found icon for '%s' at '%s'" % (key, path))
                    self.KNOWN_DIRECTORIES[key] = path
                    found = True
                    break

            if not found:
                self.KNOWN_DIRECTORIES[key] = None

        for ext in (".png", ".svg"):
            path = os.path.join(self.base_path, "places", "48", "folder" + ext)

            if os.path.isfile(path):
                logger.debug("Found generic folder icon at '%s'" % (path,))

                self.default_folder_file = path
                break

    def get_folder_icon_path(self, directory=None):
        return self.KNOWN_DIRECTORIES.get(directory, self.default_folder_file)

    def get_index_theme_path(self):
        return os.path.join(self.base_path, "index.theme")

    def has_icon_for_folder(self, directory=None):
        return self.get_folder_icon_path(directory) is not None

    def inherited_themes(self):
        if self.inherited_themes_cache == None:
            result = []

            logger.debug('Importing config parser...')
            import ConfigParser
            parser = ConfigParser.RawConfigParser()
            index_theme_path = self.get_index_theme_path()
            try:
                logger.debug('Trying to read index.theme at %s' % index_theme_path)
                parser.read(index_theme_path)
                inherits_str = parser.get('Icon Theme', 'Inherits')
                logger.debug('Theme %s inherits %s' % (self, inherits_str))

                for parent in inherits_str.split(","):
                    result.append(Theme.from_theme_name(parent))
            except:
                logger.info('Could not read index.theme for theme %s' % self)
                result = []

            self.inherited_themes_cache = result
        return self.inherited_themes_cache

    def get_ancestor_defining_folder_svg(self, directory=None):
        if self.has_icon_for_folder(directory):
            return self
        for theme in self.inherited_themes():
            ancestor = theme.get_ancestor_defining_folder_svg(directory)
            if ancestor:
                return ancestor
        return None

    def sibling(self, color):
        if color == self.color:
            # This theme implements the desired color
            return self
        elif color == Theme.KNOWN_THEMES.get(self.base_name):
            # The base version of this theme implements the desired color
            return self.get_variant(self.base_name, None)
        else:
            # The color belongs to a color variant
            return self.get_variant(self.base_name, color)

    def find_folder_icon(self, color, directory=None):
        logger.debug("Trying to find icon for directory %s in %s for theme %s" % (directory, color, self))
        relevant_ancestor = self.get_ancestor_defining_folder_svg(directory)
        if not relevant_ancestor:
            logger.debug("Could not find ancestor defining SVG")
            return None

        logger.debug("Ancestor defining SVG is %s" % relevant_ancestor)
        colored_theme = relevant_ancestor.sibling(color)

        return colored_theme.get_folder_icon_path(directory)

    def get_supported_colors(self, paths):
        if self.supported_theme_colors == None:
            supported_colors = []

            for color in COLORS:
                color_supported = True
                for directory in paths:
                    icon_path = self.find_folder_icon(color, directory)
                    if not icon_path:
                        color_supported = False
                        break
                if color_supported:
                    supported_colors.append(color)

            self.supported_theme_colors = supported_colors

        return self.supported_theme_colors

    @property
    def color(self):
        if self.color_variant:
            return self.color_variant
        else:
            return Theme.KNOWN_THEMES.get(self.base_name)


class ChangeFolderColorBase(object):
    def update_theme(self, theme_str):
        logger.info("Current icon theme: %s", theme_str)
        self.theme = Theme.from_theme_name(theme_str)
        logger.info("Its color is %s", self.theme.color)

    def set_folder_icons(self, color, items):
        for item in items:

            if item.is_gone():
                continue

            # Get object
            path = urllib.unquote(item.get_uri()[7:])
            directory = item.get_location()
            info = directory.query_info('metadata::custom-icon', 0, None)

            # Set color
            if color:
                icon_path = self.theme.find_folder_icon(color, path)
                if icon_path:
                    icon_file = Gio.File.new_for_path(icon_path)
                    icon_uri = icon_file.get_uri()
                    info.set_attribute_string('metadata::custom-icon', icon_uri)
                    logger.info('Set custom-icon of %s to %s' % (path, icon_path))
                else:
                    logger.error('Could not find %s colored icon' % color)
            else:
                # A color of None unsets the custom-icon
                info.set_attribute('metadata::custom-icon', Gio.FileAttributeType.INVALID, 0)

            # Write changes
            directory.set_attributes_from_info(info, 0, None)

            # Touch the directory to make Nemo/Caja re-render its icons
            subprocess.call(["touch", path])

class ChangeColorFolder(ChangeFolderColorBase, GObject.GObject, Caja.MenuProvider):
    def __init__(self):
        logger.info("Initializing folder-color-switcher extension...")
        self.SEPARATOR = u'\u2015' * 4
        self.settings = Gio.Settings.new("org.mate.interface")
        self.settings.connect("changed::icon-theme", self.on_theme_changed)
        self.on_theme_changed(None, None)

    def on_theme_changed(self, settings, key):
        self.update_theme(self.settings.get_string("icon-theme"))

    def menu_activate_cb(self, menu, color, folders):
        self.set_folder_icons(color, folders)

    def get_background_items(self, window, current_folder):
        return []

    # Caja invoke this function in its startup > Then, create menu entry
    def get_file_items(self, window, items_selected):
        if not items_selected:
            # No items selected
            return

        locale.setlocale(locale.LC_ALL, '')
        gettext.bindtextdomain('folder-color-switcher')
        gettext.textdomain('folder-color-switcher')

        directories = []
        directories_selected = []

        for item in items_selected:
            # Only folders
            if not item.is_directory():
                logger.info("A selected item is not a directory, skipping")
                continue

            logger.debug('URI "%s" is in selection', item.get_uri())

            if item.get_uri_scheme() != 'file':
                return

            directory = item.get_location()
            logger.debug('Valid path selected: "%s"', directory.get_path())
            directories.append(directory)
            directories_selected.append(item)

        if not directories_selected:
            return

        supported_colors = self.theme.get_supported_colors(directories)

        if supported_colors:
            logger.debug("At least one color supported: creating menu entry")
            top_menuitem = Caja.MenuItem(name='ChangeFolderColorMenu::Top', label=_("Change color"))
            submenu = Caja.Menu()
            top_menuitem.set_submenu(submenu)

            for color in supported_colors:
                name = ''.join(['ChangeFolderColorMenu::"', color, '"'])
                label = _(color)
                item = Caja.MenuItem(name=name, label=label, icon='folder-color-switcher-%s' % color.lower())
                item.connect('activate', self.menu_activate_cb, color, directories_selected)
                submenu.append_item(item)

            # Separator
            item_sep = Caja.MenuItem(name='ChangeFolderColorMenu::Sep1', label=self.SEPARATOR, sensitive=False)
            submenu.append_item(item_sep)

            # Restore
            item_restore = Caja.MenuItem(name='ChangeFolderColorMenu::Restore', label=_("Default"))
            item_restore.connect('activate', self.menu_activate_cb, None, directories_selected)
            submenu.append_item(item_restore)

            return top_menuitem,
