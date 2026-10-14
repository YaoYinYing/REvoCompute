# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the Account Quota page.

The Quota page is the reader's own resource position. It is now wired into the
application: a destination of the Account region in the shell's left navigation,
its own protected route and address (``/compute/quota``), and its own place in
the router's route switch.

These cases drive the production bundle through the deterministic fixture
harness and state the integration's own contracts, from the reader's point of
view: the Account sidebar link reaches the page by an in-document navigation, the
page renders the account's own position from the endpoints scoped to it, a hard
refresh of the page's own address serves the same page rather than a 404, the
history stack returns to it, and a signed-in non-administrator reaches their own
quota. Every assertion is made on observable browser state - the URL, the
requests the browser actually issued, the live DOM, focus, and the geometry the
browser actually laid out - never on a source file.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import ADMIN_AUTH, USER_AUTH, controlled_scenario, mount_scenario

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"


def _install_quota_reads(page: Page, subject_id: int, *, compute: list[dict] | None = None) -> None:
    """Serve the account's own canonical position from its own endpoints.

    ``compute`` overrides the entitlement's units so a case can state a position
    the default does not carry (an account over its allowance, a granted zero, a
    unit with no ceiling), while the ledger and every other fact stay canonical.
    """
    from frontend_fixtures import builders

    page.route(
        f"{ORIGIN}/compute/api/resource-entitlement",
        lambda route: route.fulfill(json=builders.build_resource_entitlement(subject_id, compute=compute)),
    )
    page.route(
        f"{ORIGIN}/compute/api/resource-ledger**",
        lambda route: route.fulfill(json=builders.build_resource_ledger(subject_id)),
    )


def test_the_quota_page_is_a_sidebar_destination_with_a_real_address(page: Page) -> None:
    """Account -> Quota in the sidebar, in-document, and the page's own address."""
    from frontend_fixtures import builders

    router = mount_scenario(page, controlled_scenario())
    subject = builders.subject_id_for(controlled_scenario().session)
    _install_quota_reads(page, subject)
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()

    # The Account region's Quota link reaches the page without loading a document.
    page.locator("[data-nav-group='account']").get_by_role("link", name="Quota", exact=True).click()
    expect(page.get_by_role("heading", name="Quota", exact=True)).to_be_visible()
    expect(page).to_have_title("Quota | REvoCompute")
    assert page.url == f"{ORIGIN}/compute/quota"
    # The page renders the account's own position, not a placeholder.
    expect(page.locator(".quota-position")).to_be_visible()
    expect(page.get_by_text("Usage against allowance")).to_be_visible()
    expect(page.locator(".quota-bar")).to_have_count(1)
    expect(page.locator(".quota-unattributed")).to_have_count(1)
    # The shell marks exactly this destination current, and only the first
    # document was ever requested: the link was an in-document navigation.
    expect(
        page.locator("[data-nav-group='account'] a[aria-current='page']")
    ).to_have_attribute("href", "/compute/quota")
    assert [record.path for record in router.requests.navigation()] == ["/compute/dashboard"]
    assert router.requests.matching("/compute/api/resource-entitlement")
    assert router.requests.matching("/compute/api/resource-ledger")


def test_a_hard_refresh_of_the_quota_page_serves_the_same_page(page: Page) -> None:
    """A direct load / refresh of /compute/quota resolves to the real page."""
    from frontend_fixtures import builders

    mount_scenario(page, controlled_scenario())
    subject = builders.subject_id_for(controlled_scenario().session)
    _install_quota_reads(page, subject)

    # A hard load of the address (as a refresh or a shared link does): the server
    # serves the entry document and the router resolves the page's own route.
    page.goto(f"{ORIGIN}/compute/quota")
    expect(page.get_by_role("heading", name="Quota", exact=True)).to_be_visible()
    expect(page.locator(".quota-position")).to_be_visible()

    # A real refresh rebuilds the page from the same address.
    page.reload()
    expect(page.get_by_role("heading", name="Quota", exact=True)).to_be_visible()
    expect(page.locator(".quota-position")).to_be_visible()
    assert page.url == f"{ORIGIN}/compute/quota"


