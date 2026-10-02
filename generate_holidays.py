# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
generate_holidays.py — 모닝콜 "공휴일에는 끄기"가 쓰는 **나라별 공휴일 자료**를 만든다

[무엇을 하나]
 python-holidays 라이브러리(vacanza/holidays, MIT 라이선스)로 나라별 공휴일을 뽑아
 app/src/main/assets/holidays/<국가코드>.json 으로 저장한다. 앱은 이 파일을 APK 안에
 넣어 들고 다니므로 **인터넷 없이** 공휴일을 판정한다(HolidayRepository.kt 가 읽는다).

[왜 손으로 쓴 규칙 대신 이 방식인가 — 오너 승인 2026-10-02]
 예전에는 한국·일본·대만·미국 4개국 규칙을 코드에 직접 적었다. 나라가 늘어날수록
 규칙(음력·이슬람력·"몇째 주 월요일"·대체공휴일…)을 손으로 옮겨 적으면 틀릴 곳이 늘어나고
 검증할 방법도 없다. python-holidays 는 150개 이상 나라의 공휴일을 정부 고시 출처와 함께
 관리하는 오픈소스라, **개발할 때 한 번 뽑아 앱에 넣는 것**이 가장 정확하고 오프라인에서도 동작한다.

[언제 다시 돌리나]
 **매년 한 번**(가을쯤 — 다음 해 공휴일 고시가 나온 뒤). README.md 의 절차를 따른다.
 라이브러리 버전은 requirements.txt 에 고정돼 있다. 버전을 올릴 때는 그 파일도 같이 바꾼다.

[불확실한 날은 공휴일로 치지 않는다 — 앱 전체 원칙]
 판정이 틀렸을 때의 무게가 다르다.
  · 공휴일인데 아니라고 판정 → 쉬는 날 알람이 울린다 (짜증)
  · 공휴일이 아닌데 맞다고 판정 → 알람이 안 울려 약속을 놓친다 (사고)
 그래서 python-holidays 가 **"추정(estimated)"** 이라고 표시하는 날짜는 자료에서 뺀다.
 구체적인 판정 방법은 아래 install_estimate_hooks() 주석 참조.

[원격 자동 갱신 — tools/holidays/publish/]
 같은 스크립트를 GitHub Actions 가 매달 돌려 GitHub Pages 에 올린다(publish/holidays-data.yml).
 앱은 manifest.json 의 version 이 갖고 있는 자료보다 새로우면 필요한 나라 파일 하나만 내려받는다.
 그래서 출력 폴더마다 **manifest.json**(나라 목록·연도 범위·버전)을 함께 쓴다.

[실행]
 python tools/holidays/generate_holidays.py                      ← 자료 생성(앱 assets 폴더)
 python tools/holidays/generate_holidays.py --out site/holidays  ← 다른 폴더로(CI 배포용)
 python tools/holidays/generate_holidays.py --from-year 2027     ← 시작 연도 지정(기본: 올해)
 python tools/holidays/generate_holidays.py --kotlin-enum        ← HolidayCountry enum 줄을 출력(복사용)
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.metadata
import json
import os
import re
import shutil
import sys
import warnings

import holidays
from holidays.constants import PUBLIC
from holidays.groups.eastern import EasternCalendarHolidays
from holidays.groups.islamic import IslamicHolidays

# ── 경로 ──────────────────────────────────────────────────────────────────────
# 이 파일 위치(tools/holidays) 기준으로 리포 루트를 찾는다 — 어느 폴더에서 실행해도 같은 곳에 쓴다.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
# 기본 출력 폴더 = 앱에 내장되는 자료. --out 으로 바꿀 수 있다(CI 는 site/holidays 로 쓴다).
DEFAULT_OUT_DIR = os.path.join(REPO_ROOT, "app", "src", "main", "assets", "holidays")

# ── 기간 ──────────────────────────────────────────────────────────────────────
# 시작 연도(기본: 올해, --from-year 로 변경)부터 10년 뒤까지(총 11년). 앱 업데이트 없이도 10년은 버틴다.
# 자료 범위를 넘는 날은 앱이 "공휴일 아님"으로 보고 경고 로그를 한 번 남긴다(HolidayRepository).
YEAR_SPAN = 10

