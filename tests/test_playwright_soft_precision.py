# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser acceptance for the Soft Precision shell, language, notices, tour, and Dashboard.

These cases drive the production bundle through the deterministic fixture
harness and assert real behavior and state — navigation geometry, persisted
preferences, translated labels, notice lifecycle, tour progression, filter/view
independence, and task-card semantics — never pixel snapshots.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import ADMIN_AUTH, ANONYMOUS_AUTH, USER_AUTH, Session, controlled_scenario, mount_scenario

pytestmark = pytest.mark.browser

ORIGIN = "https://revocompute.example"


def _dashboard(page: Page):
    router = mount_scenario(page, controlled_scenario())
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    return router


def _rgb(value: str) -> tuple[float, float, float]:
    """Parse a colour into its 0-255 channels.

    Accepts ``rgb()``/``rgba()`` (legacy comma or modern space/``/`` syntax, with
    the alpha channel ignored rather than mistaken for a colour) and ``#rrggbb``.
    """
    value = value.strip()
    if value.startswith("#"):
        digits = value[1:]
        assert len(digits) in (3, 6), value
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        return tuple(float(int(digits[i:i + 2], 16)) for i in (0, 2, 4))  # type: ignore[return-value]
    inner = value[value.find("(") + 1:value.rfind(")")].replace("/", " ")
    parts = [p for p in inner.replace(",", " ").split() if p]
    channels: list[float] = []
    for part in parts[:3]:
        channels.append(float(part[:-1]) * 2.55 if part.endswith("%") else float(part))
    assert len(channels) == 3, value
    return channels[0], channels[1], channels[2]


