"""The placement model cannot duplicate, discard or over-expand a sidebar."""

from toad.sidebar_layout import SidebarLayout


def main() -> None:
    layout = SidebarLayout()
    assert layout.ordered() == ("channels-sidebar", "thread-sidebar")
    assert layout.move("channels-sidebar", "right")
    assert layout.get("thread-sidebar").order == 0
    assert layout.get("channels-sidebar").order == 1
    assert layout.swap("channels-sidebar")
    assert layout.get("channels-sidebar").order == 0
    assert layout.get("thread-sidebar").order == 1
    assert layout.ordered() == ("thread-sidebar", "channels-sidebar")
    assert layout.move("thread-sidebar", "left")
    assert layout.ordered() == ("thread-sidebar", "channels-sidebar")
    assert layout.get("thread-sidebar").order == 0
    assert layout.width("channels-sidebar", 70)
    assert layout.get("channels-sidebar").width_percent == 50
    assert layout.width("channels-sidebar", 1)
    assert layout.get("channels-sidebar").width_percent == 15
    assert layout.float_mode("thread-sidebar") is True
    assert layout.float_mode("thread-sidebar") is False
    assert set(layout.ordered()) == {"thread-sidebar", "channels-sidebar"}
    print("sidebar placement: move, same-side swap, 15–50% width, float/push")


if __name__ == "__main__":
    main()