# ── 출력 파일 이름 ───────────────────────────────────────────────────────────
# 나라 파일 = "<두 글자 대문자 코드>.json". 지난 실행 잔재를 지울 때 이 모양만 지운다
# (--out 으로 아무 폴더나 줄 수 있으므로 다른 .json 을 실수로 지우지 않게).
COUNTRY_FILE_RE = re.compile(r"^[A-Z]{2}\.json$")
MANIFEST_NAME = "manifest.json"
LICENSE_NAME = "LICENSE-python-holidays.txt"
# manifest 형식 번호 — 앱이 이 숫자를 보고 읽을 수 있는 형식인지 판단한다. 필드를 바꾸면 올린다.
MANIFEST_SCHEMA = 1

# ── 나라 목록 ────────────────────────────────────────────────────────────────
# (ISO 3166-1 alpha-2 코드, 영어 이름, 그 나라 말로 쓴 이름)
#  · 영어 이름 → Kotlin enum 상수 이름(대문자·밑줄)과 정렬 기준.
#    KOREA·JAPAN·TAIWAN·UNITED_STATES 는 기존 저장값·코드와 맞추려고 이 이름을 유지한다.
#  · 그 나라 말 이름 → 설정의 "공휴일 국가" 목록에 보이는 이름(자기 나라는 자기 글자로 알아본다).

# ① 우선 나라 19개 — 앱의 17개 화면 언어의 나라 + 호주·뉴질랜드(오너 지정). 목록 맨 위에 이 순서로 보인다.
PRIORITY_COUNTRIES = [
    ("KR", "Korea", "대한민국"),
    ("US", "United States", "United States"),
    ("RU", "Russia", "Россия"),
    ("FR", "France", "France"),
    ("ES", "Spain", "España"),
    ("IT", "Italy", "Italia"),
    ("DE", "Germany", "Deutschland"),
    ("MY", "Malaysia", "Malaysia"),
    ("ID", "Indonesia", "Indonesia"),
    ("TH", "Thailand", "ประเทศไทย"),
    ("JP", "Japan", "日本"),
    ("VN", "Vietnam", "Việt Nam"),
    ("CN", "China", "中国"),
    ("IN", "India", "भारत"),
    ("PT", "Portugal", "Portugal"),
    ("SA", "Saudi Arabia", "السعودية"),
    ("TW", "Taiwan", "臺灣"),
    ("AU", "Australia", "Australia"),
    ("NZ", "New Zealand", "New Zealand"),
]

