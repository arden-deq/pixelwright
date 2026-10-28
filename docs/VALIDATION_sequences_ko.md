# 골격 없는 2D 시퀀스 검증 기록

검증일: 2026-10-22. `codex/design-first-sprites` / [PR #10](https://github.com/jungducknam/pixelwright/pull/10), 구현 추적 [#13](https://github.com/jungducknam/pixelwright/issues/13). 발행한 v0.6.2 릴리스와 별도로 이 브랜치 소스의 설치 ZIP을 검증합니다. 버전 상수는 0.6.2를 유지하며 새 릴리스를 발행하지 않았습니다.

## 범위

[`pixel_sequence.py`](../pixelwright/scripts/pixel_sequence.py)는 시안·공통 팔레트·픽셀·상태·시간 계약 고정, 호스트 PNG 가져오기 또는 선택적 HTTP 생성, 실제 그림 관찰, 부위·비율·동작 검사와 GIF·격자·진단 내보내기를 제공합니다. 임의 부위 이름을 쓰며 3D 입력과 Blender가 필요하지 않습니다. 자동 의미론적 분할이나 자연스러움의 자동 승인을 제공하지 않습니다.

## 테스트

macOS / Python 3.12 / Pillow 13 / NumPy 2.5.4에서 전체 **292개 테스트 PASS**, 그중 새 시퀀스 검사 26개입니다.

```sh
python -m unittest discover -s pixelwright/tests -q
```

| 독립적으로 작성하거나 주입한 사례 | 기대 결과 |
| --- | --- |
| 실제 RGBA 셀로 직접 작성한 가상 부유 장치, 실제 마스크·측정·특징점 | PASS; 네이티브 셀과 정확한 4배 반복 확대를 독립 비교, 6프레임 GIF 읽기 검증 |
| 픽셀 격자·색상은 정상이나 전 프레임이 고정 | `REQUIRED_MOTION_MISSING` FAIL |
| 물체 전체만 이동하고 특징점 간 상대 위치는 고정 | 상대 움직임 요구 FAIL |
| 상대 기준 특징점 미관찰 | REVIEW; 보간하지 않음 |
| 부위가 커지거나 관찰 길이·상대 비율 변경 | 크기·치수·비율 FAIL |
| 같은 면적·같은 색 비율에서 표식 위치만 변경 | `PART_DESIGN_CHANGED` FAIL |
| 투영 전 원본의 색을 크게 변경 | `SOURCE_COLORS_CHANGED` FAIL; 팔레트 변환 후 픽셀 PASS와 구분 |
| 연결부 이탈·부위 길이 변경 | 연결·특징점 거리 FAIL |
| 마지막 프레임 시간을 짧게 해 반복 경계 점프 | 시간 기반 속도·가속도 FAIL |
| 접점 이동·지면 이탈, 또는 루트 이동 복원 | 미끄럼·높이 FAIL / 올바른 누적 이동 복원 PASS |
| 미관찰·가림·미검토 | REVIEW; 숫자 PASS만으로 전체 PASS 불가 |
| 마스크가 투명 셀·다른 부위를 가리킴 | 관찰 검증 FAIL |
| 엄격 모드 원본 셀 손상 | 원본 격자 FAIL; 파생 미리보기로 숨기지 않음 |
| 잘못된 시트 종횡비 | FAIL; 크롭·늘이기·프레임별 맞춤 없음 |
| 전체 종횡비가 맞는 비정수 생성 크기 | 선언한 고정 전체 캔버스 파생; 원본 격자는 미인증 |
| 교체·입력 변조·오래된 관찰 | 이전 PNG/생성 기록 보존, 고정 입력 변조 거부, 새 해시와 다른 관찰 거부 |
| HTTP 전송·오류·옵션 | 선택 시안 한 장·고정 프롬프트, 키 미기록, 오류 시 기존 출력 보존, HTTPS 제한과 선택적 배경 옵션 |

테스트는 이 검사기의 빌더로 정답을 그린 후 같은 기대 좌표를 비교하는 방식이 아닙니다. 셀·마스크·관찰을 독립 작성한 fixture를 사용합니다. 이는 계약 검사기의 동작 증거이며 고품질 생성 작화의 증거는 아닙니다.

## 설치 ZIP

```sh
python tools/package_skill.py --out-dir .work/sequence-final-dist
python tools/package_skill.py --verify .work/sequence-final-dist/pixelwright-v0.6.2.zip
python tools/verify_release.py --archive .work/sequence-final-dist/pixelwright-v0.6.2.zip --out-dir .work/sequence-final-installed
```

**독립 설치 실행 PASS.** [실제 실행 결과 JSON](examples/sequence-release-check.json)을 보존했습니다. 재실행에는 비어 있는 새 설치 출력 경로를 사용합니다. `verify_release.py`는 설치 ZIP 안의 Python을 실행하므로 검토한 소스의 패키지에 사용합니다.

- 설치 ZIP: 46개 파일, 매니페스트 전체 SHA-256 검증 PASS. 실행 도구·참조 문서·비인간형 예제가 실제로 포함됩니다.
- 설치 ZIP SHA-256: `5c6abdddc247ccf0268c8ec1dc245121fe89d21c73def3385ed54619833a01ad`.
- 설치된 경로의 명령만으로 준비→원본 반입→알려진 실제 셀 관찰→검사→시트·GIF 내보내기 PASS. 3D/Blender 호출 없음.
- 네이티브 픽셀 원형 보존, 각 셀의 정확한 4배 확대, 6프레임·각 100ms·반복 GIF 읽기 검증 PASS.
- 같은 픽셀 규격에서 미관찰 전체 REVIEW, 고정 동작 전체 FAIL 검출. 변경된 그림에 튜토리얼 관찰을 재사용하는 시도와 오래된 관찰 해시 거부.
- 교체 전 PNG·생성 기록의 정확한 보존과 설치된 예제 입력의 불변성 확인.
- 기존 정적 격자·팔레트·레이어·2D 리그·GIF 시간 양자화·긴 hold 회귀 검증도 PASS.

README·스킬 진입점·제작/현황 문서 등 변경 관련 Markdown 13개의 로컬 링크·이미지 219개를 확인해 누락이 없었습니다. 원격 CI는 푸시된 커밋의 실행 상태를 별도로 확인하며, 이전 커밋의 성공을 이번 변경의 원격 성공으로 표시하지 않습니다.

## 실제 이미지 생성 예제

[Aetherseed](examples/aetherseed-2d/)의 2D 시안과 부유 시트를 호스트 image_gen으로 총 2회 생성했습니다. 3D 입력은 없고, 상태 생성에는 선택 시안 한 장과 고정 프롬프트만 넣었습니다. 호스트가 모델 식별자를 제공하지 않아 추정하지 않았습니다. 초기 시안 생성 프롬프트는 요약만 보존됐고, 상태 생성 프롬프트는 정확한 전송 내용·해시를 보존했습니다. HTTP 래퍼의 유료 실호출 검증은 아닙니다.

- 계약: 64×64 논리 프레임, 3열×2행, 공통 24색, 이진 알파, 4배 확대, 120ms×6 반복.
- 원본: 시안 1254×1254, 상태 1536×1024. 원본 PNG의 정확한 픽셀 격자는 인증하지 않습니다.
- 변환: 전체 캔버스의 고정 최근접 투영·알파 임계값 128·선택 시안의 고정 팔레트. 프레임별 크기·중심 조정 없음.
- 미관찰: 전체 REVIEW, 0 FAIL / 118 REVIEW / 1 INFO. 파생 픽셀 PASS를 동작 승인으로 바꾸지 않습니다.
- 보조 관찰 후: 전체 FAIL, 65 FAIL / 1 REVIEW / 1 INFO. 파생 픽셀 PASS, 작화 `changes_needed`, 사용자 승인 없음.
- 기준 이탈: 색 분포 23건, 색 무늬 24건, 부위 가시 면적 8건, 치수 1건, 상대 비율 2건, 시간 기반 속도 7건.
- 관찰 한계: 실제 좌표 미리보기에서 선택한 부위 경계는 접점에서 약 1셀 오차, 특징점은 1.5셀 이내 가시 셀 보정. 가림·명암·회전의 영향을 별도 검토해야 하며 이탈 65건을 확정 작화 결함 개수로 해석하지 않습니다.

```sh
python pixelwright/scripts/pixel_sequence.py check --run docs/examples/aetherseed-2d/run --observations docs/examples/aetherseed-2d/observations.json --out-dir runs/aetherseed-recheck
```

예상 종료 코드 `2`. [관찰 방법 재현 코드](examples/aetherseed-2d/observe_example.py), [관찰 파일](examples/aetherseed-2d/observations.json), [보고서](examples/aetherseed-2d/audit/report.json), [GIF](examples/aetherseed-2d/audit/hover/pixel-audit/animations/hover.gif)와 실제 격자를 함께 보존했습니다. 원본이나 허용치를 사후 수정해 PASS로 만들지 않았습니다.

기존 3D 기사의 부자연스러운 보행과 작화 결함은 그대로 미완료입니다. 이 도구 구현은 그 에셋의 품질 승인이 아닙니다. [현재 요구사항과 남은 작업](SPRITE_REQUIREMENTS_AND_STATUS_ko.md)을 따릅니다.
