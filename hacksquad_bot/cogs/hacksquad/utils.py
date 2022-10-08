import ast
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Any, Dict, List, Optional, TypedDict

import aiohttp
from dateutil.parser import isoparse
from discord import Color

from hacksquad_bot.utils.objects import Singleton

HACKSQUAD_COLOR = Color.from_rgb(255, 0, 149)


class ResponseError(Exception):
    """Something went wrong with the response"""

    code: int

    def __init__(self, status_code: int) -> None:
        self.code = status_code


class User(TypedDict):
    created_at: datetime
    "When the user has been created"

    id: str
    "Unique ID of the user"

    name: str
    "The name of the user"

    email_verified: bool
    "If the user's email has been verified"

    image: str
    "An URL to the user's GitHub's image"

    moderator: bool
    "If the user is a moderator of the event"

    handle: str
    "The GitHub handle/name"

    team_id: str
    "ID of team the user has joined"

    disqualified: bool
    "If the user has been disqualified during the event"

    github_user_id: Optional[Any]
    "An unknown value"


class PartialTeam(TypedDict):
    place: Optional[int]
    "The place of the team in the leaderboard"

    id: str
    "The team's unique ID"

    name: str
    "The team's name"

    score: int
    "The team's score/total PRs"

    slug: str
    "The unique slug of the team"


class PRStatus(Enum):
    ACCEPTED = auto()
    DELETED = auto()


class PR(TypedDict):
    id: str
    "ID of pull request in HackSquad"

    created_at: datetime
    "When the PR has been created"

    title: str
    "The PR's title"

    url: str
    "The PR's URL"

    status: PRStatus


class Team(PartialTeam):
    owner_id: str
    "The ID of the owner of the team"

    owner: Optional[User]
    "The owner, as a User object. Can be optional."

    prs: List[PR]
    "The PRs realized by the team"

    github_team_id: Optional[Any]
    "An unknown value"

    allow_auto_assign: bool
    "If the team allows auto assignement of members"

    disqualified: bool
    "If the team has been disqualified during the event"

    users: List[User]


class RequesterCachedAttribute(TypedDict):
    cached_at: datetime
    data: Any


class Requester(Singleton):
    _cache: Dict[str, RequesterCachedAttribute] = {}
    _cache_team: Dict[str, RequesterCachedAttribute] = {}

    async def _make_request(self, url: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise ResponseError(response.status)
                return await response.json()

    def _allow_cache_use(self, entry_name: str) -> bool:
        if not self._cache_team.get(entry_name):
            return False

        cached_at = self._cache_team[entry_name]["cached_at"]
        invalid_at = cached_at + timedelta(minutes=30)

        # Cached data is invalid if it's been there since 30 minutes
        return invalid_at >= datetime.now()

    def _allow_cache_team_use(self, team_slug: str) -> bool:
        if not self._cache.get(team_slug):
            return False

        cached_at = self._cache[team_slug]["cached_at"]
        invalid_at = cached_at + timedelta(minutes=30)

        # Cached data is invalid if it's been there since 30 minutes
        return invalid_at >= datetime.now()

    async def fetch_leaderboard(self) -> List[PartialTeam]:
        if self._allow_cache_use("leaderboard"):
            return self._cache["leaderboard"]["data"]

        result = await self._make_request("https://www.hacksquad.dev/api/leaderboard")

        final_result = [
            PartialTeam(
                place=None,
                id=info["id"],
                name=info["name"],
                score=info["score"],
                slug=info["slug"],
            )
            for info in result["teams"]
        ]
        self._cache["leaderboard"] = {"cached_at": datetime.now(), "data": final_result}
        return final_result

    async def fetch_team(self, slug: str) -> Team:
        if self._allow_cache_team_use(slug):
            return self._cache_team[slug]["data"]

        result = await self._make_request(f"https://www.hacksquad.dev/api/team/?id={slug}")
        info = result["team"]

        # Get owner as User object
        owner = None
        for user in info["users"]:
            if user["id"] == info["ownerId"]:
                owner = User(
                    created_at=isoparse(user["createdAt"]),
                    id=user["id"],
                    name=user["name"],
                    email_verified=user["emailVerified"],
                    image=user["image"],
                    moderator=user["moderator"],
                    handle=user["handle"],
                    team_id=user["teamId"],
                    disqualified=user["disqualified"],
                    github_user_id=user["githubUserId"],
                )

        # Convert the str list to a Python list & cleanup
        info["prs"] = ast.literal_eval(info["prs"])

        # Get all PRs as PR object
        prs = [
            PR(
                id=pr["id"],
                created_at=isoparse(pr["createdAt"]),
                title=pr["title"],
                url=pr["url"],
                status=(
                    PRStatus.DELETED
                    if pr.get("status", "ACCEPTED") == "DELETED"
                    else PRStatus.ACCEPTED
                ),
            )
            for pr in info["prs"]
        ]

        users = [
            User(
                created_at=isoparse(user["createdAt"]),
                id=user["id"],
                name=user["name"],
                email_verified=user["emailVerified"],
                image=user["image"],
                moderator=user["moderator"],
                handle=user["handle"],
                team_id=user["teamId"],
                disqualified=user["disqualified"],
                github_user_id=user["githubUserId"],
            )
            for user in info["users"]
        ]

        team = Team(
            place=None,
            id=info["id"],
            name=info["name"],
            score=info["score"],
            slug=info["slug"],
            owner_id=info["ownerId"],
            owner=owner,
            prs=prs,
            github_team_id=info["githubTeamId"],
            allow_auto_assign=info["allowAutoAssign"],
            disqualified=info["disqualified"],
            users=users,
        )
        self._cache_team[team["slug"]] = {"cached_at": datetime.now(), "data": team}
        return team

    async def fetch_contributors(self):
        if self._allow_cache_use("contributors"):
            return self._cache["contributors"]["data"]

        result = await self._make_request("https://contributors.novu.co/contributors")
        self._cache["contributors"] = {"cached_at": datetime.now(), "data": result["list"]}
        return result["list"]

    async def fetch_contributors_mini(self):
        # I do not think that we would get much of a performance benefit from this but leaving it here all the same
        if self._allow_cache_use("contributors_mini"):
            return self._cache["contributors_mini"]["data"]

        result = await self._make_request("https://contributors.novu.co/contributors-mini")
        self._cache["contributors"] = {"cached_at": datetime.now(), "data": result["list"]}
        return result["list"]