# ② 명목 GDP 상위 약 150개국(우선 나라와 겹치는 것은 자동으로 빠진다).
#  출처: IMF World Economic Outlook(2024년 10월판·2025년 4월판) 명목 GDP(미 달러) 순위를
#        대략 따라 적었다. 순서는 결과에 영향이 없다(우선 나라 뒤는 영어 이름 가나다순으로 정렬).
#        목적은 "경제 규모가 있는 나라는 빠짐없이"이므로 순위가 한두 칸 틀려도 문제없다.
#  python-holidays 가 지원하지 않거나 공휴일이 0개로 나오는 나라는 실행 결과에 따로 보고하고 뺀다.
GDP_COUNTRIES = [
    ("GB", "United Kingdom", "United Kingdom"),
    ("BR", "Brazil", "Brasil"),
    ("CA", "Canada", "Canada"),
    ("MX", "Mexico", "México"),
    ("NL", "Netherlands", "Nederland"),
    ("TR", "Turkey", "Türkiye"),
    ("CH", "Switzerland", "Schweiz"),
    ("PL", "Poland", "Polska"),
    ("BE", "Belgium", "België"),
    ("SE", "Sweden", "Sverige"),
    ("AR", "Argentina", "Argentina"),
    ("IE", "Ireland", "Éire"),
    ("AE", "United Arab Emirates", "الإمارات"),
    ("AT", "Austria", "Österreich"),
    ("SG", "Singapore", "Singapore"),
    ("IL", "Israel", "ישראל"),
    ("NO", "Norway", "Norge"),
    ("PH", "Philippines", "Pilipinas"),
    ("BD", "Bangladesh", "বাংলাদেশ"),
    ("DK", "Denmark", "Danmark"),
    ("CO", "Colombia", "Colombia"),
    ("HK", "Hong Kong", "香港"),
    ("ZA", "South Africa", "South Africa"),
    ("RO", "Romania", "România"),
    ("EG", "Egypt", "مصر"),
    ("PK", "Pakistan", "پاکستان"),
    ("CZ", "Czechia", "Česko"),
    ("CL", "Chile", "Chile"),
    ("IR", "Iran", "ایران"),
    ("FI", "Finland", "Suomi"),
    ("PE", "Peru", "Perú"),
    ("KZ", "Kazakhstan", "Қазақстан"),
    ("IQ", "Iraq", "العراق"),
    ("GR", "Greece", "Ελλάδα"),
    ("DZ", "Algeria", "الجزائر"),
    ("QA", "Qatar", "قطر"),
    ("HU", "Hungary", "Magyarország"),
    ("UA", "Ukraine", "Україна"),
    ("NG", "Nigeria", "Nigeria"),
    ("KW", "Kuwait", "الكويت"),
    ("MA", "Morocco", "المغرب"),
    ("ET", "Ethiopia", "ኢትዮጵያ"),
    ("SK", "Slovakia", "Slovensko"),
    ("DO", "Dominican Republic", "República Dominicana"),
    ("EC", "Ecuador", "Ecuador"),
    ("PR", "Puerto Rico", "Puerto Rico"),
    ("KE", "Kenya", "Kenya"),
    ("AO", "Angola", "Angola"),
    ("OM", "Oman", "عُمان"),
    ("GT", "Guatemala", "Guatemala"),
    ("BG", "Bulgaria", "България"),
    ("UZ", "Uzbekistan", "Oʻzbekiston"),
    ("LU", "Luxembourg", "Lëtzebuerg"),
    ("VE", "Venezuela", "Venezuela"),
    ("CR", "Costa Rica", "Costa Rica"),
    ("HR", "Croatia", "Hrvatska"),
    ("PA", "Panama", "Panamá"),
    ("UY", "Uruguay", "Uruguay"),
    ("LT", "Lithuania", "Lietuva"),
    ("RS", "Serbia", "Србија"),
    ("LK", "Sri Lanka", "ශ්‍රී ලංකාව"),
    ("CI", "Ivory Coast", "Côte d'Ivoire"),
    ("BY", "Belarus", "Беларусь"),
    ("TZ", "Tanzania", "Tanzania"),
    ("AZ", "Azerbaijan", "Azərbaycan"),
    ("SI", "Slovenia", "Slovenija"),
    ("GH", "Ghana", "Ghana"),
    ("TM", "Turkmenistan", "Türkmenistan"),
    ("MM", "Myanmar", "မြန်မာ"),
    ("CD", "DR Congo", "RD Congo"),
    ("JO", "Jordan", "الأردن"),
    ("LY", "Libya", "ليبيا"),
    ("BO", "Bolivia", "Bolivia"),
    ("TN", "Tunisia", "تونس"),
    ("BH", "Bahrain", "البحرين"),
    ("KH", "Cambodia", "កម្ពុជា"),
    ("LV", "Latvia", "Latvija"),
    ("PY", "Paraguay", "Paraguay"),
    ("UG", "Uganda", "Uganda"),
    ("CM", "Cameroon", "Cameroun"),
    ("NP", "Nepal", "नेपाल"),
    ("EE", "Estonia", "Eesti"),
    ("SV", "El Salvador", "El Salvador"),
    ("HN", "Honduras", "Honduras"),
    ("ZW", "Zimbabwe", "Zimbabwe"),
    ("IS", "Iceland", "Ísland"),
    ("CY", "Cyprus", "Κύπρος"),
    ("SN", "Senegal", "Sénégal"),
    ("ZM", "Zambia", "Zambia"),
    ("PG", "Papua New Guinea", "Papua Niugini"),
    ("GE", "Georgia", "საქართველო"),
    ("AM", "Armenia", "Հայաստան"),
    ("TT", "Trinidad and Tobago", "Trinidad and Tobago"),
    ("BA", "Bosnia and Herzegovina", "Bosna i Hercegovina"),
    ("AL", "Albania", "Shqipëria"),
    ("MT", "Malta", "Malta"),
    ("MN", "Mongolia", "Монгол Улс"),
    ("MO", "Macau", "澳門"),
    ("BN", "Brunei", "Brunei"),
    ("MZ", "Mozambique", "Moçambique"),
    ("BF", "Burkina Faso", "Burkina Faso"),
    ("ML", "Mali", "Mali"),
    ("GA", "Gabon", "Gabon"),
    ("BW", "Botswana", "Botswana"),
    ("BJ", "Benin", "Bénin"),
    ("JM", "Jamaica", "Jamaica"),
    ("NA", "Namibia", "Namibia"),
    ("GN", "Guinea", "Guinée"),
    ("MK", "North Macedonia", "Северна Македонија"),
    ("NI", "Nicaragua", "Nicaragua"),
    ("MG", "Madagascar", "Madagasikara"),
    ("MD", "Moldova", "Moldova"),
    ("MU", "Mauritius", "Mauritius"),
    ("TD", "Chad", "Tchad"),
    ("BS", "Bahamas", "The Bahamas"),
    ("RW", "Rwanda", "Rwanda"),
    ("NE", "Niger", "Niger"),
    ("CG", "Congo", "Congo"),
    ("XK", "Kosovo", "Kosova"),
    ("ME", "Montenegro", "Crna Gora"),
    ("MW", "Malawi", "Malawi"),
    ("TJ", "Tajikistan", "Тоҷикистон"),
    ("GQ", "Equatorial Guinea", "Guinea Ecuatorial"),
    ("MV", "Maldives", "ދިވެހިރާއްޖެ"),
    ("LA", "Laos", "ລາວ"),
    ("HT", "Haiti", "Haïti"),
    ("SO", "Somalia", "Soomaaliya"),
    ("MR", "Mauritania", "موريتانيا"),
    ("KG", "Kyrgyzstan", "Кыргызстан"),
    ("SR", "Suriname", "Suriname"),
    ("FJ", "Fiji", "Fiji"),
    ("TG", "Togo", "Togo"),
    ("SL", "Sierra Leone", "Sierra Leone"),
    ("SZ", "Eswatini", "eSwatini"),
    ("BB", "Barbados", "Barbados"),
    ("AW", "Aruba", "Aruba"),
    ("GY", "Guyana", "Guyana"),
    ("LB", "Lebanon", "لبنان"),
    ("AF", "Afghanistan", "افغانستان"),
    ("SD", "Sudan", "السودان"),
    ("YE", "Yemen", "اليمن"),
    ("SY", "Syria", "سوريا"),
    ("CU", "Cuba", "Cuba"),
    ("BT", "Bhutan", "འབྲུག་ཡུལ་"),
    ("LR", "Liberia", "Liberia"),
    ("BI", "Burundi", "Burundi"),
    ("DJ", "Djibouti", "Djibouti"),
    ("CV", "Cape Verde", "Cabo Verde"),
    ("LS", "Lesotho", "Lesotho"),
    ("BZ", "Belize", "Belize"),
    ("SS", "South Sudan", "South Sudan"),
    ("ER", "Eritrea", "ኤርትራ"),
]


