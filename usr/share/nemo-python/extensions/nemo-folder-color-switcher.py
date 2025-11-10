#!/usr/bin/python3
# -*- coding: utf-8 -*-

import gettext
import gi
import json
import locale
import os
import re
import subprocess

gi.require_version('Gtk', '3.0')
gi.require_version('Nemo', '3.0')

from gi.repository import Nemo, GObject, Gio, GLib, Gtk, Gdk, GdkPixbuf

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

# We list known color names here, just so they get picked up by makepot.
color_names = [
    _('Aqua'),
    _('Beige'),
    _('Black'),
    _('Blue'),
    _('Brown'),
    _('Cyan'),
    _('Green'),
    _('Grey'),
    _('Navy'),
    _('Orange'),
    _('Pink'),
    _('Purple'),
    _('Red'),
    _('Sand'),
    _('Teal'),
    _('White'),
    _('Yellow')
]

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

        self.nemo_settings = Gio.Settings.new("org.nemo.preferences")
        self.nemo_settings.connect("changed::ignore-view-metadata", self.on_ignore_view_metadata_changed)
        self.nemo_settings.connect("changed::default-folder-viewer", self.on_default_view_changed)
        self.on_ignore_view_metadata_changed(None)
        self.on_default_view_changed(None)

        # Read the JSON files
        self.styles = {}
        path = "/usr/share/folder-color-switcher/colors.d"
        if os.path.exists(path):
            for filename in sorted(os.listdir(path)):
                if filename.endswith(".json"):
                    try:
                        with open(os.path.join(path, filename)) as f:
                            json_text = json.loads(f.read())
                            for style_json in json_text["styles"]:
                                style_name = style_json["name"]
                                for icon_theme_json in style_json["icon-themes"]:
                                    name = icon_theme_json["theme"]
                                    self.styles[name] = style_json
                    except Exception as e:
                        print(f"Failed to parse styles from {filename}.")
                        print(e)

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

    def get_icon_uri_for_color_size_and_scale(self, icon_name: str, icon_theme_name: str, size: int, scale: int) -> str:
        logger.debug('Searching: icon "%s" for theme "%s", size %i and scale %i', icon_name, icon_theme_name, size, scale)

        icon_theme = Gtk.IconTheme.new()
        icon_theme.set_custom_theme(icon_theme_name)
        if icon_theme is not None:
            icon_info = icon_theme.choose_icon_for_scale([icon_name, None], size, scale, 0)
            if icon_info:
                uri = GLib.filename_to_uri(icon_info.get_filename(), None)
                logger.debug("Found icon at URI: %s", uri)
                return uri

        logger.debug('No icon "%s" found for color "%s", size %i and scale %i', icon_name, color, size, scale)
        return None

    def set_folder_colors(self, folders, icon_theme):
        self.parent_directory = folders[0].get_parent_info()
        logger.debug("Parent folder is: %s", self.parent_directory.get_uri())

        if icon_theme is not None:
            theme_name = icon_theme["theme"]
            icon_size = self.get_desired_icon_size()
            default_folder_icon_uri = self.get_icon_uri_for_color_size_and_scale('folder', theme_name, icon_size, self.scale_factor)

            if not default_folder_icon_uri:
                return

        for folder in folders:
            if folder.is_gone():
                continue

            # get Gio.File object
            directory = folder.get_location()
            path = directory.get_path()

            if icon_theme is not None:
                theme_name = icon_theme["theme"]
                icon_uri = default_folder_icon_uri
                icon_name = self.get_folder_icon_name(path)

                if icon_name != 'folder':
                    icon_uri = self.get_icon_uri_for_color_size_and_scale(icon_name, theme_name, icon_size, self.scale_factor)

                if icon_uri:
                    directory.set_attribute_string('metadata::custom-icon', icon_uri, 0, None)
            else:
                # A color of None unsets the custom-icon
                directory.set_attribute('metadata::custom-icon', Gio.FileAttributeType.INVALID, 0, 0, None)

            # touch the folder (to force Nemo/Caja to re-render its icon)
            returncode = subprocess.call(['touch', '-r', path, path])
            if returncode != 0:
                subprocess.call(['touch', path])


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

    def menu_activate_cb(self, menu, icon_theme, folders):
        # get scale factor from the clicked menu widget (for Hi-DPI)
        self.scale_factor = menu.get_scale_factor()
        self.set_folder_colors(folders, icon_theme)

    def get_background_items(self, window, current_folder):
        return

    def get_name_and_desc(self):
        return [("folder-color-switcher:::%s" % PLUGIN_DESCRIPTION)]

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

        icon_theme_name = Gtk.Settings.get_default().get_property("gtk-icon-theme-name")
        if icon_theme_name in self.styles:
            icon_themes = self.styles[icon_theme_name]["icon-themes"]
            locale.setlocale(locale.LC_ALL, '')
            gettext.bindtextdomain('folder-color-switcher')
            gettext.textdomain('folder-color-switcher')
            logger.debug("At least one color supported: creating menu entry")
            item = Nemo.MenuItem(name='ChangeFolderColorMenu::Top')
            item.set_widget_a(self.generate_widget(icon_themes, directories_selected))
            item.set_widget_b(self.generate_widget(icon_themes, directories_selected))
            return Nemo.MenuItem.new_separator('ChangeFolderColorMenu::TopSep'),   \
                   item,                                                           \
                   Nemo.MenuItem.new_separator('ChangeFolderColorMenu::BotSep')
        else:
            logger.debug("Could not find any supported colors")
            return

    def generate_widget(self, icon_themes, items):

        widget = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 1)
        self.scale_factor = widget.get_scale_factor()

        # Generate restore button
        button = self.make_button(None)
        button.connect('clicked', self.menu_activate_cb, None, items)
        if len(items) > 1:
            button.set_tooltip_text (_("Restores the color of the selected folders"))
        else:
            button.set_tooltip_text (_("Restores the color of the selected folder"))
        widget.pack_start(button, False, False, 1)

        for icon_theme in icon_themes:
            color_name = _(icon_theme["name"])
            button = self.make_button(icon_theme)
            button.connect('clicked', self.menu_activate_cb, icon_theme, items)
            if len(items) > 1:
                button.set_tooltip_markup (_("Changes the color of the selected folders to %s") % color_name)
            else:
                button.set_tooltip_markup (_("Changes the color of the selected folder to %s") % color_name)
            widget.pack_start(button, False, False, 1)

        widget.show_all()

        return widget

    def make_button(self, icon_theme):
        button = Nemo.SimpleButton()
        c = button.get_style_context()
        if icon_theme is None:
            c.add_class("folder-color-switcher-button")
            image = Gtk.Image(icon_name="edit-delete-symbolic")
            button.set_image(image)
        else:
            c.add_class("folder-color-switcher-button")
            self.color_svg = ""
            with open("/usr/share/folder-color-switcher/color.svg") as f:
                self.color_svg = f.read()
            svg = self.color_svg.replace("#71718e", icon_theme["color"])
            if "color2" in icon_theme:
                svg = svg.replace("#4bb4aa", icon_theme["color2"])
            else:
                svg = svg.replace("#4bb4aa", icon_theme["color"])
            svg = str.encode(svg)
            stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(svg))
            pixbuf = GdkPixbuf.Pixbuf.new_from_stream_at_scale(stream, 12 * self.scale_factor, 12 * self.scale_factor, True, None)
            surface = Gdk.cairo_surface_create_from_pixbuf(pixbuf, self.scale_factor)
            image = Gtk.Image.new_from_surface(surface)
            button.set_image(image)
        return button