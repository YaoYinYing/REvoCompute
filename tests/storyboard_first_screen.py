# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Shared browser assertion: a storyboard's evidence figure on the first screen.

Every structure-prediction storyboard now mounts one persistent structure stage
inside a hero grid with its confidence evidence beside it. This reads the laid
out boxes from the browser and states the requirement: the evidence figure is
inside the hero region, the stage occupies the hero's other column, and the
figure is fully visible at the requested viewport without scrolling.
"""

from __future__ import annotations

_LAYOUT_JS = """({hero, slot, figure}) => {
  const box = (selector) => {
    // The first laid-out match: a hidden node (an unavailable matrix) is not the
    // evidence figure the requirement is about.
    for (const node of document.querySelectorAll(selector)) {
      const rect = node.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        return {top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right,
                width: rect.width, height: rect.height};
      }
    }
    return null;
  };
  return {hero: box(hero), slot: box(slot), figure: box(figure),
          width: innerWidth, height: innerHeight};
}"""


def assert_first_screen(page, *, hero: str, slot: str, figure: str, stage_height: int = 590,
                        within_viewport: bool = True) -> dict:
    reading = page.evaluate(_LAYOUT_JS, {"hero": hero, "slot": slot, "figure": figure})
    hero_box, slot_box, figure_box = reading["hero"], reading["slot"], reading["figure"]
    assert hero_box and slot_box and figure_box, reading
    # The evidence figure belongs to the hero, not to a paragraph after it.
    assert figure_box["top"] >= hero_box["top"] - 1, reading
    assert figure_box["bottom"] <= hero_box["bottom"] + 1, reading
    assert figure_box["left"] >= hero_box["left"] - 1, reading
    assert figure_box["right"] <= hero_box["right"] + 1, reading
    assert figure_box["width"] > 100 and figure_box["height"] > 100, reading
    # The structure stage is the hero's persistent left column.
    assert slot_box["height"] >= stage_height, reading
    assert slot_box["top"] >= hero_box["top"] - 1 and slot_box["bottom"] <= hero_box["bottom"] + 1, reading
    assert slot_box["left"] >= hero_box["left"] - 1, reading
    assert figure_box["left"] >= slot_box["right"], reading
    # And it is all reachable without scrolling at the tested viewport. A page
    # with application chrome above the storyboard passes within_viewport=False
    # and still has to open the hero on the first screen.
    assert slot_box["top"] < reading["height"], reading
    assert figure_box["top"] < reading["height"], reading
    if within_viewport:
        assert figure_box["bottom"] <= reading["height"], reading
        assert slot_box["bottom"] <= reading["height"], reading
    return reading