# ── "추정" 날짜 판정 ─────────────────────────────────────────────────────────

def install_estimate_hooks() -> None:
    """
    python-holidays 내부에 두 가지 손을 써서 "추정 날짜"를 빠짐없이 표시되게 한다.

    [라이브러리가 추정을 다루는 방식]
     음력·이슬람력·힌두력처럼 달을 보는 달력의 공휴일은 내부적으로 (날짜, 추정여부) 쌍으로
     계산된다. 추정여부=True 면 이름 뒤에 "(estimated)" / "(تقديري)" / "（推定）" 같은 꼬리표를
     붙이는데, **나라마다 꼬리표를 붙일지 말지(show_estimated)를 따로 정한다.**

    [우리 판정 규칙]
     ① 라이브러리가 기본 설정으로 꼬리표를 붙이는 날짜 → 뺀다(라이브러리 스스로 "확실치 않다"고 한 날).
     ② **이슬람력 날짜는 나라가 꼬리표를 숨겨도 추정이면 뺀다.**
        이슬람 명절(라마단 끝 Eid 등)은 실제로 **초승달을 눈으로 보고** 며칠 전에야 날짜가
        확정된다. 계산으로 맞힐 수 없는 날이다. 사우디처럼 꼬리표를 숨기는 나라도 마찬가지다.
        그래서 이슬람력 쪽만 꼬리표를 강제로 켠다(IslamicHolidays.__init__ 를 감싼다).
     ③ 음력(중국·한국·베트남)·힌두력·티베트력·몽골력·싱할라력에서 나라가 꼬리표를 숨긴 날짜는 **남긴다.**
        이 달력들은 천문 계산으로 날짜가 정해져 라이브러리 저자들이 "추정"을 화면에
        내세우지 않기로 한 것이다. 이것까지 빼면 한국 설날·추석, 중국 춘절이 통째로 사라진다.
        (참고로 남긴 개수는 hidden_estimates 로 집계해 실행 결과에 보여 준다.)

    [대체·관측 휴일(observed)도 같이 빠진다]
     추정 공휴일에서 파생된 대체휴일은 라이브러리가 "(observed, estimated)" 류 꼬리표로
     이름을 만든다. 꼬리표의 핵심 단어("estimated"·"تقديري"·"推定" 등)가 이름에 들어 있으므로
     같은 검사로 걸러진다.
    """
    original_islamic_init = IslamicHolidays.__init__

    def forced_islamic_init(self, cls=None, *, show_estimated=True, calendar_delta_days=0):
        # 나라가 show_estimated=False 를 넘겨도 무시하고 항상 꼬리표를 붙인다(위 규칙 ②).
        # 단, 그 나라 클래스에 꼬리표 문구(estimated_label)가 없으면 붙일 수 없으므로
        # 원래 값대로 두고, 아래 기록용 훅의 날짜 집합으로 대신 걸러낸다.
        force = hasattr(self, "estimated_label")
        original_islamic_init(
            self,
            cls,
            show_estimated=True if force else show_estimated,
            calendar_delta_days=calendar_delta_days,
        )

    IslamicHolidays.__init__ = forced_islamic_init

    original_add = EasternCalendarHolidays._add_eastern_calendar_holiday

    def recording_add(self, name, dt_estimated, *, show_estimated=True, days_delta=0):
        # 추정 날짜를 인스턴스에 기록해 둔다.
        #  · labeled  = 꼬리표가 실제로 붙은 날(이름 검사와 별개로 한 번 더 확인하는 용도)
        #  · unlabeled = 꼬리표 없이 들어간 추정 날(규칙 ③으로 남기는 날 — 집계용)
        day, is_estimated = dt_estimated
        if is_estimated and day is not None:
            if days_delta:
                day = day + dt.timedelta(days=days_delta)
            labeled = show_estimated and hasattr(self, "estimated_label")
            bucket = "_mapalarm_labeled" if labeled else "_mapalarm_unlabeled"
            if not hasattr(self, bucket):
                setattr(self, bucket, set())
            getattr(self, bucket).add(day)
        return original_add(
            self, name, dt_estimated, show_estimated=show_estimated, days_delta=days_delta
        )

    EasternCalendarHolidays._add_eastern_calendar_holiday = recording_add


