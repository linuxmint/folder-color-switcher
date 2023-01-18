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

import os, gettext, locale, collections, re, gi

gi.require_version('Gtk', '3.0')
gi.require_version('Nemo', '3.0')

from gi.repository import Nemo, GObject, Gio, GLib, Gtk, Gdk

# i18n
APP = 'folder-color-switcher'
LOCALE_DIR = "/usr/share/locale"
locale.bindtextdomain(APP, LOCALE_DIR)
gettext.bindtextdomain(APP, LOCALE_DIR)
gettext.textdomain(APP)
_ = gettext.gettext

PLUGIN_DESCRIPTION = _('Allows you to change folder colors from the context menu under supported icon themes')

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


class ColoredIconThemeSet:
    # ordered because matched using "startsWith"
    KNOWN_THEMES = collections.OrderedDict({
        'Mint-X-Dark': 'Green',
        'Mint-X': 'Green',
        'Mint-Y-Legacy-Dark': 'Green', # falls back to Mint-Y-Legacy first, as our matcher looks for a common prefix.
        'Mint-Y-Legacy': 'Green',
        'Mint-Y-Dark': 'Green', # falls back to Mint-Y itself, but has color variants
        'Mint-Y': 'Green',
        'Rave-X-CX': 'Beige',
        'Faience': 'Beige',
        'gnome': 'Beige',
        'Matrinileare': 'Beige',
        'menta': 'Green',
        'mate': 'Beige',
        'oxygen': 'Blue'
    })

    def __init__(self):
        self.availableColoredIconThemes = {}

        self.it_settings = Gio.Settings.new("org.cinnamon.desktop.interface")
        self._on_icon_theme_changed(None)
        self.currentIconTheme.connect('changed', self._on_icon_theme_changed)

    def _on_icon_theme_changed(self, theme):
        # get current icon theme, might be a variant, e.g. "Mint-Y-Aqua"
        self.currentIconTheme = Gtk.IconTheme.get_default()

        # get its name
        self.currentIconThemeName = self.it_settings.get_string("icon-theme")
        logger.debug("IconTheme changed to: %s", self.currentIconThemeName)

        self._determine_base_icon_theme()
        self._load_available_colors()

    def _determine_base_icon_theme(self):
        # the determined base icon theme, e.g. "Mint-Y"
        self.currentBaseIconThemeName = None

        # exact match (== no color variant in use)
        if self.currentIconThemeName in self.KNOWN_THEMES:
            self.currentBaseIconThemeName = self.currentIconThemeName
            return

        # naive via name
        for theme in self.KNOWN_THEMES:
            logger.debug("Comparing known base theme '%s' with current theme '%s'" % (theme, self.currentIconThemeName))
            if self.currentIconThemeName.startswith(theme):
                self.currentBaseIconThemeName = theme
                logger.debug("Matched (%s)" % self.currentBaseIconThemeName)
                break

    def _load_available_colors(self):
        if self.currentBaseIconThemeName is None:
            # non-supported icon theme
            self.availableColoredIconThemes = {}
            return

        # add base theme color, when using a variant
        if self.currentBaseIconThemeName != self.currentIconThemeName:
            it = Gtk.IconTheme.new()
            it.set_custom_theme(self.currentBaseIconThemeName)
            base_color = self.KNOWN_THEMES[self.currentBaseIconThemeName]
            self.availableColoredIconThemes[base_color] = it

        for color in COLORS:
            it = Gtk.IconTheme.new()
            it.set_custom_theme('%s-%s' % (self.currentBaseIconThemeName, color))

            # check if the default 'folder' icon is available for the given color (size: 32).
            # HACK: to ignore fallback icons, check that the base theme name is included in the icon path
            icon_info = it.choose_icon(['folder', None], 32, 0)

            if not icon_info or self.currentBaseIconThemeName not in icon_info.get_filename():
                continue

            self.availableColoredIconThemes[color] = it

    def get_available_colors(self):
        return self.availableColoredIconThemes.keys()

    def get_icon_uri_for_color_size_and_scale(self, icon_name: str, color: str, size: int, scale: int) -> str:
        logger.debug('Searching: icon "%s" for color "%s", size %i and scale %i', icon_name, color, size, scale)
        icon_theme = self.availableColoredIconThemes.get(color, None)

        if icon_theme:
            icon_info = icon_theme.choose_icon_for_scale([icon_name, None], size, scale, 0)
            if icon_info:
                uri = GLib.filename_to_uri(icon_info.get_filename(), None)
                logger.debug("Found icon at URI: %s", uri)
                return uri

        logger.debug('No icon "%s" found for color "%s", size %i and scale %i', icon_name, color, size, scale)
        return None


