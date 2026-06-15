"""
Physical AI 뉴스 다이제스트 - 카카오톡 자동 발송
매일 오전 7시 실행 (GitHub Actions)

[출처 신뢰성 원칙]
1. RSS 소스: 검증된 공식 매체만 사용 (블로그/포럼 제외)
2. Claude 요약: 수집된 기사 내용만 사용, 외부 지식 추가 금지
3. 각 요약 항목에 출처 매체명 + 원문 제목 명시
4. 내용 불충분한 기사는 요약에서 제외
"""

import os
import re
import json
import requests
import feedparser
from datetime import datetime, timedelta, timezone
from anthropic import Anthropic

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────

KST = timezone(timedelta(hours=9))

# ★ 검증된 공식 매체만 포함 (블로그·포럼·애그리게이터 제외)
RSS_SOURCES = [
    # 영어 - 로봇/Physical AI 전문 매체
    {"url": "https://feeds.feedburner.com/ieee-spectrum/robotics",  "lang": "en", "label": "IEEE Spectrum",      "tier": 1},
    {"url": "https://techcrunch.com/tag/robotics/feed/",            "lang": "en", "label": "TechCrunch",         "tier": 1},
    {"url": "https://www.therobotreport.com/feed/",                 "lang": "en", "label": "The Robot Report",   "tier": 1},
    {"url": "https://spectrum.ieee.org/feeds/topic/robotics.rss",   "lang": "en", "label": "IEEE Spectrum(2)",   "tier": 1},
    # 영어 - 중국 테크 전문 영문 매체
    {"url": "https://technode.com/feed/",                           "lang": "en", "label": "TechNode(중국)",     "tier": 1},
    {"url": "https://www.scmp.com/rss/91/feed",                     "lang": "en", "label": "SCMP Tech",          "tier": 1},
    # 한국어 - 공식 IT 매체
    {"url": "https://www.aitimes.com/rss/allArticle.xml",           "lang": "ko", "label": "AI타임스",           "tier": 1},
    {"url": "https://www.etnews.com/rss/rss.xml",                   "lang": "ko", "label": "전자신문",           "tier": 1},
    # 중국어 - 검증된 중국 테크 매체
    {"url": "https://www.leiphone.com/feed",                        "lang": "zh", "label": "雷锋网",             "tier": 1},
    {"url": "https://36kr.com/rss/next",                            "lang": "zh", "label": "36氪",               "tier": 1},
]

# Physical AI 관련 키워드
KEYWORDS = [
    # 영어
    "physical ai", "humanoid", "robot", "robotics", "embodied ai",
    "boston dynamics", "figure ai", "1x technologies", "agility robotics",
    "nvidia gr", "tesla optimus", "unitree", "fourier intelligence",
    "manipulation", "locomotion", "dexterous", "autonomous mobile",
    "china robot", "chinese robot",
    # 한국어
    "휴머노이드", "로봇", "피지컬 ai", "물리 ai", "자율이동",
    "로봇 팔", "협동로봇", "산업용 로봇",
    # 중국어
    "机器人", "人形机器人", "具身智能", "工业机器人",
    "宇树", "傅利叶", "优必选", "智元",
]

# 요약에 포함하기 충분한 최소 내용 길이 (너무 짧은 기사 제외)
MIN_SUMMARY_LENGTH = 80


def fetch_recent_articles(hours_back: int = 24) -> list[dict]:
    """RSS에서 최근 N시간 이내 기사 수집 (내용 불충분 기사 자동 제외)"""
    cutoff = datetime.now(KST) - timedelta(hours=hours_back)
    articles = []

    for source in RSS_SOURCES:
        try:
            feed = feedparser.parse(source["url"])
            for entry in feed.entries[:20]:
                # 날짜 파싱
                pub = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).astimezone(KST)
                elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                    pub = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc).astimezone(KST)

                if pub and pub < cutoff:
                    continue

                title   = entry.get("title", "").strip()
                summary = entry.get("summary", "") or entry.get("description", "")
                summary = re.sub(r"<[^>]+>", "", summary).strip()[:600]
                link    = entry.get("link", "")

                # ★ 내용 불충분 기사 제외
                if len(summary) < MIN_SUMMARY_LENGTH:
                    continue

                # 키워드 필터링
                text_to_check = (title + " " + summary).lower()
                if any(kw.lower() in text_to_check for kw in KEYWORDS):
                    articles.append({
                        "id":      len(articles) + 1,
                        "title":   title,
                        "summary": summary,
                        "link":    link,
                        "lang":    source["lang"],
                        "label":   source["label"],
                        "pub":     pub.strftime("%m/%d %H:%M") if pub else "날짜 미상",
                    })
        except Exception as e:
            print(f"[WARN] {source['label']} 수집 실패: {e}")

    return articles