def estimated_marker(h) -> str | None:
    """
    그 나라·그 언어의 "추정" 꼬리표 핵심 단어를 돌려준다(예: "estimated", "تقديري", "推定").

    라이브러리 자신이 대체휴일 이름을 만들 때 쓰는 방식과 똑같이 자른다
    (observed_holiday_base.py — label.strip("%s ()（）")).
    꼬리표 문구가 없는 나라는 None.
    """
    label = getattr(h, "estimated_label", None)
    if not label:
        return None
    text = h.tr(label).strip("%s ()（）")
    return text or None


def generate_country(code: str, version: str, today: str, from_year: int, max_to_year: int) -> dict:
    """
    한 나라의 자료를 만든다.

    @param from_year   자료 시작 연도
    @param max_to_year 자료 끝 연도(라이브러리 지원이 더 짧으면 그 해로 줄어든다)

    @return {"file": 자료 dict 또는 None, "excluded": 뺀 날 수, "hidden": 남긴 숨은 추정 수,
             "warning": 라이브러리 경고 문구, "toYear": 실제 끝 연도}
    """
    # 일요일을 "공휴일"로 넣는 나라(스웨덴 등)는 그 옵션을 끈다.
    # 앱에서 일요일은 **요일 선택**으로 표현한다(HolidayCalendar 헤더 "일요일은 공휴일인가").
    # 여기서 일요일을 공휴일로 넣으면 사용자가 일요일을 켜 둔 알람을 코드가 뒤집게 된다.
    #  holidays.country_holidays() 는 나라별 추가 옵션을 받지 않으므로 나라 클래스를 직접 부른다
    #  (getattr(holidays, "SE") = 지연 로딩 래퍼, 호출하면 실제 클래스 인스턴스를 만든다).
    #  옵션이 있는지는 인스턴스의 include_sundays 속성으로 알아낸다(스웨덴·노르웨이가 이 이름을 쓴다).
    country_class = getattr(holidays, code)
    years = range(from_year, max_to_year + 1)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # categories=PUBLIC — 법정 공휴일만(은행 휴무·반일 휴무·지역 휴일 제외).
        # subdiv 없음 — 나라 전체 공통 공휴일만(주·지방 휴일은 넣지 않는다).
        # observed 기본값(True) — 주말과 겹쳐 옮겨 쉬는 날(대체휴일)도 포함된다.
        h = country_class(years=years, categories=PUBLIC)
        if getattr(h, "include_sundays", False):
            h = country_class(years=years, categories=PUBLIC, include_sundays=False)
        _ = list(h.items())  # 연도별 계산을 확실히 끝내 경고를 여기서 모은다.
    warning_text = "; ".join(sorted({str(w.message) for w in caught})) or None

    # 라이브러리가 지원하는 마지막 해가 우리 범위보다 짧으면 그 해까지만 자료로 인정한다.
    # (그 뒤의 날은 앱에서 "자료 범위 밖 = 공휴일 아님"으로 처리된다.)
    #  · end_year 속성 — 나라 클래스 자체의 지원 끝 해(예: 스리랑카는 정부 고시가 난 해까지만)
    #  · "available only from A to B" 경고 — 일부 공휴일만 B년까지 있는 경우(예: 인도 힌두 명절).
    #    이 경우 B년 뒤 자료는 **일부 공휴일이 빠진 불완전한 자료**라 범위에서 뺀다.
    to_year = max_to_year
    end_year = getattr(h, "end_year", None)
    if isinstance(end_year, int) and end_year < to_year:
        to_year = end_year
    for w in caught:
        match = re.search(r"available only from (\d{4}) to (\d{4})", str(w.message))
        if match and int(match.group(2)) < to_year:
            to_year = int(match.group(2))

    marker = estimated_marker(h)
    labeled = getattr(h, "_mapalarm_labeled", set())
    hidden = getattr(h, "_mapalarm_unlabeled", set())

    kept = []
    excluded = 0
    for day in sorted(h.keys()):
        if not (from_year <= day.year <= to_year):
            continue
        names = h.get_list(day)
        if marker:
            # 같은 날에 확정 공휴일과 추정 공휴일이 겹치면 확정 쪽 덕분에 공휴일이 맞다.
            certain = [n for n in names if marker not in n]
        else:
            # 꼬리표 문구가 없는 나라 — 꼬리표가 붙었어야 할 날짜 기록으로 판정(보수적으로 날짜째 뺀다).
            certain = [] if day in labeled else names
        if not certain:
            excluded += 1
            continue
        kept.append({"date": day.isoformat(), "name": "; ".join(certain)})

    hidden_in_range = sum(1 for d in hidden if from_year <= d.year <= to_year)

    data = None
    if kept:
        data = {
            "country": code,
            "source": f"python-holidays {version}",
            "generated": today,
            "fromYear": from_year,
            "toYear": to_year,
            "category": "public",
            # 추정이라 뺀 날 수(이 날에는 알람이 그대로 울린다).
            "excludedEstimated": excluded,
            "holidays": kept,
        }
    return {
        "file": data,
        "excluded": excluded,
        "hidden": hidden_in_range,
        "warning": warning_text,
        "toYear": to_year,
    }


