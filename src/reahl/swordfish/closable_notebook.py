# AI: Adds an 'x' close affordance to the tabs of a ttk.Notebook. Tk has no
# native close button, so we overlay a custom ttk 'close' element via styling
# and translate a Button-1 press+release that both fall on the close element
# of the same tab into a close-callback invocation. The button keeps the
# whole notebook visually consistent: every tab carries the same affordance.

import tkinter as tk
from tkinter import ttk


# AI: PhotoImages must remain referenced for Tk to keep them alive. Keeping the
# references at module scope avoids garbage collection while staying out of
# the host notebook's own attribute namespace.
CLOSE_BUTTON_IMAGES = []


def build_close_image(master, fill_color):
    """AI: Draw a 12x12 'x' onto a (transparent) PhotoImage and return it."""
    image = tk.PhotoImage(master=master, width=12, height=12)
    for offset in range(2, 10):
        opposite = 11 - offset
        image.put(fill_color, to=(offset, offset))
        image.put(fill_color, to=(offset + 1, offset))
        image.put(fill_color, to=(offset, opposite))
        image.put(fill_color, to=(offset + 1, opposite))
    return image


def close_images_for(master):
    """AI: Build the three state variants (idle, hover, pressed) of the icon."""
    img_normal = build_close_image(master, '#666666')
    img_active = build_close_image(master, '#222222')
    img_pressed = build_close_image(master, '#000000')
    CLOSE_BUTTON_IMAGES.extend([img_normal, img_active, img_pressed])
    return img_normal, img_active, img_pressed


def ensure_closable_style(notebook):
    """AI: Register the Closable.TNotebook ttk style once per Tk interpreter.
    element_create raises TclError if called twice with the same name; the
    layout calls below are idempotent so they do not need a guard."""
    style = ttk.Style(notebook)
    img_normal, img_active, img_pressed = close_images_for(notebook)
    try:
        style.element_create(
            'close', 'image', img_normal,
            ('active', 'pressed', '!disabled', img_pressed),
            ('active', '!disabled', img_active),
            border=4, sticky='',
        )
    except tk.TclError:
        # AI: 'close' already registered in this interpreter — the only case
        # in which element_create complains with this signature.
        pass
    style.layout('Closable.TNotebook', [
        ('Notebook.client', {'sticky': 'nswe'}),
    ])
    style.layout('Closable.TNotebook.Tab', [
        ('Notebook.tab', {'sticky': 'nswe', 'children': [
            ('Notebook.padding', {'side': 'top', 'sticky': 'nswe', 'children': [
                ('Notebook.focus', {'side': 'top', 'sticky': 'nswe', 'children': [
                    ('Notebook.label', {'side': 'left', 'sticky': ''}),
                    ('close', {'side': 'left', 'sticky': ''}),
                ]}),
            ]}),
        ]}),
    ])


def install_close_buttons(notebook, close_callback, is_closable=None):
    """AI: Show an 'x' on each tab of `notebook` and call
    close_callback(notebook, tab_index) when a tab's 'x' is clicked. The
    optional is_closable(notebook, tab_index) gate suppresses the callback
    for tabs that should not be closable (the icon itself is still drawn
    because the ttk style scope is notebook-wide)."""
    ensure_closable_style(notebook)
    notebook.configure(style='Closable.TNotebook')

    pressed_state = {'tab_index': None}

    def tab_index_at(event):
        try:
            return notebook.index(f'@{event.x},{event.y}')
        except tk.TclError:
            return None

    def close_tab_at_index(tab_index):
        """AI: Pure dispatch — invokes the close callback if the gate
        allows. Exposed via notebook.close_tab_at_index so tests can
        exercise the path without simulating mouse coordinates."""
        if is_closable is not None and not is_closable(notebook, tab_index):
            return False
        close_callback(notebook, tab_index)
        return True

    def on_press(event):
        element = notebook.identify(event.x, event.y)
        if 'close' not in element:
            return None
        tab_index = tab_index_at(event)
        if tab_index is None:
            return None
        pressed_state['tab_index'] = tab_index
        notebook.state(['pressed'])
        return 'break'

    def on_release(event):
        starting_index = pressed_state['tab_index']
        if starting_index is None:
            return None
        pressed_state['tab_index'] = None
        notebook.state(['!pressed'])
        if 'close' not in notebook.identify(event.x, event.y):
            return None
        if tab_index_at(event) != starting_index:
            return None
        close_tab_at_index(starting_index)
        return 'break'

    notebook.bind('<ButtonPress-1>', on_press, add=True)
    notebook.bind('<ButtonRelease-1>', on_release, add=True)
    notebook.close_tab_at_index = close_tab_at_index