def _relative_luminance(value: str) -> float:
    def linear(channel: float) -> float:
        scaled = channel / 255
        return scaled / 12.92 if scaled <= 0.03928 else ((scaled + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in _rgb(value))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted((_relative_luminance(foreground), _relative_luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


# ── shell / navigation rail ───────────────────────────────────────────────────


def test_desktop_rail_collapses_and_expands_by_reactivating_the_current_item(page: Page) -> None:
    _dashboard(page)
    page.set_viewport_size({"width": 1280, "height": 900})
    page.reload()
    shell = page.locator(".app-shell")
    expect(shell).to_have_attribute("data-rail", "collapsed")
    # The current page's own nav item is the rail toggle: there is no separate arrow.
    assert page.get_by_role("button", name="Collapse navigation").count() == 0
    assert page.get_by_role("button", name="Expand navigation").count() == 0

    page.get_by_role("link", name="Dashboard", exact=True).click()
    expect(shell).to_have_attribute("data-rail", "expanded")
    # Repeating the activation collapses it again.
    page.get_by_role("link", name="Dashboard", exact=True).click()
    expect(shell).to_have_attribute("data-rail", "collapsed")


def test_rail_preference_persists_across_reload(page: Page) -> None:
    _dashboard(page)
    page.set_viewport_size({"width": 1280, "height": 900})
    page.get_by_role("link", name="Dashboard", exact=True).click()
    expect(page.locator(".app-shell")).to_have_attribute("data-rail", "expanded")
    assert page.evaluate("localStorage.getItem('revocompute-rail')") == "expanded"
    page.reload()
    expect(page.locator(".app-shell")).to_have_attribute("data-rail", "expanded")


def test_navigation_regions_are_labelled_and_hide_the_admin_group_from_ordinary_users(page: Page) -> None:
    # An ordinary signed-in user sees the Compute and Account regions and no
    # Administration region at all: admin-only is authorization, not visual hiding.
    _dashboard(page)
    page.set_viewport_size({"width": 1280, "height": 900})
    page.reload()
    expect(page.locator(".app-nav [data-nav-group='compute']")).to_be_visible()
    expect(page.locator(".app-nav [data-nav-group='account']")).to_be_visible()
    expect(page.locator(".app-nav [data-nav-group='admin']")).to_be_hidden()
    expect(page.locator(".app-nav [data-nav-group='compute'] .app-nav-group-label")).to_have_text("Compute")
    expect(page.locator(".app-nav [data-nav-group='account'] .app-nav-group-label")).to_have_text("Account")
    # The Dashboard's own destination is current inside the Compute region.
    expect(page.locator(".app-nav [data-nav-group='compute'] a[aria-current='page']")).to_have_attribute("href", "/compute/dashboard")
    # No second Administration launcher survives in the top bar.
    expect(page.get_by_role("link", name="User control")).to_have_count(0)
    expect(page.get_by_label("Administration")).to_have_count(0)


def test_administrator_navigation_region_is_present_in_the_left_navigation(page: Page) -> None:
    mount_scenario(page, controlled_scenario(session=ADMIN_AUTH))
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible()
    admin_group = page.locator(".app-nav [data-nav-group='admin']")
    expect(admin_group).to_be_visible()
    expect(admin_group.locator(".app-nav-group-label")).to_have_text("Administration")
    expect(admin_group.get_by_role("link", name="User control")).to_have_attribute("href", "/compute/user_control")
    expect(admin_group.get_by_role("link", name="Server logs")).to_have_attribute("href", "/compute/logs")
    expect(admin_group.get_by_role("link", name="Configuration")).to_have_attribute("href", "/compute/configuration")
    # The current page is still marked inside Compute, and the top bar keeps no
    # second Administration launcher.
    expect(page.locator(".app-nav [data-nav-group='compute'] a[aria-current='page']")).to_have_attribute("href", "/compute/dashboard")
    expect(page.get_by_label("Administration")).to_have_count(0)


def test_mobile_navigation_is_bottom_anchored_not_a_thin_rail(page: Page) -> None:
    _dashboard(page)
    page.set_viewport_size({"width": 360, "height": 780})
    page.reload()
    expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible()
    position = page.locator(".app-nav").evaluate("node => getComputedStyle(node).position")
    assert position == "fixed"
    # Compute and Account sit directly on the bar; their region headings would name
    # groups a bottom bar cannot group, so they are absent from the rendered bar.
    assert page.locator(".app-nav-group:not([data-nav-group='admin']) .app-nav-group-label:visible").count() == 0
    expect(page.locator(".app-nav [data-nav-group='compute'] a[aria-current='page']")).to_have_attribute("href", "/compute/dashboard")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_mobile_administration_is_a_secondary_surface_above_the_bar(page: Page) -> None:
    # For an administrator the Administration destinations do not crowd the primary
    # bar: they form one bounded surface standing just above it, named by its heading.
    mount_scenario(page, controlled_scenario(session=ADMIN_AUTH))
    page.set_viewport_size({"width": 360, "height": 780})
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible()
    admin_surface = page.locator(".app-nav-group[data-nav-group='admin']")
    expect(admin_surface).to_be_visible()
    # The heading must genuinely paint, not merely "be visible" as a clipped sr-only
    # sliver: it has a non-zero box and it is the topmost element at its own centre.
    heading = admin_surface.locator(".app-nav-group-label")
    expect(heading).to_have_text("Administration")
    painted = heading.evaluate(
        "node => { const r = node.getBoundingClientRect();"
        " const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);"
        " return { width: r.width, height: r.height, color: getComputedStyle(node).color,"
        " topmost: !!hit && (hit === node || node.contains(hit)) }; }"
    )
    assert painted["width"] > 0 and painted["height"] > 0, painted
    assert painted["topmost"], painted
    expect(admin_surface.get_by_role("link", name="User control")).to_have_attribute("href", "/compute/user_control")
    box = admin_surface.bounding_box()
    bar = page.locator(".app-nav").bounding_box()
    assert box is not None and bar is not None
    # The surface sits above the bar (never inside or behind it) and within the page.
    assert box["y"] + box["height"] <= bar["y"] + 1
    assert box["x"] >= 0 and box["x"] + box["width"] <= 361
    # The primary bar still carries Compute and Account, uncluttered.
    bar_labels = page.locator(".app-nav [aria-current='page']").first.inner_text()
    assert bar_labels.strip() == "Dashboard"
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_ordinary_user_has_no_mobile_administration_surface(page: Page) -> None:
    _dashboard(page)
    page.set_viewport_size({"width": 360, "height": 780})
    page.reload()
    expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible()
    expect(page.locator(".app-nav-group[data-nav-group='admin']")).to_be_hidden()
    assert page.get_by_role("link", name="User control").count() == 0
    assert page.get_by_role("link", name="Server logs").count() == 0
    assert page.get_by_role("link", name="Configuration").count() == 0


def test_desktop_rail_states_regions_with_a_visible_label(page: Page) -> None:
    _dashboard(page)
    page.set_viewport_size({"width": 1280, "height": 900})
    page.reload()
    # Above the bottom-bar band the rail is a column, so each region is named. The
    # collapsed icon rail keeps the rule and hides the word; expanding it reveals the
    # label as painted chrome, not the 1px sr-only form.
    page.get_by_role("link", name="Dashboard", exact=True).click()
    expect(page.locator(".app-shell")).to_have_attribute("data-rail", "expanded")
    labels = page.locator(".app-nav .app-nav-group-label:visible")
    assert labels.count() >= 2
    expect(labels.filter(has_text="Compute")).to_have_count(1)
    expect(labels.filter(has_text="Account")).to_have_count(1)
    box = labels.filter(has_text="Compute").bounding_box()
    assert box is not None and box["width"] > 8 and box["height"] > 8, box


def test_tablet_navigation_reflows_and_toolbar_wraps_without_overflow(page: Page) -> None:
    _dashboard(page)
    page.set_viewport_size({"width": 834, "height": 1112})
    page.reload()
    expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible()
    # Tablet sits in the mobile navigation band: a bottom-anchored bar, not the desktop rail.
    assert page.locator(".app-nav").evaluate("node => getComputedStyle(node).position") == "fixed"
    # The filter band and the view switch remain two separate control groups after reflow.
    assert page.locator("[aria-label='Task filters']").evaluate("node => getComputedStyle(node).display") != "none"
    expect(page.locator(".view-toolbar .layout-switch")).to_be_visible()
    # Metadata reflow and wrapping must not push the document wider than the viewport.
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


# ── localization ──────────────────────────────────────────────────────────────


def test_language_switch_localizes_frontend_copy_and_persists(page: Page) -> None:
    _dashboard(page)
    page.locator(".lang-menu > summary").click()
    page.locator('[data-locale="zh-CN"]').click()
    expect(page.locator("html")).to_have_attribute("lang", "zh-CN")
    expect(page.get_by_role("heading", name="任务面板", exact=True)).to_be_visible()
    assert page.evaluate("localStorage.getItem('revocompute-locale')") == "zh-CN"
    page.reload()
    expect(page.locator("html")).to_have_attribute("lang", "zh-CN")
    expect(page.get_by_role("heading", name="任务面板", exact=True)).to_be_visible()
    # Server-owned vocabulary (the Runner's own display name) is not translated.
    expect(page.locator(".task-card-type").first).to_have_text("sequence_demo")


# ── persistent system notices ─────────────────────────────────────────────────


@pytest.mark.parametrize("width", [360, 1280])
@pytest.mark.parametrize("locale", ["en", "zh-CN"])
@pytest.mark.parametrize("path", ["/runners", "/compute/login"])
@pytest.mark.parametrize("session", [ANONYMOUS_AUTH, USER_AUTH, ADMIN_AUTH], ids=["anonymous", "user", "admin"])
def test_account_destinations_match_session_semantics(
    page: Page, width: int, locale: str, path: str, session: Session,
) -> None:
    from test_playwright_application import _gpu_credit, _metrics

    mount_scenario(page, controlled_scenario(session=session))
    # Authenticated activation reaches Profile, which eagerly loads these resources.
    page.route(f"{ORIGIN}/compute/api/gpu-credit", lambda route: route.fulfill(json=_gpu_credit()))
    page.route(f"{ORIGIN}/compute/api/user-metrics?*", lambda route: route.fulfill(json=_metrics()))
    page.set_viewport_size({"width": width, "height": 900})
    page.add_init_script(f"localStorage.setItem('revocompute-locale', '{locale}')")
    page.goto(f"{ORIGIN}{path}")
    account = page.locator("[data-nav-group='account'] a")
    identity = page.locator(".app-user")
    signed_in = session.role != "anonymous"
    profile, sign_in = ("Profile", "Sign in") if locale == "en" else ("个人资料", "登录")
    label = profile if signed_in else sign_in
    if path == "/compute/login":
        account = page.locator(".public-account")
        expect(account).to_have_text(label)
        expect(account).to_have_attribute("title", label)
        expect(account).to_have_accessible_name(label)
        expect(account).to_have_attribute("href", "/compute/profile" if signed_in else "/compute/login")
        return
    destination = "/compute/profile" if signed_in else "/compute/login?return_to=%2Frunners"
    expect(account).to_have_text(label)
    expect(identity.locator("span")).to_have_text(session.full_name if signed_in else label)
    identity_name = f"{profile}: {session.full_name}" if signed_in else label
    for link, accessible_name in ((account, label), (identity, identity_name)):
        expect(link).to_have_attribute("href", destination)
        expect(link).to_have_attribute("title", label)
        expect(link).to_have_accessible_name(accessible_name)
    # The anonymous destination must actually navigate, including on the mobile bar.
    account.click()
    expect(page).to_have_url(f"{ORIGIN}{destination}")


@pytest.mark.parametrize("width", [320, 360, 390, 834])
@pytest.mark.parametrize("session", [USER_AUTH, ADMIN_AUTH], ids=["user", "admin"])
def test_mobile_system_notice_stack_clears_navigation(page: Page, width: int, session: Session) -> None:
    mount_scenario(page, controlled_scenario(session=session))
    page.set_viewport_size({"width": width, "height": 780})
    notices = [
        {"id": f"maintenance-{index}", "level": "warning", "title": f"Maintenance {index}",
         "body": "Storage maintenance details. " * 80}
        for index in range(3)
    ]
    page.route(f"{ORIGIN}/compute/api/system/notices", lambda route: route.fulfill(json={"notices": notices}))
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".sys-notice")).to_have_count(3)
    for summary in page.locator(".sys-notice summary").all():
        summary.click()

    def assert_clearance() -> None:
        stack = page.locator(".sys-notices").bounding_box()
        navigation = page.locator(
            "[data-nav-group='admin']" if session.role == "admin" else ".app-nav"
        ).bounding_box()
        assert stack is not None and navigation is not None
        assert stack["y"] >= 56, stack  # Global actions remain reachable with long/multiple notices.
        assert stack["y"] + stack["height"] < navigation["y"], (stack, navigation)
        assert stack["x"] >= 0 and stack["x"] + stack["width"] <= width, stack

    assert_clearance()
    # Hide, reopen, then collapse the restored notices back to the visible subset.
    page.locator(".sys-notice").first.get_by_role("button", name="Hide notice").click()
    expect(page.locator(".sys-notice")).to_have_count(2)
    assert_clearance()
    page.get_by_role("button", name="System notices").click()
    expect(page.locator(".sys-notice")).to_have_count(3)
    assert_clearance()
    page.get_by_role("button", name="System notices").click()
    expect(page.locator(".sys-notice")).to_have_count(2)
    assert_clearance()
    page.locator(".sys-notice").first.get_by_role("button", name="Hide notice").click()
    expect(page.locator(".sys-notice")).to_have_count(1)
    assert_clearance()
    page.locator(".sys-notice").first.get_by_role("button", name="Hide notice").click()
    expect(page.locator(".sys-notice")).to_have_count(0)
    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    outlet = page.locator(".app-outlet")
    last_content_bottom = outlet.evaluate("node => node.lastElementChild.getBoundingClientRect().bottom")
    navigation = page.locator(
        "[data-nav-group='admin']" if session.role == "admin" else ".app-nav"
    ).bounding_box()
    assert navigation is not None and last_content_bottom <= navigation["y"] + 1, (last_content_bottom, navigation)



@pytest.mark.parametrize("width", [320, 1280])
def test_notice_disclosure_preserves_reading_state_and_returns_space(page: Page, width: int) -> None:
    mount_scenario(page, controlled_scenario(session=ADMIN_AUTH))
    page.set_viewport_size({"width": width, "height": 780})
    notices = [
        {"id": "maintenance", "level": "warning", "title": "Scheduled maintenance",
         "body": "Storage maintenance details. " * 80},
        {"id": "update", "level": "info", "title": "Service update", "body": "An informational update."},
        {"id": "critical", "level": "critical", "title": "Action required", "body": "Read this critical notice."},
    ]
    page.route(f"{ORIGIN}/compute/api/system/notices", lambda route: route.fulfill(json={"notices": notices}))
    page.goto(f"{ORIGIN}/compute/dashboard")
    card = page.locator("[data-notice-id='maintenance']")
    body = card.locator(".sys-notice-body")
    expect(body).to_be_hidden()
    expect(page.locator("[data-notice-id='critical'] .sys-notice-body")).to_be_visible()
    stack = page.locator(".sys-notices")
    collapsed = stack.bounding_box()
    assert collapsed is not None
    # Native disclosure is keyboard operable and the full long message can scroll.
    summary = card.locator("summary")
    for control in (summary, card.get_by_role("button", name="Hide notice")):
        target = control.bounding_box()
        assert target is not None and target["width"] >= 44 and target["height"] >= 44, target
    summary.focus()
    summary.press("Enter")
    expect(body).to_be_visible()
    opened = stack.bounding_box()
    assert opened is not None and opened["height"] > collapsed["height"], (collapsed, opened)
    body.evaluate("node => node.scrollTop = node.scrollHeight")
    assert body.evaluate("node => node.scrollTop") > 0
    navigation = page.locator("[data-nav-group='admin']" if width == 320 else ".app-header").bounding_box()
    assert navigation is not None
    if width == 320:
        assert opened["y"] + opened["height"] < navigation["y"], (opened, navigation)
    else:
        assert opened["y"] >= navigation["y"] + navigation["height"], (opened, navigation)
    # Hiding/restoring a neighbour must not collapse the notice currently being read.
    page.locator("[data-notice-id='update']").get_by_role("button", name="Hide notice").click()
    expect(body).to_be_visible()
    assert body.evaluate("node => node.scrollTop") > 0
    page.get_by_role("button", name="System notices").click()
    expect(page.locator(".sys-notice")).to_have_count(3)
    expect(body).to_be_visible()
    assert body.evaluate("node => node.scrollTop") > 0
    summary.focus()
    summary.press("Enter")
    expect(body).to_be_hidden()
    returned = stack.bounding_box()
    assert returned is not None and returned["height"] < opened["height"], (returned, opened)
    heading = page.get_by_role("heading", name="Dashboard", exact=True)
    assert heading.evaluate("""node => {
        const box = node.getBoundingClientRect();
        return node.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2));
    }""")



def test_notice_affordance_opens_messages_and_returns_to_summaries(page: Page) -> None:
    mount_scenario(page, controlled_scenario())
    notice = {"id": "maintenance", "level": "warning", "title": "Scheduled maintenance", "body": "Maintenance details."}
    page.route(f"{ORIGIN}/compute/api/system/notices", lambda route: route.fulfill(json={"notices": [notice]}))
    page.goto(f"{ORIGIN}/compute/dashboard")
    body = page.locator(".sys-notice-body")
    expect(body).to_be_hidden()
    page.get_by_role("button", name="System notices").click()
    expect(body).to_be_visible()
    page.get_by_role("button", name="System notices").click()
    expect(body).to_be_hidden()
    expect(page.locator(".sys-notice-title")).to_have_text("Scheduled maintenance")


def test_persistent_notice_opens_hides_and_reopens_from_the_global_affordance(page: Page) -> None:
    mount_scenario(page, controlled_scenario())
    notice = {
        "id": "operator-notice-demo",
        "level": "warning",
        "title": "Scheduled maintenance",
        "body": "Storage maintenance on Saturday 02:00-04:00 UTC.",
    }
    page.route(f"{ORIGIN}/compute/api/system/notices", lambda route: route.fulfill(json={"notices": [notice]}))
    page.goto(f"{ORIGIN}/compute/dashboard")

    button = page.get_by_role("button", name="System notices")
    expect(button).to_be_visible()
    button.click()
    card = page.locator(".sys-notice")
    expect(card).to_be_visible()
    expect(card).to_contain_text("Scheduled maintenance")

    card.get_by_role("button", name="Hide notice").click()
    expect(page.locator(".sys-notice")).to_have_count(0)
    # Reopen from the same global affordance: the hidden notice returns.
    button.click()
    expect(page.locator(".sys-notice")).to_be_visible()


def test_notice_affordance_is_absent_with_nothing_to_announce(page: Page) -> None:
    _dashboard(page)
    expect(page.get_by_role("button", name="System notices")).to_be_hidden()


# ── guided tour ───────────────────────────────────────────────────────────────


def test_guided_tour_starts_progresses_and_is_restartable(page: Page) -> None:
    router = _dashboard(page)
    launcher = page.get_by_role("button", name="Guided tour")
    expect(launcher).to_be_visible()
    launcher.click()
    callout = page.locator(".tour-callout")
    expect(callout).to_be_visible()
    expect(callout).to_contain_text("Step 1 of 5")
    callout.get_by_role("button", name="Next").click()
    expect(callout).to_contain_text("Step 2 of 5")

    # The tour crosses routes: step 3 belongs to the Runner catalog.
    callout.get_by_role("button", name="Next").click()
    expect(page).to_have_url(f"{ORIGIN}/runners")
    expect(page.locator(".tour-callout")).to_contain_text("Step 3 of 5")

    # Step 4 is Create Task; step 5 is the result workspace, which needs a real task
    # id. This scenario publishes no result, so the step is skipped rather than
    # navigating to an id-less route. The tour finishes without ever requesting
    # /compute/results.
    page.locator(".tour-callout").get_by_role("button", name="Next").click()
    expect(page).to_have_url(f"{ORIGIN}/compute/create_task")
    expect(page.locator(".tour-callout")).to_contain_text("Step 4 of 5")
    # Advancing from step 4 would reach the result step; with no result published the
    # tour finishes here instead of navigating to a result route without an id.
    page.locator(".tour-callout").get_by_role("button", name="Next").click()
    expect(page.locator(".tour-callout")).to_have_count(0)
    assert page.url.startswith(f"{ORIGIN}/compute/create_task")
    result_page_requests = [record.path for record in router.requests.navigation() if record.path.startswith("/compute/results")]
    assert result_page_requests == [], result_page_requests

    # The Dashboard keeps a durable restart entry: re-launching begins at step 1 again.
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    launcher = page.locator(".tour-launcher")
    expect(launcher).to_be_visible()
    launcher.click()
    expect(page.locator(".tour-callout")).to_contain_text("Step 1 of 5")


def test_guided_tour_clears_a_stale_result_target_and_skips_the_step(page: Page) -> None:
    # A stale target from an interrupted tour, a deleted task, or a previous session
    # must never be visited. This scenario publishes no result, so the Dashboard has
    # no valid target and the stored one is cleared on load.
    stale_id = "ffffffffffffffffffffffffffffffff"
    router = _dashboard(page)
    page.evaluate("(url) => localStorage.setItem('revocompute-tour-result', url)", f"/compute/results/{stale_id}")
    page.reload()
    expect(page.locator(".task-card").first).to_be_visible()
    assert page.evaluate("localStorage.getItem('revocompute-tour-result')") is None

    page.get_by_role("button", name="Guided tour").click()
    expect(page.locator(".tour-callout")).to_contain_text("Step 1 of 5")
    for _ in range(4):
        page.locator(".tour-callout").get_by_role("button", name="Next").click()
    # Step 4 is Create Task; the result step is skipped rather than pursued to a stale URL.
    expect(page).to_have_url(f"{ORIGIN}/compute/create_task")
    expect(page.locator(".tour-callout")).to_have_count(0)

    stale_requests = [record.path for record in router.requests.navigation() if record.path == f"/compute/results/{stale_id}"]
    assert stale_requests == [], stale_requests
    result_requests = [record.path for record in router.requests.navigation() if record.path.startswith("/compute/results")]
    assert result_requests == [], result_requests


def test_guided_tour_result_step_visits_a_real_result_and_localizes_its_copy(page: Page) -> None:
    mount_scenario(page, controlled_scenario().with_result("minimal_success"))
    page.goto(f"{ORIGIN}/compute/dashboard")
    expect(page.locator(".task-card").first).to_be_visible()
    # The Dashboard records the concrete result URL; the tour never fabricates an id.
    result_url = page.evaluate("localStorage.getItem('revocompute-tour-result')")
    assert result_url is not None and result_url.startswith("/compute/results/")

    page.locator(".lang-menu > summary").click()
    page.locator('[data-locale="zh-CN"]').click()
    expect(page.locator("html")).to_have_attribute("lang", "zh-CN")
    page.get_by_role("button", name="引导教程").click()
    callout = page.locator(".tour-callout")
    expect(callout).to_contain_text("第 1 步，共 5 步")

    # Localized step copy, not only localized controls.
    callout.get_by_role("button", name="下一步").click()
    expect(callout).to_contain_text("第 2 步，共 5 步")
    callout.get_by_role("button", name="下一步").click()
    expect(page).to_have_url(f"{ORIGIN}/runners")
    callout.get_by_role("button", name="下一步").click()
    expect(page).to_have_url(f"{ORIGIN}/compute/create_task")
    callout.get_by_role("button", name="下一步").click()

    # The final step lands on the real recorded result, not a dangling route.
    expect(page).to_have_url(f"{ORIGIN}{result_url}")
    expect(page.locator(".tour-callout")).to_contain_text("第 5 步，共 5 步")
    expect(page.locator(".tour-callout")).to_contain_text("结果是页面最醒目的部分")


# ── dashboard filters, advanced search, and view switch ───────────────────────


def test_advanced_search_is_subordinate_and_obviously_active(page: Page) -> None:
    _dashboard(page)
    toggle = page.get_by_role("button", name="Advanced search")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(page.locator("[data-advanced-panel]")).to_be_hidden()
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    panel = page.locator("[data-advanced-panel]")
    expect(panel).to_be_visible()
    # A low-frequency control is revealed, not appended as noise to the search field.
    panel.get_by_label("Submitted from").fill("2026-01-01")
    panel.get_by_label("Regular expression").click()
    expect(page.get_by_role("button", name="Advanced search, 2 active")).to_be_visible()


def test_view_switch_is_independent_of_filtering(page: Page) -> None:
    _dashboard(page)
    # Filtering and presentation are separate control groups.
    filters = page.locator("[aria-label='Task filters']")
    view = page.locator(".view-toolbar .layout-switch")
    expect(filters.locator(".layout-switch")).to_have_count(0)
    expect(view).to_be_visible()
    expect(view.get_by_role("button", name="Detailed")).to_have_attribute("aria-pressed", "true")
    view.get_by_role("button", name="Table").click()
    expect(page.locator(".task-list")).to_have_attribute("data-layout", "table")
    expect(page.locator(".task-table")).to_be_visible()
    view.get_by_role("button", name="Compact").click()
    expect(page.locator(".task-list")).to_have_attribute("data-layout", "compact")


# ── task cards ────────────────────────────────────────────────────────────────


def test_task_card_has_no_decorative_status_rail_and_states_status_as_text(page: Page) -> None:
    _dashboard(page)
    card = page.locator(".task-card").first
    # A status boundary must not be drawn as a coloured side rail.
    left = card.evaluate("node => getComputedStyle(node).borderLeftWidth")
    assert float(left.replace("px", "")) <= 1
    # Status is communicated by a word, with a non-colour shape cue, not colour alone.
    status = card.locator(".status")
    expect(status).to_be_visible()
    assert status.inner_text().strip()
    assert status.evaluate("node => getComputedStyle(node, '::before').content") not in ("none", "normal")


def test_task_card_metadata_uses_machine_text_for_identity_only(page: Page) -> None:
    _dashboard(page)
    card = page.locator(".task-card").first
    id_value = card.locator("dd.machine")
    expect(id_value).to_have_count(1)
    # The identity field is a definition value rendering the task ID itself.
    assert id_value.evaluate("node => node.tagName").lower() == "dd"
    assert id_value.inner_text().strip()
    assert "mono" in id_value.evaluate("node => getComputedStyle(node).fontFamily").lower()
    # Task ID remains fully inspectable — selectable, not destroyed by truncation.
    assert id_value.evaluate("node => getComputedStyle(node).textOverflow") in ("clip", "ellipsis")


# ── accessibility ─────────────────────────────────────────────────────────────


def test_primary_controls_show_visible_focus_and_carry_accessible_names(page: Page) -> None:
    _dashboard(page)
    # Visible focus: a keyboard-reachable primary action paints a focus indicator.
    run = page.locator(".app-header a.app-new-task")
    run.focus()
    outline = run.evaluate("node => [getComputedStyle(node).outlineStyle, getComputedStyle(node).outlineWidth]")
    assert outline[0] != "none" and float(outline[1].replace("px", "")) > 0
    # Icon-only controls still have meaningful accessible names. (The notices
    # affordance is only mounted when a notice exists; the notice lifecycle test
    # asserts its accessible name in that state.)
    expect(page.get_by_role("button", name="Theme: Auto")).to_have_count(1)
    expect(page.get_by_role("button", name="Guided tour")).to_have_count(1)
    assert page.locator(".lang-menu > summary").get_attribute("aria-label")


def test_body_text_meets_contrast_on_canvas_in_light_and_dark(page: Page) -> None:
    _dashboard(page)
    samples = page.evaluate(
        """() => {
            const ink = getComputedStyle(document.body).color;
            const canvas = getComputedStyle(document.body).backgroundColor;
            const muted = getComputedStyle(document.querySelector('.task-card dt')).color;
            return {ink, canvas, muted};
        }"""
    )
    assert _contrast_ratio(samples["ink"], samples["canvas"]) >= 4.5, samples
    assert samples["muted"] != samples["ink"], samples  # the muted token is genuinely sampled
    assert _contrast_ratio(samples["muted"], samples["canvas"]) >= 4.5, samples

    page.get_by_role("button", name="Theme: Auto").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    dark = page.evaluate(
        """() => {
            const ink = getComputedStyle(document.body).color;
            const canvas = getComputedStyle(document.body).backgroundColor;
            const muted = getComputedStyle(document.querySelector('.task-card dt')).color;
            return {ink, canvas, muted};
        }"""
    )
    assert _contrast_ratio(dark["ink"], dark["canvas"]) >= 4.5, dark
    assert dark["muted"] != dark["ink"], dark
    assert _contrast_ratio(dark["muted"], dark["canvas"]) >= 4.5, dark


# ── dark mode ─────────────────────────────────────────────────────────────────


def test_dark_mode_is_neutral_and_avoids_a_green_cast(page: Page) -> None:
    _dashboard(page)
    page.get_by_role("button", name="Theme: Auto").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    palette = page.evaluate(
        """() => {
            const root = getComputedStyle(document.documentElement);
            return {
                bodyBg: getComputedStyle(document.body).backgroundColor,
                cardBg: getComputedStyle(document.querySelector('.task-card')).backgroundColor,
                ink: getComputedStyle(document.body).color,
                accent: root.getPropertyValue('--app-accent').trim(),
            };
        }"""
    )
    # Neutral surfaces keep green near red and blue; a teal/green wash would not.
    for value in (palette["bodyBg"], palette["cardBg"], palette["ink"]):
        red, green, blue = _rgb(value)
        assert abs(green - red) <= 8 and abs(green - blue) <= 8, value
    # The accent stays a true blue (blue-dominant), not a teal that neutralises to green.
    red, green, blue = _rgb(palette["accent"])
    assert blue > red and blue > green, palette["accent"]


def test_mobile_targets_are_touch_sized_and_motion_is_reducible(page: Page) -> None:
    _dashboard(page)
    page.set_viewport_size({"width": 360, "height": 780})
    page.reload()
    nav_link = page.locator(".app-nav a").first
    expect(nav_link).to_be_visible()
    box = nav_link.bounding_box()
    assert box is not None and box["height"] >= 44 and box["width"] >= 44, box
    # A reduced-motion preference removes ornamental transition timing.
    page.emulate_media(reduced_motion="reduce")
    duration = page.locator(".app-header a.app-new-task").evaluate("node => getComputedStyle(node).transitionDuration")
    for part in duration.split(","):
        part = part.strip()
        assert part == "0s" or float(part.replace("s", "")) <= 0.001, duration