def enum_constant(english: str) -> str:
    """영어 이름 → Kotlin enum 상수 이름(예: "United States" → UNITED_STATES)."""
    out = []
    for ch in english.upper():
        out.append(ch if ch.isalnum() else "_")
    name = "".join(out)
    while "__" in name:
        name = name.replace("__", "_")
    return name.strip("_")


def ordered_countries(generated_codes: set[str]) -> list[tuple[str, str, str]]:
    """앱 목록 순서: 우선 19개국(정해진 순서) → 나머지는 영어 이름 가나다순."""
    priority = [c for c in PRIORITY_COUNTRIES if c[0] in generated_codes]
    priority_codes = {c[0] for c in PRIORITY_COUNTRIES}
    rest = [c for c in GDP_COUNTRIES if c[0] in generated_codes and c[0] not in priority_codes]
    rest.sort(key=lambda c: c[1].casefold())  # 대소문자 무시("DR Congo" 가 "Denmark" 앞에 오지 않게)
    return priority + rest


def print_kotlin_enum(countries: list[tuple[str, str, str]]) -> None:
    """HolidayCountry enum 본문 줄을 출력한다(domain/Models.kt 에 붙여 넣는 용도)."""
    for code, english, native in countries:
        native_escaped = native.replace("\\", "\\\\").replace('"', '\\"')
        print(f'    {enum_constant(english)}("{code}", "{native_escaped}"),')


