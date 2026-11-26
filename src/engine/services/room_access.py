from dataclasses import dataclass
from typing import Any, Optional

from services.media_store import canonical_media_url


@dataclass(frozen=True)
class ActiveMembership:
    room_id: str
    user_id: int
    role: str
    slot: int
    room_status: str
    room_creator_user_id: int
    room_created_at: str


@dataclass(frozen=True)
class PublicRoomMember:
    id: int
    nickname: str
    avatar_url: Optional[str]
    role: str
    slot: int


@dataclass(frozen=True)
class ActivePair:
    room_id: str
    partner_user_id: int
    partner_nickname: str


async def get_active_paired_membership(
    db: Any,
    user_id: int,
    room_id: str,
) -> Optional[ActiveMembership]:
    """Return membership only for a structurally valid active two-person room."""
    membership = await get_active_membership(db, user_id, room_id)
    if membership is None or membership.room_status != "active":
        return None
    members = await get_public_room_members(db, room_id)
    if members is None or len(members) != 2:
        return None
    if not any(member.id == user_id for member in members):
        return None
    return membership


async def get_active_published_post(
    db: Any,
    room_id: str,
    post_id: str,
) -> Optional[Any]:
    """Return an active post whose author remains an active room member."""
    cursor = await db.execute(
        """
        SELECT post.*
        FROM room_posts AS post
        JOIN rooms AS room
          ON room.id = post.room_id AND room.status = 'active'
        JOIN room_members AS author
          ON author.room_id = post.room_id
         AND author.user_id = post.author_user_id
         AND author.left_at IS NULL
        WHERE post.room_id = ? AND post.id = ?
          AND post.status = 'published' AND post.revoked_at IS NULL
        """,
        (room_id, post_id),
    )
    return await cursor.fetchone()


async def get_active_membership(
    db: Any,
    user_id: int,
    room_id: Optional[str] = None,
) -> Optional[ActiveMembership]:
    """Return the user's sole non-left membership, failing closed on ambiguity."""
    # 遵循 SEC-AUTH-002 规范: derive resource access from server-side membership.
    if room_id is None:
        cursor = await db.execute(
            """
            SELECT member.room_id, member.user_id, member.role, member.slot,
                   room.status AS room_status,
                   room.creator_user_id AS room_creator_user_id,
                   room.created_at AS room_created_at
            FROM room_members AS member
            JOIN rooms AS room ON room.id = member.room_id
            WHERE member.user_id = ? AND member.left_at IS NULL
            LIMIT 2
            """,
            (user_id,),
        )
    else:
        cursor = await db.execute(
            """
            SELECT member.room_id, member.user_id, member.role, member.slot,
                   room.status AS room_status,
                   room.creator_user_id AS room_creator_user_id,
                   room.created_at AS room_created_at
            FROM room_members AS member
            JOIN rooms AS room ON room.id = member.room_id
            WHERE member.user_id = ? AND member.room_id = ?
              AND member.left_at IS NULL
            LIMIT 2
            """,
            (user_id, room_id),
        )
    rows = await cursor.fetchall()
    if len(rows) != 1:
        return None
    row = rows[0]
    if row["role"] not in {"owner", "member"} or row["slot"] not in {1, 2}:
        return None
    if (row["role"], row["slot"]) not in {("owner", 1), ("member", 2)}:
        return None
    return ActiveMembership(
        room_id=row["room_id"],
        user_id=row["user_id"],
        role=row["role"],
        slot=row["slot"],
        room_status=row["room_status"],
        room_creator_user_id=row["room_creator_user_id"],
        room_created_at=row["room_created_at"],
    )


async def get_public_room_members(
    db: Any,
    room_id: str,
) -> Optional[tuple[PublicRoomMember, ...]]:
    """Return a structurally valid active room's minimal public member data."""
    cursor = await db.execute(
        """
        SELECT member.user_id, member.role, member.slot,
               profile.nickname, avatar.id AS avatar_asset_id
        FROM room_members AS member
        JOIN rooms AS room
          ON room.id = member.room_id AND room.status = 'active'
        JOIN profile ON profile.id = member.user_id
        LEFT JOIN media_assets AS avatar
          ON avatar.id = profile.avatar_asset_id
         AND avatar.owner_user_id = profile.id
        WHERE member.room_id = ? AND member.left_at IS NULL
        ORDER BY member.slot
        LIMIT 3
        """,
        (room_id,),
    )
    rows = await cursor.fetchall()
    if len(rows) not in {1, 2}:
        return None
    expected = [("owner", 1)] if len(rows) == 1 else [("owner", 1), ("member", 2)]
    if [(row["role"], row["slot"]) for row in rows] != expected:
        return None
    return tuple(
        PublicRoomMember(
            id=row["user_id"],
            nickname=row["nickname"],
            avatar_url=(
                canonical_media_url(row["avatar_asset_id"])
                if row["avatar_asset_id"]
                else None
            ),
            role=row["role"],
            slot=row["slot"],
        )
        for row in rows
    )


def public_member_data(member: PublicRoomMember) -> dict[str, Any]:
    return {
        "id": member.id,
        "nickname": member.nickname,
        "avatar_url": member.avatar_url,
        "role": member.role,
        "slot": member.slot,
    }


async def get_active_room_data(
    db: Any,
    user_id: int,
    room_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    membership = await get_active_membership(db, user_id, room_id)
    if membership is None or membership.room_status != "active":
        return None
    members = await get_public_room_members(db, membership.room_id)
    if members is None or not any(member.id == user_id for member in members):
        return None
    partner = next((member for member in members if member.id != user_id), None)
    waiting = len(members) == 1
    return {
        "id": membership.room_id,
        "status": "active",
        "state": "waiting" if waiting else "paired",
        "waiting": waiting,
        "created_at": membership.room_created_at,
        "members": [public_member_data(member) for member in members],
        "partner": public_member_data(partner) if partner else None,
    }


async def get_active_pair(db: Any, user_id: int) -> Optional[ActivePair]:
    """Return the current user's active two-person room, if fully paired."""
    room = await get_active_room_data(db, user_id)
    if room is None or room["state"] != "paired" or room["partner"] is None:
        return None
    return ActivePair(
        room_id=room["id"],
        partner_user_id=room["partner"]["id"],
        partner_nickname=room["partner"]["nickname"],
    )