def summarize_with_claude(articles: list[dict]) -> str:
    """Claude API로 기사 요약 생성 - 출처 확실성 최우선"""
    if not articles:
        return "📭 오늘은 관련 뉴스가 없습니다."

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    articles_text = ""
    for a in articles:
        lang_label = {"en": "영어", "ko": "한국어", "zh": "중국어"}.get(a["lang"], "")
        articles_text += (
            f"\n[기사 #{a['id']}]\n"
            f"출처: {a['label']} ({lang_label}) | {a['pub']}\n"
            f"제목: {a['title']}\n"
            f"내용: {a['summary']}\n"
        )

    today = datetime.now(KST).strftime("%Y년 %m월 %d일")

    # ★ 핵심: 출처 신뢰성 강화 프롬프트
    prompt = f"""당신은 Physical AI 분야 뉴스 큐레이터입니다.

아래 [수집된 기사]만을 근거로 {today} 아침 브리핑을 작성하세요.

[수집된 기사]
{articles_text}

[절대 규칙 - 반드시 준수]
1. 위 기사에 명시된 사실만 작성하세요. 기사에 없는 내용, 배경 지식, 추론, 예측을 추가하지 마세요.
2. 각 뉴스 항목 끝에 반드시 "출처: [매체명]" 형식으로 원본 출처를 표기하세요.
3. 기사 내용이 불분명하거나 제목만 있고 내용이 없는 경우, 해당 기사는 브리핑에서 제외하세요.
4. 중국어 기사는 번역만 하고, 번역 외의 내용을 추가하지 마세요.
5. "~할 것으로 보인다", "~로 알려졌다" 등 추측성 표현 사용 금지. 기사에 있는 사실만 서술하세요.

[형식]
- 첫 줄: 🤖 Physical AI 모닝브리핑 {today}
- 핵심 뉴스 3~5건:
  [이모지] 제목 (한 줄)
  내용 요약 2~3줄 (기사 원문 기반만)
  출처: [매체명]
- 중국 관련 뉴스에는 🇨🇳 이모지 사용
- 마지막 줄: 💡 오늘의 인사이트: [수집된 기사에서 공통으로 보이는 실제 트렌드 한 줄]
- 전체 600~900자

브리핑:"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text


def get_kakao_token() -> str:
    """카카오 리프레시 토큰으로 액세스 토큰 갱신"""
    res = requests.post(
        "https://kauth.kakao.com/oauth/token",
        data={
            "grant_type":    "refresh_token",
            "client_id":     os.environ["KAKAO_REST_API_KEY"],
            "refresh_token": os.environ["KAKAO_REFRESH_TOKEN"],
        },
    )
    res.raise_for_status()
    data = res.json()

    if "refresh_token" in data:
        print(f"[INFO] 새 리프레시 토큰 발급됨 → GitHub Secret 업데이트 필요: {data['refresh_token']}")

    return data["access_token"]


def send_kakao_message(text: str) -> bool:
    """카카오톡 나에게 보내기"""
    token = get_kakao_token()

    template = {
        "object_type": "text",
        "text": text[:1000],
        "link": {
            "web_url":        "https://www.google.com/search?q=physical+ai+robot+news",
            "mobile_web_url": "https://www.google.com/search?q=physical+ai+robot+news",
        },
    }

    res = requests.post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        headers={"Authorization": f"Bearer {token}"},
        data={"template_object": json.dumps(template, ensure_ascii=False)},
    )

    if res.status_code == 200 and res.json().get("result_code") == 0:
        print("[OK] 카카오톡 전송 완료")
        return True
    else:
        print(f"[ERR] 카카오톡 전송 실패: {res.text}")
        return False


def main():
    print(f"[START] {datetime.now(KST).strftime('%Y-%m-%d %H:%M')} KST")

    print("[1/3] RSS 뉴스 수집 중...")
    articles = fetch_recent_articles(hours_back=24)
    print(f"  → {len(articles)}건 수집됨 (내용 불충분 기사 자동 제외됨)")

    print("[2/3] Claude 요약 생성 중...")
    digest = summarize_with_claude(articles)
    print(f"  → 요약 완료 ({len(digest)}자)")
    print("─" * 40)
    print(digest)
    print("─" * 40)

    print("[3/3] 카카오톡 발송 중...")
    send_kakao_message(digest)

    print("[DONE]")


if __name__ == "__main__":
    main()
