# Changelog

Newest first. The release script moves the version heading out of
[Unreleased] and tags it; the GitHub Release title is built from the
heading, so an optional nickname in quotes lands in the title.

## [Unreleased]

- Bulk metadata: "Protect track titles" checkbox (checked by default) guards against accidentally overwriting every selected track's title; uncheck to set all titles to one value.
- File browser: "Set as top-level folder" on the folder right-click menu roots the pane there for the session only — the saved default music folder is untouched.
- Demo mode: the sample music tree now contains real (silent, tagged) audio instead of empty placeholders, so drag-and-drop, add, and sync are demonstrable end-to-end (including duplicate detection on re-drop).

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