def write_manifest(out_dir: str, version: str, today_date: dt.date, entries: dict) -> None:
    """
    manifest.json 을 쓴다 — 앱의 원격 자동 갱신이 **가장 먼저 내려받는 작은 목차 파일**.

    형식(앱이 이 필드 이름으로 읽으므로 바꾸지 말 것. 바꾸면 MANIFEST_SCHEMA 를 올린다):
     {"schema":1, "version":20261002, "generated":"2026-10-02", "source":"python-holidays 0.105",
      "countries":{"KR":{"fromYear":2026,"toYear":2036,"file":"KR.json"}, ...}}
      · version   = 생성 날짜 YYYYMMDD 정수. 앱은 이 숫자가 갖고 있는 자료보다 클 때만 나라 파일을 받는다.
      · countries = 이번에 실제로 만든 나라만. file 은 manifest 와 같은 폴더 기준 상대 경로.
    """
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "version": int(today_date.strftime("%Y%m%d")),
        "generated": today_date.isoformat(),
        "source": f"python-holidays {version}",
        "countries": entries,
    }
    with open(os.path.join(out_dir, MANIFEST_NAME), "w", encoding="utf-8", newline="\n") as fp:
        json.dump(manifest, fp, ensure_ascii=False, separators=(",", ":"))