class ChangeFolderColorBase(object):
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

    # https://standards.freedesktop.org/icon-naming-spec/icon-naming-spec-latest.html
    KNOWN_DIRECTORIES = {
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

    def __init__(self):
        self.parent_directory = None

        # view preferences
        self.ignore_view_metadata = False
        self.default_view = None

        self.themeset = ColoredIconThemeSet()

        self.nemo_settings = Gio.Settings.new("org.nemo.preferences")
        self.nemo_settings.connect("changed::ignore-view-metadata", self.on_ignore_view_metadata_changed)
        self.nemo_settings.connect("changed::default-folder-viewer", self.on_default_view_changed)
        self.on_ignore_view_metadata_changed(None)
        self.on_default_view_changed(None)

    def on_ignore_view_metadata_changed(self, settings, key="ignore-view-metadata"):
        self.ignore_view_metadata = self.nemo_settings.get_boolean(key)

    def on_default_view_changed(self, settings, key="default-folder-viewer"):
        self.default_view = self.nemo_settings.get_string(key)

    @staticmethod
    def get_default_view_zoom_level(view="icon-view"):
        zoom_lvl_string = Gio.Settings.new("org.nemo.%s" % view).get_string("default-zoom-level")
        return ChangeFolderColorBase.ZOOM_LEVELS[zoom_lvl_string]

    def get_default_view_icon_size(self):
        zoom_lvl_index = self.get_default_view_zoom_level(self.default_view)
        return ChangeFolderColorBase.ZOOM_LEVEL_ICON_SIZES[self.default_view][zoom_lvl_index]

    @staticmethod
    def get_folder_icon_name(directory):
        return ChangeFolderColorBase.KNOWN_DIRECTORIES.get(directory, 'folder')

    def get_desired_icon_size(self):
        if self.ignore_view_metadata:
            logger.info("Nemo is set to ignore view metadata")
            return self.get_default_view_icon_size()

        logger.info("Nemo is set to apply view metadata")
        return self.get_current_view_icon_size()


    def get_current_view_icon_size(self):
        # get the folder where we are currently in
        if not self.parent_directory:
            return 64

        info = self.parent_directory.get_location().query_info('metadata::*', 0, None)
        meta_view = info.get_attribute_string('metadata::nemo-default-view')

        if meta_view:
            match = re.search("OAFIID:Nemo_File_Manager_(\\w+)_View", meta_view)
            view = match.group(1).lower() + "-view"
        else:
            view = self.default_view

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
            logger.debug("Icon size for the current view is: %i", icon_size)
            return icon_size

        logger.debug("falling back to defaults")
        return self.get_default_view_icon_size()


    def set_folder_colors(self, folders, color):
        self.parent_directory = folders[0].get_parent_info()
        logger.debug("Parent folder is: %s", self.parent_directory.get_uri())

        if color:
            icon_size = self.get_desired_icon_size()
            default_folder_icon_uri = self.themeset.get_icon_uri_for_color_size_and_scale('folder', color, icon_size, self.scale_factor)

            if not default_folder_icon_uri:
                return

        for folder in folders:
            if folder.is_gone():
                continue

            # get Gio.File object
            directory = folder.get_location()
            path = directory.get_path()

            if color:
                icon_uri = default_folder_icon_uri
                icon_name = self.get_folder_icon_name(path)

                if icon_name != 'folder':
                    icon_uri = self.themeset.get_icon_uri_for_color_size_and_scale(icon_name, color, icon_size, self.scale_factor)

                if icon_uri:
                    directory.set_attribute_string('metadata::custom-icon', icon_uri, 0, None)
            else:
                # A color of None unsets the custom-icon
                directory.set_attribute('metadata::custom-icon', Gio.FileAttributeType.INVALID, 0, 0, None)

            # update the directory's modified date to make Nemo/Caja re-render its icon
            os.utime(path, None)


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

class ChangeFolderColor(ChangeFolderColorBase, GObject.GObject, Nemo.MenuProvider, Nemo.NameAndDescProvider):
    def __init__(self):
        super().__init__()

        logger.info("Initializing folder-color-switcher extension...")
        logger.debug("Known themes are: %s", ', '.join(list(ColoredIconThemeSet.KNOWN_THEMES.keys())))

    def menu_activate_cb(self, menu, color, folders):
        # get scale factor from the clicked menu widget (for Hi-DPI)
        self.scale_factor = menu.get_scale_factor()
        self.set_folder_colors(folders, color)

    def get_background_items(self, window, current_folder):
        return

    def get_name_and_desc(self):
        return [("Folder Color Switcher:::%s" % PLUGIN_DESCRIPTION)]

    # Nemo invoke this function in its startup > Then, create menu entry
    def get_file_items(self, window, items_selected):
        if not items_selected:
            # No items selected
            return

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

        supported_colors = self.themeset.get_available_colors()

        if supported_colors:
            locale.setlocale(locale.LC_ALL, '')
            gettext.bindtextdomain('folder-color-switcher')
            gettext.textdomain('folder-color-switcher')
            logger.debug("At least one color supported: creating menu entry")
            item = Nemo.MenuItem(name='ChangeFolderColorMenu::Top')
            item.set_widget_a(self.generate_widget(supported_colors, directories_selected))
            item.set_widget_b(self.generate_widget(supported_colors, directories_selected))
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
