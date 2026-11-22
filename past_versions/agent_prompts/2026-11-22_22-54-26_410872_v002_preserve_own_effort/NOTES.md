# v002_preserve_own_effort

가설: T1의 6h→8h 반올림을 코드에서 제거하고 Dev MD에 동일 업무의 소요량 보존 검사를 추가하면 Live에서도 요청한 이동만 제안된다.

실행 결과는 이 버전의 experiments/ 아래 저장합니다. 실제 Live, Mock, 모의 당사자 승인은 구분합니다.

## 실제 Live 결과

5개 실행 중 T2의 Dev/Art 분담 후보와 T5의 Dev·QA 확인 후 PM 전달이 기준을 충족했습니다. T1·T3·T4는 model_output_invalid로 종료되어 실패로 기록했습니다. 실제 사람 승인이나 PM 적용은 하지 않았습니다.

실패 원인은 생성 모델의 kind 필드 혼동(move를 plan_actions에 기록), 시간(h)을 일(day)로 바꾸지 않은 effort, 0인 조각과 누락된 title이었습니다. 자세한 필드 오류와 모델/호출 수는 experiments/*_live/summary.json과 시나리오별 JSON에 보존합니다.

다음 버전은 단위와 schema별 올바른 위치를 MD에 명시하고, 실제 필드 오류를 새 입력으로 한 번만 전달합니다. 같은 요청의 무한 재호출은 하지 않습니다.
