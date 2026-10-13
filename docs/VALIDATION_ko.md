# v0.3.0 검증 기록

검증일: **2026-10-14**. 로컬 Codex 호스트에서 Python 3.14.7, Pillow 12.3.0, NumPy 2.5.3으로 실행했습니다. 다른 Python 버전과 Claude의 실제 계정·컨테이너 설치는 이번 실행에서 검증하지 않았습니다.

## 확인 결과

| 검증 | 결과 |
| --- | --- |
| 원본 v0.2.0 회귀 테스트 | 19개 통과 |
| Pixelwright 전체 테스트 | 67개 통과: 생성기 18, 검사기 36, 프로필 10, 패키징 3 |
| skill-creator `quick_validate.py` | Skill is valid |
| 예제 랜턴 생성→검사 | 16×16, 8배, 128×128; 256개 셀 전체 PASS |
| 독립 에이전트의 Skill 사용 | 포션 작성·내보내기·검사 및 기존 불량 PNG 판정 성공 |
| 설치용 ZIP 무결성 | 단일 최상위 폴더·전체 파일 SHA-256 목록 검증 통과 |
| 설치용 ZIP만 풀어 실행 | 빌드와 검사 성공, 소스 트리의 스크립트에 의존하지 않음 |
| ZIP 실행의 부정 사례 | 한 RGBA 샘플을 바꾸자 1개 셀 FAIL, 종료 코드 2, 원본 유지 |
| 공개용 고해상도 QA 설명 | 32×48 논리 격자를 40배 확대해 1280×1920 PNG 검사; 원본 PASS, 샘플 1개 변경본 FAIL |
| 공개 패키지 메타데이터 | Apache 2.0 LICENSE·NOTICE·SECURITY.md 포함, 예상 경로와 ZIP 루트 검증 |

기본 Python 환경에 YAML 의존성이 없어 Skill 형식 검증은 `.work/validator-venv`에서 PyYAML 6.0.3을 사용했습니다. Windows 기본 인코딩을 피하기 위해 검증기를 `python -X utf8`로 실행했습니다. Pixelwright 실행기 자체는 PyYAML을 사용하지 않습니다.

## 독립 사용 검증

검증 에이전트에게 구현 결론을 전달하지 않고 Skill 경로와 다음 작업만 제공했습니다.

- 12×16 논리 캔버스의 포션 아이콘, 배율 6, 보이는 RGB 최대 8색, binary alpha.
- 원본 키트의 `strict_grid_demo/broken.png`를 32×48 논리 캔버스·배율 8로 검사하고 보정하지 않기.

포션은 저장된 네이티브 PNG가 12×16, 확대본이 72×96이며 192개 셀 전체가 단색입니다. 독립적인 Pillow/NumPy 비교도 네이티브 샘플이 정확히 6×6으로 반복됨을 확인했습니다. 보이는 RGB는 8색, 알파는 0과 255뿐입니다. 에이전트가 실제 출력과 미리보기를 보고 실루엣·코르크·액체 표현도 검토했습니다. 이 관찰은 객관적인 미학 보장으로 취급하지 않습니다.

기존 불량 샘플은 256×384의 기하를 충족하지만 `(16,13)`, `(26,22)`, `(12,35)` 셀에서 정확한 RGBA 차이를 검출했습니다. 평균 점수는 99.9969였으나 엄격한 판정은 FAIL입니다. 부분 알파 샘플도 1개 발견했습니다. 입력 SHA-256은 검사 전후 동일했습니다.

## 재실행

저장소 루트에서:

```sh
python -m unittest discover -s pixelwright/tests -v
python tools/package_skill.py --out-dir dist
python tools/package_skill.py --verify dist/pixelwright-v0.3.0.zip
python tools/verify_release.py --archive dist/pixelwright-v0.3.0.zip --out-dir .work/release-check-new
```

출력 폴더에는 실행별로 새 이름을 지정합니다. 단순 반복 실행의 산출물 덮어쓰기는 거부됩니다. `verify_release.py`는 설치 ZIP에서 빌드·감사를 실행하고 정상/불량 판정과 원본 보호를 확인합니다.

## 원본 식별

입력 기획 ZIP SHA-256:

```text
347ccde231b93654624f76782bd632c5acc6666f50587dd1bd5e18e47624993d
```

독립 검증의 기존 불량 PNG SHA-256:

```text
10999a2aa0617f1702c916f27bf1772c5b81ce8bebec89b63cb77a9a97520af4
```

배포 ZIP의 최신 해시는 `dist/SHA256SUMS`에 저장하며, 각 ZIP 내부에도 전체 파일 목록과 해시를 포함합니다. 원본 자료와 실행 기록은 `.work/`에 보존하고 배포 패키지에서 제외했습니다.
