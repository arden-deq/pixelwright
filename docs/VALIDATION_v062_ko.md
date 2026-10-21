# Pixelwright v0.6.2 GIF 장시간 hold 검증

검증일: **2026-10-21**. v0.6.1에서 별도로 재현한, 동일 프레임 병합 시 GIF의 단일 지연 상한 655.35초를 넘는 저장 오류를 수정했습니다. 원본 이미지와 동봉 예제는 보존하고 기존 QA 허용치도 유지합니다.

## 수정 범위

GIF는 프레임 하나의 지연을 최대 **655,350ms**까지 저장할 수 있습니다. 기존 인코더는 동일한 60초 프레임 11개를 하나의 660초 hold로 합치면서 이 범위를 넘겼습니다. 10ms 단위로 배정한 총 재생 시간이 상한을 넘으면 원본 프레임 경계를 보존해 병합을 막습니다. 명세의 개별 지연 상한은 기존처럼 60초여서 각 저장 지연도 GIF 범위 안입니다. 요청한 게임용 `durations_ms`·`total_ms`, 전체 재생 시간과 반복 여부는 유지합니다.

일반 길이 GIF에는 기존 인코딩 경로를 유지합니다. `preview_timing.art`·`preview_timing.rig`는 저장한 GIF를 다시 읽은 실제 프레임별 시간·총시간·반복 정보와 원본 프레임 위치를 기록합니다. 기존 10ms 단위 반올림과 REVIEW 정책, 저장 결과가 배정한 시간·반복과 다를 때의 FAIL 정책도 유지합니다.

## 회귀 검사 항목

새 회귀 테스트 **7개**를 추가했습니다. 수정 전 동일 프레임의 초과 병합에서 `struct.error`가 발생하는 것을 확인했고, 수정 후에는 다음 항목을 실제 GIF를 다시 열어 검증합니다.

- 동일한 60초 프레임 11개: 일반·리그 GIF, 반복·단회 재생 모두 총시간 660초를 보존합니다.
- 정확히 655,350ms인 경우와 10ms 초과한 경우: 각 저장 지연이 GIF 범위 안이며 원본 프레임 위치가 빠짐없이 기록됩니다.
- 반올림 전 655,347ms가 반올림 후 655,380ms가 되는 경우: 안전한 저장 경로를 사용하며 게임용 원래 시간과 REVIEW 정책을 유지합니다.
- 긴 hold 뒤 다른 프레임으로 바뀌는 경우: 660초 이후의 픽셀 전환 시각과 전체 재생 시간을 보존합니다.
- 프레임마다 다른 팔레트: RGB 픽셀과 반복 설정을 보존하고 인코딩에 전달한 이미지도 바꾸지 않습니다.
- 저장한 지연을 일부러 변조한 경우: 해당 미리보기는 FAIL이고 변조하지 않은 리그 미리보기는 검증을 통과합니다.

기존 짧은 GIF의 바이트 비교 테스트와 병합·반복·시간 메타데이터 검사도 유지했습니다. 입력 PNG·작화·명세의 해시를 비교해 원본 보존을 확인합니다.

## 전체 테스트와 설치 검증

Windows에서 Pillow 12.3.0·NumPy 2.5.4로 전체 테스트를 실행했습니다.

| 환경 | 전체 테스트 | 결과 |
| --- | ---: | --- |
| Python 3.12.10 | 239개 | 237개 통과, 심볼릭 링크 권한이 필요한 2개 건너뜀 |
| Python 3.14.7 | 239개 | 237개 통과, 심볼릭 링크 권한이 필요한 2개 건너뜀 |

설치 ZIP·개발 키트의 구조와 해시 검증을 통과했고, 설치본 CLI 검증도 두 Python 환경에서 통과했습니다. 설치본 검사에는 장시간 동일 프레임의 일반·리그 GIF와 반복·단회 재생을 포함하며, 디코딩한 픽셀·총시간·개별 지연·원본 프레임 위치·입력 해시를 비교했습니다. `release-check.json`의 `sprite_gif_long_hold_verified`는 `true`입니다. Python 컴파일, Skill 형식 검사와 `git diff --check`도 통과했습니다.

```sh
python -m unittest discover -s pixelwright/tests -v
python tools/package_skill.py --out-dir dist
python tools/package_skill.py --verify dist/pixelwright-v0.6.2.zip
python tools/verify_release.py --archive dist/pixelwright-v0.6.2.zip --out-dir .work/release-v062-check
```

[CI](../.github/workflows/ci.yml)는 Ubuntu·Windows 각각 Python 3.12·3.14에서 전체 테스트와 설치 ZIP 검증을 실행합니다. 커밋별 원격 결과는 [Actions](https://github.com/jungducknam/pixelwright/actions)에서 확인합니다.

이전 회귀 수정과 Blender 검증 기록은 [v0.6.1](VALIDATION_v061_ko.md)에 남겨 두었습니다.