def test_history_back_and_forward_return_to_the_quota_page(page: Page) -> None:
    """The page's address is a real history entry, not a transient render."""
    from frontend_fixtures import builders

    mount_scenario(page, controlled_scenario())
    subject = builders.subject_id_for(controlled_scenario().session)
    _install_quota_reads(page, subject)

    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    page.locator("[data-nav-group='account']").get_by_role("link", name="Quota", exact=True).click()
    expect(page.get_by_role("heading", name="Quota", exact=True)).to_be_visible()

    page.go_back()
    expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible()
    assert page.url == f"{ORIGIN}/compute/dashboard"
    page.go_forward()
    expect(page.get_by_role("heading", name="Quota", exact=True)).to_be_visible()
    assert page.url == f"{ORIGIN}/compute/quota"


def test_the_chinese_catalog_renders_the_quota_page(page: Page) -> None:
    """The nav label and the page are authored copy in both catalogs."""
    from frontend_fixtures import builders

    mount_scenario(page, controlled_scenario())
    subject = builders.subject_id_for(controlled_scenario().session)
    _install_quota_reads(page, subject)
    page.add_init_script("localStorage.setItem('revocompute-locale', 'zh-CN')")

    page.goto(f"{ORIGIN}/compute/quota")
    expect(page.get_by_role("heading", name="资源配额", exact=True)).to_be_visible()
    expect(page.get_by_text("已用额度与总量")).to_be_visible()
    # The Account region's own destination is localized, not left English.
    expect(
        page.locator("[data-nav-group='account']").get_by_role("link", name="资源配额", exact=True)
    ).to_be_visible()

    # The whole read-only resource envelope is localized, not only the page
    # heading: the section heading, its table's column headings and cells, and the
    # storage facts all render the Chinese catalog.
    envelope = page.locator(".resource-envelope")
    expect(envelope.get_by_role("heading", name="资源清单", level=3)).to_be_visible()
    expect(envelope.get_by_role("heading", name="持久存储", level=4)).to_be_visible()
    for heading in ["单位", "类别", "是否设限", "额度", "已用", "预留", "剩余", "用量"]:
        expect(envelope.get_by_role("columnheader", name=heading, exact=True)).to_be_visible()
    for fact in ["已占用字节", "上限", "剩余", "状态"]:
        expect(envelope.get_by_text(fact, exact=True).first).to_be_visible()
    # Unit labels and the cell words come from the catalog too.
    table = envelope.locator(".resource-envelope-table")
    expect(table.get_by_text("GPU 秒", exact=True)).to_be_visible()
    expect(table.get_by_text("CPU 核秒", exact=True)).to_be_visible()
    # The ungated CPU unit's allowance and remaining cells both read "未设限".
    expect(table.get_by_text("未设限", exact=True).first).to_be_visible()
    # The storage facts' own state value is localized; here the account is within
    # its ceiling. The fact labels are catalog copy too.
    facts = envelope.locator(".resource-storage-facts")
    expect(facts.get_by_text("在上限之内", exact=True)).to_be_visible()
    expect(facts.get_by_text("Owned bytes", exact=True)).to_have_count(0)
    # English vocabulary the localization covers must not leak through untranslated.
    expect(envelope.get_by_text("Resource envelope", exact=True)).to_have_count(0)
    expect(envelope.get_by_text("Durable storage", exact=True)).to_have_count(0)
    expect(table.get_by_text("GPU seconds", exact=True)).to_have_count(0)


