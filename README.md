# mapalarm-holidays

지도알람(MapAlarm) 앱의 모닝콜 "공휴일에는 끄기"가 쓰는 **나라별 공휴일 자료**를 매달 자동으로 만들어 게시하는 저장소입니다.

- 자료 출처: [python-holidays](https://github.com/vacanza/holidays) (MIT License) — 버전은 `requirements.txt` 에 고정
- 게시 주소: `https://kyungminkim3760.github.io/mapalarm-holidays/holidays/manifest.json` (목차) + `<국가코드>.json`
- 자동 실행: `.github/workflows/holidays-data.yml` — 매달 1일, 내용이 바뀌었을 때만 배포
- 앱은 이 자료를 **받기만** 합니다. 휴대폰에서 이곳으로 보내는 정보는 없습니다.

생성기 원본은 앱 저장소의 `tools/holidays/` 에 있습니다. 이곳 파일을 고치면 앱 저장소 쪽도 같이 맞춥니다.
