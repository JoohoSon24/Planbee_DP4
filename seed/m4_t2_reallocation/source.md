# T2. Task Reallocation

: 서로 다른 담당자 간 작업 재분배

[원본 일정 보드](/demos/m4_t2_reallocation/board)

1. 변경 요청
    
    Dev → UI Integration 작업에 예상보다 하루가 더 필요할 것 같습니다. Bug Fix는 예정대로 끝내야 합니다. 작업의 재분배를 요청합니다.
    
2. 협의 참여 에이전트
    
    Dev, Art
    
3. 협상에 관여하는 담당자별 제약 및 위임 규칙
    
    Dev : 11/23 가용 8h, 11/24 가용 8h. UI Integration 중 로직 연결 8h는 Dev 전담. Bug Fix 8h도 Dev 전담. UI Integration은 기존 8h에서 총 16h로 증가했으며, 로직 연결 8h와 에셋 연결 8h로 분리 가능.
    
    Art : 11/23 가용 8h, 기존 배정 없음. UI Integration의 에셋 연결 8h를 수행할 역량 있음. 신규 작업 인수는 Art 본인 Confirm 필요.
    
    QA : UI Integration 및 Bug Fix 완료 후 11/25~26에 Integration Test 16h. 작업 담당자가 바뀌어도 테스트 범위 축소 불가.
    
4. 기대하는 협상안(예시)
    
    Dev는 11/23 로직 연결 8h, 11/24 Bug Fix 8h. Art는 11/23 에셋 연결 8h를 인수. Art Confirm 이후 확정.
    
5. AI prompt Evaluation
- 적절한 협상 상대 탐색 : 작업을 인수할 수 있는 Art를 식별했는가
- 업무 역할 확인 : Dev 전답 작업과 Art에게 이전 가능한 작업을 구분하는가
- 권한 및 동의 : Art의 confirm을 제대로 전송하는가
- 일정 재계산 : Dev와 Art의 가용 시간, QA 선행 조건을 모두 만족하는가