@pytest.mark.parametrize("session", [USER_AUTH, ADMIN_AUTH], ids=["user", "admin"])
def test_a_signed_in_reader_reaches_their_own_quota(page: Page, session) -> None:
    """A non-administrator reaches their own quota; an administrator's does too."""
    from frontend_fixtures import builders

    mount_scenario(page, controlled_scenario(session=session))
    subject = builders.subject_id_for(session)
    _install_quota_reads(page, subject)

    page.goto(f"{ORIGIN}/compute/dashboard")
    page.locator("[data-nav-group='account']").get_by_role("link", name="Quota", exact=True).click()
    expect(page.get_by_role("heading", name="Quota", exact=True)).to_be_visible()
    expect(page.locator(".quota-position")).to_be_visible()
    assert page.url == f"{ORIGIN}/compute/quota"


# ---------------------------------------------------------------------------
# The usage bar's geometry: what the browser actually lays out.
# ---------------------------------------------------------------------------

# The first compute unit's own bar (the gated GPU unit the fixture supplies). Each
# reading is real layout: the track is exactly the allowance, so its box is the
# allowance's own width and the fill is clipped to it; the overage band past the
# track carries the fraction over 100% and must not be folded back in.
GEOMETRY = """
() => {
  const track = document.querySelector('.quota-bar');
  const takenBeforeRow = document.querySelector('.quota-bar-item').getBoundingClientRect().width;
  const used = track.querySelector('.quota-bar-used');
  const reserved = track.querySelector('.quota-bar-reserved');
  const overage = track.parentElement.querySelector('.quota-bar-overage');
  const box = el => { const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height }; };
  return {
    rowWidth: takenBeforeRow,
    track: box(track),
    used: box(used),
    reserved: box(reserved),
    overage: overage ? box(overage) : null,
    aria: track.getAttribute('aria-label'),
    isOver: track.classList.contains('is-over'),
  };
}"""


def _bar_geometry(page: Page) -> dict:
    page.goto(f"{ORIGIN}/compute/quota")
    expect(page.locator(".quota-bar").first).to_be_visible()
    return page.evaluate(GEOMETRY)


def _gpu_unit(
    *, allowance: int | None, used: int, reserved: int, enforced: bool = True, usage_complete: bool = True,
) -> list[dict]:
    """One GPU unit stated for a geometry case, plus the ungated CPU unit beside it."""
    return [
        {
            "unit": "gpu_second", "resource_class": "a100", "enforced": enforced, "allowance": allowance,
            "used": used, "reserved": reserved, "unsettled_allocations": 0, "unsettled_quantity": 0,
            "remaining": None if allowance is None else allowance - used - reserved,
            "usage_complete": usage_complete, "evidence_sources": ["slurm_accounting"],
        },
        {
            "unit": "cpu_core_second", "resource_class": "", "enforced": False, "allowance": None,
            "used": 12_000, "reserved": 0, "unsettled_allocations": 0, "unsettled_quantity": 0,
            "remaining": None, "usage_complete": True, "evidence_sources": [],
        },
    ]


def test_a_normal_bar_fills_its_track_from_real_geometry(page: Page) -> None:
    """used+reserved < 100%: the bands are real fractions of the track's own width."""
    from frontend_fixtures import builders

    mount_scenario(page, controlled_scenario())
    _install_quota_reads(page, builders.subject_id_for(controlled_scenario().session),
                         compute=_gpu_unit(allowance=100_000, used=40_000, reserved=20_000))
    geometry = _bar_geometry(page)

    assert geometry["isOver"] is False
    assert geometry["overage"] is None
    # 40% settled and 20% reserved of the track's real width, read from the DOM.
    assert geometry["used"]["width"] == pytest.approx(geometry["track"]["width"] * 0.4, rel=0.05)
    assert geometry["reserved"]["width"] == pytest.approx(geometry["track"]["width"] * 0.2, rel=0.05)
    # The fill stays inside the track; nothing overflows it. At or under the
    # allowance the track is the whole row, so no space is reserved for an overage.
    assert geometry["used"]["x"] >= geometry["track"]["x"] - 1
    assert geometry["used"]["x"] + geometry["used"]["width"] <= geometry["track"]["x"] + geometry["track"]["width"] + 1
    assert geometry["track"]["width"] == pytest.approx(geometry["rowWidth"], abs=2), geometry
    assert "40.0%" in geometry["aria"] and "20.0%" in geometry["aria"]
    assert "over allowance" not in geometry["aria"]


