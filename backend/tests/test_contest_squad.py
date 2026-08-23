from app.services.contest_archive import normalize_scoreboard_squad, squad_search_text


def _user(uid: int, name: str, *, color: str = "Red") -> dict:
    return {
        "uid": uid,
        "name": name,
        "color": color,
        "badge": None,
        "ccfLevel": 7,
        "xcpcLevel": 0,
        "isAdmin": False,
    }


def test_squad_contains_leader_and_members_with_fallback_name() -> None:
    leader = _user(1, "leader")
    row = {
        "user": leader,
        "squad": {
            "name": "",
            "leader": leader,
            "members": [_user(2, "member", color="Orange")],
        },
    }

    squad = normalize_scoreboard_squad(row, leader)

    assert squad is not None
    assert squad["name"] == "leader 的小队"
    assert [member["uid"] for member in squad["members"]] == [1, 2]
    assert squad["members"][1]["color"] == "Orange"
    assert squad_search_text(squad) == "leader 的小队 leader 1 member 2"


def test_solo_row_has_no_squad() -> None:
    user = _user(1, "solo")

    assert normalize_scoreboard_squad({"user": user}, user) is None
    assert squad_search_text(None) is None
