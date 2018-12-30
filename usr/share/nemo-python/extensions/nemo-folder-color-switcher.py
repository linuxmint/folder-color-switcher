#!/usr/bin/python3
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

import os, gettext, locale, collections, re
import subprocess
try:
	# Python2 (Mint 19)
	import ConfigParser as configparser
except:
	# Python 3 (Mint 19.1)
	import configparser

from gi.repository import Nemo, GObject, Gio, GLib, Gtk, Gdk, GdkPixbuf, cairo
_ = gettext.gettext
P_ = gettext.ngettext

import signal
signal.signal(signal.SIGINT, signal.SIG_DFL)


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

    # view[zoom-level] -> icon size
    # Notes:
    # - icon size:    values from nemo/libnemo-private/nemo-icon-info.h (checked)
    # - list view:    icon sizes don't match the defined sizes in nemo-icon-info.h (yet)
    # - compact view: hasn't defined sizes defined in nemo-icon-info.h
    ZOOM_LEVEL_ICON_SIZES = {
        'icon-view'    : [24, 32, 48, 64, 96, 128, 256],
        #'list-view'    : [16, 24, 32, 48, 72, 96,  192], # defined values
        # sizes measured manually for reasons above
        'list-view'    : [16, 16, 24, 32, 48, 72,  96 ],
        'compact-view' : [16, 16, 18, 24, 36, 48,  96 ]
    }
    ZOOM_LEVELS = {
        'smallest' : 0,
        'smaller'  : 1,
        'small'    : 2,
        'standard' : 3,
        'large'    : 4,
        'larger'   : 5,
        'largest'  : 6
    }

    def __init__(self, base_name, color_variant):
        self.base_name = base_name
        self.color_variant = color_variant

        self.base_path = str("/usr/share/icons/%s/" % self)

        self.variants = {}
        self.default_folder_file = {}
        self.inherited_themes_cache = None
        self.supported_theme_colors = None
        self.supported_icon_sizes = {}
        self.icon_path_cache = {}

        # https://standards.freedesktop.org/icon-naming-spec/icon-naming-spec-latest.html
        self.KNOWN_DIRECTORIES = {
            GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP): 'user-desktop',
            GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS): 'folder-documents',
            GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD): 'folder-download',
            GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_MUSIC): 'folder-music',
            GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES): 'folder-pictures',
            GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PUBLIC_SHARE): 'folder-publicshare',
            GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_TEMPLATES): 'folder-templates',
            GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_VIDEOS): 'folder-videos',
            GLib.get_home_dir(): 'user-home'
        }

        self.discover_supported_icon_sizes()

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
            try:
                variant = Theme(base_name, color)
                self.variants[key] = variant
                return variant
            except:
                # Theme does not exist
                return None

    def discover_image_support(self, icon_size):
        logger.debug("Discovering image support for theme %s" % self)

        if icon_size in self.icon_path_cache:
            logger.info("Icons paths for theme %s in size %i are cached" % (self, icon_size))
            return

        self.default_folder_file[icon_size] = None
        self.icon_path_cache[icon_size] = {}

        # special directories
        for key in self.KNOWN_DIRECTORIES.keys():
            self.icon_path_cache[icon_size][key] = None

            for ext in (".png", ".svg"):
                path = os.path.join(self.base_path, "places", str(icon_size), self.KNOWN_DIRECTORIES[key] + ext)

                if os.path.isfile(path):
                    logger.debug("Found icon for '%s' at '%s'" % (key, path))
                    self.icon_path_cache[icon_size][key] = path
                    break

        # usual directories
        for ext in (".png", ".svg"):
            path = os.path.join(self.base_path, "places", str(icon_size), "folder" + ext)

            if os.path.isfile(path):
                logger.debug("Found generic folder icon at '%s'" % path)
                self.default_folder_file[icon_size] = path
                break

    def discover_supported_icon_sizes(self):
        parser = configparser.ConfigParser()
        index_theme_path = self.get_index_theme_path()

        if not os.path.isfile(index_theme_path):
            logger.debug("Theme %s is not available" % self)
            raise Exception("Theme %s is not available" % self)

        try:
            logger.debug('Trying to read index.theme at %s' % index_theme_path)
            parser.read(index_theme_path)

            for section in parser.sections():
                search = re.search("^places/(\\d+)$",section)

                if search:
                    scalable = parser.get(section, "Type")
                    logger.debug("Discovered theme icon size: %s, type: %s", search.group(1), scalable )
                    self.supported_icon_sizes[int(search.group(1))] = scalable

        except:
            logger.info('Could not read index.theme for theme %s' % self)

    def get_default_view_icon_size(self):
        default_view = self.get_default_view()
        zoom_lvl_index = self.get_default_view_zoom_level(default_view)

        return self.ZOOM_LEVEL_ICON_SIZES[default_view][zoom_lvl_index]

    def get_current_view_icon_size(self):
        # get the folder where we are currently in
        dir = ChangeColorFolder.current_directory
        info = dir.query_info('metadata::*', 0, None)
        meta_view = info.get_attribute_string('metadata::nemo-default-view')

        if meta_view:
            match = re.search("OAFIID:Nemo_File_Manager_(\\w+)_View", meta_view)
            view = match.group(1).lower() + "-view"
        else:
            view = self.get_default_view()

        if view in self.ZOOM_LEVEL_ICON_SIZES.keys():
            # the zoom level is store as string ('0', ... , '6')
            meta_zoom_lvl = info.get_attribute_string("metadata::nemo-%s-zoom-level" % view)

            if not meta_zoom_lvl:
                # if view is set while the conresponding zoom level is not
                # (e.g. user switched views in this folder but never used zoom)
                zoom_level = self.get_default_view_zoom_level(view)
            else:
                zoom_level = int(meta_zoom_lvl)

            icon_size = self.ZOOM_LEVEL_ICON_SIZES[view][zoom_level]
            logger.debug("Icon size for the current view is: %i" % icon_size)
            return icon_size

        logger.debug("falling back to defaults")
        return self.get_default_view_icon_size()

    def get_best_available_icon_size(self, desired_icon_size):
        logger.debug("Finding the best available icon size for size: %i", desired_icon_size)

        # prefer SVG (scalable size) if available
        for size in self.supported_icon_sizes:
            if self.supported_icon_sizes[size] == "Scalable":
                logger.debug("Best available icon size is: %i (scalable)", size)
                return size

        # direct match
        if self.supported_icon_sizes.get(desired_icon_size):
            logger.debug("Desired icon size is avaiable: %i", desired_icon_size)
            return desired_icon_size

        # choose closest matching icon size
        best_abs = 9999
        for val in self.supported_icon_sizes:
            vabs = abs(val - desired_icon_size)

            if vabs < best_abs:
                best_abs = vabs
                best_size = val

        logger.debug("Best available icon size is: %i", best_size)
        return best_size

    def get_default_view(self):
        nemo_prefs = Gio.Settings.new("org.nemo.preferences")
        return nemo_prefs.get_string("default-folder-viewer")

    def get_default_view_zoom_level(self, view="icon-view"):
        zoom_lvl_string = Gio.Settings.new("org.nemo." + view).get_string("default-zoom-level")
        return self.ZOOM_LEVELS[zoom_lvl_string]

    def get_folder_icon_path(self, directory=None):
        if ChangeColorFolder.ignore_view_metadata:
            logger.info("Nemo is set to ignore view metadata")
            desired_size = self.get_default_view_icon_size()
        else:
            logger.info("Nemo is set to apply view metadata")
            desired_size = self.get_current_view_icon_size()

        icon_size = self.get_best_available_icon_size(desired_size)

        # scan for available folder icons
        self.discover_image_support(icon_size)

        # return the icon path if available or fall back to the generic folder icon
        return self.icon_path_cache[icon_size].get(directory.get_path(), self.default_folder_file[icon_size])

    def get_index_theme_path(self):
        return os.path.join(self.base_path, "index.theme")

    def has_icon_for_folder(self, directory=None):
        return self.get_folder_icon_path(directory) is not None

    def inherited_themes(self):
        if self.inherited_themes_cache == None:
            result = []

            parser = configparser.RawConfigParser()
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
        logger.debug("Trying to find icon for directory %s in %s for theme %s" % (directory.get_path(), color, self))
        relevant_ancestor = self.get_ancestor_defining_folder_svg(directory)
        if not relevant_ancestor:
            logger.debug("Could not find ancestor defining SVG")
            return None

        logger.debug("Ancestor defining SVG is %s" % relevant_ancestor)
        colored_theme = relevant_ancestor.sibling(color)

        if not colored_theme:
            return None

        return colored_theme.get_folder_icon_path(directory)

    def get_supported_colors(self, directories):
        if self.supported_theme_colors == None:
            supported_colors = []

            for color in COLORS:
                logger.debug("Checking for theme color %s" % color)
                color_supported = True
                for directory in directories:
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
    current_directory = None
    ignore_view_metadata = False

    def update_theme(self, theme_str):
        logger.info("Current icon theme: %s", theme_str)
        self.theme = Theme.from_theme_name(theme_str)
        logger.info("Its color is %s", self.theme.color)

    def set_folder_icons(self, color, items):
        for item in items:

            if item.is_gone():
                continue

            # get Gio.File object
            directory = item.get_location()
            path = directory.get_path()
            info = directory.query_info('metadata::custom-icon', 0, None)

            # Set color
            if color:
                icon_path = self.theme.find_folder_icon(color, directory)
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