def test_an_over_limit_bar_is_not_clipped_to_the_track(page: Page) -> None:
    """used+reserved > 100%: the overage is drawn past the track, not folded back."""
    from frontend_fixtures import builders

    mount_scenario(page, controlled_scenario())
    # 80% settled + 40% reserved = 120% of the allowance: 20% over.
    _install_quota_reads(page, builders.subject_id_for(controlled_scenario().session),
                         compute=_gpu_unit(allowance=100_000, used=80_000, reserved=40_000, usage_complete=False))
    geometry = _bar_geometry(page)

    assert geometry["isOver"] is True
    # The over-allowance band exists and is drawn past the track's right edge, so
    # the overdraw is visible rather than clamped into the last 20% of the track.
    assert geometry["overage"] is not None, geometry
    track_right = geometry["track"]["x"] + geometry["track"]["width"]
    assert geometry["overage"]["x"] >= track_right - 2, geometry
    assert geometry["overage"]["width"] > 1, geometry
    # Over the allowance the track keeps the allowance's own width and the overage
    # band takes the rest of the row, so its width states the over-100 fraction as
    # a share of the whole row (100/120 = 83.3% track, 16.7% overage).
    assert geometry["track"]["width"] == pytest.approx(geometry["rowWidth"] * (100 / 120), rel=0.06), geometry
    assert geometry["overage"]["width"] == pytest.approx(geometry["rowWidth"] * (20 / 120), rel=0.12), geometry
    # The overage is genuinely additional: it extends past the track's right edge.
    assert geometry["overage"]["x"] + geometry["overage"]["width"] > track_right + 1, geometry
    # The accessibility label states the true over-100 total, not a clamped 100%.
    assert "120.0%" in geometry["aria"], geometry["aria"]
    assert "over allowance" in geometry["aria"]


def test_a_zero_allowance_bar_is_the_enforced_zero_text_state(page: Page) -> None:
    """A granted zero is text, never a fabricated 0%-of-nothing bar."""
    from frontend_fixtures import builders

    mount_scenario(page, controlled_scenario())
    _install_quota_reads(page, builders.subject_id_for(controlled_scenario().session),
                         compute=_gpu_unit(allowance=0, used=0, reserved=0))
    page.goto(f"{ORIGIN}/compute/quota")
    expect(page.locator(".quota-position")).to_be_visible()

    # No bar is drawn for the zero-allowance unit, and the page says why.
    gpu_item = page.locator(".quota-bar-item").first
    expect(gpu_item.locator(".quota-bar")).to_have_count(0)
    expect(gpu_item.locator(".quota-bar-note")).to_contain_text("enforced zero")
    # The ungated CPU unit is distinct: it has no denominator either, but its own
    # wording (not the zero-ceiling wording).
    ungated_item = page.locator(".quota-bar-item").nth(1)
    expect(ungated_item.locator(".quota-bar")).to_have_count(0)
    expect(ungated_item.locator(".quota-bar-note")).to_contain_text("Not gated")


def test_a_unit_with_no_ceiling_draws_no_bar(page: Page) -> None:
    """allowance === null: an ungated unit has no denominator to draw against."""
    from frontend_fixtures import builders

    mount_scenario(page, controlled_scenario())
    _install_quota_reads(page, builders.subject_id_for(controlled_scenario().session),
                         compute=_gpu_unit(allowance=None, used=12_000, reserved=0, enforced=False))
    page.goto(f"{ORIGIN}/compute/quota")
    expect(page.locator(".quota-position")).to_be_visible()

    assert page.locator(".quota-bar").count() == 0
    expect(page.locator(".quota-bar-note").first).to_contain_text("Not gated")
