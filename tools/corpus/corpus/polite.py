"""수집 예절을 코드로 강제하는 HTTP 세션 (수집 규칙 ①②③④⑩).

- robots.txt를 호스트마다 읽고 막힌 주소는 요청하지 않는다
- 요청은 한 번에 하나, 시작 간격 2초 이상
- 평일 9~18시(한국 시간)에는 요청하지 않고 멈춘다(학교 업무 시간 회피)
- User-Agent에 프로젝트 이름을 적는다
- 403·429·5xx가 이어지면 간격을 두 배로 늘리고, 연속 5번이면 멈춘다
"""

import re
import time
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import requests

KST = timezone(timedelta(hours=9))
USER_AGENT = "DocuMind-corpus-collector/0.1 (Inha Technical College chatbot research project)"
DISTRESS_STATUS = {403, 429}
MAX_INTERVAL = 30.0


class Stop(Exception):
    """수집을 멈춰야 하는 상황(업무 시간, 오류 연속). 나중에 이어 받으면 된다."""


class RobotsDisallowed(Exception):
    pass


def wildcard_disallows(robots_text: str, user_agent: str) -> list[re.Pattern[str]]:
    """표준 해석기(urllib.robotparser)가 지원하지 않는 `*`·`$` 규칙을 정규식으로 만든다.

    학교 robots.txt는 `Disallow: /*/topMngr` 같은 와일드카드 규칙을 쓴다.
    `User-agent: *` 묶음과 우리 User-Agent 이름이 들어간 묶음만 본다.
    """
    patterns: list[re.Pattern[str]] = []
    applies = False
    agent_name = user_agent.split("/")[0].lower()
    for raw_line in robots_text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, value = (part.strip() for part in line.split(":", 1))
        field = field.lower()
        if field == "user-agent":
            applies = value == "*" or value.lower() in agent_name
        elif field == "disallow" and applies and value and ("*" in value or value.endswith("$")):
            body = re.escape(value.rstrip("$")).replace(r"\*", ".*")
            patterns.append(re.compile("^" + body + ("$" if value.endswith("$") else "")))
    return patterns


class PoliteSession:
    def __init__(
        self,
        user_agent: str = USER_AGENT,
        min_interval: float = 2.0,
        max_consecutive_errors: int = 5,
        allow_business_hours: bool = False,
        http: requests.Session | None = None,
        clock=time.monotonic,
        sleep=time.sleep,
        now=lambda: datetime.now(KST),
        timeout: float = 60.0,
        max_requests: int | None = None,
    ):
        self.user_agent = user_agent
        self.base_interval = min_interval
        self.interval = min_interval
        self.max_consecutive_errors = max_consecutive_errors
        self.allow_business_hours = allow_business_hours
        self.http = http or requests.Session()
        self.clock = clock
        self.sleep = sleep
        self.now = now
        self.timeout = timeout
        self.max_requests = max_requests
        self.consecutive_errors = 0
        self.requests_made = 0
        self._last_start: float | None = None
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._wildcards: dict[str, list[re.Pattern[str]]] = {}

    def in_business_hours(self) -> bool:
        current = self.now()
        return current.weekday() < 5 and 9 <= current.hour < 18

    def _wait_turn(self) -> None:
        if self._last_start is not None:
            remaining = self.interval - (self.clock() - self._last_start)
            if remaining > 0:
                self.sleep(remaining)
        self._last_start = self.clock()

    def _raw_get(self, url: str, referer: str | None, stream: bool = False) -> requests.Response:
        if not self.allow_business_hours and self.in_business_hours():
            raise Stop("평일 9~18시에는 수집하지 않는다(수집 규칙 ②). 업무 시간이 끝난 뒤 이어 받는다")
        self._wait_turn()
        headers = {"User-Agent": self.user_agent}
        if referer:
            headers["Referer"] = referer
        if self.max_requests is not None and self.requests_made >= self.max_requests:
            raise Stop(f"요청 상한 {self.max_requests}회에 닿아 멈춘다(시험 실행)")
        self.requests_made += 1
        return self.http.get(url, headers=headers, timeout=self.timeout, stream=stream)

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            response = self._raw_get(f"{origin}/robots.txt", None)
            text = response.text if response.status_code == 200 else ""
            parser.parse(text.splitlines())  # robots.txt가 없으면 모두 허용(표준 해석)
            self._robots[origin] = parser
            self._wildcards[origin] = wildcard_disallows(text, self.user_agent)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        if any(pattern.match(path) for pattern in self._wildcards[origin]):
            return False
        return self._robots[origin].can_fetch(self.user_agent, url)

    def get(self, url: str, referer: str | None = None, stream: bool = False) -> requests.Response:
        if not self.allowed(url):
            raise RobotsDisallowed(url)
        response = self._raw_get(url, referer, stream)
        if response.status_code in DISTRESS_STATUS or response.status_code >= 500:
            self.consecutive_errors += 1
            self.interval = min(self.interval * 2, MAX_INTERVAL)
            if self.consecutive_errors >= self.max_consecutive_errors:
                raise Stop(f"오류 응답이 {self.consecutive_errors}번 이어져 멈춘다(마지막 {response.status_code}): {url}")
        else:
            self.consecutive_errors = 0
            self.interval = self.base_interval
        return response
