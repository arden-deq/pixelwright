# Pixelwright v0.7.0 릴리스 검증 기록

검증일: **2026-11-03**. 대상 커밋은 이 기록이 들어간 `main`의 릴리스 커밋입니다.

## 이번 버전에 들어간 것

- **게임 계약**([`pixel_game.py`](../pixelwright/scripts/pixel_game.py), [문서](../pixelwright/references/game.md)): 게임 하나의 기본 해상도, 1× 픽셀 크기, 팔레트, 에셋 종류별 크기, 스타일 결정을 `game.json`에 담습니다. 명령은 다섯 가지입니다.
  - `brief`: 그리기 전에 따를 규칙을 출력합니다.
  - `viewport`: 창 크기별 정수 배율과 여백을 계산합니다.
  - `asset`: 1× 에셋을 검사합니다.
  - `intake`: 새 에셋을 기준 에셋 옆에 1×로 놓고 비교합니다.
  - `screen`: 무손실 게임 스크린샷을 검사합니다.
- **범주별 외곽선 규칙:** 범주에 `"outline": false`를 두면 맵칩과 지형을 외곽선 검사에서 뺍니다.
- **[엔진 설정 문서](../pixelwright/references/engines.md):** Unity, Godot 4, Phaser 3, PixiJS, 웹 캔버스, LÖVE, GameMaker를 다룹니다.
- **`SKILL.md`:** 게임 작업이면 스타일 결정을 먼저 모으고, 게임 규칙 8가지를 따르도록 했습니다.
- **예제 게임:** 쯔꾸르(RPG Maker 2000) 스타일 맵 키트입니다. 320×240 화면, 16×16 맵칩 4종, 나무, 연못, 24×32 주인공으로 되어 있고, 원본은 [`tools/generate_game_example.py`](../tools/generate_game_example.py)가 다시 만듭니다. README의 그림 세 장(맵, 수용 비교, 화면 검사)은 이 예제와 실제 검사 결과로 만들었습니다.
- **버전 문자열:** 모든 스크립트와 패키지를 0.7.0으로 올렸습니다.

## 실행 결과

| 환경 | 단위 테스트 | 패키지 검증 | 설치 ZIP 실행 검증 |
| --- | --- | --- | --- |
| Python 3.12.3 · Pillow 12.3.0 · NumPy 2.5.4 | 259개 모두 통과 | 통과 | 통과 |
| Python 3.14.6 · Pillow 12.3.0 · NumPy 2.5.4 | 259개 모두 통과 | — | — |
| Python 3.12.3 · Pillow 13.0.0 · NumPy 2.5.4 | 259개 모두 통과 | — | — |

- 설치 ZIP `pixelwright-v0.7.0.zip`에는 파일 57개가 들어 있습니다.
- 설치 ZIP 실행 검증은 기존 검사(격자, 팔레트, 레이어, 스프라이트)를 모두 통과했습니다.
- 새 게임 단계의 결과:
  - 예제 풀 맵칩·나무·연못·주인공이 각 범주로 통과합니다.
  - 2배로 키운 주인공은 `COARSE_PIXELS`로 실패합니다.
  - 깨끗한 4배 화면은 통과합니다.
  - 주인공을 화면 픽셀 2개만큼 어긋나게 그린 화면은 `CELL_NOT_UNIFORM`으로 실패합니다.
- Windows 결과는 GitHub CI의 Windows Python 3.12·3.14 작업으로 확인합니다.

재현:

```sh
python -m unittest discover -s pixelwright/tests
python tools/package_skill.py --out-dir dist
python tools/package_skill.py --verify dist/pixelwright-v0.7.0.zip
python tools/verify_release.py --archive dist/pixelwright-v0.7.0.zip --out-dir .work/release-v070-check
```

게임 계약 판정별 결과와 한계는 [게임 계약 검증 기록](VALIDATION_game_contract_ko.md)에 있습니다. 실제 엔진에서 캡처한 화면으로는 아직 검사하지 않았습니다.