def main() -> int:
    parser = argparse.ArgumentParser(description="python-holidays → 앱 공휴일 자료 생성")
    parser.add_argument("--kotlin-enum", action="store_true", help="HolidayCountry enum 줄만 출력")
    parser.add_argument("--out", default=DEFAULT_OUT_DIR,
                        help="출력 폴더(기본: app/src/main/assets/holidays). CI 는 site/holidays")
    parser.add_argument("--from-year", type=int, default=None,
                        help="자료 시작 연도(기본: 올해). 끝 연도는 시작+10")
    args = parser.parse_args()

    # 출력을 파일로 돌리면(> enum.txt) Windows 는 cp949 로 써서 현지어 이름(ñ 등)에서 멈춘다.
    # 콘솔이 아닐 때만 UTF-8 로 고정한다(콘솔은 Python 이 알아서 유니코드로 출력).
    if not sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8")

    out_dir = os.path.abspath(args.out)          # 상대 경로면 실행한 폴더 기준
    today_date = dt.date.today()                 # 생성 날짜 = manifest version 의 근거
    from_year = args.from_year if args.from_year is not None else today_date.year
    to_year_max = from_year + YEAR_SPAN

    version = importlib.metadata.version("holidays")
    today = today_date.isoformat()
    supported = holidays.list_supported_countries()

    # 같은 나라가 두 목록에 들어 있으면 우선 목록 것을 쓴다.
    seen = set()
    requested = []
    for entry in PRIORITY_COUNTRIES + GDP_COUNTRIES:
        if entry[0] not in seen:
            seen.add(entry[0])
            requested.append(entry)

    unsupported = [c for c in requested if c[0] not in supported]
    candidates = [c for c in requested if c[0] in supported]

    if args.kotlin_enum:
        # enum 출력은 자료 폴더에 실제로 있는 나라 기준(생성 후 실행).
        # manifest.json 은 나라가 아니므로 나라 파일 모양(두 글자.json)만 센다.
        existing = {
            f[:-5] for f in os.listdir(out_dir) if COUNTRY_FILE_RE.match(f)
        } if os.path.isdir(out_dir) else set()
        print_kotlin_enum(ordered_countries(existing))
        return 0

    install_estimate_hooks()
    os.makedirs(out_dir, exist_ok=True)

    # 지난번 실행에서 만들었지만 이번에 빠진 나라 파일은 지운다(목록과 자료가 어긋나지 않게).
    # 나라 파일 모양과 manifest.json 만 지운다 — --out 폴더의 다른 파일은 건드리지 않는다.
    for f in os.listdir(out_dir):
        if COUNTRY_FILE_RE.match(f) or f == MANIFEST_NAME:
            os.remove(os.path.join(out_dir, f))

    generated = []
    manifest_entries = {}  # manifest.json 의 countries — 만든 순서(우선 나라 → GDP 목록 순)
    empty = []
    for code, english, _native in candidates:
        result = generate_country(code, version, today, from_year, to_year_max)
        if result["file"] is None:
            empty.append(code)
            continue
        path = os.path.join(out_dir, f"{code}.json")
        with open(path, "w", encoding="utf-8", newline="\n") as fp:
            # 크기를 줄이려고 공백 없이 쓴다(APK 용량). ensure_ascii=False — 현지어 이름을 그대로.
            json.dump(result["file"], fp, ensure_ascii=False, separators=(",", ":"))
        generated.append(code)
        manifest_entries[code] = {
            "fromYear": result["file"]["fromYear"],
            "toYear": result["file"]["toYear"],
            "file": f"{code}.json",
        }
        notes = []
        if result["excluded"]:
            notes.append(f"추정 제외 {result['excluded']}일")
        if result["hidden"]:
            notes.append(f"숨은 추정 유지 {result['hidden']}일")
        if result["toYear"] != to_year_max:
            notes.append(f"자료 끝 {result['toYear']}년")
        if result["warning"]:
            notes.append(f"경고: {result['warning']}")
        # 이상치 점검 — 한 해 평균 30일이 넘으면 일요일·반일 휴무 같은 것이 섞였을 수 있다. 눈으로 확인할 것.
        years = result["toYear"] - from_year + 1
        if len(result["file"]["holidays"]) / years > 30:
            notes.append("⚠ 한 해 30일 초과 — 내용 확인 필요")
        print(f"{code} {english}: {len(result['file']['holidays'])}일" + (" · " + " · ".join(notes) if notes else ""))

    # python-holidays 라이선스(MIT)는 배포물에 함께 넣어야 한다.
    dist = importlib.metadata.distribution("holidays")
    license_files = [f for f in (dist.files or []) if str(f).replace("\\", "/").endswith("licenses/LICENSE")]
    if not license_files:
        print("오류: python-holidays LICENSE 파일을 찾지 못했다", file=sys.stderr)
        return 1
    shutil.copyfile(
        dist.locate_file(license_files[0]),
        os.path.join(out_dir, LICENSE_NAME),
    )

    # 목차는 마지막에 쓴다 — 중간에 실패하면 manifest 가 없어 배포 단계에서 바로 드러난다.
    write_manifest(out_dir, version, today_date, manifest_entries)

    print()
    print(f"생성: {len(generated)}개국 ({from_year}~{to_year_max}) · python-holidays {version} · {out_dir}")
    print("미지원:", ", ".join(f"{c[0]}({c[1]})" for c in unsupported) or "없음")
    print("공휴일 0개라 제외:", ", ".join(empty) or "없음")
    print("※ 나라 목록이 바뀌었으면 --kotlin-enum 으로 enum 줄을 다시 뽑아 HolidayCountry 를 갱신한다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
