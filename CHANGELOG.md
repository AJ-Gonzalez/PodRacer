# Changelog

Newest first. The release script moves the version heading out of
[Unreleased] and tags it; the GitHub Release title is built from the
heading, so an optional nickname in quotes lands in the title.

## [Unreleased]

- Bulk metadata: "Protect track titles" checkbox (checked by default) guards against accidentally overwriting every selected track's title; uncheck to set all titles to one value.
- File browser: "Set as top-level folder" on the folder right-click menu roots the pane there for the session only — the saved default music folder is untouched.
- Demo mode: the sample music tree now contains real (silent, tagged) audio instead of empty placeholders, so drag-and-drop, add, and sync are demonstrable end-to-end (including duplicate detection on re-drop).
- Library: all four columns (Title/Artist/Album/Time) are now user-resizable like the left pane. Defaults are proportional — Title/Artist/Album 30% each, Time 10% of the pane width, tracked across window resizes until you drag a column — and both panes' column widths persist across launches. Appearance menu gains "Reset column widths" to restore the defaults and clear the saved layout.
- Two new themes: Human (Ubuntu 8.04 Hardy Heron's default — warm beige/brown, palette taken from the shipped human-theme gtkrc) and Aero at Night (Frutiger Aero's aqua on a deep-teal night). Both WCAG AA verified.
- New theme: Mint at Night — flat deep-green night with mint accents (palette #091413 #285a48 #408a71 #b0e4cc, colorhunt.co). WCAG AA verified.
- Themes are now categorized in the Theme menu: category headers group the flat themes (Flat Sunrise, Dusk Flat, Flat Earth, Mint at Night) under "Flat"; the rest stay under "Classic".
- Theme menu categories: ATLA (Water Tribe, Last Agni Kai, Fire Nation, Earth Kingdom, Air Nomad, Si Wong Desert) and Computery Stuff (I know Kung Fu, My name is Neo).
- New theme: Si Wong Desert — sandbender dunes at dusk (umber/ochre/amber, palette #7b542f #b6771d #ff9d00 #ffcf71, colorhunt.co). WCAG AA verified.
- New theme: Human Dark — Hardy Heron's Human on dark-brown panels with the classic Ubuntu orange titlebar (#dd4814, darkened for AA). WCAG AA verified.
- New theme menu category: Retro Aesthetics (Frutiger Aero, Aero at Night, Aqua, Dark Aqua, Human, Human Dark).
- New flat themes: Lilac Love 2D (the Lilac Love palette, flattened) and Squished Forest (the Minty Forest palette, flattened — flat mint backdrop, flat deep-teal header). Both WCAG AA verified.
- Flat themes now get square buttons (border-radius 0); every other theme keeps the rounded glossy buttons.
- New theme: Solarized Dark — Ethan Schoonover's Solarized dark terminal palette (base03/base0/base02, cyan accent). Computery Stuff category. WCAG AA verified.
- New theme: Machine in Motion — near-black steel with a red warning accent (palette #171717 #444444 #da0037 #ededed, colorhunt.co), flat with square buttons. WCAG AA verified.
- New flat themes: Bought a Binder (Butch Cassidy flattened), Square Rooms (Human Dark flattened — solid brown + solid orange titlebar), and Hip to be Square (muted American Beauty/Psycho palette #d7cba2 #d4cfc1 #6d6e8e #343030 #577655, color-hex). All with square buttons, WCAG AA verified.
- New theme menu category: Psychonaut (Magenta Daydream, Bubblegum Haze, Analog Sunrise, Stoner Shore).
- New Computery Stuff themes: Kanagawa Terminal, Miasma Terminal, and Tokyo Night Terminal (palettes from terminalcolors.com), plus the flat Tokyo Night 2D. All WCAG AA verified.
- New theme: XP Memories — Windows XP Luna (XP blue titlebar/buttons, beige window face, XP navy text, Bliss-sky backdrop). Retro Aesthetics category. WCAG AA verified.
- Theme menu: each category (Classic, Psychonaut, Retro Aesthetics, ATLA, Computery Stuff, Flat) is now its own submenu instead of inline headers.
- New theme: Windows 95 — the classic face, flat (gray #c0c0c0 panels, navy #000080 titlebar/buttons, teal #008080 desktop backdrop, square buttons). WCAG AA verified.
- New themes: Aqua-pilled and Aqua-Pilled Dark — the Aqua/Dark Aqua palettes with pill-shaped (capsule) buttons. Retro Aesthetics category.
- Library: every song row now shows a small theme-tinted music note beside its title.

## [1.2.1] - 2026-08-19 "Headlong"

- Packaging: the .deb now installs the desktop entry, app icon, and AppStream metadata (previously binary-only, so the app never appeared in the DE menu).

## [1.2.0] - 2026-08-19 "Headlong"

- Accessibility: Line spacing setting (Appearance → Line spacing — Normal/Relaxed/Roomy/Spacious) scales list rows and wrapped dialog text.
- Accessibility: Follow system theme (Appearance → Theme) — resolves to flat System Dark/System Light and tracks live light/dark flips.
- Accessibility: full contrast audit — invisible text on menu selection/pressed states fixed in 11 light-accent themes, low-contrast placeholders fixed in 21; every text pair across all 38 themes is now WCAG-AA enforced by tests and `scripts/check_contrast.py`.
- Icons: 14 theme-tinted Lucide icons on buttons and menus; the Theme menu shows a moon/sun with (Dark)/(Light) labels per theme.
- Nine new themes: I know Kung Fu, My name is Neo, Give me the night, Blue Office, Beige Flag, Flat Sunrise, Dusk Flat, Flat Earth, Naan Binary — all WCAG AA verified.
- Six new themes: Coffee Shop, Water Tribe (light), Last Agni Kai, Fire Nation, Earth Kingdom, Air Nomad (light) — all WCAG AA verified.
- Four new bundled fonts (SIL OFL) in Appearance → Font: Atkinson Hyperlegible (low vision), Lexend (reading proficiency), Macondo and Amarante.

## [1.1.1] - 2026-08-13 "Headlong"

## [1.1.0] - 2026-08-13 "Headlong"