css_colors = b"""
.folder-color-switcher-button,
.folder-color-switcher-restore {
    min-height: 16px;
    min-width: 16px;
    padding: 0;
}
.folder-color-switcher-button {
    border-style: solid;
    border-width: 1px;
    border-radius: 1px;
    border-color: transparent;
}

.folder-color-switcher-button:hover {
    border-color: #9c9c9c;
}

.folder-color-switcher-restore {
    background-color: transparent;
}

.folder-color-switcher-restore:hover {
    background-color: rgba(255,255,255,0);
}
"""

provider = Gtk.CssProvider()
provider.load_from_data(css_colors)
screen = Gdk.Screen.get_default()
Gtk.StyleContext.add_provider_for_screen (screen, provider, 600) # GTK_STYLE_PROVIDER_PRIORITY_APPLICATION

class ChangeColorFolder(ChangeFolderColorBase, GObject.GObject, Nemo.MenuProvider, Nemo.NameAndDescProvider):
    def __init__(self):
        logger.info("Initializing folder-color-switcher extension...")
        locale.setlocale(locale.LC_ALL, '')
        gettext.bindtextdomain('folder-color-switcher')
        gettext.textdomain('folder-color-switcher')

        self.SEPARATOR = u'\u2015' * 4
        self.settings = Gio.Settings.new("org.cinnamon.desktop.interface")
        self.settings.connect("changed::icon-theme", self.on_theme_changed)
        self.on_theme_changed(None, None)

        self.nemo_settings = Gio.Settings.new("org.nemo.preferences")
        self.nemo_settings.connect("changed::ignore-view-metadata", self.on_ignore_view_metadata_changed)
        self.on_ignore_view_metadata_changed(None)

    def on_theme_changed(self, settings, key):
        self.update_theme(self.settings.get_string("icon-theme"))

    def on_ignore_view_metadata_changed(self, settings, key="ignore-view-metadata"):
        ChangeColorFolder.ignore_view_metadata = self.nemo_settings.get_boolean(key)

    def menu_activate_cb(self, menu, color, folders):
        self.set_folder_icons(color, folders)

    def get_background_items(self, window, current_folder):
        logger.debug("Current folder is: " + current_folder.get_name())
        ChangeColorFolder.current_directory = current_folder.get_location()
        return

    def get_name_and_desc(self):
        return [("Folder Color Switcher:::Allows you to change folder colors from the context menu under supported icon themes")]

    # Nemo invoke this function in its startup > Then, create menu entry
    def get_file_items(self, window, items_selected):
        if not items_selected:
            # No items selected
            return

        directories = []
        for item in items_selected:
            # Only folders
            if not item.is_directory():
                logger.info("A selected item is not a directory, exiting")
                return

            logger.debug('URI "%s" is in selection', item.get_uri())

            if item.get_uri_scheme() != 'file':
                return

            directory = item.get_location()
            logger.debug('Valid path selected: "%s"', directory.get_path())
            directories.append(directory)

        supported_colors = self.theme.get_supported_colors(directories)

        if supported_colors:
            logger.debug("At least one color supported: creating menu entry")
            item = Nemo.MenuItem(name='ChangeFolderColorMenu::Top')
            item.set_widget_a(self.generate_widget(supported_colors, items_selected))
            item.set_widget_b(self.generate_widget(supported_colors, items_selected))
            return Nemo.MenuItem.new_separator('ChangeFolderColorMenu::TopSep'),   \
                   item,                                                           \
                   Nemo.MenuItem.new_separator('ChangeFolderColorMenu::BotSep')
        else:
            logger.debug("Could not find any supported colors")
            return

    def generate_widget(self, colors, items):
        widget = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 1)

        # Generate restore button
        button = FolderColorButton("restore")
        button.connect('clicked', self.menu_activate_cb, None, items)
        if len(items) > 1:
            button.set_tooltip_text (_("Restores the color of the selected folders"))
        else:
            button.set_tooltip_text (_("Restores the color of the selected folder"))
        widget.pack_start(button, False, False, 1)

        # Generate buttons for the colors
        for color in colors:
            color_code = color
            color_name = _(color).lower()
            button = FolderColorButton(color_code)
            button.connect('clicked', self.menu_activate_cb, color_code, items)
            if len(items) > 1:
                button.set_tooltip_markup (_("Changes the color of the selected folders to %s") % color_name)
            else:
                button.set_tooltip_markup (_("Changes the color of the selected folder to %s") % color_name)
            widget.pack_start(button, False, False, 1)

        widget.show_all()

        return widget


class FolderColorButton(Nemo.SimpleButton):
    def __init__(self, color):
        super(FolderColorButton, self).__init__()

        c = self.get_style_context()
        if color == "restore":
            c.add_class("folder-color-switcher-button")
            image = Gtk.Image(icon_name="edit-delete-symbolic")
            self.set_image(image)
        else:
            c.add_class("folder-color-switcher-button")
            image = Gtk.Image()
            image.set_from_file("/usr/share/icons/hicolor/22x22/apps/folder-color-switcher-%s.png" % color.lower())
            self.set_image(image)
