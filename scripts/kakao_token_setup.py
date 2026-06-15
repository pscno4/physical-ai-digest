"""
카카오 리프레시 토큰 최초 발급 스크립트
한 번만 실행하면 됩니다.
"""

import os
import requests
import webbrowser
from urllib.parse import urlencode

REST_API_KEY = input("카카오 REST API 키를 입력하세요: ").strip()

# 1단계: 인가 코드 발급 URL 열기
params = urlencode({
    "client_id":     REST_API_KEY,
    "redirect_uri":  "https://example.com/oauth",   # 앱 설정에 등록한 URI
    "response_type": "code",
    "scope":         "talk_message",
})
auth_url = f"https://kauth.kakao.com/oauth/authorize?{params}"

print("\n아래 URL을 브라우저에서 열고, 로그인 후 리다이렉트된 주소를 복사하세요:")
print(auth_url)
webbrowser.open(auth_url)

code = input("\n리다이렉트 URL에서 ?code= 뒤의 값을 붙여넣으세요: ").strip()

# 2단계: 액세스 토큰 + 리프레시 토큰 발급
res = requests.post(
    "https://kauth.kakao.com/oauth/token",
    data={
        "grant_type":   "authorization_code",
        "client_id":    REST_API_KEY,
        "redirect_uri": "https://example.com/oauth",
        "code":         code,
    },
)
data = res.json()

if "refresh_token" in data:
    print("\n✅ 발급 완료!")
    print(f"  ACCESS_TOKEN  : {data['access_token']}")
    print(f"  REFRESH_TOKEN : {data['refresh_token']}")
    print("\n아래 두 값을 GitHub Secrets에 등록하세요:")
    print(f"  KAKAO_REST_API_KEY  = {REST_API_KEY}")
    print(f"  KAKAO_REFRESH_TOKEN = {data['refresh_token']}")
else:
    print(f"\n❌ 오류: {data}")
